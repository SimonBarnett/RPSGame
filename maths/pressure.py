"""Pack pressure / local density field.

Gives ground when friends pile up, slides off fear blobs,
and steers toward sparse prey instead of the densest clump.
Cached once per world runcount.
"""

import math


class PressureField:
    KERNEL = 140.0

    @staticmethod
    def _lists(world):
        rc = getattr(world, 'runcount', 0)
        cache = getattr(world, '_pressure_lists', None)
        if cache and cache[0] == rc:
            return cache[1]
        buckets = {'FRIEND': {}, 'FEAR': {}, 'PREY': {}, 'ALL': []}
        from config import FEAR_OF, PREY_OF
        particles = getattr(world, 'particles', None) or []
        for p in particles:
            t = getattr(p, 'type', None)
            if t is None:
                continue
            buckets['ALL'].append(p)
            buckets['FRIEND'].setdefault(t, []).append(p)
        buckets['_fear_of'] = FEAR_OF
        buckets['_prey_of'] = PREY_OF
        world._pressure_lists = (rc, buckets)
        return buckets

    @staticmethod
    def _kernel(d, reach):
        if d >= reach or d <= 1e-6:
            return 0.0
        x = 1.0 - d / reach
        return x * x

    @staticmethod
    def density_at(particle, kind='FRIEND', reach=None):
        """Scalar density of kind at particle position."""
        reach = float(reach or PressureField.KERNEL)
        world = particle.w
        bags = PressureField._lists(world)
        pts = []
        t = particle.type
        if kind == 'FRIEND':
            pts = bags['FRIEND'].get(t, ())
        elif kind == 'FEAR':
            fear = bags['_fear_of'].get(t)
            pts = bags['FRIEND'].get(fear, ())
        elif kind == 'PREY':
            prey = bags['_prey_of'].get(t)
            pts = bags['FRIEND'].get(prey, ())
        else:
            pts = bags['ALL']
        acc = 0.0
        x, y = particle.x, particle.y
        spatial = getattr(world, 'spatial', None)
        if spatial is not None and hasattr(spatial, 'query'):
            try:
                nearby = spatial.query(x, y, reach)
            except Exception:
                nearby = pts
        else:
            nearby = pts
        for o in nearby:
            if o is particle:
                continue
            if kind == 'FRIEND' and o.type != t:
                continue
            if kind == 'FEAR' and o.type != bags['_fear_of'].get(t):
                continue
            if kind == 'PREY' and o.type != bags['_prey_of'].get(t):
                continue
            d = math.hypot(o.x - x, o.y - y)
            acc += PressureField._kernel(d, reach)
        return acc

    @staticmethod
    def gradient(particle, kind='FRIEND', reach=None):
        """Approximate density gradient (points uphill)."""
        reach = float(reach or PressureField.KERNEL)
        world = particle.w
        bags = PressureField._lists(world)
        t = particle.type
        if kind == 'FRIEND':
            pts = bags['FRIEND'].get(t, ())
        elif kind == 'FEAR':
            pts = bags['FRIEND'].get(bags['_fear_of'].get(t), ())
        elif kind == 'PREY':
            pts = bags['FRIEND'].get(bags['_prey_of'].get(t), ())
        else:
            pts = bags['ALL']
        gx = gy = 0.0
        x, y = particle.x, particle.y
        spatial = getattr(world, 'spatial', None)
        nearby = pts
        if spatial is not None and hasattr(spatial, 'query'):
            try:
                nearby = spatial.query(x, y, reach)
            except Exception:
                nearby = pts
        for o in nearby:
            if o is particle:
                continue
            if kind == 'FRIEND' and o.type != t:
                continue
            if kind == 'FEAR' and o.type != bags['_fear_of'].get(t):
                continue
            if kind == 'PREY' and o.type != bags['_prey_of'].get(t):
                continue
            dx, dy = o.x - x, o.y - y
            d = math.hypot(dx, dy) or 1.0
            k = PressureField._kernel(d, reach)
            if k <= 0:
                continue
            gx += dx / d * k
            gy += dy / d * k
        return gx, gy

    @staticmethod
    def force(particle, st=None):
        """Down own density + fear density, toward sparse prey."""
        st = st or (particle.strat() if hasattr(particle, 'strat') else {})
        reach = float(st.get('pressure_radius', PressureField.KERNEL))
        own_w = float(st.get('pressure_own', 1.0))
        fear_w = float(st.get('pressure_fear', 1.15))
        prey_w = float(st.get('pressure_prey', 0.65))
        ogx, ogy = PressureField.gradient(particle, 'FRIEND', reach)
        fgx, fgy = PressureField.gradient(particle, 'FEAR', reach)
        pgx, pgy = PressureField.gradient(particle, 'PREY', reach)
        # downhill own + fear, uphill prey but damped so we prefer gaps
        prey_den = PressureField.density_at(particle, 'PREY', reach)
        sparse = 1.0 / (1.0 + prey_den)
        fx = -own_w * ogx - fear_w * fgx + prey_w * sparse * pgx
        fy = -own_w * ogy - fear_w * fgy + prey_w * sparse * pgy
        particle._pressure_own = PressureField.density_at(particle, 'FRIEND', reach)
        particle._pressure_fear = PressureField.density_at(particle, 'FEAR', reach)
        particle._pressure_prey = prey_den
        return fx, fy

    @staticmethod
    def heading(particle, st=None):
        fx, fy = PressureField.force(particle, st)
        if fx * fx + fy * fy < 1e-8:
            return None
        return math.atan2(fx, -fy)
