"""
JSON strategy loader.

Templates live in strategies/templates/*.json.
Each type gets strategies/types/{TYPE}/{ID}.json and tunes its own copy.
Math binaries stay in maths/ and arena/; JSON only names them.
"""

import json
from strategies.meta_load import banned as _meta_banned, force as _meta_force
import os
import copy
import math
import random
EXPLORE_TYPES = set()

from config import TYPE_DEFAULTS, STRATEGY_KEYS

MOTION_KEYS = (
    'speed_base', 'turn_base', 'size',
    'strength_range', 'agility_range', 'bravery_range',
    'prey', 'fear', 'display_name', 'icon', 'color',
)

try:
    from app_paths import strategies_root
    ROOT = strategies_root()
except Exception:
    ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(ROOT, 'templates')
TYPES_DIR = os.path.join(ROOT, 'types')
TYPES = ('ROCK', 'PAPER', 'SCISSORS')

# Populated by reload()
MATH_MODULES = {}
TACTICS = {}
STRATEGIES = {}          # template id -> spec
TEAM_OVERLAYS = {}       # type -> id -> overlay
STRATEGY_IDS = ()
DEFAULT_ORDER = ()
_SPEC_CACHE = {}
_DIRTY_OVERLAYS = set()
_BOOK_CACHE = {}


def _read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    payload = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
    tmp = path + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(payload)
        try:
            os.replace(tmp, path)
        except OSError:
            # WinError 5: dest locked/read-only — write in place
            try:
                os.chmod(path, 0o666)
            except Exception:
                pass
            with open(path, 'w', encoding='utf-8') as f:
                f.write(payload)
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(payload)


def _merge(template, overlay):
    out = copy.deepcopy(template) if template else {}
    if not overlay:
        return out
    for k, v in overlay.items():
        if k in ('when', 'switch', 'weights', 'stats', 'bounds', 'base') and isinstance(v, dict):
            base = dict(out.get(k) or {})
            base.update(v)
            out[k] = base
        else:
            out[k] = copy.deepcopy(v)
    return out



def merge_template(overlay, template):
    """Startup: add new template fields without wiping learned values."""
    out = dict(overlay or {})
    tmpl = template or {}
    for k in ('title', 'desc', 'mode', 'id'):
        if k not in out and k in tmpl:
            out[k] = tmpl[k]
    tw = dict(tmpl.get('when') or {})
    ow = dict(out.get('when') or {})
    states = []
    for s in list(ow.get('states') or []) + list(tw.get('states') or []):
        if s and s not in states:
            states.append(s)
    if states:
        ow['states'] = states
    # Priority is a template prior only. Never keep a learned ceiling.
    if 'priority' in tw:
        ow['priority'] = tw['priority']
    elif 'priority' not in ow:
        ow['priority'] = 50
    out['when'] = ow
    ot = list(out.get('tactics') or [])
    for tid in tmpl.get('tactics') or []:
        if tid not in ot:
            ot.append(tid)
    out['tactics'] = ot
    om = list(out.get('math') or [])
    for m in tmpl.get('math') or []:
        if m not in om:
            om.append(m)
    out['math'] = om
    tt = dict(tmpl.get('tunables') or {})
    otu = dict(out.get('tunables') or {})
    for k, v in tt.items():
        if k not in otu:
            otu[k] = v
    out['tunables'] = otu
    tm = list(tmpl.get('movement') or [])
    omv = list(out.get('movement') or [])
    if len(omv) < len(tm):
        omv.extend(copy.deepcopy(tm[len(omv):]))
    out['movement'] = omv
    w = dict(out.get('weights') or {})
    for k, bounds in otu.items():
        if k.startswith('switch.') or k.startswith('when.') or k.startswith('movement['):
            continue
        if k not in w:
            if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
                w[k] = (float(bounds[0]) + float(bounds[1])) * 0.5
            elif k in tmpl.get('weights', {}):
                w[k] = tmpl['weights'][k]
    out['weights'] = w
    # Bounds + base travel with the strategy (template → type copy)
    tb = dict(tmpl.get('bounds') or {})
    ob = dict(out.get('bounds') or {})
    for k, v in tb.items():
        if k not in ob:
            ob[k] = v
    # tunables are bounds too
    for k, v in otu.items():
        if k.startswith('switch.') or k.startswith('when.') or k.startswith('movement['):
            continue
        if k not in ob and isinstance(v, (list, tuple)) and len(v) >= 3:
            ob[k] = list(v)
    out['bounds'] = ob
    tbase = dict(tmpl.get('base') or {})
    obase = dict(out.get('base') or {})
    for k, v in tbase.items():
        if k not in obase:
            obase[k] = v
    out['base'] = obase
    if 'switch' not in out and 'switch' in tmpl:
        out['switch'] = dict(tmpl['switch'])
    return out


def reload():
    """Load math + tactics + every template. Create missing per-type copies."""
    global _SPEC_CACHE, _BOOK_CACHE
    _SPEC_CACHE = {}
    _BOOK_CACHE = {}
    global MATH_MODULES, TACTICS, STRATEGIES, TEAM_OVERLAYS, STRATEGY_IDS, DEFAULT_ORDER
    MATH_MODULES = _read_json(os.path.join(ROOT, 'math.json'), {}) or {}
    TACTICS = _read_json(os.path.join(ROOT, 'tactics.json'), {}) or {}
    STRATEGIES = {}
    if os.path.isdir(TEMPLATES):
        for name in sorted(os.listdir(TEMPLATES)):
            if not name.endswith('.json'):
                continue
            spec = _read_json(os.path.join(TEMPLATES, name), None)
            if not isinstance(spec, dict):
                continue
            sid = str(spec.get('id') or name[:-5]).upper()
            spec['id'] = sid
            spec.setdefault('mode', 'HUNT')
            spec.setdefault('when', {'states': ['CONTESTED'], 'priority': 50})
            spec.setdefault('tactics', [])
            spec.setdefault('math', [])
            spec.setdefault('movement', [])
            spec.setdefault('switch', {'hold_frames': 8, 'margin': 1.0})
            STRATEGIES[sid] = spec
    STRATEGY_IDS = tuple(STRATEGIES.keys())
    # Priority desc then name — used if a type has no order yet
    DEFAULT_ORDER = tuple(
        sid for sid, _ in sorted(
            ((s, STRATEGIES[s].get('when', {}).get('priority', 50)) for s in STRATEGY_IDS),
            key=lambda kv: (-kv[1], kv[0]))
    )
    TEAM_OVERLAYS = {t: {} for t in TYPES}
    for t in TYPES:
        tdir = os.path.join(TYPES_DIR, t)
        os.makedirs(tdir, exist_ok=True)
        for sid, spec in STRATEGIES.items():
            path = os.path.join(tdir, sid + '.json')
            ov = _read_json(path, None)
            created = not isinstance(ov, dict)
            if created:
                ov = _seed_overlay(t, spec)
            else:
                ov = merge_template(ov, spec)
            ov['id'] = sid
            ov['type'] = t
            if created:
                _write_json(path, ov)
            TEAM_OVERLAYS[t][sid] = ov
        # Drop leftover type-wide profile files — knobs live on each strategy JSON
        try:
            os.remove(os.path.join(tdir, '_profile.json'))
        except Exception:
            pass
        apply_overlay_to_defaults(t)
        for sid, ov in TEAM_OVERLAYS[t].items():
            st = _stats_bag(ov)
            ov['stats'] = st
            TEAM_OVERLAYS[t][sid] = ov
    _purge_stale_briefs()
    return STRATEGY_IDS


def _seed_overlay(type_name, spec):
    d = TYPE_DEFAULTS.get(type_name, {})
    weights = {}
    for key in STRATEGY_KEYS:
        if key in d:
            try:
                val = d[key]
                weights[key] = float(val) if not isinstance(val, (list, tuple, dict)) else val
            except Exception:
                weights[key] = d[key]
    for tid in spec.get('tactics') or []:
        knob = (TACTICS.get(tid) or {}).get('knob')
        if knob and knob in d and knob not in weights:
            try:
                weights[knob] = float(d[knob])
            except Exception:
                pass
    sw = dict(spec.get('switch') or {})
    sw['hold_frames'] = int(d.get('switch_hold_frames', sw.get('hold_frames', 8)))
    sw['margin'] = float(d.get('switch_margin', sw.get('margin', 1.0)))
    when = dict(spec.get('when') or {})
    bounds = dict(spec.get('bounds') or {})
    for k, v in (spec.get('tunables') or {}).items():
        if k.startswith('switch.') or k.startswith('when.') or k.startswith('movement['):
            continue
        if k not in bounds and isinstance(v, (list, tuple)) and len(v) >= 3:
            bounds[k] = list(v)
    base = dict(spec.get('base') or {})
    for k in ('speed_base', 'turn_base', 'size', 'late_speed_mult', 'late_turn_mult',
              'late_count_threshold'):
        if k not in base and k in d:
            base[k] = d[k]
    return {
        'id': spec['id'],
        'type': type_name,
        'enabled': True,
        'title': spec.get('title', spec['id']),
        'mode': spec.get('mode', 'HUNT'),
        'desc': spec.get('desc', ''),
        'when': when,
        'tactics': list(spec.get('tactics') or []),
        'math': list(spec.get('math') or []),
        'movement': list(spec.get('movement') or []),
        'switch': sw,
        'bounds': bounds,
        'base': base,
        'weights': weights,
        'stats': {'ticks': 0, 'wins': 0, 'games': 0},
    }


def spec_for(type_name, strategy_id):
    """Template merged with this type's overlay (cached)."""
    key = (type_name, strategy_id)
    hit = _SPEC_CACHE.get(key)
    if hit is not None:
        return hit
    tmpl = STRATEGIES.get(strategy_id) or {}
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id) or {}
    out = _merge(tmpl, ov)
    _SPEC_CACHE[key] = out
    return out


def invalidate_spec_cache():
    global _SPEC_CACHE, _BOOK_CACHE
    _SPEC_CACHE = {}
    _BOOK_CACHE = {}
_DIRTY_OVERLAYS = set()
_BOOK_CACHE = {}


def list_ids():
    if not STRATEGY_IDS:
        reload()
    return list(STRATEGY_IDS)


def _book(type_name):
    hit = _BOOK_CACHE.get(type_name)
    if hit is not None:
        return hit
    d = TYPE_DEFAULTS.get(type_name, {})
    items = []
    for sid in STRATEGY_IDS or list_ids():
        spec = spec_for(type_name, sid)
        if spec.get('enabled', True) is False:
            continue
        pr = int((spec.get('when') or {}).get('priority', 50))
        items.append((-pr, sid))
    order = tuple(sid for _, sid in sorted(items)) or DEFAULT_ORDER
    # Global hold fallback from config
    hold = int(d.get('switch_hold_frames', 8))
    margin = float(d.get('switch_margin', 1.0))
    book = {'order': order, 'switch_hold': hold, 'switch_margin': margin}
    _BOOK_CACHE[type_name] = book
    return book



BANNED = {
    "PAPER": frozenset(("GATE_CAMP", "PACK_HUNT", "LANE_SWEEP", "ROLE_SWEEP", "DELAY_FEAST")),
    "SCISSORS": frozenset(("ROLE_SWEEP", "GATE_CAMP", "PACK_HUNT", "LANE_SWEEP", "STALL_BREAK", "SCREEN_HUNT")),
}
FALLBACK = {
    "PAPER": ("FORT_KITE", "ORBIT_KITE", "OPEN_KITE", "ETA_STRIKE", "CROSS_LANE"),
    "SCISSORS": ("BOUNCE_JUKE", "FORT_KITE", "ORBIT_KITE", "SURVIVE_FEAR"),
    "ROCK": ("LANE_SWEEP", "SCREEN_HUNT", "PACK_HUNT"),
}

def _banned(type_name):
    return BANNED.get(str(type_name or "").upper(), frozenset())

def _fallback(type_name, legal=None):
    legal = [s for s in (legal or []) if s and s not in _banned(type_name)]
    if legal:
        return legal[0]
    for sid in FALLBACK.get(str(type_name or "").upper(), ("PACK_HUNT",)):
        return sid
    return "PACK_HUNT"

def _legal_ids(type_name, state):
    """Strategy ids whose when.states contain this game state."""
    if not STRATEGY_IDS:
        reload()
    legal = []
    for sid in STRATEGY_IDS or list_ids():
        spec = spec_for(type_name or 'ROCK', sid) if type_name else (STRATEGIES.get(sid) or {})
        if spec.get('enabled', True) is False:
            continue
        try:
            from strategies import balance as _bal
            if sid in (_bal.BANNED.get(str(type_name or '').upper()) or ()):
                continue
        except Exception:
            pass
        states = (spec.get('when') or {}).get('states') or []
        if state in states:
            legal.append(sid)
    ban = _banned(type_name)
    if ban:
        legal = [s for s in legal if s not in ban]
    if state == 'LAST_PREY_RISK':
        care = [s for s in legal if s in (
            'LAST_PREY_CARE', 'LAST_MEAL_ORBIT', 'LAST_MEAL_STALL',
            'GIVE_GROUND', 'PRESSURE_BREAK', 'ORBIT_KITE')]
        care = [s for s in care if s not in ('DELAY_FEAST', 'ETA_STRIKE')]
        if care:
            legal = care
    if state == 'CONTESTED':
        legal = [s for s in legal if s not in (
            'HOLD_COVER', 'REGROUP_RIDGE')]
        if type_name == 'PAPER':
            prefer = list(_meta_force('PAPER', 'CONTESTED') or ())
            kite = [s for s in legal if s in prefer] if prefer else legal
            legal = kite or prefer or legal
        if type_name == 'SCISSORS':
            # OPEN_KITE farmed Paper while evading Rock (16g window 0/25/75).
            # Keep OPEN_KITE for OUTNUMBERED/SMALL_UNIT; CONTESTED uses cover/juke.
            mix = [s for s in legal if s in (
                'FORT_KITE', 'BOUNCE_JUKE', 'ORBIT_KITE', 'SURVIVE_FEAR')]
            if mix:
                legal = mix
    if state == 'OUTNUMBERED' and type_name == 'PAPER':
        # Do not dive Rock while outnumbered — Scissors converts the pile.
        screen = [s for s in legal if s in ('SCREEN_HUNT', 'OPEN_KITE', 'ORBIT_KITE')]
        legal = screen or [s for s in legal if s not in ('HOLD_COVER', 'PACK_HUNT', 'LANE_SWEEP')] or legal
    if state == 'CLEAR_HUNT':
        finish = [s for s in legal if s in ENDGAME_FINISH]
        legal = [s for s in (finish or legal) if s not in (
            'LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_STALL',
            'GIVE_GROUND', 'PRESSURE_BREAK', 'SURVIVE_FEAR',
            'LAST_MAN_RUN', 'LAST_MAN_CLOCK', 'ORBIT_KITE')]
    return legal


def _arm_posterior(type_name, strategy_id, state=None, opponent=None):
    st = ((TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id) or {}).get('stats') or {}
    slot = {}
    if opponent:
        slot = ((st.get('by_vs') or {}).get(opponent) or {})
    if (not slot) and state:
        slot = ((st.get('by_state') or {}).get(state) or {})
    a = float(slot.get('alpha', st.get('alpha', 1.0)) or 1.0)
    b = float(slot.get('beta', st.get('beta', 1.0)) or 1.0)
    n = float(slot.get('n', st.get('games', 0)) or 0)
    return max(1e-3, a), max(1e-3, b), n, st


def _thompson_sample(alpha, beta):
    x = random.gammavariate(alpha, 1.0)
    y = random.gammavariate(beta, 1.0)
    denom = x + y
    return (x / denom) if denom > 0 else 0.5


def _select_score(type_name, strategy_id, state=None, opponent=None):
    """Thompson sample + UCB bonus + EMA + template prior.

    Contextual: opponent posterior (by_vs) then by_state, then global.
    """
    spec = spec_for(type_name or 'ROCK', strategy_id)
    pri = float((spec.get('when') or {}).get('priority', 50) or 50)
    a, b, n, st = _arm_posterior(type_name, strategy_id, state, opponent=opponent)
    th = _thompson_sample(a, b)
    ema = float(st.get('ema') or 0.0)
    # state-level pulls across all legal arms (approx from this overlay's n)
    N = max(2.0, float(st.get('games') or 0) + n + 1.0)
    if n <= 0:
        ucb = 0.62
    else:
        ucb = 0.38 * math.sqrt(math.log(N) / n)
    q = 0.0
    try:
        from optimizer import rl
        q = rl.bonus(type_name, state, strategy_id)
    except Exception:
        q = 0.0
    return 0.50 * th + 0.22 * ema + 0.002 * pri + ucb + q


def _note_pull(type_name, sid, state=None):
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(sid)
    if not ov:
        return
    st = dict(ov.get('stats') or {})
    st['pulls'] = int(st.get('pulls') or 0) + 1
    if state:
        by = dict(st.get('pulls_by_state') or {})
        by[str(state)] = int(by.get(str(state)) or 0) + 1
        st['pulls_by_state'] = by
    ov['stats'] = st
    TEAM_OVERLAYS[type_name][sid] = ov
    try:
        _DIRTY_OVERLAYS.add((type_name, sid))
    except Exception:
        pass


def sample_arm(type_name, legal, state=None, opponent=None, explore=0.12):
    """UCB1 over the legal set. t = sum of pulls in this set, not one overlay's life.

    Unpulled arms (n=0) go first. c=0.70. Tiny epsilon only after every arm has a pull.
    """
    legal = [s for s in (legal or []) if s]
    if not legal:
        return None
    if len(legal) == 1:
        _note_pull(type_name, legal[0], state)
        return legal[0]
    posts = []
    t = 0.0
    for sid in legal:
        a, b, n, st = _arm_posterior(type_name, sid, state, opponent=opponent)
        n = float(n or 0)
        t += max(0.0, n)
        posts.append((sid, a, b, n, st))
    t = max(t, 1.0)
    unpulled = [sid for sid, a, b, n, st in posts if n <= 0]
    if unpulled:
        pick = random.choice(unpulled)
        _note_pull(type_name, pick, state)
        return pick
    if str(state or "") == "CONTESTED" and t >= 20:
        try:
            from optimizer import mcts as _mcts
            pick = _mcts.pick(type_name, legal, state, opponent=opponent)
            if pick in legal:
                _note_pull(type_name, pick, state)
                return pick
        except Exception:
            pass
    if random.random() < max(0.0, min(0.15, float(explore))):
        pick = random.choice(legal)
        _note_pull(type_name, pick, state)
        return pick
    if state == 'CONTESTED' and set(legal) <= {'PACK_HUNT', 'LANE_SWEEP'}:
        pulls = {}
        for sid in legal:
            st = ((TEAM_OVERLAYS.get(type_name) or {}).get(sid) or {}).get('stats') or {}
            pulls[sid] = int((st.get('pulls_by_state') or {}).get('CONTESTED') or 0)
        tot = sum(pulls.values())
        if tot >= 8:
            lead = max(legal, key=lambda s: pulls.get(s, 0))
            if pulls.get(lead, 0) / tot > 0.65 and random.random() < 0.40:
                other = [s for s in legal if s != lead]
                if other:
                    pick = other[0]
                    _note_pull(type_name, pick, state)
                    return pick
    c = 0.70
    best_sid, best_s = posts[0][0], -1e9
    for sid, a, b, n, st in posts:
        mu = a / (a + b)
        bonus = c * math.sqrt(math.log(t + 1.0) / max(1.0, n))
        q = 0.0
        try:
            from optimizer import rl
            q = 0.15 * float(rl.bonus(type_name, state, sid) or 0)
        except Exception:
            q = 0.0
        score = mu + bonus + q
        if score > best_s:
            best_s, best_sid = score, sid
    _note_pull(type_name, best_sid, state)
    return best_sid


def strategy_for_state(state, type_name=None, opponent=None):
    legal = _legal_ids(type_name, state)
    if not legal:
        pool = (_book(type_name)['order'] if type_name else DEFAULT_ORDER) or list_ids()
        return pool[0] if pool else 'PACK_HUNT'
    extra = 0.28 if type_name in EXPLORE_TYPES else 0.12
    return sample_arm(type_name, legal, state, opponent=opponent, explore=extra) or legal[0]


ENDGAME_FINISH = (
    'CLEAR_SPLIT', 'CLEAR_FAN', 'FINISH_CLOCK', 'MARK_ONE',
    'LANE_SWEEP', 'CROSS_LANE', 'STALL_BREAK',
    'WALL_CUTOFF', 'ETA_SPLIT',
)
ENDGAME_CARE = (
    'LAST_PREY_CARE', 'LAST_MEAL_ORBIT', 'LAST_MEAL_STALL',
)
ENDGAME_PREY = (
    'LAST_MAN_RUN', 'LAST_MAN_CLOCK', 'SURVIVE_FEAR', 'ORBIT_KITE',
    'FEAR_RIDGE', 'SHADOW_PREY',
)


def endgame_switch(type_name, game_state, current=None, fear=0, prey=0,
                   self_count=None, opponent=None):
    """
    Hard cutover at endgame boundaries. Hold does not apply.
    Predator with no fear left → finish doctrine (minimise remaining time).
    Last meals while fear lives → CARE (do not finish).
    Last man / no prey + fear → evade (maximise remaining time).
    Returns (sid, hold, switched) or None if this is not an endgame state.
    """
    state = str(game_state or '')
    cur = current
    if state == 'CLEAR_HUNT' and int(fear or 0) <= 0 and int(prey or 0) > 0:
        legal = [s for s in _legal_ids(type_name, 'CLEAR_HUNT') if s in ENDGAME_FINISH]
        if not legal:
            legal = list(ENDGAME_FINISH)
        sid = sample_arm(type_name, legal, 'CLEAR_HUNT', opponent=opponent) or 'CLEAR_SPLIT'
        if sid not in (TEAM_OVERLAYS.get(type_name) or {}):
            sid = 'CLEAR_SPLIT'
        return sid, 0, sid != cur
    if state == 'LAST_PREY_RISK' and int(fear or 0) > 0:
        legal = [s for s in _legal_ids(type_name, 'LAST_PREY_RISK') if s in ENDGAME_CARE]
        sid = sample_arm(type_name, legal or ['LAST_PREY_CARE'], 'LAST_PREY_RISK', opponent=opponent)
        return sid or 'LAST_PREY_CARE', 0, sid != cur
    # Paper CONTESTED is kite-first via _legal_ids / select(). Do not force PACK/LANE here.
    if state == 'LAST_MAN' and int(fear or 0) > 0:
        legal = [s for s in _legal_ids(type_name, 'LAST_MAN') if s in ENDGAME_PREY]
        sid = sample_arm(type_name, legal or ['LAST_MAN_RUN'], 'LAST_MAN', opponent=opponent)
        return sid or 'LAST_MAN_RUN', 0, sid != cur
    if state == 'NO_PREY_FEAR_ALIVE' and int(fear or 0) > 0:
        legal = [s for s in _legal_ids(type_name, 'NO_PREY_FEAR_ALIVE') if s in ENDGAME_PREY]
        sid = sample_arm(type_name, legal or ['SURVIVE_FEAR'], 'NO_PREY_FEAR_ALIVE', opponent=opponent)
        return sid or 'SURVIVE_FEAR', 0, sid != cur
    return None


def select(type_name, game_state, current=None, hold_frames=0, opponent=None):
    """
    Pick a strategy id for this team from its own JSON copies.
    Returns (strategy_id, new_hold_frames, switched).
    """
    if not STRATEGY_IDS:
        reload()
    cut = endgame_switch(type_name, game_state, current=current,
                         fear=1 if game_state in ('LAST_PREY_RISK', 'LAST_MAN',
                                                 'NO_PREY_FEAR_ALIVE', 'NEAR_WIPE') else 0,
                         prey=1 if game_state in ('CLEAR_HUNT', 'LAST_PREY_RISK',
                                                 'CONTESTED') else 0,
                         opponent=opponent)
    if cut is not None:
        return cut
    book = _book(type_name)
    ban = _banned(type_name)
    legal = _legal_ids(type_name, game_state)
    desired = strategy_for_state(game_state, type_name, opponent=opponent)
    if desired in ban or (legal and desired not in legal):
        desired = _fallback(type_name, legal)
    if current in ban or (current is not None and legal and current not in legal):
        return desired, 0, True
    if current is None or current == desired:
        return desired, 0, False
    if current not in legal:
        return desired, 0, True
    cur = spec_for(type_name, current)
    cur_states = (cur.get('when') or {}).get('states') or []
    if game_state in cur_states:
        slack = float((cur.get('switch') or {}).get('margin', book['switch_margin']) or 1.0)
        slack = max(0.0, min(2.0, slack)) * 0.08   # additive score slack
        if (_select_score(type_name, desired, game_state, opponent=opponent)
                < _select_score(type_name, current, game_state, opponent=opponent) + slack):
            return current, 0, False
    # Commit to the outgoing strategy (hold once you are in).
    hold_need = max(1, int((cur.get('switch') or {}).get('hold_frames', book['switch_hold'])))
    hold_frames = int(hold_frames) + 1
    if hold_frames >= hold_need:
        return desired, 0, True
    return current, hold_frames, False


def tactics_for(strategy_id, type_name=None):
    spec = spec_for(type_name, strategy_id) if type_name else (STRATEGIES.get(strategy_id) or {})
    return list(spec.get('tactics') or [])


def tactic_enabled(strategy_id, tactic_id, type_name=None):
    return tactic_id in tactics_for(strategy_id, type_name)


def tactic_weight(type_name, tactic_id, strat_dict=None):
    meta = TACTICS.get(tactic_id) or {}
    knob = meta.get('knob')
    spec = spec_for(type_name, (strat_dict or {}).get('_strategy_id')) if strat_dict else {}
    weights = spec.get('weights') or {}
    src = strat_dict if strat_dict is not None else TYPE_DEFAULTS.get(type_name, {})
    if knob and knob in weights:
        try:
            return float(weights[knob])
        except Exception:
            pass
    if not knob:
        return 1.0
    try:
        return float(src.get(knob, 1.0))
    except Exception:
        return 1.0


def team_mode_name(strategy_id, type_name=None):
    spec = spec_for(type_name, strategy_id) if type_name else (STRATEGIES.get(strategy_id) or {})
    return spec.get('mode', 'HUNT')


def movement_for(strategy_id, type_name=None):
    spec = spec_for(type_name, strategy_id) if type_name else (STRATEGIES.get(strategy_id) or {})
    return list(spec.get('movement') or [])


def annotate(strat_dict, strategy_id, type_name=None):
    out = dict(strat_dict)
    out['_strategy_id'] = strategy_id
    out['_tactics'] = tactics_for(strategy_id, type_name)
    out['_movement'] = movement_for(strategy_id, type_name)
    for tid in TACTICS:
        out['_tac_%s' % tid] = 1.0 if tid in out['_tactics'] else 0.0
    # Overlay weights win while this strategy is active
    spec = spec_for(type_name or 'ROCK', strategy_id)
    for k, v in (spec.get('weights') or {}).items():
        try:
            out[k] = float(v)
        except Exception:
            pass
    # Finish doctrine: never let learned sep/cohesion keep a blob off the last prey.
    if out.get('_game_state') == 'CLEAR_HUNT' or strategy_id in (
            'CLEAR_SPLIT', 'CLEAR_FAN', 'FINISH_CLOCK', 'MARK_ONE'):
        out['cohesion_weight'] = 0.0
        out['speed_match_weight'] = 0.0
        out['sep_distance'] = max(6.0, float(out.get('sep_distance') or 6.0))
        out['pack_hunt_mult'] = min(0.25, float(out.get('pack_hunt_mult') or 0.25))
        out['hide_among_prey_weight'] = 0.0
        out['fort_cover_weight'] = min(0.25, float(out.get('fort_cover_weight') or 0.25))
    return out


def tunables_for(type_name, strategy_id):
    """Declared tunables from the strategy JSON (template + overlay)."""
    spec = spec_for(type_name, strategy_id)
    raw = spec.get('tunables')
    out = {}
    if isinstance(raw, dict) and raw:
        for k, v in raw.items():
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                out[k] = (float(v[0]), float(v[1]), float(v[2]))
            elif isinstance(v, dict):
                out[k] = (float(v.get('lo', 0)), float(v.get('hi', 2)), float(v.get('step', 0.05)))
    if out:
        return out
    # Drop-in strategy with no tunables block: derive from tactics + switch + movement
    out['switch.hold_frames'] = (2, 16, 1)
    out['switch.margin'] = (0.5, 2.0, 0.05)
    # when.priority is frozen at the template value — not a tunable.
    from config import STRATEGY_BOUNDS
    for tid in spec.get('tactics') or []:
        knob = (TACTICS.get(tid) or {}).get('knob')
        if not knob:
            continue
        if knob in STRATEGY_BOUNDS:
            lo, hi, step = STRATEGY_BOUNDS[knob]
            out[knob] = (float(lo), float(hi), float(step))
        else:
            out[knob] = (0.0, 3.0, 0.05)
    for i, step in enumerate(spec.get('movement') or []):
        if 'blend' in step:
            out['movement[%d].blend' % i] = (0.0, 1.0, 0.05)
        if 'weight' in step:
            out['movement[%d].weight' % i] = (0.0, 2.0, 0.05)
    return out


def _get_path(ov, path):
    if path.startswith('switch.'):
        return (ov.get('switch') or {}).get(path.split('.', 1)[1])
    if path.startswith('when.'):
        return (ov.get('when') or {}).get(path.split('.', 1)[1])
    if path.startswith('movement[') and ']' in path:
        idx = int(path.split('[', 1)[1].split(']', 1)[0])
        field = path.split('].', 1)[1]
        mv = list(ov.get('movement') or [])
        if 0 <= idx < len(mv):
            return mv[idx].get(field)
        return None
    return (ov.get('weights') or {}).get(path)


def _set_path(ov, path, value):
    if path.startswith('switch.'):
        sw = dict(ov.get('switch') or {})
        sw[path.split('.', 1)[1]] = value
        ov['switch'] = sw
        return
    if path.startswith('when.'):
        when = dict(ov.get('when') or {})
        when[path.split('.', 1)[1]] = value
        ov['when'] = when
        return
    if path.startswith('movement[') and ']' in path:
        idx = int(path.split('[', 1)[1].split(']', 1)[0])
        field = path.split('].', 1)[1]
        mv = [dict(s) for s in (ov.get('movement') or [])]
        while len(mv) <= idx:
            mv.append({})
        mv[idx][field] = value
        ov['movement'] = mv
        return
    w = dict(ov.get('weights') or {})
    w[path] = value
    ov['weights'] = w


def nudge_tunable(type_name, strategy_id, path, direction, strength=1.0, bounds=None):
    """Move one strategy-declared tunable on this type's overlay only."""
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id)
    if not ov:
        return None
    if path == 'when.priority' or path.endswith('.priority'):
        return None
    if bounds is None:
        bounds = tunables_for(type_name, strategy_id).get(path)
    if not bounds:
        return None
    lo, hi, step = bounds
    cur = _get_path(ov, path)
    if cur is None:
        cur = (lo + hi) * 0.5
    try:
        cur_f = float(cur)
    except Exception:
        return None
    mag = max(0.25, min(3.0, abs(float(strength))))
    nxt = cur_f + direction * step * mag
    if path.endswith('hold_frames') or path.endswith('priority') or path.endswith('ttl'):
        nxt = int(round(nxt))
    nxt = max(lo, min(hi, nxt))
    if abs(nxt - cur_f) < abs(step) * 0.05:
        return ov
    _set_path(ov, path, nxt)
    TEAM_OVERLAYS[type_name][strategy_id] = ov
    return ov


def save_overlay(type_name, strategy_id, overlay=None):
    if overlay is None:
        overlay = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id)
    if not overlay:
        return
    overlay = dict(overlay)
    overlay['id'] = strategy_id
    overlay['type'] = type_name
    TEAM_OVERLAYS.setdefault(type_name, {})[strategy_id] = overlay
    _DIRTY_OVERLAYS.add((type_name, strategy_id))


def save_all_overlays(force=False):
    global _DIRTY_OVERLAYS
    if force:
        for tname, bag in TEAM_OVERLAYS.items():
            for sid, ov in bag.items():
                _DIRTY_OVERLAYS.add((tname, sid))
    dirty = list(_DIRTY_OVERLAYS)
    _DIRTY_OVERLAYS = set()
    written = []
    for tname, sid in dirty:
        ov = (TEAM_OVERLAYS.get(tname) or {}).get(sid)
        if ov is None:
            continue
        path = os.path.join(TYPES_DIR, tname, sid + '.json')
        _write_json(path, ov)
        written.append(path)
    return written


def nudge_overlay(type_name, strategy_id, field, direction, amount=1.0):
    """direction +1 / -1. field is 'hold_frames' | 'margin' | 'priority'."""
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id)
    if not ov:
        return None
    if field in ('hold_frames', 'margin'):
        sw = dict(ov.get('switch') or {})
        cur = float(sw.get(field, 8 if field == 'hold_frames' else 1.0))
        step = 1.0 if field == 'hold_frames' else 0.05
        nxt = cur + direction * step * amount
        if field == 'hold_frames':
            nxt = max(2, min(16, int(round(nxt))))
        else:
            nxt = max(0.5, min(2.0, nxt))
        sw[field] = nxt
        ov['switch'] = sw
    elif field == 'priority':
        when = dict(ov.get('when') or {})
        cur = int(when.get('priority', 50))
        states = list(when.get('states') or [])
        cap = 72
        sid = str(ov.get('id') or strategy_id or '')
        if 'CLEAR_HUNT' in states:
            cap = 100
        elif 'LAST_MAN' in states or 'NEAR_WIPE' in states:
            cap = 96
        elif sid in ('LAST_PREY_CARE', 'DELAY_FEAST') and 'LAST_PREY_RISK' in states:
            cap = 90
        elif 'NO_PREY_FEAR_ALIVE' in states:
            cap = 92
        when['priority'] = max(1, min(cap, cur + int(direction * 4 * amount)))
        ov['when'] = when
    TEAM_OVERLAYS[type_name][strategy_id] = ov
    return ov


def note_stats(type_name, strategy_id, ticks=0, win=False):
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id)
    if not ov:
        return
    st = dict(ov.get('stats') or {})
    st['ticks'] = int(st.get('ticks', 0)) + int(ticks)
    st['games'] = int(st.get('games', 0)) + 1
    if win:
        st['wins'] = int(st.get('wins', 0)) + 1
    ov['stats'] = st



def _purge_stale_briefs():
    """Briefs belong only in optimizer/grok/. Kill every other copy."""
    try:
        from optimizer.paths import ROOT as _OPT_ROOT
    except Exception:
        _OPT_ROOT = os.path.join(os.path.dirname(ROOT), 'optimizer')
    stale = [
        os.path.join(_OPT_ROOT, 'GROK_BRIEF.json'),
        os.path.join(_OPT_ROOT, 'GROK_BRIEF.md'),
        os.path.join(ROOT, 'GROK_BRIEF.json'),
        os.path.join(ROOT, 'GROK_BRIEF.md'),
        os.path.join(ROOT, 'brief.json'),
        os.path.join(ROOT, 'brief.md'),
        os.path.join(os.path.dirname(ROOT), 'GROK_BRIEF.json'),
        os.path.join(os.path.dirname(ROOT), 'GROK_BRIEF.md'),
    ]
    for path in stale:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass


def write_grok_brief(metrics=None):
    """Human + machine snapshot Grok can read to invent the next strategy."""
    if not STRATEGY_IDS:
        reload()
    lines = [
        '# GROK_BRIEF — live doctrine',
        '',
        'Use this file plus `strategies/SCHEMA.md` to invent a new strategy JSON.',
        'Do not edit Python. Drop `strategies/templates/NEW_ID.json` and restart.',
        '',
        '## Math binaries you may name in `movement[].fn` and `math`',
        '',
    ]
    for mid, spec in MATH_MODULES.items():
        apis = spec.get('api') or []
        lines.append('- `%s` (%s) — %s' % (mid, spec.get('file'), spec.get('use')))
        for a in apis:
            lines.append('  - `%s.%s`' % (mid, a.split('.')[-1] if '.' in str(a) else a))
    lines += ['', '## Tactics you may list', '']
    for tid, spec in TACTICS.items():
        lines.append('- `%s` → %s.%s  knob=`%s`  [%s] %s' % (
            tid, spec.get('math'), (spec.get('fn') or '').split('.')[-1],
            spec.get('knob'), spec.get('goal'), spec.get('desc')))
    lines += ['', '## Templates', '']
    for sid in STRATEGY_IDS:
        spec = STRATEGIES[sid]
        when = spec.get('when') or {}
        lines.append('### %s' % sid)
        lines.append('- mode `%s` when %s priority %s' % (
            spec.get('mode'), when.get('states'), when.get('priority')))
        lines.append('- tactics: %s' % ', '.join(spec.get('tactics') or []))
        lines.append('- movement: %s' % json.dumps(spec.get('movement') or []))
        lines.append('- %s' % spec.get('desc', ''))
        lines.append('')
    lines += ['## Per-type tuned copies (from types/{TYPE}/*.json stats)', '']
    for t in TYPES:
        lines.append('### %s' % t)
        rows = []
        unused = []
        for sid in STRATEGY_IDS:
            ov = (TEAM_OVERLAYS.get(t) or {}).get(sid) or {}
            sw = ov.get('switch') or {}
            when = ov.get('when') or {}
            st = ov.get('stats') or {}
            ticks = int(st.get('ticks') or 0)
            games = int(st.get('games') or 0)
            wins = int(st.get('wins') or 0)
            blunder = int(st.get('last_prey_blunder') or 0)
            rec = (ticks, games, wins, blunder, sid, ov, sw, when, st)
            if ticks or games or wins:
                rows.append(rec)
            else:
                unused.append(sid)
        rows.sort(reverse=True)
        for ticks, games, wins, blunder, sid, ov, sw, when, st in rows:
            wr = (100.0 * wins / games) if games else 0.0
            lines.append(
                '- **%s** ticks=%d games=%d wins=%d wr=%.0f%% blunder=%d pri=%s hold=%s margin=%s' % (
                    sid, ticks, games, wins, wr, blunder,
                    when.get('priority'), sw.get('hold_frames'), sw.get('margin')))
        if unused:
            lines.append('- unused: %s' % ', '.join(unused))
        lines.append('')
    lines += [
        '## Invent next',
        '',
        '1. Find a gap (state + math combo no template covers well).',
        '2. Write templates/NEW_ID.json using only tactics and fns listed above.',
        '3. Keep `id` unique and UPPER_SNAKE.',
        '4. Types will clone it; optimiser will tune switch + weights per type.',
        '',
    ]
    try:
        from optimizer.paths import ROOT as _OPT_ROOT
        opt = _OPT_ROOT
    except Exception:
        opt = os.path.join(os.path.dirname(ROOT), 'optimizer')
    grok = os.path.join(opt, 'grok')
    os.makedirs(grok, exist_ok=True)
    _purge_stale_briefs()
    text = '\n'.join(lines) + '\n'
    path = os.path.join(grok, 'GROK_BRIEF.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    suggest = os.path.join(grok, 'SUGGESTIONS.md')
    if not os.path.exists(suggest):
        with open(suggest, 'w', encoding='utf-8') as f:
            f.write('# Strategy suggestions\n\nDrop invented templates in strategies/templates/.\n')
    snap = {
        'math': MATH_MODULES,
        'tactics': TACTICS,
        'templates': STRATEGIES,
        'overlays': TEAM_OVERLAYS,
        'ids': list(STRATEGY_IDS),
        'bounds': _read_json(os.path.join(ROOT, 'bounds.json'), {}),
    }
    _write_json(os.path.join(grok, 'GROK_BRIEF.json'), snap)
    return path


def apply_overlay_to_defaults(type_name, strategy_id=None):
    """Copy overlay weights into TYPE_DEFAULTS so effective_strategy sees JSON."""
    bag = TEAM_OVERLAYS.get(type_name) or {}
    sid = strategy_id or ('PACK_HUNT' if 'PACK_HUNT' in bag else (next(iter(bag), None)))
    ov = bag.get(sid) or {}
    weights = ov.get('weights') or {}
    dest = TYPE_DEFAULTS.get(type_name)
    if dest is None:
        return
    for k, v in weights.items():
        dest[k] = v
    for k, v in (ov.get('base') or {}).items():
        dest[k] = v
    sw = ov.get('switch') or {}
    if 'hold_frames' in sw:
        dest['switch_hold_frames'] = int(sw['hold_frames'])
    if 'margin' in sw:
        dest['switch_margin'] = float(sw['margin'])


def write_defaults_into_overlay(type_name, strategy_id=None):
    """Copy current TYPE_DEFAULTS strategy knobs into overlay weights (persist)."""
    d = TYPE_DEFAULTS.get(type_name) or {}
    sids = [strategy_id] if strategy_id else list((TEAM_OVERLAYS.get(type_name) or {}))
    for sid in sids:
        ov = (TEAM_OVERLAYS.get(type_name) or {}).get(sid)
        if not ov:
            continue
        weights = dict(ov.get('weights') or {})
        for key in STRATEGY_KEYS:
            if key in d:
                weights[key] = d[key]
        ov['weights'] = weights
        sw = dict(ov.get('switch') or {})
        if 'switch_hold_frames' in d:
            sw['hold_frames'] = int(d.get('switch_hold_frames', sw.get('hold_frames', 8)))
        if 'switch_margin' in d:
            sw['margin'] = float(d.get('switch_margin', sw.get('margin', 1.0)))
        ov['switch'] = sw
        TEAM_OVERLAYS[type_name][sid] = ov


def nudge_weight(type_name, strategy_id, key, value):
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id)
    if ov is None:
        return
    if key in ('speed_base', 'turn_base', 'size',
               'late_speed_mult', 'late_turn_mult', 'late_count_threshold'):
        base = dict(ov.get('base') or {})
        base[key] = value
        ov['base'] = base
    else:
        w = dict(ov.get('weights') or {})
        w[key] = value
        ov['weights'] = w
    TEAM_OVERLAYS[type_name][strategy_id] = ov
    _DIRTY_OVERLAYS.add((type_name, strategy_id))


def strategy_bounds(type_name, strategy_id, key=None):
    """Bounds owned by this type/strategy copy (template fallback)."""
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id) or {}
    tmpl = STRATEGIES.get(strategy_id) or {}
    bag = dict(tmpl.get('bounds') or {})
    bag.update(ov.get('bounds') or {})
    if key is None:
        return bag
    v = bag.get(key)
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        return float(v[0]), float(v[1]), float(v[2])
    return None

def _profile_path(type_name):
    return os.path.join(TYPES_DIR, type_name, '_profile.json')


def load_profile(type_name):
    data = _read_json(_profile_path(type_name), None)
    return data if isinstance(data, dict) else {}


def save_profile(type_name, profile):
    profile = dict(profile or {})
    profile['type'] = type_name
    weights = {}
    for k, v in (profile.get('weights') or {}).items():
        if isinstance(v, tuple):
            v = list(v)
        weights[k] = v
    profile['weights'] = weights
    _write_json(_profile_path(type_name), profile)
    return _profile_path(type_name)


def persist_learned(games_seen=0, changes=None):
    """Write dirty types/{TYPE}/{SID}.json. No _profile.json."""
    note = list(changes or [])[:12]
    if note or games_seen:
        for tname, sid in list(_DIRTY_OVERLAYS):
            ov = (TEAM_OVERLAYS.get(tname) or {}).get(sid)
            if not isinstance(ov, dict):
                continue
            ov['games_seen'] = games_seen
            if note:
                prefix = '%s.%s.' % (tname, sid)
                own = [c for c in note if str(c).startswith(prefix) or str(c).startswith(tname + '.')]
                ov['last_changes'] = own[:8] if own else note[:4]
    written = save_all_overlays()
    for t in TYPES:
        try:
            os.remove(_profile_path(t))
        except Exception:
            pass
    return written or [os.path.join(TYPES_DIR, t) for t in TYPES]



def _stats_bag(ov):
    st = dict(ov.get('stats') or {})
    st.setdefault('ticks', 0)
    st.setdefault('wins', 0)
    st.setdefault('games', 0)
    st.setdefault('conversions_for', 0)
    st.setdefault('conversions_against', 0)
    st.setdefault('last_prey_blunder', 0)
    st.setdefault('blocked_womble', 0)
    st.setdefault('by_mode', {})
    st.setdefault('ema', 0.0)
    st.setdefault('glimpse', 0)
    st.setdefault('alpha', 1.0)
    st.setdefault('beta', 1.0)
    st.setdefault('by_state', {})
    st.setdefault('by_vs', {})
    _hydrate_posterior(st)
    _cap_posterior(st)
    return st


PRIOR_STRENGTH = 16.0


def _hydrate_posterior(st):
    """If α,β never left the prior, seed them from historical wins/games."""
    a = float(st.get('alpha') or 1.0)
    b = float(st.get('beta') or 1.0)
    games = float(st.get('games') or 0)
    wins = float(st.get('wins') or 0)
    if games >= 4 and a <= 1.05 and b <= 1.05:
        wr = max(0.0, min(1.0, wins / max(1.0, games)))
        st['alpha'] = 1.0 + wr * PRIOR_STRENGTH
        st['beta'] = 1.0 + (1.0 - wr) * PRIOR_STRENGTH
        if st.get('ema') in (0, 0.0, None) or abs(float(st.get('ema') or 0)) < 0.02:
            st['ema'] = (wr - 0.33) * 0.6


def _cap_posterior(st):
    """Keep Beta from locking after a lucky streak (max effective sample 16)."""
    a = max(1e-3, float(st.get('alpha') or 1.0))
    b = max(1e-3, float(st.get('beta') or 1.0))
    s = a + b
    if s > PRIOR_STRENGTH:
        a = 1.0 + (a / s) * (PRIOR_STRENGTH - 2.0)
        b = 1.0 + (b / s) * (PRIOR_STRENGTH - 2.0)
        st['alpha'], st['beta'] = a, b


def credit_decisions(match):
    """Fold one match of decisions into per-type per-strategy overlay stats.

    match = {
      winner: 'ROCK',
      ticks: {type: {sid: n}},
      mode_ticks: {type: {sid: {mode: n}}},
      conversions: [{winner_type, loser_was, winner_strategy, loser_strategy,
                     winner_mode, last_prey_with_fear, blocked_womble}],
    }
    """
    types = TYPES
    ticks = match.get('ticks') or {}
    mode_ticks = match.get('mode_ticks') or {}
    winner = str(match.get('winner') or '').upper()
    MIN_CREDIT = 1
    EMA = 0.12
    for tname in types:
        bag = TEAM_OVERLAYS.setdefault(tname, {})
        used = ticks.get(tname) or {}
        modes = mode_ticks.get(tname) or {}
        type_ticks = float(sum(int(v or 0) for v in used.values()) or 1)
        for sid, n in used.items():
            if sid not in bag:
                continue
            ov = bag[sid]
            st = _stats_bag(ov)
            n = int(n or 0)
            st['ticks'] = int(st['ticks']) + n
            share = n / type_ticks
            # Glimpse only: do not treat a 2-tick flicker as a game/win.
            care = sid in ('LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_STALL')
            if n < (1 if care else MIN_CREDIT):
                st['glimpse'] = int(st.get('glimpse') or 0) + 1
                payoff = -0.02
            else:
                st['games'] = int(st['games']) + 1
                if tname == winner:
                    st['wins'] = float(st.get('wins') or 0) + share
                payoff = (share if tname == winner else -0.25 * share)
            st['ema'] = (1.0 - EMA) * float(st.get('ema') or 0) + EMA * payoff
            if n >= (1 if care else MIN_CREDIT):
                if tname == winner:
                    st['alpha'] = float(st.get('alpha') or 1.0) + share
                else:
                    st['beta'] = float(st.get('beta') or 1.0) + share
                if int(st.get('last_prey_blunder') or 0) and care is False:
                    st['beta'] = float(st.get('beta') or 1.0) + 0.4
            state_bag = ((match.get('state_ticks') or {}).get(tname) or {}).get(sid) or {}
            bys = dict(st.get('by_state') or {})
            for stname, cn in state_bag.items():
                cn = int(cn or 0)
                if cn <= 0:
                    continue
                slot = dict(bys.get(stname) or {'n': 0, 'alpha': 1.0, 'beta': 1.0, 'ema': 0.0})
                slot['n'] = int(slot.get('n') or 0) + cn
                frac = cn / max(1.0, float(n))
                if n >= MIN_CREDIT and tname == winner:
                    slot['alpha'] = float(slot.get('alpha') or 1.0) + share * frac
                elif n >= MIN_CREDIT:
                    slot['beta'] = float(slot.get('beta') or 1.0) + share * frac
                slot['ema'] = 0.88 * float(slot.get('ema') or 0) + 0.12 * payoff
                bys[stname] = slot
            st['by_state'] = bys
            by = dict(st.get('by_mode') or {})
            sid_modes = modes.get(sid) if isinstance(modes.get(sid), dict) else {}
            for md, c in sid_modes.items():
                slot = dict(by.get(md) or {})
                slot['ticks'] = int(slot.get('ticks', 0)) + int(c or 0)
                by[md] = slot
            st['by_mode'] = by
            ov['stats'] = st
            bag[sid] = ov
            _DIRTY_OVERLAYS.add((tname, sid))
        TEAM_OVERLAYS[tname] = bag
    for row in match.get('conversions') or []:
        wt = str(row.get('winner_type') or '').upper()
        ws = row.get('winner_strategy')
        ls = row.get('loser_strategy')
        lt = str(row.get('loser_was') or '').upper()
        md = str(row.get('winner_mode') or '')
        blunder = int(row.get('last_prey_with_fear') or 0)
        blocked = int(row.get('blocked_womble') or 0)
        # Last-meal foul: blame the hunt doctrine that occupied the match,
        # not CARE (CARE is forced on in LAST_PREY_RISK).
        HUNT_BLAME = {
            'CHOKE_PINCH', 'PACK_HUNT', 'DENSITY_RAID', 'CLOSE_QUARTERS',
            'ETA_STRIKE', 'LANE_SWEEP', 'PAIR_LOCK', 'WALL_POUNCE',
            'SCREEN_HUNT', 'ROLE_SWEEP',
        }
        CARE_SIDS = {'LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_STALL'}
        if blunder and wt:
            used = (match.get('ticks') or {}).get(wt) or {}
            hunt_used = [(s, int(n or 0)) for s, n in used.items() if s in HUNT_BLAME]
            if hunt_used:
                blame_sid = max(hunt_used, key=lambda kv: kv[1])[0]
                if blame_sid in (TEAM_OVERLAYS.get(wt) or {}):
                    bov = TEAM_OVERLAYS[wt][blame_sid]
                    bst = _stats_bag(bov)
                    bst['last_prey_blunder'] = int(bst['last_prey_blunder']) + 1
                    bst['ema'] = float(bst.get('ema') or 0) - 0.45
                    bst['beta'] = float(bst.get('beta') or 1.0) + 1.4
                    bov['stats'] = bst
                    TEAM_OVERLAYS[wt][blame_sid] = bov
                    _DIRTY_OVERLAYS.add((wt, blame_sid))
                    row['blamed_strategy'] = blame_sid
        if wt in TEAM_OVERLAYS and ws in (TEAM_OVERLAYS.get(wt) or {}):
            ov = TEAM_OVERLAYS[wt][ws]
            st = _stats_bag(ov)
            st['conversions_for'] = int(st['conversions_for']) + 1
            if blunder:
                # CARE on the contact is occupancy, not the herding failure.
                if ws in CARE_SIDS:
                    st['ema'] = float(st.get('ema') or 0) - 0.05
                    st['beta'] = float(st.get('beta') or 1.0) + 0.15
                else:
                    st['last_prey_blunder'] = int(st['last_prey_blunder']) + 1
                    st['ema'] = float(st.get('ema') or 0) - 0.35
                    st['beta'] = float(st.get('beta') or 1.0) + 1.2
            else:
                st['ema'] = float(st.get('ema') or 0) + 0.04
                st['alpha'] = float(st.get('alpha') or 1.0) + 0.35
            if lt in ('ROCK', 'PAPER', 'SCISSORS'):
                vs = dict(st.get('by_vs') or {})
                slotv = dict(vs.get(lt) or {'alpha': 1.0, 'beta': 1.0, 'n': 0})
                slotv['n'] = int(slotv.get('n') or 0) + 1
                if blunder:
                    slotv['beta'] = float(slotv.get('beta') or 1.0) + 1.0
                else:
                    slotv['alpha'] = float(slotv.get('alpha') or 1.0) + 0.4
                vs[lt] = slotv
                st['by_vs'] = vs
            if blocked:
                st['blocked_womble'] = int(st['blocked_womble']) + 1
            by = dict(st.get('by_mode') or {})
            slot = dict(by.get(md) or {})
            slot['conversions_for'] = int(slot.get('conversions_for', 0)) + 1
            if blunder:
                slot['last_prey_blunder'] = int(slot.get('last_prey_blunder', 0)) + 1
            by[md] = slot
            st['by_mode'] = by
            ov['stats'] = st
            TEAM_OVERLAYS[wt][ws] = ov
            _DIRTY_OVERLAYS.add((wt, ws))
        if lt in TEAM_OVERLAYS and ls in (TEAM_OVERLAYS.get(lt) or {}):
            ov = TEAM_OVERLAYS[lt][ls]
            st = _stats_bag(ov)
            st['conversions_against'] = int(st['conversions_against']) + 1
            st['ema'] = float(st.get('ema') or 0) - 0.03
            st['beta'] = float(st.get('beta') or 1.0) + 0.25
            by = dict(st.get('by_mode') or {})
            slot = dict(by.get(md) or {})
            slot['conversions_against'] = int(slot.get('conversions_against', 0)) + 1
            by[md] = slot
            st['by_mode'] = by
            ov['stats'] = st
            TEAM_OVERLAYS[lt][ls] = ov
            _DIRTY_OVERLAYS.add((lt, ls))
    try:
        from optimizer import rl
        wipe = {}
        for row in match.get('conversions') or []:
            if int(row.get('last_prey_with_fear') or 0):
                ht = str(row.get('winner_type') or '')
                wipe[ht] = wipe.get(ht, 0) + 1
                rl.settle_convert(
                    ht, row.get('winner_strategy'), True,
                    prey_left=0, fear_left=1,
                    game_state='LAST_PREY_RISK')
        rl.settle_game(
            match.get('winner'),
            match.get('duration_s') or 0,
            wipe,
            match.get('state_ticks'),
            endgame_s=match.get('endgame_seconds') or 0,
            endgame_hunter=match.get('endgame_hunter'),
            ticks=match.get('ticks'))
    except Exception as e:
        try:
            from optimizer.paths import log_path
            with open(log_path('metrics_optimize.log'), 'a', encoding='utf-8') as f:
                f.write('rl.settle_game failed: %s\n' % e)
        except Exception:
            pass
    invalidate_spec_cache()


def strategy_decision_score(type_name, strategy_id):
    """Per-role payoff. Stall/last-man score time-alive, hunters score conversions."""
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id) or {}
    st = ov.get('stats') or {}
    cf = float(st.get('conversions_for') or 0)
    ca = float(st.get('conversions_against') or 0)
    bl = float(st.get('last_prey_blunder') or 0)
    games = max(1.0, float(st.get('games') or 1))
    ticks = float(st.get('ticks') or 0)
    wr = float(st.get('wins') or 0) / games
    states = set(((ov.get('when') or {}).get('states') or []))
    sid = str(strategy_id or '')
    stall = bool(states & {'LAST_PREY_RISK', 'LAST_MAN', 'NO_PREY_FEAR_ALIVE', 'NEAR_WIPE', 'OUTNUMBERED'})
    stall = stall or sid in (
        'LAST_MEAL_STALL', 'LAST_MAN_RUN', 'LAST_STAND', 'DELAY_FEAST',
        'SURVIVE_FEAR', 'BOUNCE_JUKE', 'ESCORT_RING')
    hunt_clear = 'CLEAR_HUNT' in states or sid in ('CLEAR_SPLIT',)
    ema = st.get('ema')
    ema_f = float(ema) if ema is not None else 0.0
    if stall:
        return 0.55 * ema_f + (ticks / max(80.0, games * 60.0)) + wr - 4.0 * bl - 0.15 * ca
    if hunt_clear:
        return 0.45 * ema_f + (cf / max(20.0, ticks)) * 8.0 + wr - 3.0 * bl
    return 0.50 * ema_f + (cf - ca) / max(8.0, ticks / 10.0) - 3.0 * bl + 0.5 * wr


def apply_learned(type_name, key, value):
    """Type-level prior only. Per-strategy overlays are updated by credit_decisions."""
    TYPE_DEFAULTS.setdefault(type_name, {})[key] = value


def nudge_all_overlays(type_name, key, value):
    """Write a learned knob onto every overlay for this type, not just TITLE's current card."""
    bag = TEAM_OVERLAYS.get(type_name) or {}
    for sid in list(bag.keys()):
        nudge_weight(type_name, sid, key, value)


# Load on import so particle / logger see STRATEGY_IDS immediately.
reload()
