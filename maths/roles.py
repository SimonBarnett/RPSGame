"""Assign SCREEN / BAIT / STRIKE / ESCORT from local fear vs prey geometry."""

import math

ROLES = ('SCREEN', 'BAIT', 'STRIKE', 'ESCORT')


class Roles:
    @staticmethod
    def _counts(p):
        self_n = p.selfcount() if hasattr(p, 'selfcount') else 1
        fear_n = p.fearCount() if hasattr(p, 'fearCount') else 0
        prey_n = p.preyCount() if hasattr(p, 'preyCount') else 0
        return self_n, fear_n, prey_n

    @staticmethod
    def _nearest(p, kind):
        bag = getattr(p, '_sector_nearest', None) or {}
        hit = bag.get(kind)
        if hit:
            return hit
        return (1e18, None)

    @staticmethod
    def assign_team(world, team_type):
        members = [q for q in world.particles if q.type == team_type]
        n = len(members)
        if n == 0:
            return {}
        scored = []
        for q in members:
            fd, fear = Roles._nearest(q, 'FEAR')
            pd, prey = Roles._nearest(q, 'PREY')
            scored.append((fd, pd, q))
        scored.sort(key=lambda t: t[0])  # closest to fear first
        out = {}
        self_n = n
        fear_alive = any(t[1] is not None for _, _, q in [(0, 0, None)] )  # placeholder
        fear_alive = any(Roles._nearest(q, 'FEAR')[1] is not None for q in members)
        prey_alive = any(Roles._nearest(q, 'PREY')[1] is not None for q in members)

        if self_n <= 2:
            for q in members:
                out[id(q)] = 'ESCORT' if fear_alive else 'STRIKE'
                q._tactical_role = out[id(q)]
            return out

        n_screen = 1 if fear_alive else 0
        if self_n >= 6 and fear_alive:
            n_screen = 2
        n_bait = 1 if self_n >= 5 and prey_alive and fear_alive else 0

        for i, (_fd, _pd, q) in enumerate(scored):
            if i < n_screen:
                role = 'SCREEN'
            elif n_bait and i == n - 1:
                role = 'BAIT'
            elif self_n <= 3 and fear_alive:
                role = 'ESCORT'
            else:
                role = 'STRIKE'
            out[id(q)] = role
            q._tactical_role = role
        return out

    @staticmethod
    def assign(particle):
        """Assign this frame for the particle's team; return this particle's role."""
        cached = getattr(particle.w, '_role_frame', None)
        rc = getattr(particle.w, 'runcount', 0)
        if cached != rc:
            particle.w._role_cache = {}
            particle.w._role_frame = rc
        key = particle.type
        bag = getattr(particle.w, '_role_cache', {})
        if key not in bag:
            bag[key] = Roles.assign_team(particle.w, particle.type)
            particle.w._role_cache = bag
        role = bag[key].get(id(particle), getattr(particle, '_tactical_role', 'STRIKE'))
        particle._tactical_role = role
        return role

    @staticmethod
    def heading(particle, st=None):
        """Role-coloured heading, or None if the role has no extra pull."""
        role = getattr(particle, '_tactical_role', None) or Roles.assign(particle)
        near = getattr(particle, '_sector_nearest', None) or {}
        if role == 'SCREEN':
            fear = near.get('FEAR')
            if fear and fear[1] is not None:
                d, o = fear
                return math.atan2(particle.x - o.x, -(particle.y - o.y))
        if role == 'BAIT':
            fear = near.get('FEAR')
            if fear and fear[1] is not None:
                # run perpendicular to fear
                d, o = fear
                return math.atan2(-(o.y - particle.y), -(o.x - particle.x))
        if role in ('STRIKE', 'ESCORT'):
            prey = near.get('PREY')
            if prey and prey[1] is not None:
                o = prey[1]
                return math.atan2(o.x - particle.x, -(o.y - particle.y))
        return None
