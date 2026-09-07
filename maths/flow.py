"""Potential-field heading: attract prey, repel fear, ridge off walls/forts."""

import math


class FlowField:
    @staticmethod
    def _wall_force(p):
        w = p.w
        m = 80.0
        fx = fy = 0.0
        if p.x < m:
            fx += (m - p.x) / m
        if p.x > w.width - m:
            fx -= (p.x - (w.width - m)) / m
        if p.y < m:
            fy += (m - p.y) / m
        if p.y > w.height - m:
            fy -= (p.y - (w.height - m)) / m
        return fx, fy

    @staticmethod
    def _fort_force(p):
        fx = fy = 0.0
        forts = getattr(p.w, 'fort_list', None) or getattr(p.w, 'forts_list', None) or []
        if not forts and hasattr(p.w, 'forts') and not isinstance(p.w.forts, int):
            forts = p.w.forts
        for f in forts or []:
            fx0 = getattr(f, 'x', None)
            fy0 = getattr(f, 'y', None)
            if fx0 is None:
                continue
            r = float(getattr(f, 'r', None) or getattr(f, 'radius', 40.0) or 40.0)
            dx, dy = p.x - fx0, p.y - fy0
            d = math.hypot(dx, dy) or 1.0
            reach = r * 3.2
            if d < reach:
                s = (reach - d) / reach
                fx += dx / d * s
                fy += dy / d * s
        return fx, fy

    @staticmethod
    def force(particle, st=None):
        st = st or (particle.strat() if hasattr(particle, 'strat') else {})
        fx = fy = 0.0
        prey_w = float(st.get('near_target_aggro', 1.4))
        fear_w = float(st.get('escape_bonus', 1.0)) * float(st.get('fear_close_mult', 1.6)) * 0.35
        wall_w = float(st.get('avoid_weight', 1.4)) * 0.45
        fort_w = float(st.get('fort_cover_weight', 1.0)) * 0.35

        nearest = getattr(particle, '_sector_nearest', None) or {}
        prey = nearest.get('PREY')
        if prey:
            d, other = prey
            if other is not None and d and d > 1.0:
                fx += prey_w * (other.x - particle.x) / d
                fy += prey_w * (other.y - particle.y) / d
        fear = nearest.get('FEAR')
        if fear:
            d, other = fear
            if other is not None and d and d > 1.0:
                fx -= fear_w * (other.x - particle.x) / (d * 0.25 + 8.0) * 18.0
                fy -= fear_w * (other.y - particle.y) / (d * 0.25 + 8.0) * 18.0

        wx, wy = FlowField._wall_force(particle)
        fx += wall_w * wx
        fy += wall_w * wy
        ox, oy = FlowField._fort_force(particle)
        fx += fort_w * ox
        fy += fort_w * oy
        return fx, fy

    @staticmethod
    def heading(particle, st=None):
        fx, fy = FlowField.force(particle, st)
        if fx * fx + fy * fy < 1e-8:
            return None
        return math.atan2(fx, -fy)
