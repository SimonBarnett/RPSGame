"""Desync — break mirrored trajectories.

When both sides pick the same card (LANE_SWEEP vs LANE_SWEEP) they
share a heading field and pile into the same gap. Each unit gets a
stable angular offset from its id so the pack fans instead of cloning.
"""
from __future__ import annotations
import math


class Desync:
    @staticmethod
    def _uid(particle):
        ident = getattr(particle, 'uid', None) or id(particle)
        try:
            return int(ident)
        except Exception:
            return abs(hash(ident))

    @staticmethod
    def offset(particle, st=None):
        st = st or {}
        span = float(st.get('desync_span', 0.55) or 0.55)
        n = max(2, int(st.get('desync_slots', 5) or 5))
        slot = Desync._uid(particle) % n
        # centre slot = 0, others fan ±
        mid = (n - 1) * 0.5
        return ((slot - mid) / max(mid, 1.0)) * span

    @staticmethod
    def heading(particle, base=None, st=None):
        """Return current heading plus a stable fan offset."""
        if base is None:
            base = float(getattr(particle, 'angle', 0.0) or 0.0)
        off = Desync.offset(particle, st)
        # bias the fan toward nearest prey so it is not a random wander
        near = getattr(particle, '_sector_nearest', None) or {}
        hit = near.get('PREY')
        if hit and hit[1] is not None:
            prey = hit[1]
            aim = math.atan2(prey.x - particle.x, -(prey.y - particle.y))
            return (aim + off) % (2 * math.pi)
        return (base + off) % (2 * math.pi)
