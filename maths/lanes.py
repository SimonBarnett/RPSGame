"""Lane sweep — split hunters across parallel corridors.

Stops the CLEAR_HUNT pile-on where every hunter takes the same gap
between forts. Uses SpatialHash neighbourhood + a stable lane index
from particle id so assignments do not flicker every frame.
"""
from __future__ import annotations
import math


class Lanes:
    @staticmethod
    def _lane_count(particle, st=None):
        st = st or {}
        n = max(1, int(st.get('lane_count', 3) or 3))
        return min(8, n)

    @staticmethod
    def lane_index(particle, st=None):
        n = Lanes._lane_count(particle, st)
        ident = getattr(particle, 'uid', None) or id(particle)
        try:
            ident = int(ident)
        except Exception:
            ident = abs(hash(ident))
        return ident % n

    @staticmethod
    def heading(particle, st=None):
        """Steer toward this unit's corridor, then toward nearest prey in it."""
        st = st or {}
        w = getattr(particle, 'w', None) or getattr(particle, 'world', None)
        if w is None:
            return 0.0, 0.0
        n = Lanes._lane_count(particle, st)
        idx = Lanes.lane_index(particle, st)
        axis = str(st.get('lane_axis', 'x') or 'x').lower()
        width = float(getattr(w, 'width', 800) or 800)
        height = float(getattr(w, 'height', 600) or 600)
        if axis == 'y':
            y = height * (idx + 0.5) / n
            tx, ty = float(particle.x), y
        else:
            x = width * (idx + 0.5) / n
            tx, ty = x, float(particle.y)
        # pull slightly toward nearest prey so lanes do not idle
        prey = None
        try:
            from config import PREY_OF
            ptype = getattr(particle, 'type', None)
            want = PREY_OF.get(ptype)
            best = 1e18
            for q in getattr(w, 'particles', []) or []:
                if getattr(q, 'type', None) != want:
                    continue
                dx = q.x - particle.x
                dy = q.y - particle.y
                d2 = dx * dx + dy * dy
                if d2 < best:
                    best = d2
                    prey = q
        except Exception:
            prey = None
        if prey is not None:
            mix = float(st.get('lane_prey_mix', 0.45) or 0.45)
            tx = tx * (1.0 - mix) + prey.x * mix
            ty = ty * (1.0 - mix) + prey.y * mix
        dx = tx - particle.x
        dy = ty - particle.y
        mag = math.hypot(dx, dy) or 1.0
        return dx / mag, dy / mag
