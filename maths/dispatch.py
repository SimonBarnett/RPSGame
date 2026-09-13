"""Resolve movement[].fn names from strategy JSON to math binaries."""

import math

from maths.flow import FlowField
from maths.roles import Roles
from maths.form import Formation
from maths.orbit import Orbit
from maths.pressure import PressureField
from maths.time import TimeTo
from maths.lanes import Lanes
from maths.intercept import Intercept
from maths.desync import Desync
from maths.boids import SwarmIntelligence


def _as_heading(h):
    """Math modules may return an angle or a (dx, dy) unit vector."""
    if h is None:
        return None
    if isinstance(h, (tuple, list)) and len(h) >= 2:
        try:
            return math.atan2(float(h[0]), -float(h[1]))
        except Exception:
            return None
    try:
        return float(h)
    except Exception:
        return None


def _blend(a, b, t):
    if a is None:
        return b
    if b is None:
        return a
    a = _as_heading(a)
    b = _as_heading(b)
    if a is None:
        return b
    if b is None:
        return a
    return SwarmIntelligence.blend_headings(a, b, blend=max(0.0, min(1.0, float(t))))


def _hash_heading(p, **k):
    """Nearest prey in the spatial hash (CLOSE_QUARTERS / HASH_MELEE)."""
    w = getattr(p, 'w', None)
    spatial = getattr(w, 'spatial', None) if w is not None else None
    if spatial is None:
        return None
    from config import PREY_OF
    prey_t = PREY_OF.get(getattr(p, 'type', None))
    r = float(k.get('radius') or (getattr(p, 'size', 20) * 7.0))
    try:
        near = spatial.query(p.x, p.y, r) or []
    except Exception:
        return None
    best, best_d = None, 1e18
    for q in near:
        if q is p or getattr(q, 'type', None) != prey_t:
            continue
        d2 = (q.x - p.x) ** 2 + (q.y - p.y) ** 2
        if d2 < best_d:
            best, best_d = q, d2
    if best is None:
        return None
    return math.atan2(best.x - p.x, -(best.y - p.y))


def _bounce_heading(p, **k):
    """Heading after a wall rebound — phys.bounce_walls as an evade reset."""
    w = getattr(p, 'w', None)
    if w is None:
        return None
    W = float(getattr(w, 'width', 800) or 800)
    H = float(getattr(w, 'height', 600) or 600)
    m = float(getattr(p, 'size', 20) or 20) * 3.2
    ang = float(getattr(p, 'angle', 0.0) or 0.0)
    vx, vy = math.sin(ang), -math.cos(ang)
    bounced = False
    if p.x > W - m and vx > 0:
        vx = -abs(vx)
        bounced = True
    elif p.x < m and vx < 0:
        vx = abs(vx)
        bounced = True
    if p.y > H - m and vy > 0:
        vy = -abs(vy)
        bounced = True
    elif p.y < m and vy < 0:
        vy = abs(vy)
        bounced = True
    if not bounced:
        return None
    return math.atan2(vx, -vy)


def _cover_clear_heading(p, **k):
    """Chase prey only if the fort LOS is clear; otherwise hide."""
    from arena.fort import FortLOS
    from config import PREY_OF, FEAR_OF
    near = getattr(p, '_sector_nearest', None) or {}
    prey = (near.get('PREY') or (None, None))[1]
    fear = (near.get('FEAR') or (None, None))[1]
    if prey is None:
        prey_t = PREY_OF.get(getattr(p, 'type', None))
        best, bd = None, 1e18
        for q in getattr(getattr(p, 'w', None), 'particles', None) or []:
            if q is p or getattr(q, 'type', None) != prey_t:
                continue
            d2 = (q.x - p.x) ** 2 + (q.y - p.y) ** 2
            if d2 < bd:
                best, bd = q, d2
        prey = best
    if prey is None:
        return None
    world = getattr(p, 'w', None)
    if world is not None and FortLOS.clear(world, p.x, p.y, prey.x, prey.y):
        return math.atan2(prey.x - p.x, -(prey.y - p.y))
    if fear is not None:
        h, _ = FortLOS.cover_heading(p, fear)
        return h
    return None


REGISTRY = {
    'hash.heading': _hash_heading,
    'hash.query': _hash_heading,
    'phys.bounce_heading': _bounce_heading,
    'phys.bounce_walls': _bounce_heading,
    'cover.clear': _cover_clear_heading,
    'cover.clear_heading': _cover_clear_heading,
    'cover.occludes': _cover_clear_heading,
    'flow.heading': lambda p, **k: FlowField.heading(p),
    'flow.force': lambda p, **k: FlowField.heading(p),
    'roles.assign': lambda p, **k: (Roles.assign(p) and None),
    'roles.heading': lambda p, **k: Roles.heading(p),
    'form.slot_heading': lambda p, **k: Formation.slot_heading(p, shape=k.get('shape', 'wedge')),
    'orbit.heading': lambda p, **k: Orbit.heading(p, radius=k.get('radius')),
    'time.heading': lambda p, **k: TimeTo.heading(p),
    'time.eta': lambda p, **k: None,
    'pressure.heading': lambda p, **k: PressureField.heading(p),
    'pressure.force': lambda p, **k: PressureField.heading(p),
    'lanes.heading': lambda p, **k: Lanes.heading(p),
    'intercept.heading': lambda p, **k: Intercept.heading(p, mode=k.get('mode', 'lead')),
    'intercept.lead': lambda p, **k: Intercept.heading(p, mode='lead'),
    'intercept.chord': lambda p, **k: Intercept.heading(p, mode='chord'),
    'desync.heading': lambda p, **k: Desync.heading(p),
}


_CHASE_FNS = frozenset({
    'time.heading', 'time.eta',
    'intercept.heading', 'intercept.lead', 'intercept.chord',
    'lanes.heading',
})


def apply(particle, desired, mode='idle', steps=None):
    """Blend JSON movement steps onto desired heading. Returns heading."""
    # Last-prey-with-fear: do not run chase math. Convert stays legal on touch.
    try:
        st = particle.strat() or {}
        if st.get('_game_state') == 'LAST_PREY_RISK' or (
                int(getattr(particle, 'fearCount', lambda: 0)() or 0) > 0
                and int(getattr(particle, 'preyCount', lambda: 99)() or 99) <= 3):
            if steps:
                steps = [s for s in steps if str((s or {}).get('fn') or '') not in _CHASE_FNS]
    except Exception:
        pass
    if steps is None:
        try:
            import strategies.playbook as playbook
            sid = (particle.strat() or {}).get('_strategy_id')
            steps = playbook.movement_for(sid, particle.type.name) if sid else []
        except Exception:
            steps = []
    for step in steps or []:
        fn = step.get('fn')
        if not fn:
            continue
        when = step.get('when')
        if when and when not in (mode, getattr(particle, '_game_state', None),
                                 (particle.strat() or {}).get('_game_state')):
            if when != 'chase' or mode != 'chase':
                if when not in (mode, 'always'):
                    continue
        call = REGISTRY.get(fn)
        if call is None:
            continue
        extra = {k: v for k, v in step.items() if k not in ('fn', 'blend', 'weight', 'when')}
        try:
            h = call(particle, **extra)
        except Exception:
            continue
        if h is None:
            continue
        blend = step.get('blend')
        if blend is None:
            w = step.get('weight')
            blend = 0.45 if w is None else min(1.0, float(w) * 0.5)
        desired = _blend(desired, h, blend)
    return desired
