"""ETA, closing speed, convert-before-fear checks."""

import math


class TimeTo:
    @staticmethod
    def closing_speed(a, b):
        dx, dy = b.x - a.x, b.y - a.y
        d = math.hypot(dx, dy) or 1.0
        ux, uy = dx / d, dy / d
        sa = float(getattr(a, 'speed', 0.0) or 0.0)
        sb = float(getattr(b, 'speed', 0.0) or 0.0)
        ax, ay = math.sin(a.angle) * sa, -math.cos(a.angle) * sa
        bx, by = math.sin(b.angle) * sb, -math.cos(b.angle) * sb
        relx, rely = ax - bx, ay - by
        return relx * ux + rely * uy

    @staticmethod
    def eta(a, b):
        d = math.hypot(b.x - a.x, b.y - a.y)
        close = TimeTo.closing_speed(a, b)
        if close <= 0.05:
            return 1e9
        return d / close

    @staticmethod
    def intercept_frames(hunter, prey, lookahead=12.0):
        if prey is None:
            return 1e9
        px = prey.x + math.sin(prey.angle) * prey.speed * lookahead
        py = prey.y - math.cos(prey.angle) * prey.speed * lookahead
        d = math.hypot(px - hunter.x, py - hunter.y)
        sp = max(0.15, float(getattr(hunter, 'speed', 1.0) or 1.0))
        return d / sp

    @staticmethod
    def can_convert_before_fear(particle, prey=None, fear=None):
        near = getattr(particle, '_sector_nearest', None) or {}
        if prey is None:
            hit = near.get('PREY')
            prey = hit[1] if hit else None
        if fear is None:
            hit = near.get('FEAR')
            fear = hit[1] if hit else None
        if prey is None:
            return False
        if fear is None:
            return True
        return TimeTo.eta(particle, prey) + 8.0 < TimeTo.eta(fear, particle)

    @staticmethod
    def heading(particle, st=None):
        """If convert-before-fear fails, peel off prey toward escape heading."""
        near = getattr(particle, '_sector_nearest', None) or {}
        prey = (near.get('PREY') or (None, None))[1]
        fear = (near.get('FEAR') or (None, None))[1]
        if fear is None or prey is None:
            return None
        if TimeTo.can_convert_before_fear(particle, prey, fear):
            return math.atan2(prey.x - particle.x, -(prey.y - particle.y))
        return math.atan2(particle.x - fear.x, -(particle.y - fear.y))
