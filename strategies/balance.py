"""Live class-balance locks.

GATE_CAMP x ROLE_SWEEP farmed Paper to ~8% over thousands of games.
Illegal cards cannot stay selected. Trailing type is forced onto its working set.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from strategies.meta_load import banned as _meta_banned, force as _meta_force, load as _meta_load

def _refresh():
    global BANNED, FORCE
    m = _meta_load(force=True)
    BANNED = {k: frozenset(v) for k, v in (m.get('banned') or {}).items()}
    FORCE = {k: {st: tuple(lst) for st, lst in (pool or {}).items()}
             for k, pool in (m.get('force') or {}).items()}
    if not BANNED:
        BANNED = _BANNED_FALLBACK
    if not FORCE:
        FORCE = _FORCE_FALLBACK

_BANNED_FALLBACK = {
    'PAPER': frozenset({
        'GATE_CAMP', 'DELAY_FEAST', 'PACK_HUNT', 'LANE_SWEEP', 'ROLE_SWEEP',
    }),
    'SCISSORS': frozenset({
        'ROLE_SWEEP', 'PACK_HUNT', 'LANE_SWEEP', 'GATE_CAMP', 'SCREEN_HUNT',
        'STALL_BREAK',
    }),
}

_FORCE_FALLBACK = {
    'PAPER': {
        'CONTESTED': ('FORT_KITE', 'OPEN_KITE', 'ORBIT_KITE', 'BOUNCE_JUKE', 'CROSS_LANE'),
        'OUTNUMBERED': ('FORT_KITE', 'OPEN_KITE', 'ORBIT_KITE'),
        'NO_PREY_FEAR_ALIVE': ('FEAR_RIDGE', 'FORT_KITE', 'OPEN_KITE'),
        'NEAR_WIPE': ('ESCORT_RING', 'LAST_MAN_RUN', 'OPEN_KITE'),
        'LAST_MAN': ('LAST_MAN_RUN', 'FEAR_RIDGE'),
        'CLEAR_HUNT': ('ETA_STRIKE', 'CROSS_LANE', 'CLEAR_SPLIT'),
        'LAST_PREY_RISK': ('LAST_PREY_CARE', 'LAST_MEAL_ORBIT', 'LAST_MEAL_STALL', 'GIVE_GROUND'),
    },
    'SCISSORS': {
        'CONTESTED': ('FORT_KITE', 'BOUNCE_JUKE', 'ORBIT_KITE', 'SURVIVE_FEAR'),
        'OUTNUMBERED': ('ORBIT_KITE', 'BOUNCE_JUKE', 'FORT_KITE'),
        'CLEAR_HUNT': ('CLEAR_SPLIT', 'ETA_STRIKE', 'CROSS_LANE'),
        'LAST_PREY_RISK': ('LAST_PREY_CARE', 'LAST_MEAL_ORBIT', 'GIVE_GROUND'),
        'NO_PREY_FEAR_ALIVE': ('SURVIVE_FEAR', 'ORBIT_KITE'),
        'NEAR_WIPE': ('ESCORT_RING', 'LAST_MAN_RUN'),
        'LAST_MAN': ('LAST_MAN_RUN', 'SURVIVE_FEAR'),
    },
    'ROCK': {
        'CONTESTED': ('SCREEN_HUNT', 'PACK_HUNT', 'ETA_STRIKE', 'LANE_SWEEP'),
        'CLEAR_HUNT': ('CLEAR_SPLIT', 'ETA_STRIKE'),
        'LAST_PREY_RISK': ('LAST_PREY_CARE', 'LAST_MEAL_ORBIT', 'GIVE_GROUND'),
        'NEAR_WIPE': ('ESCORT_RING', 'LAST_MAN_RUN'),
        'LAST_MAN': ('LAST_MAN_RUN',),
    },
}

_TARGET = 1.0 / 3.0
_share_cache = {'n': 0, 'share': {'ROCK': _TARGET, 'PAPER': _TARGET, 'SCISSORS': _TARGET}}


_refresh()

def _metrics_csv():
    return Path(__file__).resolve().parents[1] / 'optimizer' / 'metrics' / 'metrics_games.csv'


def recent_share(window=40):
    path = _metrics_csv()
    try:
        nfile = path.stat().st_size
    except OSError:
        return dict(_share_cache['share'])
    if _share_cache['n'] == nfile:
        return dict(_share_cache['share'])
    counts = Counter()
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        if len(lines) < 2:
            return dict(_share_cache['share'])
        header = lines[0].split(',')
        wi = header.index('winner') if 'winner' in header else 5
        for row in lines[-window:]:
            parts = row.split(',')
            if len(parts) <= wi:
                continue
            w = parts[wi].strip()
            if w in ('ROCK', 'PAPER', 'SCISSORS'):
                counts[w] += 1
    except Exception:
        return dict(_share_cache['share'])
    tot = sum(counts.values()) or 1
    share = {t: counts.get(t, 0) / tot for t in ('ROCK', 'PAPER', 'SCISSORS')}
    _share_cache['n'] = nfile
    _share_cache['share'] = share
    return dict(share)


def trailing_type(window=40):
    share = recent_share(window)
    return min(share, key=share.get), share


def evict(type_name, sid, state='CONTESTED'):
    t = str(type_name or '').upper()
    sid = str(sid or '')
    banned = BANNED.get(t) or frozenset()
    options = (FORCE.get(t) or {}).get(state) or (FORCE.get(t) or {}).get('CONTESTED') or ()
    share = recent_share(40)
    if t == 'PAPER' and state == 'CONTESTED' and share.get('PAPER', 0) < 0.28:
        options = ('FORT_KITE', 'OPEN_KITE', 'ORBIT_KITE', 'BOUNCE_JUKE')
    if t == 'SCISSORS' and state == 'CONTESTED' and share.get('SCISSORS', 0) > 0.38:
        options = ('BOUNCE_JUKE', 'FORT_KITE', 'SURVIVE_FEAR')
    if t == 'ROCK' and state == 'CONTESTED' and share.get('ROCK', 0) > 0.40:
        options = ('SCREEN_HUNT', 'ETA_STRIKE', 'ESCORT_RING')
    if state == 'LAST_PREY_RISK':
        options = (FORCE.get(t) or {}).get('LAST_PREY_RISK') or (
            'LAST_PREY_CARE', 'LAST_MEAL_ORBIT', 'GIVE_GROUND')
        if sid not in options:
            return options[0], True
    if sid in banned or (options and sid not in options and state == 'CONTESTED'):
        return (options[0] if options else sid), True
    return sid, False


def force_pool(type_name, state):
    t = str(type_name or '').upper()
    return list((FORCE.get(t) or {}).get(state) or ())
