"""JS-identical think / collide / step.

Port of rps_pub/rps.js createSim internals. Learning stays in Python
(credit / GP-EI / persist). Match-time play uses this tick on both engines.
"""
from __future__ import annotations

import math

from config import ParticleType, PREY_OF, FEAR_OF, TYPE_DEFAULTS
from strategies import playbook

PREY_N = {'ROCK': 'SCISSORS', 'PAPER': 'ROCK', 'SCISSORS': 'PAPER'}
FEAR_N = {'ROCK': 'PAPER', 'PAPER': 'SCISSORS', 'SCISSORS': 'ROCK'}

CRUISE_MULT = 5.5
LAST_MAN_FEAR_SPEED = 1.25
DEFAULT_MOTION = {
    'ROCK': {'speed': 1.22, 'turn': 14.06},
    'PAPER': {'speed': 1.76, 'turn': 12.06},
    'SCISSORS': {'speed': 1.33, 'turn': 12.84},
}
WALL_RESTITUTION = 0.92
PAIR_RESTITUTION = 0.35
FRIEND_RESTITUTION = 0.55
PAIR_FRICTION = 0.32
FRIEND_FRICTION = 0.06
WALL_FRICTION = 0.04
FORT_FRICTION = 0.08
FORT_RESTITUTION = 0.75
COLLISION_SPEED_KEEP = 0.5
SEPARATION_SLOP = 0.5
SLIP_DAMP = 0.42
SPIN_DAMP = 0.985
THRUST = 0.22
MASS = {'ROCK': 1.35, 'SCISSORS': 1.0, 'PAPER': 0.72}
FEAR_BUILD = 0.35
FEAR_DECAY = 0.04
FEAR_DECAY_FAST = 0.18

SECTORS = (
    (0, 0.0),
    (1, -math.pi / 4),
    (2, math.pi / 4),
    (3, -math.pi / 6),
    (4, math.pi / 6),
    (5, -math.pi / 3),
    (6, math.pi / 3),
    (7, -math.pi / 2),
    (8, math.pi / 2),
    (9, -math.pi * 3 / 4),
    (10, math.pi * 3 / 4),
    (11, math.pi),
)

DEFAULT_MOVES = {
    'PACK_HUNT': [{'fn': 'sectors.orient', 'blend': 0.35}, {'fn': 'boids.desired_heading', 'blend': 0.45}, {'fn': 'intercept.heading', 'blend': 0.4}],
}

CHASE_FNS = {
    'time.heading', 'time.eta', 'intercept.heading', 'intercept.lead',
    'intercept.chord', 'lanes.heading',
}


def _tname(p):
    t = getattr(p, 'type', None)
    return t.name if hasattr(t, 'name') else str(t)


def _pid(p):
    return int(getattr(p, 'id', 0) or 0)


def _enum(name):
    return ParticleType[name]


def ang_norm(a):
    a = a % (math.pi * 2)
    if a < 0:
        a += math.pi * 2
    return a


def _snap(v, scale):
    """Round-half-up. Same as Math.floor(v*scale+0.5)/scale for v>=0."""
    return math.floor(float(v) * scale + 0.5) / scale


def _snap_signed(v, scale):
    v = float(v)
    if v >= 0:
        return _snap(v, scale)
    return -_snap(-v, scale)


def snap_pose(p):
    """Kill libm ULP drift so PY/JS stay on the same grid."""
    p.x = _snap(p.x, 1e4)
    p.y = _snap(p.y, 1e4)
    p.angle = _snap(ang_norm(p.angle), 1e6)
    _ensure_vel(p)
    p.vx = _snap_signed(p.vx, 1e4)
    p.vy = _snap_signed(p.vy, 1e4)
    p.omega = _snap_signed(p.omega, 1e6)
    p.speed = _snap(max(0.0, math.hypot(p.vx, p.vy)), 1e6)


def _ensure_vel(p):
    if getattr(p, 'vx', None) is None or getattr(p, 'vy', None) is None:
        sp = float(getattr(p, 'speed', 0) or 0)
        p.vx = math.sin(p.angle) * sp
        p.vy = -math.cos(p.angle) * sp
    if getattr(p, 'omega', None) is None:
        p.omega = 0.0


def _mass_of(p):
    sz = float(getattr(p, 'size', 18) or 18)
    return float(MASS.get(_tname(p), 1.0)) * (sz / 18.0) ** 2


def _inertia_of(p, mass=None):
    sz = float(getattr(p, 'size', 18) or 18)
    m = _mass_of(p) if mass is None else mass
    return 0.5 * m * sz * sz


def _omega_cross(omega, rx, ry):
    """ωẑ × r in screen coords (y down): clockwise if omega>0."""
    return (-omega * ry, omega * rx)


def ang_diff(a, b):
    return math.atan2(math.sin(b - a), math.cos(b - a))


def heading_to(ax, ay, bx, by):
    return math.atan2(bx - ax, -(by - ay))


def blend_headings(a, b, w):
    if b is None:
        return a
    if a is None:
        return b
    px, py = math.sin(a), -math.cos(a)
    sx, sy = math.sin(b), -math.cos(b)
    x = px * (1 - w) + sx * w
    y = py * (1 - w) + sy * w
    if abs(x) + abs(y) < 1e-9:
        return a
    return math.atan2(x, -y)


def _body_vel(p):
    if getattr(p, 'vx', None) is not None and getattr(p, 'vy', None) is not None:
        return float(p.vx), float(p.vy)
    sp = float(getattr(p, 'speed', 0) or 0)
    return math.sin(p.angle) * sp, -math.cos(p.angle) * sp


def chase_heading(p, prey, look):
    if prey is None:
        return None
    vx, vy = _body_vel(prey)
    px = prey.x + vx * look
    py = prey.y + vy * look
    return heading_to(p.x, p.y, px, py)


def _fort_r(f):
    return float(getattr(f, 'r', None) or getattr(f, 'radius', 20) or 20)


def _fort_scale(f):
    return float(getattr(f, 'scale', 1.0) or 1.0)


def line_hits_circle(ax, ay, bx, by, cx, cy, r):
    abx, aby = bx - ax, by - ay
    acx, acy = cx - ax, cy - ay
    ab2 = abx * abx + aby * aby or 1.0
    t = (acx * abx + acy * aby) / ab2
    t = max(0.0, min(1.0, t))
    px, py = ax + abx * t, ay + aby * t
    return (px - cx) ** 2 + (py - cy) ** 2 < r * r


def fort_occludes(forts, ax, ay, bx, by, margin=2):
    for f in forts or ():
        if _fort_scale(f) < 0.7:
            continue
        r = _fort_r(f) + margin
        if not line_hits_circle(ax, ay, bx, by, f.x, f.y, r):
            continue
        da = math.hypot(ax - f.x, ay - f.y)
        db = math.hypot(bx - f.x, by - f.y)
        if da > r + 1 and db > r + 1:
            return f
    return None


def sector_of(bearing):
    best, bd = 0, 1e9
    for i, c in SECTORS:
        d = abs(ang_diff(c, bearing))
        if d < bd:
            bd, best = d, i
    return best


def rank_dirs(p, particles, c, forts):
    tn = _tname(p)
    self_n = c.get(tn, 0)
    prey_n = c.get(PREY_N[tn], 0)
    fear_n = c.get(FEAR_N[tn], 0)
    near, far = 5 * p.size, 30 * p.size
    scores = [{'id': i, 'c': ang, 'risk': 0.0, 'reward': 0.0, 'conf': 0.4} for i, ang in SECTORS]
    for q in particles:
        if q is p:
            continue
        dx, dy = q.x - p.x, q.y - p.y
        dist = math.hypot(dx, dy)
        if dist > far or dist < 0.5:
            continue
        if dist <= near:
            df = 1.0
        else:
            df = 1.0 - (dist - near) / (far - near)
        if df <= 0:
            continue
        bear = ang_diff(p.angle, heading_to(p.x, p.y, q.x, q.y))
        s = scores[sector_of(bear)]
        qn = _tname(q)
        if qn == FEAR_N[tn]:
            fm = 1 + 0.35 * df
            if dist < 10 * p.size:
                fm *= 2.6
            if fear_n >= self_n:
                fm *= 1.35
            s['risk'] += max(0.35, df * fm)
        elif qn == PREY_N[tn]:
            amt = df
            if df > 0.5:
                amt *= 1.6
            if df > 0.8:
                amt += 0.5
            if fear_n > 0 and prey_n <= 2:
                amt *= max(0.0, (prey_n - 1) / 3.0)
            elif fear_n <= 0:
                amt *= 3.0
            s['reward'] += amt
            if df > 0.5:
                s['risk'] *= 0.75
        elif qn == tn:
            if self_n < fear_n:
                s['risk'] += df * 0.5
            if dist < p.size * 5:
                s['risk'] += df * 0.25
    for s in scores:
        s['score'] = s['reward'] + s['conf'] * 0.2 - s['risk'] * 1.15
    return scores


def swarm_heading(p, particles, state, prey, fear, w=None):
    w = w or {}
    sx = sy = cx = cy = ax = ay = 0.0
    n_sep = n_coh = 0
    try:
        sep_mul = max(0.6, min(2.2, float(w.get('sep_distance', 6.5)) / 6.5))
    except Exception:
        sep_mul = 1.0
    sep_r = p.size * 3.0 * sep_mul
    tn = _tname(p)
    for q in particles:
        if q is p or _tname(q) != tn:
            continue
        dx, dy = p.x - q.x, p.y - q.y
        d2 = dx * dx + dy * dy
        if d2 < sep_r * sep_r and d2 > 1:
            sx += dx / d2
            sy += dy / d2
            n_sep += 1
        if state != 'CLEAR_HUNT' and d2 < (p.size * 14) ** 2:
            cx += q.x
            cy += q.y
            n_coh += 1
    fx = fy = 0.0
    sep_w = 3.4 if state == 'CLEAR_HUNT' else (2.8 if state in ('LAST_MAN', 'NEAR_WIPE') else 2.4)
    if n_sep:
        m = 3.0 if n_sep >= 3 else 1.6
        fx += sx * sep_w * m
        fy += sy * sep_w * m
    prey_obj = getattr(prey, 'obj', prey) if prey is not None else None
    if isinstance(prey, dict):
        prey_obj = prey.get('obj')
    fear_obj = getattr(fear, 'obj', fear) if fear is not None else None
    if isinstance(fear, dict):
        fear_obj = fear.get('obj')
    if n_coh and n_sep < 2 and prey_obj is None and state not in (
            'CLEAR_HUNT', 'LAST_MAN', 'CONTESTED', 'SMALL_UNIT'):
        fx += ((cx / n_coh) - p.x) * 0.002
        fy += ((cy / n_coh) - p.y) * 0.002
    if fear_obj is not None and state != 'CLEAR_HUNT':
        dx, dy = p.x - fear_obj.x, p.y - fear_obj.y
        d = math.hypot(dx, dy) or 1.0
        if d < p.size * 8:
            fw = 0.9 if state in ('LAST_MAN', 'NO_PREY_FEAR_ALIVE') else 1.1
            fx += (dx / d) * fw
            fy += (dy / d) * fw
    if prey_obj is not None and state != 'LAST_PREY_RISK':
        pd = math.hypot(prey_obj.x - p.x, prey_obj.y - p.y)
        if 1 < pd < p.size * 10:
            fx += (prey_obj.x - p.x) / pd * 0.35
            fy += (prey_obj.y - p.y) / pd * 0.35
    elif prey_obj is not None and state == 'LAST_PREY_RISK':
        pd = math.hypot(prey_obj.x - p.x, prey_obj.y - p.y) or 1.0
        if pd < p.size * 6:
            fx += (p.x - prey_obj.x) / pd * 1.1
            fy += (p.y - prey_obj.y) / pd * 1.1
    if abs(fx) + abs(fy) < 0.05:
        return None
    return math.atan2(fx, -fy)


def cover_heading(p, threat, forts):
    if threat is None or not forts:
        return None
    best, best_s = None, -1e9
    for f in forts:
        if _fort_scale(f) < 0.7:
            continue
        tx, ty = threat.x - f.x, threat.y - f.y
        td = math.hypot(tx, ty) or 1.0
        r = _fort_r(f)
        hx = f.x - (tx / td) * (r + p.size * 1.4)
        hy = f.y - (ty / td) * (r + p.size * 1.4)
        d = math.hypot(p.x - hx, p.y - hy)
        score = 200 / (d + 20) - (0 if fort_occludes(forts, hx, hy, threat.x, threat.y, 2) else 40)
        if score > best_s:
            best_s, best = score, (hx, hy)
    return heading_to(p.x, p.y, best[0], best[1]) if best else None


def hide_among_prey(p, preys, fear):
    if not preys:
        return None
    sx = sy = n = 0
    for q in preys:
        if math.hypot(q.x - p.x, q.y - p.y) < 220:
            sx += q.x
            sy += q.y
            n += 1
    if not n:
        return None
    h = heading_to(p.x, p.y, sx / n, sy / n)
    if fear is not None:
        h = blend_headings(h, heading_to(fear.x, fear.y, p.x, p.y), 0.25)
    return h


def anti_corner_herd(p, prey, W, H):
    if prey is None:
        return None
    m = 120.0
    ex = max(0.0, 1.0 - min(prey.x, W - prey.x) / m)
    ey = max(0.0, 1.0 - min(prey.y, H - prey.y) / m)
    cs = min(1.0, ex * ey * 1.4 + 0.35 * max(ex, ey) * min(ex, ey))
    if cs < 0.25:
        return None
    return heading_to(p.x, p.y, W * 0.5, H * 0.5)


def orbit_heading(p, anchor, radius=None):
    if anchor is None:
        return None
    dx, dy = p.x - anchor.x, p.y - anchor.y
    d = math.hypot(dx, dy) or 1.0
    rx, ry = dx / d, dy / d
    tx, ty = -ry, rx
    vx, vy = math.sin(p.angle), -math.cos(p.angle)
    if vx * tx + vy * ty < 0:
        tx, ty = -tx, -ty
    R = radius or ((getattr(anchor, 'r', None) or getattr(anchor, 'size', 20) or 20) + p.size * 3)
    radial = (d - R) / R
    fx = tx - 0.55 * radial * rx
    fy = ty - 0.55 * radial * ry
    return math.atan2(fx, -fy)


def lane_heading(p, W, H, prey, idx=0):
    n = 3
    i = (int(getattr(p, 'id', 0) or 0) + int(idx or 0)) % n
    x = W * (i + 0.5) / n
    tx, ty = x, p.y
    if prey is not None:
        tx = tx * 0.55 + prey.x * 0.45
        ty = ty * 0.55 + prey.y * 0.45
    return heading_to(p.x, p.y, tx, ty)


def form_heading(p, allies, prey):
    if not allies:
        return None
    cx = sum(q.x for q in allies) / len(allies)
    cy = sum(q.y for q in allies) / len(allies)
    if prey is not None:
        hx, hy = prey.x - cx, prey.y - cy
    else:
        hx, hy = math.sin(p.angle), -math.cos(p.angle)
    hd = math.hypot(hx, hy) or 1.0
    px, py = -hy / hd, hx / hd
    gap = p.size * 3.2
    try:
        idx = allies.index(p)
    except ValueError:
        idx = 0
    off = (idx - (len(allies) - 1) / 2.0) * gap
    sx = cx + (hx / hd) * gap * 0.4 + px * off
    sy = cy + (hy / hd) * gap * 0.4 + py * off
    return heading_to(p.x, p.y, sx, sy)


def flow_heading(p, W, H, forts):
    fx = fy = 0.0
    m = 70.0
    if p.x < m:
        fx += (m - p.x) / m
    if p.x > W - m:
        fx -= (p.x - (W - m)) / m
    if p.y < m:
        fy += (m - p.y) / m
    if p.y > H - m:
        fy -= (p.y - (H - m)) / m
    for f in forts or ():
        dx, dy = p.x - f.x, p.y - f.y
        d = math.hypot(dx, dy) or 1.0
        if d < _fort_r(f) + 50:
            fx += dx / d
            fy += dy / d
    if abs(fx) + abs(fy) < 0.05:
        return None
    return math.atan2(fx, -fy)


def pressure_heading(p, particles):
    fx = fy = 0.0
    for q in particles:
        if q is p:
            continue
        dx, dy = p.x - q.x, p.y - q.y
        d2 = dx * dx + dy * dy
        if 1 < d2 < 160 * 160:
            fx += dx / d2
            fy += dy / d2
    if abs(fx) + abs(fy) < 1e-6:
        return None
    return math.atan2(fx, -fy)


def intercept_heading(p, prey, mode):
    if prey is None:
        return None
    if mode == 'chord':
        vx, vy = _body_vel(prey)
        px = prey.x + vx * 6
        py = prey.y + vy * 6
        return heading_to(p.x, p.y, px, py)
    return chase_heading(p, prey, 18)


def time_heading(p, prey, fear):
    if prey is None:
        return None
    if fear is None:
        return chase_heading(p, prey, 12)
    eta_p = math.hypot(prey.x - p.x, prey.y - p.y) / max(0.4, p.speed)
    eta_f = math.hypot(fear.x - p.x, fear.y - p.y) / max(0.4, getattr(fear, 'speed', p.speed) or p.speed)
    if eta_p + 8 < eta_f:
        return chase_heading(p, prey, 12)
    return heading_to(fear.x, fear.y, p.x, p.y)


def desync_heading(p, prey):
    n, span = 5, 0.55
    slot = int(getattr(p, 'id', 0) or 0) % n
    mid = (n - 1) * 0.5
    off = ((slot - mid) / max(mid, 1)) * span
    base = heading_to(p.x, p.y, prey.x, prey.y) if prey is not None else p.angle
    return ang_norm(base + off)


def roles_assign(members):
    n = len(members)
    if not n:
        return
    members.sort(key=lambda q: int(getattr(q, 'id', 0) or 0))
    for i, m in enumerate(members):
        if n <= 2:
            m._role = 'STRIKE'
        elif i == 0:
            m._role = 'SCREEN'
        elif i == n - 1:
            m._role = 'ESCORT'
        else:
            m._role = 'STRIKE' if i % 2 else 'BAIT'


def roles_heading(p, prey, fear):
    role = getattr(p, '_role', None) or 'STRIKE'
    if role == 'SCREEN' and fear is not None:
        return heading_to(p.x, p.y, fear.x, fear.y)
    if role == 'BAIT' and prey is not None:
        return orbit_heading(p, prey, p.size * 6)
    if role == 'ESCORT' and prey is not None:
        return heading_to(p.x, p.y, prey.x, prey.y)
    return chase_heading(p, prey, 12) if prey is not None else None


def apply_moves(want, steps, ctx):
    p, state, mode = ctx['p'], ctx['state'], ctx['mode']
    # Same as rps.js: const prey = ctx.prey && ctx.prey.obj
    pr = ctx.get('prey')
    if isinstance(pr, dict):
        prey = pr.get('obj')
    else:
        prey = pr if pr is not None else ctx.get('prey_obj')
    fr = ctx.get('fear')
    if isinstance(fr, dict):
        fear = fr.get('obj')
    else:
        fear = fr if fr is not None else ctx.get('fear_obj')
    lst = list(steps or [])
    fear_n, prey_n = ctx.get('fearN', 0), ctx.get('preyN', 0)
    if state == 'LAST_PREY_RISK' or (fear_n > 0 and prey_n <= 1):
        lst = [s for s in lst if str((s or {}).get('fn') or '') not in CHASE_FNS]
    if state in ('CONTESTED', 'SMALL_UNIT'):
        lst = [s for s in lst if not str((s or {}).get('fn') or '').startswith('cover.')]
    if state == 'CLEAR_HUNT':
        lst = [s for s in lst if not str((s or {}).get('fn') or '').startswith(('orbit.', 'pressure.', 'cover.'))]
        if not any('chase' in str((s or {}).get('fn') or '') for s in lst):
            lst = [{'fn': 'sectors.chase_heading', 'blend': 0.85}] + lst
    elif state in ('LAST_MAN', 'NO_PREY_FEAR_ALIVE', 'NEAR_WIPE'):
        keep = [{'fn': 'sectors.orient', 'blend': 0.8}]
        raid = (state == 'LAST_MAN' and prey_n > 0) or state == 'NEAR_WIPE'
        for s in lst:
            fn = str((s or {}).get('fn') or '')
            if (not raid) and fn.startswith(('orbit.', 'time.', 'intercept.')):
                continue
            keep.append(s)
        if raid and not any(
                'chase' in str((s or {}).get('fn') or '')
                or str((s or {}).get('fn') or '').startswith('intercept.')
                for s in keep):
            keep.append({'fn': 'sectors.chase_heading', 'blend': 0.55})
        lst = keep
    W, H, forts, particles = ctx['W'], ctx['H'], ctx['forts'], ctx['particles']
    look = ctx.get('look', 12)

    def resolve(fn):
        if fn in ('flow.heading', 'flow.force'):
            return flow_heading(p, W, H, forts)
        if fn == 'roles.heading':
            return roles_heading(p, prey, fear)
        if fn == 'roles.assign':
            roles_assign(list(ctx.get('allies') or []))
            return None
        if fn == 'form.slot_heading':
            return form_heading(p, ctx.get('allies') or [], prey)
        if fn == 'orbit.heading':
            return orbit_heading(p, prey or fear, None)
        if fn in ('time.heading', 'time.eta'):
            return time_heading(p, prey, fear)
        if fn in ('pressure.heading', 'pressure.force'):
            return pressure_heading(p, particles)
        if fn == 'lanes.heading':
            return lane_heading(p, W, H, prey)
        if fn in ('intercept.heading', 'intercept.lead'):
            return intercept_heading(p, prey, 'lead')
        if fn in ('intercept.fear', 'intercept.block'):
            return intercept_heading(p, fear, 'lead')
        if fn == 'intercept.chord':
            return intercept_heading(p, prey, 'chord')
        if fn == 'desync.heading':
            return desync_heading(p, prey)
        if fn == 'voronoi.assign' or 'voronoi' in fn:
            return chase_heading(p, prey, look) if prey is not None else None
        if fn in ('hash.heading', 'hash.query') or 'hash' in fn:
            return chase_heading(p, prey, look) if prey is not None else None
        if fn in ('phys.bounce_heading', 'phys.bounce_walls') or 'bounce' in fn:
            m = p.size * 3.2
            vx, vy = math.sin(p.angle), -math.cos(p.angle)
            hit = False
            if p.x > W - m and vx > 0:
                vx = -abs(vx)
                hit = True
            elif p.x < m and vx < 0:
                vx = abs(vx)
                hit = True
            if p.y > H - m and vy > 0:
                vy = -abs(vy)
                hit = True
            elif p.y < m and vy < 0:
                vy = abs(vy)
                hit = True
            return math.atan2(vx, -vy) if hit else None
        if fn in ('cover.clear', 'cover.clear_heading', 'cover.occludes'):
            if prey is not None and not fort_occludes(forts, p.x, p.y, prey.x, prey.y, 2):
                return chase_heading(p, prey, look)
            return cover_heading(p, fear, forts)
        if fn == 'sectors.chase_heading' or 'chase' in fn:
            return chase_heading(p, prey, look) if prey is not None else None
        if fn == 'sectors.orient' or 'fear' in fn:
            return heading_to(fear.x, fear.y, p.x, p.y) if fear is not None else None
        if fn == 'boids.desired_heading' or 'boids' in fn:
            return swarm_heading(p, particles, state, ctx.get('prey'), ctx.get('fear'))
        if fn == 'cover.cover_heading' or fn.startswith('cover'):
            return cover_heading(p, fear, forts)
        if 'steer' in fn or 'wall' in fn:
            return flow_heading(p, W, H, forts)
        if 'hide' in fn:
            return hide_among_prey(p, ctx.get('preys') or [], fear)
        if 'corner' in fn:
            return anti_corner_herd(p, prey, W, H)
        return None

    for step in lst:
        step = step or {}
        fn = str(step.get('fn') or '')
        if not fn:
            continue
        when = step.get('when')
        if when and when not in (mode, state, 'always') and not (when == 'chase' and mode == 'chase'):
            continue
        h = resolve(fn)
        if h is None:
            continue
        blend = step.get('blend')
        if blend is None:
            wt = step.get('weight')
            blend = min(1.0, float(wt) * 0.5) if wt is not None else 0.45
        want = blend_headings(want, h, float(blend))
    return want


def nearest(p, type_name, particles):
    best, best_d = None, 1e12
    cap = (30 * p.size) ** 2
    for q in particles:
        if q is p or _tname(q) != type_name:
            continue
        d2 = (q.x - p.x) ** 2 + (q.y - p.y) ** 2
        if d2 < best_d and d2 <= cap:
            best_d, best = d2, q
    return {'obj': best, 'd': math.sqrt(best_d)} if best is not None else None


def pack_eject(p, particles, W, H):
    edge = p.size * 5.5
    on_edge = p.x < edge or p.x > W - edge or p.y < edge or p.y > H - edge
    if not on_edge:
        return None
    nx = ny = 0.0
    if p.x < edge:
        nx = 1.0
    elif p.x > W - edge:
        nx = -1.0
    if p.y < edge:
        ny = 1.0
    elif p.y > H - edge:
        ny = -1.0
    return ang_norm(math.atan2(nx, -ny) + ((int(getattr(p, 'id', 0) or 0) % 7) - 3) * 0.22)


def wall_escape(p, W, H, pad):
    band = p.size * 4.0
    fx = fy = 0.0
    if p.x < band:
        fx += (band - p.x) / band
    if p.x > W - band:
        fx -= (p.x - (W - band)) / band
    if p.y < band:
        fy += (band - p.y) / band
    if p.y > H - band:
        fy -= (p.y - (H - band)) / band
    if abs(fx) + abs(fy) < 0.04:
        return None
    corner = (p.x < band or p.x > W - band) and (p.y < band or p.y > H - band)
    return {'h': math.atan2(fx, -fy), 'w': 0.85 if corner else 0.7}


def _apply_plane_impulse(p, nx, ny, rx, ry, e, mu):
    _ensure_vel(p)
    mass = _mass_of(p)
    inertia = _inertia_of(p, mass)
    ox, oy = _omega_cross(p.omega, rx, ry)
    vcx, vcy = p.vx + ox, p.vy + oy
    rel_n = vcx * nx + vcy * ny
    if rel_n >= 0:
        return
    inv_m = 1.0 / max(1e-9, mass)
    jn = -(1.0 + e) * rel_n / inv_m
    tx, ty = -ny, nx
    rel_t = vcx * tx + vcy * ty
    rxt = rx * ty - ry * tx
    kt = inv_m + (rxt * rxt) / max(1e-9, inertia)
    jt = -rel_t / max(1e-9, kt)
    max_j = mu * abs(jn)
    if jt > max_j:
        jt = max_j
    elif jt < -max_j:
        jt = -max_j
    jx = jn * nx + jt * tx
    jy = jn * ny + jt * ty
    p.vx += jx * inv_m
    p.vy += jy * inv_m
    p.omega += (rx * jy - ry * jx) / max(1e-9, inertia)


def bounce_wall(p, W, H):
    _ensure_vel(p)
    e = WALL_RESTITUTION
    mu = WALL_FRICTION
    m = p.size + 1
    r = float(p.size)
    hit = False
    if p.x > W - m:
        p.x = W - m
        _apply_plane_impulse(p, -1.0, 0.0, r, 0.0, e, mu)
        hit = True
    elif p.x < m:
        p.x = m
        _apply_plane_impulse(p, 1.0, 0.0, -r, 0.0, e, mu)
        hit = True
    if p.y > H - m:
        p.y = H - m
        _apply_plane_impulse(p, 0.0, -1.0, 0.0, r, e, mu)
        hit = True
    elif p.y < m:
        p.y = m
        _apply_plane_impulse(p, 0.0, 1.0, 0.0, -r, e, mu)
        hit = True
    if hit:
        # Off the wall, not at a shared centre point.
        nx = 0.0
        ny = 0.0
        if p.x <= m + 0.5:
            nx = 1.0
        elif p.x >= W - m - 0.5:
            nx = -1.0
        if p.y <= m + 0.5:
            ny = 1.0
        elif p.y >= H - m - 0.5:
            ny = -1.0
        p.angle = math.atan2(nx, -ny)
        p.speed = max(math.hypot(p.vx, p.vy), 2.8)
        p.vx = math.sin(p.angle) * p.speed
        p.vy = -math.cos(p.angle) * p.speed
    else:
        p.speed = math.hypot(p.vx, p.vy)


def bounce_fort(p, forts):
    _ensure_vel(p)
    for f in forts or ():
        if _fort_scale(f) < 0.85:
            continue
        dx, dy = p.x - f.x, p.y - f.y
        dist = math.hypot(dx, dy)
        min_d = p.size + _fort_r(f) + SEPARATION_SLOP
        if dist >= min_d or dist < 1e-8:
            continue
        nx = math.sin(p.angle + math.pi) if dist < 1e-5 else dx / dist
        ny = -math.cos(p.angle + math.pi) if dist < 1e-5 else dy / dist
        p.x = f.x + nx * min_d
        p.y = f.y + ny * min_d
        r = float(p.size)
        _apply_plane_impulse(p, nx, ny, nx * r, ny * r, FORT_RESTITUTION, FORT_FRICTION)
        p.angle = math.atan2(nx, -ny)
        p.speed = max(math.hypot(p.vx, p.vy), 2.4)
        p.vx = math.sin(p.angle) * p.speed
        p.vy = -math.cos(p.angle) * p.speed


def _apply_pair_impulse(a, b, nx, ny, e, mu):
    _ensure_vel(a)
    _ensure_vel(b)
    ra, rb = float(a.size), float(b.size)
    rax, ray = nx * ra, ny * ra
    rbx, rby = -nx * rb, -ny * rb
    aox, aoy = _omega_cross(a.omega, rax, ray)
    box, boy = _omega_cross(b.omega, rbx, rby)
    rvx = (a.vx + aox) - (b.vx + box)
    rvy = (a.vy + aoy) - (b.vy + boy)
    rel_n = rvx * nx + rvy * ny
    if rel_n > 0:
        return
    ma, mb = _mass_of(a), _mass_of(b)
    ia, ib = _inertia_of(a, ma), _inertia_of(b, mb)
    inv_a, inv_b = 1.0 / max(1e-9, ma), 1.0 / max(1e-9, mb)
    kn = inv_a + inv_b
    jn = -(1.0 + e) * rel_n / max(1e-9, kn)
    tx, ty = -ny, nx
    rel_t = rvx * tx + rvy * ty
    rxta = rax * ty - ray * tx
    rxtb = rbx * ty - rby * tx
    kt = inv_a + inv_b + (rxta * rxta) / max(1e-9, ia) + (rxtb * rxtb) / max(1e-9, ib)
    jt = -rel_t / max(1e-9, kt)
    max_j = mu * abs(jn)
    if jt > max_j:
        jt = max_j
    elif jt < -max_j:
        jt = -max_j
    jx = jn * nx + jt * tx
    jy = jn * ny + jt * ty
    a.vx += jx * inv_a
    a.vy += jy * inv_a
    b.vx -= jx * inv_b
    b.vy -= jy * inv_b
    a.omega += (rax * jy - ray * jx) / max(1e-9, ia)
    b.omega += (rbx * jy - rby * jx) / max(1e-9, ib)
    a.speed = math.hypot(a.vx, a.vy)
    b.speed = math.hypot(b.vx, b.vy)


def voronoi_assign(hunters, preys):
    mapping = {}
    if not preys or not hunters:
        return mapping
    cap = max(1, int(math.ceil(len(hunters) / float(len(preys)))))
    load = {_pid(pr): 0 for pr in preys}
    pairs = []
    for h in hunters:
        for pr in preys:
            d = (h.x - pr.x) ** 2 + (h.y - pr.y) ** 2
            pairs.append((d, h, pr))
    pairs.sort(key=lambda t: t[0])
    for _, h, pr in pairs:
        hid, prid = _pid(h), _pid(pr)
        if mapping.get(hid):
            continue
        if load.get(prid, 0) >= cap:
            continue
        mapping[hid] = pr
        load[prid] = load.get(prid, 0) + 1
    for h in hunters:
        hid = _pid(h)
        if mapping.get(hid):
            continue
        dest, best = preys[0], 1e18
        for pr in preys:
            prid = _pid(pr)
            score = load.get(prid, 0) * 1e9 + (h.x - pr.x) ** 2 + (h.y - pr.y) ** 2
            if score < best:
                best, dest = score, pr
        mapping[hid] = dest
        load[_pid(dest)] = load.get(_pid(dest), 0) + 1
    return mapping


def _card_moves(tname, card):
    ov = (playbook.TEAM_OVERLAYS.get(tname) or {}).get(card) or {}
    mv = ov.get('movement')
    if mv:
        return list(mv)
    mv = playbook.movement_for(card, tname)
    return mv or DEFAULT_MOVES['PACK_HUNT']


def _spec(tname, card):
    try:
        return playbook.spec_for(tname, card) or {}
    except Exception:
        return {}


def _max_speed(p, c, world_k):
    tn = _tname(p)
    spec = _spec(tn, getattr(p, 'card', None) or 'PACK_HUNT')
    base = spec.get('base') or {}
    mot = DEFAULT_MOTION.get(tn) or {'speed': 1.3, 'turn': 13.0}
    try:
        sp0 = float(base.get('speed_base') or mot['speed'])
    except Exception:
        sp0 = mot['speed']
    sp = sp0 * CRUISE_MULT * world_k
    self_n = c.get(tn, 0)
    fear_n = c.get(FEAR_N[tn], 0)
    if self_n <= 2:
        sp *= 1.2
    if self_n == 1 and fear_n > 0:
        sp *= LAST_MAN_FEAR_SPEED
    return max(0.8, sp)


def _ensure_state(world):
    if getattr(world, '_js_hold', None) is None:
        world._js_hold = {
            'ROCK': {'card': None, 'frames': 0},
            'PAPER': {'card': None, 'frames': 0},
            'SCISSORS': {'card': None, 'frames': 0},
        }
    if getattr(world, '_js_voronoi', None) is None:
        world._js_voronoi = {'key': '', 'map': {}}
    if getattr(world, '_js_tick_i', None) is None:
        world._js_tick_i = 0


def think(world, p, counts, W, H, pad, world_k, forts):
    tn = _tname(p)
    self_n = counts.get(tn, 0)
    prey_n = counts.get(PREY_N[tn], 0)
    fear_n = counts.get(FEAR_N[tn], 0)
    state = playbook.match_state(self_n, fear_n, prey_n)
    slot = world._js_hold[tn]
    sid, frames, _ = playbook.select(
        tn, state, current=slot.get('card'), hold_frames=slot.get('frames') or 0)
    slot['card'] = sid
    slot['frames'] = frames
    p.card = sid
    p.state = state
    team = None
    try:
        team = world.teams.get(p.type)
        if team is not None:
            team.strategy_id = sid
            team.strategy_hold = frames
    except Exception:
        pass
    prey_t, fear_t = PREY_N[tn], FEAR_N[tn]
    prey = nearest(p, prey_t, world.particles)
    fear = nearest(p, fear_t, world.particles)
    if fear and fear.get('obj') is not None and fear_n > 0:
        fo = fear['obj']
        p._lastFear = {'x': fo.x, 'y': fo.y}
        near, far = 5 * p.size, 30 * p.size
        df = 1.0 if fear['d'] < near else max(0.0, 1.0 - (fear['d'] - near) / max(1.0, far - near))
        p._fear_intensity = min(1.0, float(getattr(p, '_fear_intensity', 0) or 0) + FEAR_BUILD * max(0.3, df))
        p._frames_since_fear = 0
    else:
        p._frames_since_fear = int(getattr(p, '_frames_since_fear', 0) or 0) + 1
        rate = FEAR_DECAY_FAST if fear_n <= 0 else FEAR_DECAY
        extra = min(0.06, p._frames_since_fear * 0.002)
        p._fear_intensity = max(0.0, float(getattr(p, '_fear_intensity', 0) or 0) - rate - extra)
    spec = _spec(tn, sid)
    base = spec.get('base') or {}
    mot = DEFAULT_MOTION.get(tn) or {'speed': 1.3, 'turn': 13.0}
    try:
        max_turn = float(base.get('turn_base') or mot['turn']) * math.pi / 180.0
    except Exception:
        max_turn = mot['turn'] * math.pi / 180.0
    w = spec.get('weights') or {}
    cruise = _max_speed(p, counts, world_k)
    mode, want, look = 'idle', p.angle, 12.0
    last = getattr(p, '_lastFear', None)
    fobj = (fear and fear.get('obj')) or last
    if isinstance(fobj, dict):
        class _P:  # lastFear snapshot {x,y}
            pass
        snap = _P()
        snap.x, snap.y = float(fobj.get('x', 0)), float(fobj.get('y', 0))
        fobj = snap
    sectors = rank_dirs(p, world.particles, counts, forts)
    wlook, wmargin = 90.0, pad + p.size + 22
    for s in sectors:
        hx = math.sin(p.angle + s['c'])
        hy = -math.cos(p.angle + s['c'])
        pen = 0.0
        for frac in (0.35, 0.65, 1.0):
            ax = p.x + hx * wlook * frac
            ay = p.y + hy * wlook * frac
            if ax < wmargin:
                pen = max(pen, (wmargin - ax) / wmargin)
            elif ax > W - wmargin:
                pen = max(pen, (ax - (W - wmargin)) / wmargin)
            if ay < wmargin:
                pen = max(pen, (wmargin - ay) / wmargin)
            elif ay > H - wmargin:
                pen = max(pen, (ay - (H - wmargin)) / wmargin)
        if pen > 0:
            s['risk'] += 1.4 * pen
        s['score'] = s['reward'] + s['conf'] * 0.2 - s['risk'] * 1.15
    best_s = safest = sectors[0]
    for s in sectors[1:]:
        if s['score'] > best_s['score']:
            best_s = s
        if s['risk'] < safest['risk']:
            safest = s
    sector_h = ang_norm(p.angle + best_s['c'])
    safe_h = ang_norm(p.angle + safest['c'])
    if fear_n > 0 and prey_n <= 1 and prey and prey['d'] < p.size * 6:
        want = heading_to(prey['obj'].x, prey['obj'].y, p.x, p.y)
        want = blend_headings(want, safe_h, 0.55)
        mode = 'evade'
        p._locked = None
    elif state == 'CLEAR_HUNT' and prey_n > 0:
        mode = 'chase'
        hunters = [q for q in world.particles if _tname(q) == tn]
        preys_l = [q for q in world.particles if _tname(q) == prey_t]
        ids = [str(_pid(q)) for q in preys_l]
        ids.sort()
        key = prey_t + ':' + ','.join(ids) + ':' + str(int(world._js_tick_i / 8))
        bag = world._js_voronoi
        if bag.get('key') != key:
            bag['key'] = key
            bag['map'] = voronoi_assign(hunters, preys_l)
        tgt = bag['map'].get(_pid(p))
        if tgt is None or _tname(tgt) != prey_t:
            ordered = sorted(hunters, key=lambda z: _pid(z))
            try:
                hi = ordered.index(p)
            except ValueError:
                hi = abs(_pid(p))
            tgt = preys_l[hi % len(preys_l)] if preys_l else None
            if tgt is not None:
                bag['map'][_pid(p)] = tgt
        p._locked = tgt
        want = chase_heading(p, tgt, look) if tgt is not None else want
    elif fear and fobj is not None and fear_n > 0 and state != 'CLEAR_HUNT':
        fear_ahead = abs(ang_diff(p.angle, heading_to(p.x, p.y, fobj.x, fobj.y))) < math.pi / 2
        fear_close = fear['d'] < 8 * p.size or (fear_ahead and fear['d'] < 12 * p.size)
        if fear_close:
            mode = 'evade'
            want = safe_h
            p._locked = None
        elif prey:
            mode = 'chase'
            want = blend_headings(chase_heading(p, prey['obj'], look), sector_h, 0.35)
            p._locked = prey['obj']
    elif prey:
        closer = 0
        for q in world.particles:
            if q is p or _tname(q) != tn:
                continue
            if math.hypot(q.x - prey['obj'].x, q.y - prey['obj'].y) + p.size < prey['d']:
                closer += 1
        if closer >= 3:
            mode = 'bias'
            want = sector_h
            p._locked = None
        else:
            mode = 'chase'
            want = blend_headings(chase_heading(p, prey['obj'], look), sector_h, 0.35)
            p._locked = prey['obj']
    else:
        want = sector_h
        mode = 'bias'
    we = wall_escape(p, W, H, pad)
    if we:
        want = blend_headings(want, we['h'], we['w'])
    swarm = swarm_heading(p, world.particles, state, prey, fear, w)
    if mode == 'evade':
        want = blend_headings(want, swarm, 0.35)
    elif mode == 'chase' and state != 'CLEAR_HUNT':
        want = blend_headings(want, swarm, 0.25)
    # JS: unset _lock_ttl is not <= 0 (undefined <= 0 is false). Particle.__init__
    # seeds 0, which would expire a lock assigned this frame.
    ttl = getattr(p, '_lock_ttl', None)
    if ttl is None:
        pass
    else:
        ttl = int(ttl)
        if ttl > 0:
            ttl -= 1
            p._lock_ttl = ttl
        if getattr(p, '_locked', None) is not None and ttl <= 0:
            p._locked = None
    if mode == 'chase' and getattr(p, '_locked', None) is not None:
        p._lock_ttl = 80
    allies = [q for q in world.particles if _tname(q) == tn]
    preys = [q for q in world.particles if _tname(q) == prey_t]
    if not getattr(p, '_role', None):
        roles_assign(list(allies))
    hide_h = hide_among_prey(p, preys, fear['obj'] if fear else None)
    if hide_h and state in ('OUTNUMBERED', 'NO_PREY_FEAR_ALIVE'):
        want = blend_headings(want, hide_h, 0.35)
    corner_h = anti_corner_herd(p, prey['obj'] if prey else None, W, H)
    if corner_h and fear_n > 0 and mode == 'chase':
        want = blend_headings(want, corner_h, 0.4)
    cov = cover_heading(p, fear['obj'] if fear else None, forts)
    if cov and mode == 'evade' and fear and fear['d'] < p.size * 6:
        want = blend_headings(want, cov, 0.25)
    assigned = getattr(p, '_locked', None) if state == 'CLEAR_HUNT' else (prey['obj'] if prey else None)
    prey_ctx = {'obj': assigned, 'd': 0} if assigned is not None else prey
    want = apply_moves(want, _card_moves(tn, sid), {
        'p': p, 'particles': world.particles, 'forts': forts, 'W': W, 'H': H,
        'prey': prey_ctx, 'fear': fear, 'state': state, 'mode': mode,
        'look': look, 'fearN': fear_n, 'preyN': prey_n, 'allies': allies, 'preys': preys,
        'prey_obj': assigned, 'fear_obj': fear['obj'] if fear else None,
    })
    locked = getattr(p, '_locked', None)
    if state == 'CLEAR_HUNT' and locked is not None and locked in world.particles:
        want = chase_heading(p, locked, look)
        mode = 'chase'
    if fear_n > 0 and prey_n <= 1 and prey and prey.get('obj') is not None and prey['d'] < p.size * 4:
        want = safe_h
        mode = 'bias'
        p._locked = None
    if mode == 'evade':
        want = ang_norm(want + ((int(getattr(p, 'id', 0) or 0) % 7) - 3) * 0.2)
    we2 = wall_escape(p, W, H, pad)
    if we2:
        want = blend_headings(want, we2['h'], we2['w'])
    eject = pack_eject(p, world.particles, W, H)
    if eject is not None:
        want = blend_headings(want, eject, 0.85)
    near_n = 0
    r5 = (p.size * 5) ** 2
    for q in allies:
        if q is p:
            continue
        dx, dy = q.x - p.x, q.y - p.y
        if dx * dx + dy * dy < r5:
            near_n += 1
    if near_n >= 3:
        want = blend_headings(want, desync_heading(p, prey['obj'] if prey else None), 0.3)
    if mode == 'evade' and fear and fear['d'] < p.size * 6:
        ahead = abs(ang_diff(p.angle, heading_to(p.x, p.y, fear['obj'].x, fear['obj'].y)))
        if ahead < 0.6:
            p.speed *= 0.72
    for f in forts or ():
        if _fort_scale(f) < 0.85:
            continue
        dx, dy = p.x - f.x, p.y - f.y
        d = math.hypot(dx, dy)
        r = _fort_r(f)
        if d < r + p.size * 3.2:
            t1 = math.atan2(-dy, dx)
            t2 = ang_norm(t1 + math.pi)
            tang = t1 if abs(ang_diff(want, t1)) <= abs(ang_diff(want, t2)) else t2
            out = math.atan2(dx, -dy)
            ww = 0.92 if d < r + p.size * 1.8 else 0.5
            want = blend_headings(blend_headings(want, tang, ww), out, 0.28)
    if want is not None:
        dlt = ang_diff(p.angle, want)
        p.angle = ang_norm(p.angle + max(-max_turn, min(max_turn, dlt)))
    target_sp = cruise
    if mode == 'evade':
        target_sp = cruise * 1.12
    if mode == 'chase' and state == 'CLEAR_HUNT':
        target_sp = cruise * 1.35
    if p.speed < target_sp:
        p.speed += min(THRUST, target_sp - p.speed)
    else:
        p.speed += (target_sp - p.speed) * THRUST
    if p.speed > cruise * 1.35:
        p.speed = cruise * 1.35


def _unstick_friends(particles):
    for _pass in range(2):
        for i in range(len(particles)):
            p = particles[i]
            min_d = p.size * 2.55
            min_d2 = min_d * min_d
            for j in range(i + 1, len(particles)):
                q = particles[j]
                if p.type != q.type:
                    continue
                dx, dy = p.x - q.x, p.y - q.y
                d2 = dx * dx + dy * dy
                if d2 >= min_d2 or d2 < 1e-8:
                    continue
                d = math.sqrt(d2)
                push = (min_d - d) * 0.85
                nx, ny = dx / d, dy / d
                p.x += nx * push
                p.y += ny * push
                q.x -= nx * push
                q.y -= ny * push


def collide(world, allow_convert=True):
    particles = world.particles
    types_alive = len({_tname(p) for p in particles})
    eat_cd = 6 if types_alive <= 2 else 10
    for p in particles:
        cd = int(getattr(p, '_eat_cd', 0) or 0)
        if cd > 0:
            p._eat_cd = cd - 1
    for i in range(len(particles)):
        a = particles[i]
        for j in range(i + 1, len(particles)):
            b = particles[j]
            dx, dy = b.x - a.x, b.y - a.y
            dist = math.hypot(dx, dy)
            min_d = a.size + b.size
            if dist >= min_d or dist < 1e-8:
                continue
            nx, ny = dx / dist, dy / dist
            same = a.type == b.type
            push = (min_d - dist + SEPARATION_SLOP) * (1.15 if same else 0.55)
            a.x -= nx * push
            a.y -= ny * push
            b.x += nx * push
            b.y += ny * push
            if same:
                continue
            an, bn = _tname(a), _tname(b)
            a_eats = PREY_N.get(an) == bn
            b_eats = PREY_N.get(bn) == an
            if not a_eats and not b_eats:
                continue
            _apply_pair_impulse(a, b, nx, ny, PAIR_RESTITUTION, PAIR_FRICTION)
            if not allow_convert:
                continue
            winner_p = a if a_eats else b
            if int(getattr(winner_p, '_eat_cd', 0) or 0) > 0:
                continue
            hx, hy = math.sin(winner_p.angle), -math.cos(winner_p.angle)
            face = (hx * nx + hy * ny) if a_eats else (-hx * nx - hy * ny)
            if face < 0.25:
                continue
            loser = b if a_eats else a
            lose_was = loser.type
            loser.type = winner_p.type
            winner_p._eat_cd = eat_cd
            W = float(getattr(world, 'width', 800) or 800)
            H = float(getattr(world, 'height', 600) or 600)
            world_k = min(W, H) / 800.0
            wn = _tname(winner_p)
            mot = DEFAULT_MOTION.get(wn) or {'speed': 1.3}
            keep = float(mot['speed']) * CRUISE_MULT * world_k * COLLISION_SPEED_KEEP
            for body in (a, b):
                body.speed = keep
                body.vx = math.sin(body.angle) * keep
                body.vy = -math.cos(body.angle) * keep
            try:
                if hasattr(world, 'metrics') and world.metrics is not None:
                    world.metrics.log_conversion(winner_p, loser, loser_type_before=lose_was)
            except Exception:
                pass
            try:
                winner_p.get_team().register_conversion()
            except Exception:
                pass


def _cruise_of(p, world_k):
    mot = DEFAULT_MOTION.get(_tname(p)) or {'speed': 1.3}
    return float(mot['speed']) * CRUISE_MULT * world_k


def victory_steer(p, particles, dance, tick, W, H, world_k, charge_ang):
    """Winner celebration. dance 0=haka 1=charge 2=ring 3=wave 4=pairs."""
    cruise = _cruise_of(p, world_k)
    pid = _pid(p)
    ordered = sorted(particles, key=_pid)
    n = max(1, len(ordered))
    try:
        idx = next(i for i, q in enumerate(ordered) if _pid(q) == pid)
    except StopIteration:
        idx = pid % n
    cx = sum(q.x for q in particles) / n
    cy = sum(q.y for q in particles) / n
    beat = int(tick) % 18
    if dance == 0:
        p.angle = math.pi
        if beat <= 4:
            p.speed = cruise * 0.15
        elif beat <= 11:
            p.angle = math.pi + (0.18 if (idx % 2) else -0.18)
            p.speed = cruise * 1.25
        else:
            p.angle = math.pi
            p.speed = cruise * 0.45
    elif dance == 1:
        p.angle = float(charge_ang)
        p.speed = cruise * 1.2
    elif dance == 2:
        R = 0.28 * min(W, H)
        ang = ang_norm((tick * 0.07) + (2.0 * math.pi * idx / n))
        tx = cx + math.cos(ang) * R
        ty = cy + math.sin(ang) * R
        p.angle = heading_to(p.x, p.y, tx, ty)
        p.speed = cruise * 1.05
    elif dance == 3:
        p.angle = (math.pi * 0.5) if (idx % 2 == 0) else (math.pi * 1.5)
        p.speed = cruise * (1.0 + 0.25 * math.sin(tick * 0.22 + idx * 0.7))
    else:
        mate = ordered[idx ^ 1] if n > 1 else p
        if beat < 9:
            p.angle = heading_to(p.x, p.y, mate.x, mate.y)
            p.speed = cruise * 1.15
        else:
            p.angle = heading_to(p.x, p.y, p.x + (p.x - mate.x), p.y + (p.y - mate.y))
            p.speed = cruise * 0.7
    p.vx = math.sin(p.angle) * p.speed
    p.vy = -math.cos(p.angle) * p.speed


def step(world, move=True, keep_alive=False):
    """One JS-identical tick. Mutates world.particles in place."""
    _ensure_state(world)
    W = float(getattr(world, 'width', 800) or 800)
    H = float(getattr(world, 'height', 600) or 600)
    world_k = min(W, H) / 800.0
    pad = max(16.0, 28.0 * world_k)
    body = 18.0 * world_k
    forts = list(getattr(world, 'fort_list', None) or [])
    try:
        world.particles.sort(key=_pid)
    except Exception:
        pass
    particles = list(world.particles or [])
    if not particles:
        return
    for p in particles:
        if not getattr(world, '_js_sized', False):
            p.size = body
            # Match rps.js createSim spawn: _lock_ttl unset, fear clocks at 0.
            p._lock_ttl = None
            p._frames_since_fear = 0
            p._fear_intensity = 0.0
            _ensure_vel(p)
        if not hasattr(p, 'card'):
            p.card = None
        if not hasattr(p, '_fear_intensity'):
            p._fear_intensity = 0.0
    world._js_sized = True
    counts = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
    for p in particles:
        counts[_tname(p)] = counts.get(_tname(p), 0) + 1
    alive = [k for k, v in counts.items() if v > 0]
    winner = None
    if len(alive) <= 1:
        winner = alive[0] if alive else 'NONE'
        world._js_match_over = True
    play_ai = move and not winner
    world._js_tick_i = int(getattr(world, '_js_tick_i', 0) or 0) + 1
    if winner and getattr(world, '_js_dance', None) is None:
        from arena.layout import mulberry32
        seed = int(getattr(world, '_pin_match_seed', 1) or 1)
        rng = mulberry32((seed + world._js_tick_i) & 0xffffffff)
        world._js_dance = int(rng() * 5) % 5
        world._js_charge_ang = rng() * math.pi * 2
    if play_ai or (not move):
        for p in particles:
            think(world, p, counts, W, H, pad, world_k, forts)
            p.angle = _snap(ang_norm(p.angle), 1e6)
            p.speed = _snap(max(0.0, p.speed), 1e6)
    elif winner and (move or keep_alive):
        dance = int(getattr(world, '_js_dance', 0) or 0)
        charge_ang = float(getattr(world, '_js_charge_ang', 1.2) or 1.2)
        for p in particles:
            victory_steer(p, particles, dance, world._js_tick_i, W, H, world_k, charge_ang)
    if move or keep_alive:
        for p in particles:
            _ensure_vel(p)
            hx, hy = math.sin(p.angle), -math.cos(p.angle)
            sp = float(p.speed or 0)
            tx, ty = hx * sp, hy * sp
            p.vx = p.vx * 0.20 + tx * 0.80
            p.vy = p.vy * 0.20 + ty * 0.80
            ox, oy = p.x, p.y
            p.x += p.vx
            p.y += p.vy
            dist = math.hypot(p.x - ox, p.y - oy)
            p.omega *= SPIN_DAMP
            roll = float(getattr(p, 'roll', 0) or 0) + p.omega
            if dist > 0.15:
                roll += 0.35 * dist / max(4.0, p.size)
            p.roll = roll
            p._roll_angle = roll
            p.x = _snap(p.x, 1e4)
            p.y = _snap(p.y, 1e4)
        collide(world, allow_convert=not winner)
        _unstick_friends(world.particles)
        for p in list(world.particles):
            bounce_wall(p, W, H)
            bounce_fort(p, forts)
            p.x = max(p.size + 2, min(W - p.size - 2, p.x))
            p.y = max(p.size + 2, min(H - p.size - 2, p.y))
            snap_pose(p)
    try:
        world.type_counts = {t: sum(1 for p in world.particles if p.type == t) for t in ParticleType}
    except Exception:
        pass
