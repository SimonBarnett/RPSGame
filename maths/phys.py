"""
Immutable physics for Rock-Paper-Scissors particles.

Integration, wall rebound, pair collision impulse, speed governance.
Strategy / AI stay in particle.py.
Do not import particle at module level.
"""

import math


def _cfg():
    from config import Config
    return Config


def maxspeed(p):
    """Cruise speed from type motion + last-man fear bonus."""
    C = _cfg()
    d = p.type_defaults()
    base = d["speed_base"] + p.strength
    tf = getattr(C, 'SPEED_TEAM_FACTOR', 0.0)
    if tf:
        base *= 1.0 + tf * math.log1p(max(0, p.w.teamSize))
    speed = base * getattr(C, 'CRUISE_MULT', 5.5)
    if getattr(C, 'LATE_SPEED_ENABLED', False):
        if p.selfcount() <= d.get("late_count_threshold", 2):
            speed *= d.get("late_speed_mult", 1.20)
    if p.selfcount() == 1 and p.fearCount() > 0:
        speed *= float(getattr(C, 'LAST_MAN_FEAR_SPEED', 1.25))
    return max(0.8, speed)


def enforce_speed(p, source='move'):
    """Bleed excess above maxspeed, then hard-cap."""
    C = _cfg()
    ms = p.maxspeed()
    if p.speed > ms + 1e-6:
        before = p.speed
        excess = before - ms
        if getattr(C, 'DEBUG_SPEED', False):
            rc = getattr(p.w, 'runcount', 0)
            if rc - getattr(p, '_last_speed_log', -999) >= getattr(C, 'DEBUG_SPEED_EVERY', 30):
                p._last_speed_log = rc
                try:
                    with open('speed_debug.log', 'a', encoding='utf-8') as f:
                        f.write(
                            f'rc={rc} id={getattr(p, "id", 0):04x} type={p.type.name} src={source} '
                            f'speed={before:.3f} max={ms:.3f} excess={excess:.3f} '
                            f'ratio={before / ms:.3f}\n'
                        )
                except Exception:
                    pass
        p.speed -= excess * getattr(C, 'OVERSPEED_DECAY', 0.35)
        if p.speed > ms * getattr(C, 'OVERSPEED_HARD_RATIO', 1.0):
            p.speed = ms
    floor = ms / 10
    if p.speed < floor:
        p.speed = floor


def bounce_walls(p):
    """Reflect velocity off arena walls; clamp position inside bounds."""
    C = _cfg()
    e = C.WALL_RESTITUTION
    bounced = False
    vx = math.sin(p.angle) * p.speed
    vy = -math.cos(p.angle) * p.speed
    w = p.w
    if p.x > w.width - p.size:
        p.x = w.width - p.size
        if vx > 0:
            vx = -vx * e
            bounced = True
    elif p.x < p.size:
        p.x = p.size
        if vx < 0:
            vx = -vx * e
            bounced = True
    if p.y > w.height - p.size:
        p.y = w.height - p.size
        if vy > 0:
            vy = -vy * e
            bounced = True
    elif p.y < p.size:
        p.y = p.size
        if vy < 0:
            vy = -vy * e
            bounced = True
    if bounced:
        p.angle = math.atan2(vx, -vy)
        p.speed = math.hypot(vx, vy)
        p.turn = 0
        p._vision_dirty = True
        enforce_speed(p, source='wall')
    return bounced


def integrate(p):
    """Advance position from heading + speed; roll marble from translation only."""
    C = _cfg()
    ox, oy = p.x, p.y
    p.x += math.sin(p.angle) * p.speed
    p.y -= math.cos(p.angle) * p.speed
    dist = math.hypot(p.x - ox, p.y - oy)
    if dist > 0.15:
        rad = max(4.0, float(p.size))
        gain = float(getattr(C, 'MARBLE_ROLL_GAIN', 0.85))
        p._roll_angle = (getattr(p, '_roll_angle', 0.0) + gain * dist / rad) % (2.0 * math.pi)
    if getattr(C, 'TRAIL_LEN', 0) > 0 and getattr(p.w, 'runcount', 0) % 2 == 0:
        trail = getattr(p, '_trail', None)
        if trail is not None:
            trail.append((p.x, p.y))
            if len(trail) > C.TRAIL_LEN:
                trail.pop(0)


def collide_pair(p1, p2):
    """
    Mechanical overlap response.
    Returns None if no contact, 'same' for friend split, 'opposite' after impulse.
    Does not convert types — caller handles RPS rules.
    """
    C = _cfg()
    dx, dy = p2.x - p1.x, p2.y - p1.y
    dist = math.hypot(dx, dy)
    min_d = p1.size + p2.size
    if dist >= min_d or dist < 1e-8:
        return None
    same = p1.type == p2.type
    nx, ny = dx / dist, dy / dist
    overlap = min_d - dist + C.SEPARATION_SLOP
    push = overlap * 0.55
    p1.x -= nx * push
    p1.y -= ny * push
    p2.x += nx * push
    p2.y += ny * push
    v1x = math.sin(p1.angle) * p1.speed
    v1y = -math.cos(p1.angle) * p1.speed
    v2x = math.sin(p2.angle) * p2.speed
    v2y = -math.cos(p2.angle) * p2.speed
    rvx, rvy = v1x - v2x, v1y - v2y
    vel_n = rvx * nx + rvy * ny

    if same:
        tx, ty = -ny, nx
        try:
            side1 = 1.0 if (hash(getattr(p1, 'id', id(p1))) & 1) else -1.0
        except Exception:
            side1 = 1.0
        side2 = -side1
        head_on = vel_n < -0.05
        slide = 0.55 if head_on else 0.30

        def _slide_heading(angle, side, away_sign):
            hx = math.sin(angle)
            hy = -math.cos(angle)
            sx = hx * (1.0 - slide) + (tx * side + nx * away_sign * 0.35) * slide
            sy = hy * (1.0 - slide) + (ty * side + ny * away_sign * 0.35) * slide
            if abs(sx) + abs(sy) < 1e-9:
                return angle
            return math.atan2(sx, -sy) % (2 * math.pi)

        p1.angle = _slide_heading(p1.angle, side1, -1.0)
        p2.angle = _slide_heading(p2.angle, side2, 1.0)
        p1.speed = max(p1.speed, p1.maxspeed() * 0.75)
        p2.speed = max(p2.speed, p2.maxspeed() * 0.75)
        enforce_speed(p1, source='collide_friend')
        enforce_speed(p2, source='collide_friend')
        p1._vision_dirty = p2._vision_dirty = True
        return 'same'

    e = C.RESTITUTION
    j = -(1.0 + e) * vel_n / 2.0
    ix, iy = j * nx, j * ny
    v1x += ix
    v1y += iy
    v2x -= ix
    v2y -= iy
    p1.angle = math.atan2(v1x, -v1y)
    p2.angle = math.atan2(v2x, -v2y)
    keep = getattr(C, 'COLLISION_SPEED_KEEP', 0.5)
    p1.speed = p1.maxspeed() * keep
    p2.speed = p2.maxspeed() * keep
    enforce_speed(p1, source='collide')
    enforce_speed(p2, source='collide')
    p1.turn = p2.turn = 0
    p1._vision_dirty = p2._vision_dirty = True
    return 'opposite'

class SpatialHash:
    """
    Uniform grid spatial hash for broad-phase neighbor queries.
    rebuild() once per frame; query(x,y,r) returns particles whose cells
    overlap the search circle, optionally distance-filtered.
    Complexity: insert O(1), rebuild O(n), query O(k) local cells.
    """
    __slots__ = ('cell', 'grid', 'count')

    def __init__(self, cell=80.0):
        self.cell = max(16.0, float(cell))
        self.grid = {}
        self.count = 0

    def clear(self):
        self.grid.clear()
        self.count = 0

    def _key(self, x, y):
        c = self.cell
        return (int(x // c), int(y // c))

    def insert(self, particle):
        k = self._key(particle.x, particle.y)
        bucket = self.grid.get(k)
        if bucket is None:
            self.grid[k] = [particle]
        else:
            bucket.append(particle)
        self.count += 1

    def rebuild(self, particles):
        """Full rebuild from particle list (call once per frame after moves)."""
        self.grid.clear()
        self.count = 0
        insert = self.insert
        for p in particles:
            insert(p)

    def query(self, x, y, radius, distance_filter=True):
        """
        Particles near (x,y).
        If distance_filter: only those with hypot <= radius (exact).
        Else: all in overlapping cells (slightly larger set, faster).
        """
        c = self.cell
        r = max(0, int(radius / c) + 1)
        cx, cy = int(x // c), int(y // c)
        out = []
        g = self.grid
        if distance_filter:
            r2 = radius * radius
            for ix in range(cx - r, cx + r + 1):
                for iy in range(cy - r, cy + r + 1):
                    bucket = g.get((ix, iy))
                    if not bucket:
                        continue
                    for p in bucket:
                        dx = p.x - x
                        dy = p.y - y
                        if dx * dx + dy * dy <= r2:
                            out.append(p)
        else:
            for ix in range(cx - r, cx + r + 1):
                for iy in range(cy - r, cy + r + 1):
                    bucket = g.get((ix, iy))
                    if bucket:
                        out.extend(bucket)
        return out

    def query_pairs(self, particles, max_dist):
        """
        Unique pairs within max_dist (for collision broad-phase).
        Yields (p1, p2) with id(p1) < id(p2).
        """
        seen = set()
        r2 = max_dist * max_dist
        for p in particles:
            for q in self.query(p.x, p.y, max_dist, distance_filter=True):
                if q is p:
                    continue
                a, b = (p, q) if id(p) < id(q) else (q, p)
                key = (id(a), id(b))
                if key in seen:
                    continue
                dx, dy = a.x - b.x, a.y - b.y
                if dx * dx + dy * dy <= r2:
                    seen.add(key)
                    yield a, b


# ---------------------------------------------------------------------------
