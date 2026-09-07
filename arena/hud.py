"""
HUD for Rock, Paper, Scissors.

Toolbar (type counts, match timer, audio toggle) and winner banner.
particle.py imports draw_toolbar / draw_winner_banner — do not import particle.
"""

import math
import pygame


def _phase_name(world):
    phase = getattr(world, 'phase', None)
    return getattr(phase, 'name', '') or ''


def _type_name(ptype):
    return getattr(ptype, 'name', None) or str(ptype)


def draw_winner_banner(world):
    """Animated semi-transparent winner panel with icon."""
    wtype = world.particles[0].type if world.particles else None
    name = _type_name(wtype) if wtype is not None else '?'

    elapsed = max(0, pygame.time.get_ticks() - (world.gameover_start_ticks or pygame.time.get_ticks()))
    fade = min(1.0, elapsed / 600.0)
    pulse = 1.0 + 0.06 * math.sin(elapsed / 280.0) if elapsed > 600 else 0.85 + 0.15 * fade
    float_y = 6 * math.sin(elapsed / 400.0) if elapsed > 400 else 0

    icon_sz = int(64 * pulse)
    pad_x, pad_y = 28, 20
    text_main = world.winner_font.render(f"{name} WINS", True, (255, 220, 80))
    frozen = getattr(world, 'frozen_match_ms', 0) or 0
    if not frozen and world.match_start_ticks is not None:
        frozen = max(0, pygame.time.get_ticks() - world.match_start_ticks)
    mm, ss = divmod(frozen // 1000, 60)
    text_sub = world.winner_font_sm.render(
        f"match over  ·  {mm:02d}:{ss:02d}", True, (180, 180, 200)
    )

    panel_w = max(text_main.get_width(), icon_sz) + pad_x * 2
    panel_h = icon_sz + text_main.get_height() + text_sub.get_height() + pad_y * 2 + 16

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    alpha = int(175 * fade)
    pygame.draw.rect(panel, (18, 18, 28, alpha), panel.get_rect(), border_radius=14)
    pygame.draw.rect(panel, (80, 80, 110, min(200, alpha + 30)), panel.get_rect(), 2, border_radius=14)

    icon = world.winner_icons.get(wtype) if wtype is not None else None
    if icon is not None:
        if icon_sz != 64:
            icon = pygame.transform.smoothscale(icon, (icon_sz, icon_sz))
        if fade < 1.0:
            icon = icon.copy()
            icon.set_alpha(int(255 * fade))
        ix = (panel_w - icon_sz) // 2
        panel.blit(icon, (ix, pad_y))
    else:
        pygame.draw.circle(panel, (200, 200, 200),
                           (panel_w // 2, pad_y + icon_sz // 2), max(4, icon_sz // 2))

    ring_alpha = int(220 * fade)
    ring_s = pygame.Surface((icon_sz + 12, icon_sz + 12), pygame.SRCALPHA)
    pygame.draw.circle(ring_s, (40, 200, 80, ring_alpha),
                       ((icon_sz + 12) // 2, (icon_sz + 12) // 2), icon_sz // 2 + 4, 3)
    panel.blit(ring_s, ((panel_w - icon_sz - 12) // 2, pad_y - 6))

    if fade < 1.0:
        text_main = text_main.copy()
        text_main.set_alpha(int(255 * fade))
        text_sub = text_sub.copy()
        text_sub.set_alpha(int(220 * fade))
    ty = pad_y + icon_sz + 8
    panel.blit(text_main, ((panel_w - text_main.get_width()) // 2, ty))
    panel.blit(text_sub, ((panel_w - text_sub.get_width()) // 2, ty + text_main.get_height() + 2))

    px = (world.width - panel_w) // 2
    py = int((world.height - panel_h) // 2 + float_y)
    world.screen.blit(panel, (px, py))


def draw_toolbar(world):
    """Semi-transparent top-right toolbar: counts, time, audio."""
    icons = getattr(world, 'toolbar_icons', {}) or {}
    order = list(icons.keys())
    if not order:
        counts = getattr(world, 'type_counts', {}) or {}
        order = list(counts.keys())

    icon_size = 28
    pad = 10
    gap = 6
    line_h = icon_size + gap
    footer_h = 52
    panel_w = 120
    n = max(3, len(order))
    panel_h = pad * 2 + n * line_h - gap + footer_h

    panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    pygame.draw.rect(panel, (18, 18, 28, 165), panel.get_rect(), border_radius=12)
    pygame.draw.rect(panel, (80, 80, 110, 190), panel.get_rect(), 2, border_radius=12)

    # HUD badge colours (ROCK red, PAPER yellow, SCISSORS blue)
    fallback_rgb = ((236, 78, 108), (247, 196, 48), (70, 178, 230))

    winner_type = None
    pname = _phase_name(world)
    if pname in ('GAMEOVER', 'FORTS_OUT') and world.particles:
        winner_type = world.particles[0].type

    y = pad
    if hasattr(world, 'visible_type_counts'):
        live_counts = world.visible_type_counts()
    else:
        live_counts = getattr(world, 'type_counts', {}) or {}

    for i, t in enumerate(order):
        count = live_counts.get(t, 0)
        cx = pad + icon_size // 2
        cy = y + icon_size // 2

        if count == 0:
            pygame.draw.circle(panel, (220, 40, 40), (cx, cy), icon_size // 2 + 3, 3)
        elif t == winner_type:
            pygame.draw.circle(panel, (40, 200, 80), (cx, cy), icon_size // 2 + 3, 3)

        if t in icons:
            panel.blit(icons[t], (pad, y))
        else:
            pygame.draw.circle(panel, fallback_rgb[i % 3], (cx, cy), icon_size // 2 - 1)

        if count == 0:
            txt = world.toolbar_font.render("0", True, (255, 70, 70))
        else:
            txt = world.toolbar_font.render(str(count), True, (235, 235, 245))
        panel.blit(txt, (pad + icon_size + 12, y + 4))
        y += line_h

    pygame.draw.line(panel, (70, 70, 95, 160), (pad, y + 2), (panel_w - pad, y + 2), 1)
    y += 10

    winner_up = pname in ('GAMEOVER', 'FORTS_OUT')
    if winner_up and getattr(world, 'frozen_match_ms', 0):
        elapsed_ms = world.frozen_match_ms
    elif world.match_start_ticks is not None and pname == 'PLAYING':
        elapsed_ms = max(0, pygame.time.get_ticks() - world.match_start_ticks)
    else:
        elapsed_ms = 0
    secs = elapsed_ms // 1000
    mm, ss = divmod(secs, 60)
    time_str = f"{mm:02d}:{ss:02d}"
    time_lbl = world.toolbar_font_sm.render("TIME", True, (160, 160, 185))
    time_col = (255, 70, 70) if winner_up else (235, 235, 245)
    time_val = world.toolbar_font.render(time_str, True, time_col)
    panel.blit(time_lbl, (pad, y))
    panel.blit(time_val, (pad + 42, y - 2))
    y += 24

    audio_lbl = world.toolbar_font_sm.render("AUDIO", True, (160, 160, 185))
    panel.blit(audio_lbl, (pad, y + 2))
    btn_x, btn_y, btn_w, btn_h = pad + 52, y, 48, 20
    btn_col = (40, 160, 90) if world.audio_enabled else (140, 50, 50)
    pygame.draw.rect(panel, btn_col, (btn_x, btn_y, btn_w, btn_h), border_radius=4)
    pygame.draw.rect(panel, (200, 200, 220), (btn_x, btn_y, btn_w, btn_h), 1, border_radius=4)
    state = "ON" if world.audio_enabled else "OFF"
    st = world.toolbar_font_sm.render(state, True, (255, 255, 255))
    panel.blit(st, (btn_x + (btn_w - st.get_width()) // 2, btn_y + 2))

    px = world.width - panel_w - 14
    py = 12
    world.screen.blit(panel, (px, py))
    world._audio_btn_rect = pygame.Rect(px + btn_x, py + btn_y, btn_w, btn_h)
