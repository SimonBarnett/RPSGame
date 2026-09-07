"""Formation slots: wedge, line, ring about the pack centroid."""

import math


class Formation:
    @staticmethod
    def _pack(particle):
        mates = [q for q in particle.w.particles if q.type == particle.type]
        if not mates:
            return particle.x, particle.y, particle.angle, [particle]
        cx = sum(q.x for q in mates) / len(mates)
        cy = sum(q.y for q in mates) / len(mates)
        # pack heading = mean velocity
        sx = sum(math.sin(q.angle) * max(0.1, getattr(q, 'speed', 1.0)) for q in mates)
        sy = sum(-math.cos(q.angle) * max(0.1, getattr(q, 'speed', 1.0)) for q in mates)
        heading = math.atan2(sx, sy) if (sx or sy) else particle.angle
        return cx, cy, heading, mates

    @staticmethod
    def slot_point(particle, shape='wedge', spacing=None):
        cx, cy, heading, mates = Formation._pack(particle)
        mates = sorted(mates, key=lambda q: getattr(q, 'id', id(q)))
        try:
            idx = next(i for i, q in enumerate(mates) if q is particle)
        except StopIteration:
            idx = 0
        n = max(1, len(mates))
        size = float(getattr(particle, 'size', 20.0) or 20.0)
        gap = float(spacing or size * 2.4)
        hx, hy = math.sin(heading), -math.cos(heading)
        px, py = -hy, hx  # perpendicular
        role = getattr(particle, '_tactical_role', 'STRIKE')
        if shape == 'ring':
            ang = heading + (2.0 * math.pi * idx / n)
            r = gap * max(1.6, n * 0.35)
            return cx + math.sin(ang) * r, cy - math.cos(ang) * r
        if shape == 'line':
            off = (idx - (n - 1) / 2.0) * gap
            return cx + px * off, cy + py * off
        # wedge: SCREEN forward-left/right, STRIKE on axis, BAIT rear
        if role == 'SCREEN':
            side = -1.0 if idx % 2 == 0 else 1.0
            return cx + hx * gap * 1.1 + px * side * gap, cy + hy * gap * 1.1 + py * side * gap
        if role == 'BAIT':
            return cx - hx * gap * 1.6, cy - hy * gap * 1.6
        if role == 'ESCORT':
            ang = heading + math.pi + (idx - n / 2.0) * 0.4
            return cx + math.sin(ang) * gap * 1.2, cy - math.cos(ang) * gap * 1.2
        off = (idx - (n - 1) / 2.0) * gap * 0.7
        return cx + hx * gap * 0.4 + px * off, cy + hy * gap * 0.4 + py * off

    @staticmethod
    def slot_heading(particle, shape='wedge', spacing=None):
        x, y = Formation.slot_point(particle, shape=shape, spacing=spacing)
        dx, dy = x - particle.x, y - particle.y
        if dx * dx + dy * dy < 4.0:
            return None
        return math.atan2(dx, -dy)
