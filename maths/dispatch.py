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


REGISTRY = {
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
