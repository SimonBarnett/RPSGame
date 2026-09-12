"""
Forts for Rock, Paper, Scissors.

Placement, collision, LOS, intro/outro scale animation, draw, light occlusion.
particle.py imports this module — do not import particle at module level.
"""

import math
import random
import pygame


def _config():
    from config import Config
    return Config


class Fort:
    __slots__ = ('x', 'y', 'radius', 'scale', 'target_radius')
    def __init__(self, x, y, radius):
        self.x = float(x)
        self.y = float(y)
        self.radius = float(radius)
        self.target_radius = float(radius)
        self.scale = 1.0

    @property
    def draw_radius(self):
        return max(1.0, float(self.radius) * max(0.0, float(self.scale)))


class FortLOS:
    """Segment vs fort-circle occlusion tests."""

    @staticmethod
    def clear(world, ax, ay, bx, by, margin=2.0):
        """True if segment A→B does not intersect any fort interior."""
        forts = getattr(world, 'fort_list', None) or []
        if not forts:
            return True
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-8:
            return True
        for f in forts:
            # Skip if fort not yet fully formed
            if getattr(f, 'scale', 1.0) < 0.85:
                continue
            r = f.radius + margin
            # Closest point on segment to fort centre
            t = ((f.x - ax) * dx + (f.y - ay) * dy) / L2
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            cx = ax + t * dx
            cy = ay + t * dy
            if (cx - f.x) ** 2 + (cy - f.y) ** 2 < r * r:
                return False
        return True

    @staticmethod
    def occludes(world, observer, target, margin=2.0):
        return not FortLOS.clear(world, observer.x, observer.y, target.x, target.y, margin)

    @staticmethod
    def best_cover_fort(particle, threat, max_dist=None):
        """Fort that best sits between particle and threat (cover)."""
        if threat is None:
            return None, 0.0
        forts = getattr(particle.w, 'fort_list', None) or []
        if not forts:
            return None, 0.0
        size = particle.size
        max_d = max_dist if max_dist is not None else 22 * size
        best, best_score = None, 0.0
        tx, ty = threat.x, threat.y
        px, py = particle.x, particle.y
        for f in forts:
            if getattr(f, 'scale', 1.0) < 0.85:
                continue
            d_self = math.hypot(f.x - px, f.y - py)
            if d_self > max_d or d_self < f.radius + size:
                continue
            d_threat = math.hypot(f.x - tx, f.y - ty)
            # Cover quality: fort near line between self and threat, self on opposite side
            # Angle self→fort vs self→threat should be small, fort closer than threat
            ang_f = math.atan2(f.x - px, -(f.y - py))
            ang_t = math.atan2(tx - px, -(ty - py))
            ad = abs((ang_f - ang_t + math.pi) % (2 * math.pi) - math.pi)
            if ad > math.radians(55):
                continue
            # Prefer fort between: d_self + fort radius < d_threat-ish
            between = 1.0 if d_self + f.radius < d_threat + 40 else 0.4
            score = between * (1.0 - ad / math.radians(55)) * (1.0 - d_self / max_d)
            if score > best_score:
                best_score = score
                best = f
        return best, best_score

    @staticmethod
    def cover_heading(particle, threat, st=None):
        """Heading that puts a fort between self and threat (hide point just behind fort)."""
        fort, score = FortLOS.best_cover_fort(particle, threat)
        if fort is None or score < 0.08:
            return None, 0.0
        st = st or {}
        # Point slightly past fort centre away from threat
        tx, ty = threat.x - fort.x, threat.y - fort.y
        tl = math.hypot(tx, ty) + 1e-6
        ux, uy = tx / tl, ty / tl
        # Hide spot: fort centre - unit_toward_threat * (radius + size*1.2)
        hide_r = fort.radius + particle.size * 1.2
        hx = fort.x - ux * hide_r
        hy = fort.y - uy * hide_r
        heading = math.atan2(hx - particle.x, -(hy - particle.y)) % (2 * math.pi)
        return heading, score


def place_forts(world):
    """JS-identical fort ring (arena.layout). Radius scales with min(W,H)/720."""
    from arena.layout import world_metrics, place_forts as _place, make_rand
    world.fort_list = []
    n = max(0, int(getattr(world, 'forts', 0)))
    if n == 0:
        return
    m = world_metrics(world.width, world.height)
    rng = getattr(world, '_layout_rng', None)
    if rng is None:
        from arena.layout import mulberry32
        seed = int(getattr(world, 'match_seed', 0) or 0)
        if seed <= 0:
            seed = random.randint(1, 2 ** 31 - 1)
            world.match_seed = seed
        rng = mulberry32(seed)
        world._layout_rng = rng
    laid = _place(m['W'], m['H'], n, m['pad'], make_rand(rng))
    world.fort_list = [Fort(row['x'], row['y'], row['r']) for row in laid]
    for f in world.fort_list:
        f.scale = 0.0


def collide_particle(particle):
    """Rebound a particle off fully-formed forts (same spirit as walls)."""
    C = _config()
    w = particle.w
    for f in getattr(w, 'fort_list', []) or []:
        if getattr(f, 'scale', 1.0) < 0.85:
            continue
        dx, dy = particle.x - f.x, particle.y - f.y
        dist = math.hypot(dx, dy)
        min_d = particle.size + f.radius
        if dist >= min_d:
            continue
        if dist < 1e-5:
            nx = math.sin(particle.angle + math.pi)
            ny = -math.cos(particle.angle + math.pi)
        else:
            nx, ny = dx / dist, dy / dist
        particle.x = f.x + nx * (min_d + C.SEPARATION_SLOP)
        particle.y = f.y + ny * (min_d + C.SEPARATION_SLOP)
        vx = math.sin(particle.angle) * particle.speed
        vy = -math.cos(particle.angle) * particle.speed
        vel_n = vx * nx + vy * ny
        if vel_n < 0:
            e = C.FORT_RESTITUTION
            vx -= (1.0 + e) * vel_n * nx
            vy -= (1.0 + e) * vel_n * ny
        particle.angle = math.atan2(vx, -vy)
        particle.speed = math.hypot(vx, vy)
        particle.turn = 0
        particle._vision_dirty = True
        particle.enforce_speed(source='fort')
        particle._commit_dir = None
        particle._commit_frames = 0


def light_axes(world=None):
    C = _config()
    lx = float(getattr(C, 'LIGHT_DX', -0.32))
    ly = float(getattr(C, 'LIGHT_DY', -0.55))
    llen = math.hypot(lx, ly) or 1.0
    to_light = (lx / llen, ly / llen)
    shadow = (-to_light[0], -to_light[1])
    return to_light, shadow


def fort_occlusion(world, x, y, pr=0.0):
    """0..1 how much a point is occluded by forts blocking the key light."""
    forts = getattr(world, 'fort_list', None) or []
    if not forts:
        return 0.0
    C = _config()
    to_light, _shadow = light_axes(world)
    ldx, ldy = to_light
    length_k = float(getattr(C, 'FORT_SHADOW_LEN', 5.5))
    pen = float(getattr(C, 'FORT_SHADOW_PENUMBRA', 0.55))
    best = 0.0
    for f in forts:
        sc = float(getattr(f, 'scale', 1.0))
        if sc <= 0.15:
            continue
        r = float(f.draw_radius)
        if r < 4:
            continue
        fx = f.x - x
        fy = f.y - y
        t = fx * ldx + fy * ldy
        if t <= 0.0:
            continue
        maxlen = r * length_k
        if t > maxlen:
            continue
        perp = abs(fx * ldy - fy * ldx)
        half = r + pr + pen * r * (t / max(r, 1.0)) * 0.25
        if perp > half:
            continue
        along = 1.0 - t / maxlen
        across = max(0.0, 1.0 - perp / max(half, 1e-6))
        occ = (0.35 + 0.65 * along) * across * min(1.0, sc)
        if occ > best:
            best = occ
    return max(0.0, min(1.0, best))


def marble_shadow_clip(world, x, y, radius):
    """mode, shadow_angle, occ for a marble disc vs fort shadows."""
    to_light, shadow = light_axes(world)
    r = float(radius)
    pl = fort_occlusion(world, x + to_light[0] * r, y + to_light[1] * r, pr=0.0)
    pd = fort_occlusion(world, x + shadow[0] * r, y + shadow[1] * r, pr=0.0)
    pc = fort_occlusion(world, x, y, pr=r * 0.15)
    ang = math.atan2(shadow[0], -shadow[1])
    if pl < 0.08 and pd < 0.08 and pc < 0.08:
        return 'none', ang, 0.0
    if pl > 0.22 and pd > 0.22:
        return 'full', ang, max(pl, pd, pc)
    if pd >= pl:
        return 'cap', ang, max(pd, pc)
    return 'cap', (ang + math.pi) % (2 * math.pi), max(pl, pc)


def animate_in(world, elapsed_ms):
    """Grow forts from scale 0. Returns True when intro is finished."""
    C = _config()
    stagger = getattr(C, 'FORT_STAGGER_MS', 90)
    intro = getattr(C, 'FORT_INTRO_MS', 900)
    forts = getattr(world, 'fort_list', []) or []
    if not forts:
        return True
    done = True
    for i, f in enumerate(forts):
        local = elapsed_ms - i * stagger
        if local <= 0:
            f.scale = 0.0
            done = False
        elif local >= intro:
            f.scale = 1.0
        else:
            t = local / intro
            f.scale = 1.0 - (1.0 - t) ** 3
            done = False
    return done


def animate_out(world, elapsed_ms):
    """Shrink forts to 0. Returns True when outro is finished."""
    C = _config()
    outro = max(1, int(getattr(C, 'FORT_OUTRO_MS', 800)))
    t = min(1.0, float(elapsed_ms) / outro)
    for f in getattr(world, 'fort_list', []) or []:
        f.scale = max(0.0, 1.0 - t)
    return t >= 1.0


def draw_forts(world):
    """Contact shadow + optional glow + body. Skip on TITLE."""
    phase = getattr(world, 'phase', None)
    if getattr(phase, 'name', '') == 'TITLE':
        return
    C = _config()
    screen = world.screen
    surfaces = getattr(world, 'surfaces', None)
    if surfaces is None:
        return
    for f in getattr(world, 'fort_list', []) or []:
        if f.scale <= 0.02:
            continue
        dr = f.draw_radius
        sh = surfaces.fort_shadow(dr, alpha=int(110 * max(0.2, min(1.0, f.scale))))
        screen.blit(sh, sh.get_rect(center=(int(f.x), int(f.y + dr * 0.32))))
        if getattr(C, 'ENABLE_FORT_GLOW', False):
            glow = surfaces.soft_circle((90, 110, 160), int(dr + 10), int(35 * f.scale))
            screen.blit(glow, glow.get_rect(center=(int(f.x), int(f.y))))
        body = surfaces.fort_body(dr)
        screen.blit(body, body.get_rect(center=(int(f.x), int(f.y))))
