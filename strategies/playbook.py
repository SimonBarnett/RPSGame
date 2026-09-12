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
_MAP_CELLS = None
_MAP_MTIME = 0.0
_GROK_LAST_GAMES = -1
_GROK_BRIEF_EVERY = 20
PERSIST_BO_OBS = 20
CURRENT_TEAM = 12


def set_match_context(team_size=None):
    global CURRENT_TEAM
    if team_size is None:
        return
    try:
        CURRENT_TEAM = max(1, int(team_size))
    except Exception:
        pass

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
JS_STRATEGIES = os.path.join(os.path.dirname(ROOT), 'rps_pub', 'strategies')

# Populated by reload()
MATH_MODULES = {}
TACTICS = {}
STRATEGIES = {}          # template id -> spec
TEAM_OVERLAYS = {}       # type -> id -> overlay
STRATEGY_IDS = ()
DEFAULT_ORDER = ()
_SPEC_CACHE = {}
_DIRTY_OVERLAYS = set()
_LAST_WRITTEN = []
_BOOK_CACHE = {}


def _read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _shrink_ab(slot, cap=24.0):
    """Keep a small Thompson posterior; do not persist conversion counts."""
    if not isinstance(slot, dict):
        return slot
    try:
        a = float(slot.get('alpha') or 1.0)
        b = float(slot.get('beta') or 1.0)
    except Exception:
        return slot
    s = a + b
    if s > cap:
        k = cap / s
        slot['alpha'] = a * k
        slot['beta'] = b * k
    return slot


def _disk_overlay(ov, for_js=False):
    """Strip learner-only bags before a NAS write. JS is play-only."""
    if not isinstance(ov, dict):
        return ov
    out = dict(ov)
    out.pop('last_changes', None)
    if for_js:
        st = dict(out.get('stats') or {})
        bys = {}
        for k, v in (st.get('by_state') or {}).items():
            if isinstance(v, dict):
                bys[k] = {
                    'alpha': float(v.get('alpha') or 1.0),
                    'beta': float(v.get('beta') or 1.0),
                }
        out['stats'] = {
            'alpha': float(st.get('alpha') or 1.0),
            'beta': float(st.get('beta') or 1.0),
            'ema': float(st.get('ema') or 0.0),
            'by_state': bys,
        }
        out.pop('q', None)
        out.pop('games_seen', None)
        return out
    st = dict(out.get('stats') or {})
    st.pop('q', None)
    st.pop('pulls', None)
    st.pop('pulls_by_state', None)
    st.pop('mc_G', None)
    bo = dict(st.get('bo') or {})
    if bo:
        n = PERSIST_BO_OBS
        st['bo'] = {
            'keys': list(bo.get('keys') or []),
            'X': list(bo.get('X') or [])[-n:],
            'y': list(bo.get('y') or [])[-n:],
            'c': list(bo.get('c') or [])[-n:],
        }
    vs = dict(st.get('by_vs') or {})
    for lt, slot in list(vs.items()):
        vs[lt] = _shrink_ab(dict(slot or {}))
    st['by_vs'] = vs
    bys = dict(st.get('by_state') or {})
    for stname, slot in list(bys.items()):
        bys[stname] = _shrink_ab(dict(slot or {}))
    st['by_state'] = bys
    out['stats'] = st
    out.pop('q', None)
    return out


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
_LAST_WRITTEN = []
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
    try:
        b = _meta_banned(type_name)
        if b:
            return b
    except Exception:
        pass
    return BANNED.get(str(type_name or "").upper(), frozenset())

def _fallback(type_name, legal=None):
    legal = [s for s in (legal or []) if s and s not in _banned(type_name)]
    if legal:
        return legal[0]
    for sid in FALLBACK.get(str(type_name or "").upper(), ("PACK_HUNT",)):
        return sid
    return "PACK_HUNT"

CARD_FOR_STATE = {
    'CLEAR_HUNT': ['CLEAR_SPLIT', 'CLEAR_FAN', 'FINISH_CLOCK', 'PACK_HUNT'],
    'LAST_PREY_RISK': ['LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_ORBIT'],
    'LAST_MAN': ['LAST_MAN_RUN', 'SURVIVE_FEAR', 'ORBIT_KITE'],
    'NEAR_WIPE': ['BODY_CHECK', 'LAST_MAN_RUN', 'SURVIVE_FEAR', 'SCATTER_RAID'],
    'NO_PREY_FEAR_ALIVE': ['SURVIVE_FEAR', 'ORBIT_KITE', 'SHADOW_PREY', 'HOLD_COVER'],
    'OUTNUMBERED': ['GIVE_GROUND', 'HOLD_COVER', 'SHADOW_PREY'],
    'SMALL_UNIT': ['SCATTER_RAID', 'OPEN_KITE', 'SCREEN_HUNT'],
    'CONTESTED': ['PACK_HUNT', 'SCREEN_HUNT', 'OPEN_KITE', 'ESCORT_RING'],
}
ENDGAME_STATES = frozenset({
    'CLEAR_HUNT', 'LAST_MAN', 'NO_PREY_FEAR_ALIVE', 'NEAR_WIPE', 'LAST_PREY_RISK',
})


def match_state(self_n, fear_n, prey_n):
    """Same order as rps.js gameState. Play-only; learning does not change this."""
    self_n = int(self_n or 0)
    fear_n = int(fear_n or 0)
    prey_n = int(prey_n or 0)
    if self_n <= 0:
        return 'DEAD'
    if fear_n <= 0 and prey_n > 0:
        return 'CLEAR_HUNT'
    if fear_n > 0 and prey_n <= 0:
        return 'NO_PREY_FEAR_ALIVE'
    if self_n == 1 and fear_n > 0:
        return 'LAST_MAN'
    if self_n <= 2 and fear_n > 0:
        return 'NEAR_WIPE'
    try:
        from strategies.meta_load import last_prey_max
        lp = int(last_prey_max() or 2)
    except Exception:
        lp = 2
    if fear_n > 0 and prey_n <= lp:
        return 'LAST_PREY_RISK'
    if fear_n > self_n:
        return 'OUTNUMBERED'
    if self_n <= 3 and fear_n > 0:
        return 'SMALL_UNIT'
    return 'CONTESTED'


def _legal_ids(type_name, state):
    """Same legal set as rps.js legalFromJson: when.states, meta banned, meta force."""
    if not STRATEGY_IDS:
        reload()
    ban = _banned(type_name)
    bag = TEAM_OVERLAYS.get(type_name) or {}
    legal = []
    for sid in STRATEGY_IDS or list_ids():
        spec = spec_for(type_name or 'ROCK', sid) if type_name else (STRATEGIES.get(sid) or {})
        if spec.get('enabled', True) is False:
            continue
        if sid in ban:
            continue
        states = (spec.get('when') or {}).get('states') or []
        if state in states:
            legal.append(sid)
    try:
        forced_ids = list(_meta_force(type_name, state) or ())
    except Exception:
        forced_ids = []
    if forced_ids:
        forced = [s for s in forced_ids if s in bag and s not in ban]
        if forced:
            legal = forced
    if not legal:
        pool = CARD_FOR_STATE.get(str(state or ''), CARD_FOR_STATE['CONTESTED'])
        legal = [s for s in pool if (s in bag or s in (STRATEGIES or {})) and s not in ban]
    if str(state) == 'LAST_PREY_RISK':
        care = CARD_FOR_STATE.get('LAST_PREY_RISK') or []
        legal = [s for s in legal if s in care]
        if not legal:
            legal = [s for s in care if (s in bag or s in (STRATEGIES or {})) and s not in ban]
    return legal


def _card_mean(type_name, strategy_id, state=None):
    """Greedy posterior mean. Same formula as rps.js cardMean (no Thompson)."""
    st = ((TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id) or {}).get('stats') or {}
    slot = {}
    if state:
        slot = ((st.get('by_state') or {}).get(state) or {})
    try:
        a = float(slot.get('alpha', st.get('alpha', 1.0)) or 1.0)
        b = float(slot.get('beta', st.get('beta', 1.0)) or 1.0)
    except Exception:
        return 0.33
    if a + b <= 0:
        return 0.33
    return a / (a + b)


def pick_card(type_name, state):
    """Play-only greedy pick. Learning updates JSON after the match, not here."""
    legal = _legal_ids(type_name, state)
    if not legal:
        pool = CARD_FOR_STATE.get(str(state or ''), CARD_FOR_STATE['CONTESTED'])
        return pool[0]
    best, best_s = legal[0], -1e18
    for sid in legal:
        spec = spec_for(type_name, sid)
        pri = float((spec.get('when') or {}).get('priority', 50) or 50)
        mu = _card_mean(type_name, sid, state)
        s = mu * 10.0 + pri * 0.01
        if s > best_s:
            best_s, best = s, sid
    return best


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
    try:
        champ = _map_champion(type_name, state)
        if champ and strategy_id == champ:
            q += 0.08
    except Exception:
        pass
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


def set_map_cells(cells):
    """In-process MAP archive. Avoid getmtime on the NAS inside select()."""
    global _MAP_CELLS, _MAP_MTIME
    _MAP_CELLS = list(cells or [])
    _MAP_MTIME = -1.0


def _map_champion(type_name, state, team_size=None):
    """Sid occupying this (state, team_bucket, type) niche, else any bucket."""
    global _MAP_CELLS, _MAP_MTIME
    if _MAP_CELLS is None:
        try:
            from optimizer.paths import grok_path
            path = grok_path('map_elites.json')
            raw = _read_json(path, {}) or {}
            _MAP_CELLS = list(raw.get('cells') or [])
            _MAP_MTIME = -1.0
        except Exception:
            _MAP_CELLS = []
    st = str(state or '')
    tn = str(type_name or '')
    try:
        ts = int(team_size if team_size is not None else CURRENT_TEAM or 12)
    except Exception:
        ts = 12
    bucket = 24
    for e in (8, 12, 16, 24):
        if ts <= e:
            bucket = e
            break
    exact, any_b = None, None
    for cell in _MAP_CELLS:
        if str(cell.get('type') or '') != tn:
            continue
        if str(cell.get('state') or '') != st:
            continue
        vis = int(cell.get('visits') or 0)
        if int(cell.get('team_bucket') or 0) == bucket:
            if exact is None or vis > int(exact.get('visits') or 0):
                exact = cell
        if any_b is None or vis > int(any_b.get('visits') or 0):
            any_b = cell
    hit = exact or any_b
    return (hit or {}).get('sid')


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
    if random.random() < max(0.0, min(0.15, float(explore))):
        pick = random.choice(legal)
        _note_pull(type_name, pick, state)
        return pick
    best_sid, best_s = legal[0], -1e9
    for sid in legal:
        score = _select_score(type_name, sid, state, opponent=opponent)
        if score > best_s:
            best_s, best_sid = score, sid
    _note_pull(type_name, best_sid, state)
    return best_sid


def strategy_for_state(state, type_name=None, opponent=None):
    return pick_card(type_name, state)


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
    """JS has no separate endgame picker — hold skip lives in select()."""
    return None


def select(type_name, game_state, current=None, hold_frames=0, opponent=None):
    """Same as rps.js pickCardHold. Returns (strategy_id, new_hold_frames, switched)."""
    if not STRATEGY_IDS:
        reload()
    state = str(game_state or 'CONTESTED')
    desired = pick_card(type_name, state)
    legal = _legal_ids(type_name, state)
    if current in _banned(type_name):
        return desired, 0, True
    if state in ENDGAME_STATES and current != desired:
        return desired, 0, True
    if not current or current == desired:
        return desired, 0, False
    if legal and current not in legal:
        return desired, 0, True
    spec = spec_for(type_name, desired)
    sw = spec.get('switch') or {}
    hold_need = max(1, int(sw.get('hold_frames', 8) or 8))
    margin = float(sw.get('margin', 1.0) or 1.0)
    hold_frames = int(hold_frames) + 1
    if hold_frames >= hold_need * margin:
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
    mag = max(0.25, min(1.4, abs(float(strength))))
    span = max(1e-9, float(hi) - float(lo))
    at_lo = (cur_f - float(lo)) / span <= 0.02
    at_hi = (float(hi) - cur_f) / span <= 0.02
    if at_lo and direction < 0:
        direction = 1
        mag = min(mag, 0.45)
    elif at_hi and direction > 0:
        direction = -1
        mag = min(mag, 0.45)
    nxt = cur_f + direction * step * mag
    if path.endswith('hold_frames') or path.endswith('priority') or path.endswith('ttl'):
        nxt = int(round(nxt))
    nxt = max(lo, min(hi, nxt))
    if path.endswith('hold_frames'):
        nxt = max(2, min(24, int(nxt)))
        if strategy_id in (
                'LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_STALL', 'LAST_MEAL_ORBIT'):
            nxt = max(10, nxt)
    if abs(nxt - cur_f) < abs(step) * 0.05:
        return None
    _set_path(ov, path, nxt)
    TEAM_OVERLAYS[type_name][strategy_id] = ov
    try:
        _DIRTY_OVERLAYS.add((type_name, strategy_id))
    except Exception:
        pass
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
    global _DIRTY_OVERLAYS, _LAST_WRITTEN
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
        _write_json(path, _disk_overlay(ov, for_js=False))
        written.append(path)
    if written:
        _LAST_WRITTEN.extend(written)
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


def write_grok_brief(metrics=None, force=False):
    """Human + machine snapshot Grok can read to invent the next strategy.

    Throttled: full overlay dumps stall the next match on NAS.
    """
    global _GROK_LAST_GAMES
    games = 0
    try:
        from optimizer.logger import Metrics
        games = int(Metrics.read_games_total() or 0)
    except Exception:
        games = 0
    if (not force) and _GROK_LAST_GAMES >= 0 and (games - _GROK_LAST_GAMES) < _GROK_BRIEF_EVERY:
        return None
    _GROK_LAST_GAMES = games
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
    slim = {}
    for t in TYPES:
        bag = {}
        for sid, ov in (TEAM_OVERLAYS.get(t) or {}).items():
            st = (ov or {}).get('stats') or {}
            bag[sid] = {
                'id': sid,
                'ticks': int(st.get('ticks') or 0),
                'games': int(st.get('games') or 0),
                'wins': float(st.get('wins') or 0),
                'blunder': int(st.get('last_prey_blunder') or 0),
                'ema': round(float(st.get('ema') or 0), 4),
            }
        slim[t] = bag
    snap = {
        'math': MATH_MODULES,
        'tactics': TACTICS,
        'templates': {k: {
            'id': k,
            'mode': (v or {}).get('mode'),
            'when': (v or {}).get('when'),
            'tactics': (v or {}).get('tactics'),
            'math': (v or {}).get('math'),
        } for k, v in (STRATEGIES or {}).items()},
        'overlays': slim,
        'ids': list(STRATEGY_IDS),
        'games': games,
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
    global _LAST_WRITTEN
    written = save_all_overlays(force=False)
    pending = []
    seen = set()
    for p in list(written) + list(_LAST_WRITTEN):
        if p and p not in seen:
            seen.add(p)
            pending.append(p)
    _LAST_WRITTEN = []
    for t in TYPES:
        try:
            os.remove(_profile_path(t))
        except Exception:
            pass
        if any(os.path.basename(os.path.dirname(p)) == t for p in pending):
            write_type_index(t)
    try:
        from config import Config
        fast = bool(getattr(Config, 'FAST_SIM', False))
    except Exception:
        fast = False
    try:
        if not fast:
            full = bool(games_seen) and (int(games_seen) % 200 == 0)
            publish_to_js(paths=pending, full=full)
    except Exception:
        pass
    try:
        if not fast:
            write_grok_brief(force=False)
    except Exception:
        pass
    return pending


def write_type_index(type_name):
    """JS loadTeamBook reads types/{T}/index.json. Keep it next to the overlays."""
    d = os.path.join(TYPES_DIR, type_name)
    names = []
    try:
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.json') or fn.endswith('.tmp.json'):
                continue
            if '.tmp' in fn:
                continue
            sid = fn[:-5]
            if sid == 'index':
                continue
            names.append(sid)
    except Exception:
        return None
    path = os.path.join(d, 'index.json')
    _write_json(path, names)
    return path


def publish_to_js(dest=None, paths=None, full=False):
    """Mirror strategy JSON into rps_pub/strategies so the embed is a copy, not a fork."""
    import shutil
    dest = dest or JS_STRATEGIES
    if not dest or not os.path.isdir(os.path.dirname(dest)):
        return []
    os.makedirs(dest, exist_ok=True)
    copied = []
    if not full:
        for src in paths or ():
            if not src or not os.path.isfile(src):
                continue
            try:
                rel = os.path.relpath(src, ROOT)
            except Exception:
                continue
            if rel.startswith('..'):
                continue
            dst = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(dst) or dest, exist_ok=True)
            ov = _read_json(src, None)
            if isinstance(ov, dict) and ov.get('id'):
                _write_json(dst, _disk_overlay(ov, for_js=True))
            else:
                shutil.copy2(src, dst)
            copied.append(dst)
        return copied
    skip_dir = {'__pycache__'}
    skip_ext = {'.py', '.pyc', '.pyo', '.md'}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in skip_dir]
        rel = os.path.relpath(root, ROOT)
        out_dir = dest if rel == '.' else os.path.join(dest, rel)
        os.makedirs(out_dir, exist_ok=True)
        for fn in files:
            if fn.endswith('.tmp') or '.tmp.' in fn:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in skip_ext:
                continue
            if ext != '.json' and fn != 'SCHEMA.md':
                continue
            src = os.path.join(root, fn)
            dst = os.path.join(out_dir, fn)
            ov = _read_json(src, None)
            if isinstance(ov, dict) and (ov.get('id') or ov.get('weights') or ov.get('when')):
                _write_json(dst, _disk_overlay(ov, for_js=True))
            else:
                shutil.copy2(src, dst)
            copied.append(dst)
    for t in TYPES:
        td = os.path.join(dest, 'types', t)
        if not os.path.isdir(td):
            continue
        for fn in os.listdir(td):
            if '.tmp' in fn:
                try:
                    os.remove(os.path.join(td, fn))
                except Exception:
                    pass
    return copied



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
    try:
        set_match_context(match.get('teamSize'))
    except Exception:
        pass
    MIN_CREDIT = 8
    MIN_SHARE = 0.08
    EMA = 0.12
    CARE_SIDS = {
        'LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_STALL', 'LAST_MEAL_ORBIT',
    }
    SHORT_STATES = {
        'LAST_PREY_RISK', 'LAST_MAN', 'NEAR_WIPE', 'NO_PREY_FEAR_ALIVE',
    }
    type_blunder = set()
    for row in match.get('conversions') or []:
        if int(row.get('last_prey_with_fear') or 0):
            ht = str(row.get('winner_type') or '').upper()
            if ht:
                type_blunder.add(ht)
    for tname in types:
        bag = TEAM_OVERLAYS.setdefault(tname, {})
        used = ticks.get(tname) or {}
        modes = mode_ticks.get(tname) or {}
        type_ticks = float(sum(int(v or 0) for v in used.values()) or 1)
        for sid, n in used.items():
            if sid not in bag:
                continue
            n = int(n or 0)
            if n <= 0:
                continue
            ov = bag[sid]
            st = _stats_bag(ov)
            st['ticks'] = int(st['ticks']) + n
            share = n / type_ticks
            care = sid in CARE_SIDS
            state_bag = ((match.get('state_ticks') or {}).get(tname) or {}).get(sid) or {}
            if not isinstance(state_bag, dict):
                state_bag = {}
            short_n = sum(int(v or 0) for k, v in state_bag.items() if str(k) in SHORT_STATES)
            credited = (n >= 1) if (care or short_n >= 1) else (n >= MIN_CREDIT and share >= MIN_SHARE)
            if not credited:
                st['glimpse'] = int(st.get('glimpse') or 0) + 1
                payoff = -0.02
            else:
                st['games'] = int(st['games']) + 1
                if care:
                    clean = tname not in type_blunder
                    payoff = 0.15 * share + (0.28 if clean else -0.40)
                else:
                    if tname == winner:
                        st['wins'] = float(st.get('wins') or 0) + share
                        st['alpha'] = float(st.get('alpha') or 1.0) + share
                    else:
                        st['beta'] = float(st.get('beta') or 1.0) + share
                    payoff = (share if tname == winner else -0.25 * share)
                    if int(st.get('last_prey_blunder') or 0):
                        st['beta'] = float(st.get('beta') or 1.0) + 0.4
            st['ema'] = (1.0 - EMA) * float(st.get('ema') or 0) + EMA * payoff
            bys = dict(st.get('by_state') or {})
            for stname, cn in (state_bag or {}).items():
                cn = int(cn or 0)
                if cn <= 0:
                    continue
                stname = str(stname)
                slot = dict(bys.get(stname) or {'n': 0, 'alpha': 1.0, 'beta': 1.0, 'ema': 0.0})
                slot['n'] = int(slot.get('n') or 0) + cn
                state_credit = (cn >= 1) if stname in SHORT_STATES else credited
                if state_credit:
                    frac = share * (cn / float(n))
                    if care:
                        if tname not in type_blunder:
                            slot['alpha'] = float(slot.get('alpha') or 1.0) + frac
                        else:
                            slot['beta'] = float(slot.get('beta') or 1.0) + frac
                    elif tname == winner:
                        slot['alpha'] = float(slot.get('alpha') or 1.0) + frac
                    else:
                        slot['beta'] = float(slot.get('beta') or 1.0) + frac
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
            if credited:
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
        CARE_SIDS = {
            'LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_STALL', 'LAST_MEAL_ORBIT',
        }
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
                    bys = dict(bst.get('by_state') or {})
                    slot = dict(bys.get('LAST_PREY_RISK') or {'n': 0, 'alpha': 1.0, 'beta': 1.0, 'ema': 0.0})
                    slot['n'] = int(slot.get('n') or 0) + 1
                    slot['beta'] = float(slot.get('beta') or 1.0) + 1.4
                    slot['ema'] = float(slot.get('ema') or 0) - 0.45
                    bys['LAST_PREY_RISK'] = slot
                    bst['by_state'] = bys
                    bov['stats'] = bst
                    TEAM_OVERLAYS[wt][blame_sid] = bov
                    _DIRTY_OVERLAYS.add((wt, blame_sid))
                    row['blamed_strategy'] = blame_sid
        if wt in TEAM_OVERLAYS and ws in (TEAM_OVERLAYS.get(wt) or {}):
            ov = TEAM_OVERLAYS[wt][ws]
            st = _stats_bag(ov)
            if ws in CARE_SIDS:
                # Forced stall occupancy — do not treat contact as a hunt conversion.
                if blunder:
                    st['ema'] = float(st.get('ema') or 0) - 0.05
            else:
                st['conversions_for'] = int(st['conversions_for']) + 1
                if blunder:
                    st['last_prey_blunder'] = int(st['last_prey_blunder']) + 1
                    st['ema'] = float(st.get('ema') or 0) - 0.35
                    st['beta'] = float(st.get('beta') or 1.0) + 1.2
                else:
                    st['ema'] = float(st.get('ema') or 0) + 0.04
                    st['alpha'] = float(st.get('alpha') or 1.0) + 0.35
            if lt in ('ROCK', 'PAPER', 'SCISSORS') and ws not in CARE_SIDS:
                vs = dict(st.get('by_vs') or {})
                slotv = dict(vs.get(lt) or {'alpha': 1.0, 'beta': 1.0, 'n': 0})
                slotv['n'] = int(slotv.get('n') or 0) + 1
                if blunder:
                    slotv['beta'] = float(slotv.get('beta') or 1.0) + 1.0
                else:
                    slotv['alpha'] = float(slotv.get('alpha') or 1.0) + 0.4
                vs[lt] = _shrink_ab(slotv)
                st['by_vs'] = vs
            near_ticks = 0
            try:
                sbag = ((match.get('state_ticks') or {}).get(wt) or {}).get(ws) or {}
                if isinstance(sbag, dict):
                    near_ticks = int(sbag.get('NEAR_WIPE') or 0)
            except Exception:
                near_ticks = 0
            if near_ticks > 0 and not blunder:
                st['alpha'] = float(st.get('alpha') or 1.0) + 0.55
                st['ema'] = float(st.get('ema') or 0) + 0.08
                bys = dict(st.get('by_state') or {})
                slotn = dict(bys.get('NEAR_WIPE') or {'n': 0, 'alpha': 1.0, 'beta': 1.0, 'ema': 0.0})
                slotn['alpha'] = float(slotn.get('alpha') or 1.0) + 0.55
                bys['NEAR_WIPE'] = slotn
                st['by_state'] = bys
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
    try:
        from optimizer import mcts as _mcts
        _mcts.flush()
    except Exception:
        pass
    invalidate_spec_cache()


def strategy_decision_score(type_name, strategy_id):
    """Per-role payoff in roughly [-2, 2]. Blunders are a rate, not a count."""
    ov = (TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id) or {}
    st = ov.get('stats') or {}
    cf = float(st.get('conversions_for') or 0)
    ca = float(st.get('conversions_against') or 0)
    bl = float(st.get('last_prey_blunder') or 0)
    games = max(1.0, float(st.get('games') or 1))
    ticks = float(st.get('ticks') or 0)
    wr = float(st.get('wins') or 0) / games
    bl_rate = min(1.0, bl / games)
    states = set(((ov.get('when') or {}).get('states') or []))
    sid = str(strategy_id or '')
    stall = bool(states & {'LAST_PREY_RISK', 'LAST_MAN', 'NO_PREY_FEAR_ALIVE', 'NEAR_WIPE', 'OUTNUMBERED'})
    stall = stall or sid in (
        'LAST_MEAL_STALL', 'LAST_MAN_RUN', 'LAST_STAND', 'DELAY_FEAST',
        'SURVIVE_FEAR', 'BOUNCE_JUKE', 'ESCORT_RING', 'LAST_PREY_CARE',
        'LAST_MEAL_ORBIT')
    hunt_clear = 'CLEAR_HUNT' in states or sid in ('CLEAR_SPLIT', 'CLEAR_FAN')
    ema = st.get('ema')
    ema_f = max(-1.0, min(1.0, float(ema) if ema is not None else 0.0))
    if stall:
        alive = math.tanh(ticks / max(80.0, games * 80.0))
        score = 0.45 * ema_f + 0.25 * alive + 0.20 * wr - 1.6 * bl_rate
    elif hunt_clear:
        krate = math.tanh(8.0 * cf / max(20.0, ticks))
        score = 0.40 * ema_f + 0.35 * krate + 0.20 * wr - 1.4 * bl_rate
    else:
        conv = math.tanh((cf - ca) / max(8.0, ticks / 10.0))
        score = 0.40 * ema_f + 0.30 * conv + 0.25 * wr - 1.5 * bl_rate
    return max(-2.0, min(2.0, score))


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
