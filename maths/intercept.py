"""Lead pursuit and chord-cut of a moving target.

Counters orbit-kiting: instead of chasing the current bearing, cut the
chord of the predicted path so a circling prey runs into the hunter.
"""
from __future__ import annotations
import math


class Intercept:
    @staticmethod
    def _prey(particle):
        near = getattr(particle, '_sector_nearest', None) or {}
        hit = near.get('PREY')
        if hit:
            return hit[1]
        w = getattr(particle, 'w', None)
        if w is None:
            return None
        try:
            from config import PREY_OF
            want = PREY_OF.get(getattr(particle, 'type', None))
        except Exception:
            want = None
        best = None
        best_d = 1e18
        for q in getattr(w, 'particles', []) or []:
            if q is particle:
                continue
            if want is not None and getattr(q, 'type', None) != want:
                continue
            d = (q.x - particle.x) ** 2 + (q.y - particle.y) ** 2
            if d < best_d:
                best_d = d
                best = q
        return best

    @staticmethod
    def lead_point(hunter, prey, lookahead=10.0):
        if prey is None:
            return None
        look = float(lookahead)
        try:
            look = float((hunter.strat() or {}).get('predict_lookahead', look))
        except Exception:
            pass
        look = max(2.0, min(28.0, look))
        sp = float(getattr(prey, 'speed', 0.0) or 0.0)
        px = prey.x + math.sin(prey.angle) * sp * look
        py = prey.y - math.cos(prey.angle) * sp * look
        return px, py

    @staticmethod
    def chord_point(hunter, prey, lookahead=10.0):
        """Midpoint between prey now and prey later — the chord of the orbit."""
        lead = Intercept.lead_point(hunter, prey, lookahead)
        if lead is None:
            return None
        return (0.5 * (prey.x + lead[0]), 0.5 * (prey.y + lead[1]))

    @staticmethod
    def heading(particle, mode='lead', lookahead=None, st=None):
        prey = Intercept._prey(particle)
        if prey is None:
            return None
        look = lookahead
        if look is None:
            look = (st or {}).get('predict_lookahead', 12.0)
        if mode == 'chord':
            pt = Intercept.chord_point(particle, prey, look)
        else:
            pt = Intercept.lead_point(particle, prey, look)
        if pt is None:
            return None
        return math.atan2(pt[0] - particle.x, -(pt[1] - particle.y))
