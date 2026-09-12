"""
Marble visuals for Rock / Paper / Scissors particles.

Body, contact shadow, facing icon, roll speckle.
No movement / AI — particle.py calls display_particle(p, screen).
Do not import particle at module level.
"""

import math
import pygame


def _cfg():
    from config import Config
    return Config


def _type_defaults():
    from config import TYPE_DEFAULTS
    return TYPE_DEFAULTS


def _playing():
    from config import MatchPhase
    return MatchPhase.PLAYING


# 3/4 tilt: maps the underside (floor, z=-1) onto the BOTTOM of the disk
# so the speckle is visible at the contact patch. Camera looks from +Z
# and a little from -Y (top of screen).
_ROLL_TILT = 0.62


def roll_speckle_proj(particle, orbit=0.55):
    """
    No-slip roll on the playfield.

    Frame: +X right, +Y down, +Z toward camera.
    Floor contact is the reverse face: P0 = (0, 0, -1).
    Travel H = (sin θ, -cos θ, 0). Floor normal N = (0, 0, 1).
    Roll axis A = N × H = (-Hy, Hx, 0). Right-hand: +roll moves the
    contact mark backward (−H) — the sphere rolls forward.

    P(φ) = (−H sin φ, −cos φ).
    Hide only once the mark has gone *under the front* (z<0 and on +H).
    Rear underside (floor, reverse side) stays visible via the 3/4 tilt.
    Returns (qx, qy, qz, sx, sy) or None.
    """
    heading = float(particle.angle)
    roll = float(getattr(particle, '_roll_angle', None) or getattr(particle, 'roll', 0.0) or 0.0)
    hx = math.sin(heading)
    hy = -math.cos(heading)
    # P0 = (0,0,-1). Rodrigues around A=(-hy,hx,0) collapses to:
    s = math.sin(roll)
    c = math.cos(roll)
    qx = -hx * s
    qy = -hy * s
    qz = -c
    # Front-underside is out of sight; floor/rear-underside is the start pose
    if qz < -0.02 and (qx * hx + qy * hy) > 0.08:
        return None
    # 3/4 project: underside sits on the bottom rim (toward the drop shadow)
    sx = qx
    sy = qy - _ROLL_TILT * qz
    return qx, qy, qz, sx, sy

def blit_roll_speckle(particle, screen, sc, vx, vy, rad, shine=1.0, clip_mode='none', clip_ang=0.0):
    if shine <= 0.08:
        return
    proj = roll_speckle_proj(particle)
    if proj is None:
        return
    qx, qy, qz, sx, sy = proj
    # Hide speckle when it sits on the shadowed cap
    if clip_mode == 'cap':
        cx = math.sin(clip_ang)
        cy = -math.cos(clip_ang)
        if qx * cx + qy * cy > 0.0:
            return
    scale = 0.86
    px = vx + int(sx * rad * scale)
    py = vy + int(sy * rad * scale)
    # Facing camera (qz→+1) is larger; floor/reverse (qz→−1) is a tight contact dot
    face = 0.5 + 0.5 * max(-1.0, min(1.0, qz))
    size = max(2, int((0.38 + 0.62 * face) * rad * 0.20 * (0.55 + 0.45 * shine)))
    alpha = max(28, min(255, int((70 + 160 * face) * shine)))
    if sc is not None:
        # white-ish cached dot
        dot = sc.trail_dot((255, 255, 255), size)
        if alpha < 250:
            try:
                dot = dot.copy()
                dot.set_alpha(alpha)
            except Exception:
                pass
        screen.blit(dot, dot.get_rect(center=(px, py)))
    else:
        pygame.draw.circle(screen, (255, 255, 255), (px, py), size)

def display_particle(particle, screen):

    sc = getattr(particle.w, 'surfaces', None)
    palette = getattr(_cfg(), 'MARBLE_COLORS', None) or {}
    col = palette.get(particle.type.name) or _type_defaults().get(particle.type.name, {}).get("color", (180, 180, 200))
    vs = max(0.0, getattr(particle, '_vis_scale', 1.0))
    if vs <= 0.02:
        return
    vx = int(particle.x)
    vy = int(particle.y + getattr(particle, '_vis_y_offset', 0.0))
    # Cached trail dots (only when fully visible)
    phase = getattr(particle.w, 'phase', _playing())
    if (phase == _playing() and vs > 0.85 and particle._trail
            and getattr(_cfg(), 'TRAIL_LEN', 0) > 0 and sc is not None):
        n = len(particle._trail)
        for i, (tx, ty) in enumerate(particle._trail):
            r = max(1, int(particle.size * 0.15 * (i + 1) / n * vs))
            dot = sc.trail_dot(col, r)
            screen.blit(dot, dot.get_rect(center=(int(tx), int(ty))))
    # Cached team-colour halo
    if getattr(_cfg(), 'ENABLE_GLOW', False) and sc is not None:
        gr = max(3, int(particle.size * 1.15 * vs))
        glow = sc.soft_circle(col, gr, int(getattr(_cfg(), 'GLOW_ALPHA', 70) * min(1.0, vs)))
        screen.blit(glow, glow.get_rect(center=(vx, vy)))
    use_marble = getattr(_cfg(), 'ENABLE_MARBLE', True) and sc is not None
    if use_marble:
        rad = max(6, int(particle.size * 1.05 * vs))
        shadow = sc.marble_shadow(rad, alpha=int(90 * min(1.0, vs)))
        screen.blit(shadow, shadow.get_rect(center=(vx, vy + max(3, rad // 2))))
        icon = None
        if particle.animation_images and getattr(_cfg(), 'MARBLE_ICON', True):
            try:
                icon = particle.animation_images[particle.type.value]
            except Exception:
                icon = None
        mode, sang, occ = 'none', 0.0, 0.0
        if (getattr(_cfg(), 'MARBLE_OCCLUSION', False)
                and hasattr(particle.w, 'marble_shadow_clip')):
            mode, sang, occ = particle.w.marble_shadow_clip(particle.x, particle.y, rad)
        lit = sc.get_marble(col, rad, 0.0, icon=None, type_value=particle.type.value, shaded=False)
        screen.blit(lit, lit.get_rect(center=(vx, vy)))
        cap_ok = getattr(_cfg(), 'MARBLE_CAP_SHADOW', False)
        if mode == 'full' or (mode == 'cap' and not cap_ok):
            dim = sc.get_marble(col, rad, 0.0, icon=None, type_value=particle.type.value, shaded=True)
            screen.blit(dim, dim.get_rect(center=(vx, vy)))
        elif mode == 'cap' and cap_ok:
            dim = sc.get_marble(col, rad, 0.0, icon=None, type_value=particle.type.value, shaded=True)
            cap = sc.shadow_cap_mask(rad, sang)
            layer = dim.copy()
            if cap.get_size() != layer.get_size():
                cap = pygame.transform.smoothscale(cap, layer.get_size())
            layer.blit(cap, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            screen.blit(layer, layer.get_rect(center=(vx, vy)))
        # Icon faces travel direction (heading), not roll
        if icon is not None and particle.animation_images:
            try:
                scale = float(getattr(_cfg(), 'MARBLE_ICON_SCALE', 0.42))
                iw = max(6, int(rad * 2 * scale))
                ic = sc.facing_icon(
                    particle.animation_images, particle.type.value, particle.angle, iw,
                    alpha=int(getattr(_cfg(), 'MARBLE_ICON_ALPHA', 165)),
                    step_deg=max(8, int(getattr(_cfg(), 'ROT_CACHE_STEP', 12))),
                )
                if ic is not None:
                    screen.blit(ic, ic.get_rect(center=(vx, vy)))
            except Exception:
                pass
        shine = 0.15 if mode == 'full' else 1.0
        if shine > 0.08:
            blit_roll_speckle(particle, screen, sc, vx, vy, rad, shine=shine,
                                    clip_mode=mode, clip_ang=sang)
    elif particle.animation_images and sc is not None:
        img = sc.rotated_sprite(
            particle.animation_images, particle.type.value, particle.angle,
            step_deg=getattr(_cfg(), 'ROT_CACHE_STEP', 6)
        )
        if img is not None:
            if vs < 0.99:
                w = max(1, int(img.get_width() * vs))
                h = max(1, int(img.get_height() * vs))
                img = pygame.transform.smoothscale(img, (w, h))
            screen.blit(img, img.get_rect(center=(vx, vy)))
    elif particle.animation_images:
        img = pygame.transform.rotozoom(
            particle.animation_images[particle.type.value], -math.degrees(particle.angle), vs
        )
        screen.blit(img, img.get_rect(center=(vx, vy)))
    else:
        pygame.draw.circle(screen, col, (vx, vy), max(1, int(particle.size * vs)))

