"""First-visit Monte Carlo for strategy Q.

Policy stays Thompson + UCB in playbook.select. This module only writes a
Q bonus. One episode = one match.

Objectives, in order:
  1. Win the match.
  2. Do not convert last 1–3 prey while your predator is alive.
  3. Endgame: hunter → short CLEAR_HUNT; remaining prey → long evade.

Return G is computed once at gameover and applied to every first (s, a)
this type visited. No max-Q bootstrap (avoids lucky CHOKE inflation).
"""
from __future__ import annotations

import json
import math
import os

from optimizer.paths import METRICS

Q_PATH = os.path.join(METRICS, 'rl_q.json')
ALPHA = 0.10
Q_CLAMP = 6.0

_Q = {}          # type -> state -> action -> value
_EP = {}         # type -> [(state, action), ...] first visits
_SEEN = {}       # type -> set((state, action))


def _load():
    global _Q
    if _Q:
        return
    try:
        raw = json.load(open(Q_PATH, encoding='utf-8'))
        if isinstance(raw, dict):
            _Q = raw
    except Exception:
        _Q = {}


def _save():
    try:
        os.makedirs(METRICS, exist_ok=True)
        tmp = Q_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_Q, f)
        os.replace(tmp, Q_PATH)
    except Exception:
        pass


def state_key(game_state, prey_count, fear_count):
    pc = 4 if prey_count is None else max(0, min(4, int(prey_count)))
    fc = 1 if (fear_count or 0) > 0 else 0
    return '%s|p%d|f%d' % (game_state or 'CONTESTED', pc, fc)


def q_get(type_name, state, action):
    _load()
    return float(((_Q.get(type_name) or {}).get(state) or {}).get(action) or 0.0)


def q_set(type_name, state, action, value):
    _load()
    bag = _Q.setdefault(type_name, {})
    slot = bag.setdefault(state, {})
    slot[action] = max(-Q_CLAMP, min(Q_CLAMP, float(value)))


def bonus(type_name, game_state, strategy_id, prey_count=None, fear_count=None):
    s = state_key(game_state, prey_count, fear_count)
    return 0.30 * math.tanh(q_get(type_name, s, strategy_id) / 2.0)


def remember(type_name, game_state, strategy_id, prey_count=None, fear_count=None):
    """First visit only — occupancy must not drown the Q update."""
    if not type_name or not strategy_id:
        return
    s = state_key(game_state, prey_count, fear_count)
    key = (s, str(strategy_id))
    seen = _SEEN.setdefault(type_name, set())
    if key in seen:
        return
    seen.add(key)
    _EP.setdefault(type_name, []).append(key)


def _mc_update(type_name, G):
    for s, a in _EP.get(type_name) or []:
        q = q_get(type_name, s, a)
        q_set(type_name, s, a, q + ALPHA * (G - q))


def _dur_scale():
    """FAST_SIM matches are ~1–8s of tick time; live is ~20–50s."""
    try:
        from config import Config
        if getattr(Config, 'FAST_SIM', False):
            return 0.28
    except Exception:
        pass
    return 1.0


def _num(v, default=0.0):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return float(default)


def _state_occupancy(state_ticks, type_name):
    """Flatten to {state: ticks}.

    Logger sends strategy_state_ticks as {type: {sid: {state: n}}}.
    Older callers may pass {type: {state: n}}.
    """
    bag = (state_ticks or {}).get(type_name) or {}
    if not isinstance(bag, dict):
        return {}
    out = {}
    for k, v in bag.items():
        if isinstance(v, dict):
            for st, n in v.items():
                out[str(st)] = out.get(str(st), 0.0) + _num(n)
        else:
            out[str(k)] = out.get(str(k), 0.0) + _num(v)
    return out


def episode_return(type_name, winner, duration_s, wipe_by_type,
                   endgame_s=0.0, endgame_hunter=None, state_ticks=None):
    """Scalar G for this type this match."""
    dur = _num(duration_s)
    eg = _num(endgame_s)
    won = 1.0 if str(winner or '').upper() == type_name else 0.0
    wiped = _num((wipe_by_type or {}).get(type_name, 0)) > 0
    sc = _dur_scale()
    sc = max(0.55, sc)
    wipe_short = 10.0
    dur_center = 18.0
    dur_span = 12.0

    # 1. Win, but not a 3-second blob melt
    G = 1.15 * won
    if won and dur < 8.0:
        G -= 0.85

    # 2. Not-losing: longer match is always good.
    G += 0.55 * math.tanh((dur - dur_center) / dur_span)
    if wiped:
        G -= 2.80
        G -= 0.55 * max(0.0, (wipe_short - dur) / max(1e-6, wipe_short))
        G -= 0.25 * won
    else:
        occ = _state_occupancy(state_ticks, type_name)
        care = occ.get('LAST_PREY_RISK', 0.0)
        total = sum(occ.values()) or 1.0
        if care / total > 0.06:
            G += 0.22

    # 3. Long endgame rallies are good for hunter and prey.
    if eg > 0.4:
        G += 0.30 * math.tanh((eg - 6.0) / 8.0)

    return max(-5.0, min(4.0, G))


def settle_game(winner, duration_s, wipe_by_type, state_ticks=None,
                endgame_s=0.0, endgame_hunter=None, ticks=None):
    _load()
    # Seed first-visits from occupancy if Team.update never called remember.
    for t, bag in (ticks or {}).items():
        t = str(t).upper()
        for sid, n in (bag or {}).items():
            if _num(n) <= 0:
                continue
            st_bag = ((state_ticks or {}).get(t) or {}).get(sid) or {}
            names = []
            if isinstance(st_bag, dict) and st_bag:
                names = [k for k, v in st_bag.items() if _num(v) > 0]
            if not names:
                if t in (wipe_by_type or {}) and wipe_by_type.get(t):
                    names = ['LAST_PREY_RISK']
                else:
                    names = ['CONTESTED']
            for st_name in names:
                remember(t, st_name, sid, prey_count=2 if st_name == 'LAST_PREY_RISK' else 4,
                         fear_count=1 if st_name in ('LAST_PREY_RISK', 'NO_PREY_FEAR_ALIVE',
                                                    'OUTNUMBERED', 'NEAR_WIPE', 'LAST_MAN') else 0)
    for t in ('ROCK', 'PAPER', 'SCISSORS'):
        G = episode_return(
            t, winner, duration_s, wipe_by_type,
            endgame_s=endgame_s, endgame_hunter=endgame_hunter,
            state_ticks=state_ticks)
        _mc_update(t, G)
        # Ride along on overlays so Q survives even if rl_q.json is dropped.
        try:
            import strategies.playbook as pb
            for s, a in list(_EP.get(t) or []):
                ov = (pb.TEAM_OVERLAYS.get(t) or {}).get(a)
                if not ov:
                    continue
                st = dict(ov.get('stats') or {})
                qbag = dict(st.get('q') or {})
                qbag[s] = q_get(t, s, a)
                st['q'] = qbag
                st['mc_G'] = round(G, 4)
                ov['stats'] = st
                pb.TEAM_OVERLAYS[t][a] = ov
                pb._DIRTY_OVERLAYS.add((t, a))
        except Exception:
            pass
    _EP.clear()
    _SEEN.clear()
    _save()


def settle_convert(hunter, hunter_sid, last_prey_with_fear, prey_left, fear_left,
                   game_state=None):
    """Record the visit; the return is applied at settle_game.

    A last-prey-with-fear convert also writes an immediate first-visit so the
    hunting doctrine is in the episode even if select never logged it.
    """
    if not hunter:
        return
    remember(hunter, game_state or 'LAST_PREY_RISK', hunter_sid or 'PACK_HUNT',
             prey_count=max(0, int(prey_left or 0)),
             fear_count=1 if last_prey_with_fear or (fear_left or 0) > 0 else 0)
