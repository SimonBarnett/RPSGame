"""Tangent + stand-off heading around a target or fort.

World heading matches phys.integrate:
    vx, vy = sin(angle)*speed, -cos(angle)*speed
    angle  = atan2(vx, -vy)          # 0 = up (-Y)

Geometry (screen: +X right, +Y down):
    r̂ = (P - A) / |P - A|            # out from anchor
    t̂_ccw = (-r̂.y, r̂.x)              # 90° CCW
    t̂_cw  = -t̂_ccw

Steer = tangent + radial spring:
    radial = (|P-A| - R) / R         # >0 too far, <0 too close
    F = sign * t̂  -  k * radial * r̂
    heading = atan2(Fx, -Fy)

Sign is taken from current velocity so a particle already circling
does not flip. If that tangent heads into a wall, the sign flips.
"""

import math


class Orbit:
    @staticmethod
    def _anchor(particle, around=None):
        if around is not None:
            return (
                around.x, around.y,
                float(getattr(around, 'size', 20.0) or 20.0),
                around,
            )
        near = getattr(particle, '_sector_nearest', None) or {}
        prey = near.get('PREY')
        if prey and prey[1] is not None:
            o = prey[1]
            return o.x, o.y, float(getattr(o, 'size', 20.0) or 20.0), o
        forts = getattr(particle.w, 'fort_list', None) or []
        if not forts and hasattr(particle.w, 'forts') and not isinstance(particle.w.forts, int):
            forts = particle.w.forts
        best = None
        best_d = 1e18
        for f in forts or []:
            fx, fy = getattr(f, 'x', None), getattr(f, 'y', None)
            if fx is None:
                continue
            d = (particle.x - fx) ** 2 + (particle.y - fy) ** 2
            if d < best_d:
                best_d = d
                best = f
        if best is not None:
            r = float(getattr(best, 'r', None) or getattr(best, 'radius', 40.0) or 40.0)
            return best.x, best.y, r, best
        return None

    @staticmethod
    def tangent_basis(dx, dy):
        """Unit radial and CCW tangent from offset (dx, dy) = P - A."""
        d = math.hypot(dx, dy) or 1.0
        rx, ry = dx / d, dy / d
        tx, ty = -ry, rx          # 90° CCW
        return d, rx, ry, tx, ty

    @staticmethod
    def velocity_sign(particle, tx, ty):
        """+1 if current velocity already leans CCW, else -1 (CW)."""
        sp = float(getattr(particle, 'speed', 0.0) or 0.0)
        vx = math.sin(particle.angle) * sp
        vy = -math.cos(particle.angle) * sp
        if vx * vx + vy * vy < 1e-6:
            pid = getattr(particle, 'id', id(particle))
            return 1.0 if (hash(pid) & 1) else -1.0
        return 1.0 if (vx * tx + vy * ty) >= 0.0 else -1.0

    @staticmethod
    def _wall_penalty(particle, hx, hy, look=48.0):
        w = particle.w
        nx = particle.x + hx * look
        ny = particle.y + hy * look
        m = 28.0
        hit = 0.0
        if nx < m:
            hit += (m - nx) / m
        if nx > w.width - m:
            hit += (nx - (w.width - m)) / m
        if ny < m:
            hit += (m - ny) / m
        if ny > w.height - m:
            hit += (ny - (w.height - m)) / m
        return hit

    @staticmethod
    def heading(particle, around=None, radius=None, st=None, predict=True):
        hit = Orbit._anchor(particle, around)
        if hit is None:
            return None
        ax, ay, ar, obj = hit
        if predict and obj is not None and hasattr(obj, 'angle'):
            look = float((st or {}).get('predict_lookahead', 8.0) if st is not None
                         else 8.0)
            try:
                look = float((particle.strat() or {}).get('predict_lookahead', look))
            except Exception:
                pass
            sp = float(getattr(obj, 'speed', 0.0) or 0.0)
            ax = ax + math.sin(obj.angle) * sp * look * 0.35
            ay = ay - math.cos(obj.angle) * sp * look * 0.35
        dx, dy = particle.x - ax, particle.y - ay
        d, rx, ry, tx, ty = Orbit.tangent_basis(dx, dy)
        size = float(getattr(particle, 'size', 20.0) or 20.0)
        stand = float(radius or (ar + size * 2.8))
        radial = (d - stand) / max(stand, 1.0)
        # spring gain: stronger when inside the ring (about to clip the body)
        k = 1.35 if radial < 0 else 0.85
        sign = Orbit.velocity_sign(particle, tx, ty)
        fx = sign * tx - k * radial * rx
        fy = sign * ty - k * radial * ry
        # If this tangent drives into a wall, flip
        if Orbit._wall_penalty(particle, fx, fy) > Orbit._wall_penalty(particle, -fx, -fy) + 0.15:
            sign = -sign
            fx = sign * tx - k * radial * rx
            fy = sign * ty - k * radial * ry
        if fx * fx + fy * fy < 1e-8:
            return None
        return math.atan2(fx, -fy)
