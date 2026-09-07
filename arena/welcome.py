"""
Welcome / title card for Rock, Paper, Scissors.

Sega / C64 CRT inter-match screen with a live learn ticker.
particle.py imports draw_welcome — this module must not import particle.
"""

import math
import random
import colorsys
import pygame


TYPE_COL = {
    'ROCK': (236, 78, 108),
    'PAPER': (247, 196, 48),
    'SCISSORS': (70, 178, 230),
}


def _fonts():
    return (
        pygame.font.Font(None, 72),
        pygame.font.Font(None, 36),
        pygame.font.Font(None, 28),
        pygame.font.Font(None, 22),
        pygame.font.Font(None, 18),
        pygame.font.Font(None, 16),
    )


def _ensure_crt_cache(world):
    """Build scan / vignette overlays once per resolution."""
    w, h = world.width, world.height
    cache = getattr(world, '_crt_cache', None)
    if cache and cache.get('w') == w and cache.get('h') == h:
        return cache
    scan = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(0, h, 2):
        a = 55 if (y % 4) == 0 else 28
        pygame.draw.line(scan, (0, 0, 0, a), (0, y), (w, y))
    # RGB triad hint every 3 px
    for x in range(0, w, 3):
        pygame.draw.line(scan, (40, 0, 0, 12), (x, 0), (x, h))
        pygame.draw.line(scan, (0, 40, 0, 10), (x + 1, 0), (x + 1, h))
        pygame.draw.line(scan, (0, 0, 40, 12), (x + 2, 0), (x + 2, h))

    vig = pygame.Surface((w, h), pygame.SRCALPHA)
    cx, cy = w * 0.5, h * 0.5
    max_r = math.hypot(cx, cy)
    # coarse vignette rings — cheap, cached
    for i in range(8, 0, -1):
        t = i / 8.0
        a = int(18 + 28 * t * t)
        r = int(max_r * (0.55 + 0.5 * t))
        pygame.draw.circle(vig, (0, 0, 0, a), (int(cx), int(cy)), r, 18)

    cache = {
        'w': w, 'h': h,
        'scan': scan, 'vig': vig,
        'fonts': _fonts(),
        'noise': [(random.randint(0, w - 1), random.randint(0, h - 1)) for _ in range(80)],
    }
    world._crt_cache = cache
    return cache


def draw_welcome(world, duration_ms=4400):
    """Draw the welcome page onto world.screen. duration_ms from Config.TITLE_MS."""
    el = world._phase_elapsed()
    total = duration_ms
    t = el / max(1, total)
    cx, cy = world.width // 2, world.height // 2
    cache = _ensure_crt_cache(world)
    font_big0, font_sm, font_flash, font_h, font_sm2, font_tiny = cache['fonts']

    # 50 Hz phosphor flicker
    flicker = 0.92 + 0.08 * math.sin(el * 0.33)

    # --- C64 raster bars (reuse one strip, tint by blit) ---
    bar_h = 16
    strip = pygame.Surface((world.width, bar_h), pygame.SRCALPHA)
    for i in range(world.height // bar_h + 3):
        y = (i * bar_h + int(el * 0.09)) % (world.height + bar_h) - bar_h
        hue = (i * 17 + el * 0.11) % 360
        r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360.0, 0.82, 0.50 * flicker)
        strip.fill((int(r * 255), int(g * 255), int(b * 255), 62))
        world.screen.blit(strip, (0, y))

    # Rolling bright sweep (electron beam)
    sweep_y = int((el * 0.22) % (world.height + 80)) - 40
    beam = pygame.Surface((world.width, 28), pygame.SRCALPHA)
    for k in range(28):
        a = int(26 * (1.0 - abs(k - 14) / 14.0))
        pygame.draw.line(beam, (180, 255, 210, a), (0, k), (world.width, k))
    world.screen.blit(beam, (0, sweep_y))

    world.screen.blit(cache['scan'], (0, 0))
    world.screen.blit(cache['vig'], (0, 0))

    # Sparse phosphor sparkle
    ticks = pygame.time.get_ticks()
    for i, (nx, ny) in enumerate(cache['noise']):
        if ((ticks // 90) + i) % 11 == 0:
            world.screen.set_at((nx, ny), (200, 255, 210))

    fade = 1.0
    if t < 0.10:
        fade = t / 0.10
    elif t > 0.90:
        fade = max(0.0, (1.0 - t) / 0.10)
    fade *= flicker

    bounce = 1.0 + 0.07 * math.sin(el / 140.0)
    title = "Rock, Paper, Scissors"
    credit = "by Simon Barnett"
    size = max(48, int(72 * bounce))
    font_big = pygame.font.Font(None, size)

    hue = (el * 0.14) % 360
    rr, gg, bb = colorsys.hsv_to_rgb(hue / 360.0, 1.0, 1.0)
    fill = (int(rr * 255), int(gg * 255), int(bb * 255))
    rr2, gg2, bb2 = colorsys.hsv_to_rgb(((hue + 48) % 360) / 360.0, 1.0, 1.0)
    accent = (int(rr2 * 255), int(gg2 * 255), int(bb2 * 255))

    def blit_chrome(text, font, center, fill_col, alpha=255):
        # Breathing chromatic aberration
        spread = 2 + int(2 * abs(math.sin(el / 220.0)))
        shadows = [
            ((-spread, 0), (255, 36, 36)),
            ((spread, 0), (36, 48, 255)),
            ((0, 2), (40, 255, 80)),
            ((2, 2), (0, 0, 0)),
        ]
        for (ox, oy), col in shadows:
            s = font.render(text, True, col)
            if alpha < 255:
                s = s.copy()
                s.set_alpha(alpha)
            world.screen.blit(s, s.get_rect(center=(center[0] + ox, center[1] + oy)))
        # Phosphor bloom — two larger, dimmer copies
        bloom = font.render(text, True, fill_col)
        for scale, a in ((1.06, 50), (1.12, 24)):
            bw, bh = bloom.get_size()
            g = pygame.transform.smoothscale(bloom, (max(1, int(bw * scale)), max(1, int(bh * scale))))
            g.set_alpha(int(a * (alpha / 255.0)))
            world.screen.blit(g, g.get_rect(center=center))
        main = bloom
        if alpha < 255:
            main = main.copy()
            main.set_alpha(alpha)
        world.screen.blit(main, main.get_rect(center=center))

    alpha = int(255 * fade)
    title_y = int(world.height * 0.16) + int(6 * math.sin(el / 180.0))
    blit_chrome(title, font_big, (cx, title_y), fill, alpha)

    flash = 0.50 + 0.50 * abs(math.sin(el / 110.0))
    cred_col = (int(255 * flash), int(220 * flash), int(80 * flash))
    cred_s = font_sm.render(credit, True, cred_col)
    if alpha < 255:
        cred_s = cred_s.copy()
        cred_s.set_alpha(alpha)
    for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2)):
        o = font_sm.render(credit, True, (0, 0, 0))
        if alpha < 255:
            o = o.copy()
            o.set_alpha(alpha)
        world.screen.blit(o, o.get_rect(center=(cx + ox, title_y + 52 + oy)))
    world.screen.blit(cred_s, cred_s.get_rect(center=(cx, title_y + 52)))

    icons = getattr(world, 'winner_icons', {}) or {}
    keys = list(icons.keys())
    fallback = ((236, 78, 108), (247, 196, 48), (70, 178, 230))
    orbit_r = 72 + 6 * math.sin(el / 200.0)
    orbit_cy = int(world.height * 0.34)
    for i in range(3):
        ang = el / 380.0 + i * (2 * math.pi / 3)
        ix = cx + int(math.cos(ang) * orbit_r)
        iy = orbit_cy + int(math.sin(ang) * orbit_r * 0.28)
        icon = icons.get(keys[i]) if i < len(keys) else None
        glow_col = fallback[i]
        pygame.draw.circle(world.screen, glow_col + (0,), (ix, iy), 28)
        glow = pygame.Surface((56, 56), pygame.SRCALPHA)
        pygame.draw.circle(glow, glow_col + (55,), (28, 28), 26)
        world.screen.blit(glow, glow.get_rect(center=(ix, iy)))
        if icon is not None:
            sz = 38 + int(5 * math.sin(el / 150.0 + i))
            img = pygame.transform.smoothscale(icon, (sz, sz))
            if alpha < 255:
                img = img.copy()
                img.set_alpha(alpha)
            world.screen.blit(img, img.get_rect(center=(ix, iy)))
        else:
            pygame.draw.circle(world.screen, fallback[i], (ix, iy), 16)

    feed = getattr(world, '_learn', None) or {}
    learning = feed.get('phase') in ('compute', 'show', 'persist')
    if not learning and int(el / 180) % 2 == 0:
        tip = font_flash.render("GET READY!", True, accent)
        if alpha < 255:
            tip = tip.copy()
            tip.set_alpha(alpha)
        world.screen.blit(tip, tip.get_rect(center=(cx, world.height - 36)))

    draw_learn_panel(world, fade=fade, cache=cache)


def draw_learn_panel(world, fade=1.0, cache=None):
    """CRT monitor overlay of the optimiser during TITLE."""
    feed = getattr(world, '_learn', None)
    if not feed:
        return
    phase = feed.get('phase') or 'idle'
    if phase in ('idle',):
        return
    if cache is None:
        cache = _ensure_crt_cache(world)
    _, _, _, font, font_sm, font_tiny = cache['fonts']

    w, h = world.width, world.height
    pad = 18
    panel_h = min(300, int(h * 0.40))
    panel_w = min(w - 2 * pad, 940)
    px = (w - panel_w) // 2
    ticks = pygame.time.get_ticks()
    # slight vertical roll / jitter like a loose yoke
    jitter = int(1.5 * math.sin(ticks / 90.0) + 0.8 * math.sin(ticks / 37.0))
    py = h - panel_h - 14 + jitter
    alpha = int(220 * max(0.4, min(1.0, fade)))

    surf = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    surf.fill((4, 12, 10, alpha))
    # bezel
    pygame.draw.rect(surf, (30, 90, 60, 220), surf.get_rect(), 6, border_radius=12)
    pygame.draw.rect(surf, (120, 255, 180, 210), surf.get_rect().inflate(-8, -8), 1, border_radius=8)

    # phosphor glass gradient
    glass = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
    for i in range(0, panel_h, 4):
        a = int(18 * (1.0 - i / float(panel_h)))
        pygame.draw.line(glass, (140, 255, 190, a), (8, i), (panel_w - 8, i))
    surf.blit(glass, (0, 0))

    # inner scan + rolling bar
    for y in range(0, panel_h, 3):
        pygame.draw.line(surf, (0, 0, 0, 40), (8, y), (panel_w - 8, y))
    roll = int((ticks * 0.12) % max(1, panel_h - 20))
    pygame.draw.rect(surf, (80, 255, 160, 28), (8, roll, panel_w - 16, 10))

    # corner LEDs
    led_on = (ticks // 240) % 2 == 0
    pygame.draw.circle(surf, (40, 255, 120) if led_on else (20, 80, 40), (16, 16), 4)
    pygame.draw.circle(surf, (255, 200, 60) if phase == 'persist' else (80, 50, 10),
                       (panel_w - 16, 16), 4)

    gen = feed.get('gen', 0)
    games = feed.get('games', 0)
    wins = feed.get('wins') or {}
    window = int(feed.get('window') or 0)
    wr = int(wins.get('ROCK', 0) or 0)
    wp = int(wins.get('PAPER', 0) or 0)
    ws = int(wins.get('SCISSORS', 0) or 0)
    status = str(feed.get('status') or phase).upper()
    if window:
        header = '► LEARN  GEN %03d  LIFE %d  WIN %d R%d P%d S%d  [%s]' % (
            gen, games, window, wr, wp, ws, status)
    else:
        header = '► LEARNING  GEN %03d   LIFE %d   [%s]' % (gen, games, status)
    # chroma split header
    hdr_r = font.render(header, True, (255, 40, 40))
    hdr_b = font.render(header, True, (40, 80, 255))
    hdr = font.render(header, True, (130, 255, 190))
    surf.blit(hdr_r, (13, 8))
    surf.blit(hdr_b, (15, 8))
    surf.blit(hdr, (14, 8))

    fit = feed.get('fitness') or {}
    fbar = float(feed.get('fbar') or 0)
    bar_x, bar_y = 14, 36
    bar_w = panel_w - 28
    row_h = 18
    mx = max([abs(float(v)) for v in fit.values()] + [0.15, abs(fbar)])
    pulse = 0.75 + 0.25 * abs(math.sin(ticks / 160.0))
    for i, name in enumerate(('ROCK', 'PAPER', 'SCISSORS')):
        y = bar_y + i * row_h
        col = TYPE_COL[name]
        wcount = int((feed.get('wins') or {}).get(name, 0) or 0)
        lab = font_tiny.render('%s W%d' % (name[:1], wcount), True, col)
        surf.blit(lab, (bar_x, y - 1))
        track = pygame.Rect(bar_x + 28, y + 4, bar_w - 28, 8)
        pygame.draw.rect(surf, (12, 22, 18, 220), track, border_radius=3)
        val = float(fit.get(name, 0) or 0)
        span = max(mx, 1e-6)
        frac = max(0.0, min(1.0, abs(val) / span))
        ww = max(1, int(track.w * frac)) if abs(val) > 1e-6 else 0
        r = pygame.Rect(track.x, track.y, ww, track.h)
        glow = tuple(min(255, int(c * pulse)) for c in col) + (230,)
        pygame.draw.rect(surf, glow, r, border_radius=3)
        num = font_tiny.render('%+.3f' % val, True, col)
        surf.blit(num, (track.right - num.get_width(), y - 2))

    events = feed.get('events') or []
    shown = int(feed.get('shown', 0) or 0)
    cursor = max(0, shown)
    window = events[max(0, cursor - 8):cursor]
    ty = bar_y + 3 * row_h + 6

    if phase == 'compute':
        blink = 0.45 + 0.55 * abs(math.sin(ticks / 140.0))
        dots = '.' * (1 + (ticks // 280) % 3)
        msg = font_sm.render('READING MATCH HISTORY' + dots, True,
                             (int(130 * blink), int(255 * blink), int(180 * blink)))
        surf.blit(msg, (14, ty))
    elif phase == 'persist':
        blink = 0.55 + 0.45 * abs(math.sin(ticks / 90.0))
        msg = font_sm.render('WRITING STRATEGY JSON  █', True,
                             (int(255 * blink), int(220 * blink), int(80 * blink)))
        surf.blit(msg, (14, ty))
    elif not window:
        msg = font_sm.render('NO KNOB MOVES — STRATEGY STABLE', True, (150, 210, 170))
        surf.blit(msg, (14, ty))
    else:
        for j, ev in enumerate(window):
            col = TYPE_COL.get(ev.get('type'), (200, 200, 200))
            sid = ev.get('strategy') or ''
            key = ev.get('key') or ''
            old, new = ev.get('old') or '', ev.get('new') or ''
            if old and new:
                line = '%s %s  %s  %s → %s' % (ev.get('type'), sid, key, old, new)
            else:
                line = ev.get('raw') or key
            if len(line) > 76:
                line = line[:73] + '…'
            highlight = (j == len(window) - 1)
            # phosphor decay: older rows greener / dimmer
            age = len(window) - 1 - j
            dim = max(0.35, 1.0 - 0.08 * age)
            if highlight:
                draw = col
                # type-on: reveal extra chars on the newest line
                nchar = 8 + ((ticks // 30) % max(1, len(line)))
                if phase == 'show':
                    line = line[:nchar]
            else:
                draw = (
                    int(col[0] * dim * 0.55 + 40 * (1 - dim)),
                    int(col[1] * dim * 0.85 + 80 * (1 - dim)),
                    int(col[2] * dim * 0.55 + 40 * (1 - dim)),
                )
            txt = font_tiny.render(line, True, draw)
            surf.blit(txt, (14, ty + j * 16))
        if phase == 'show' and (ticks // 280) % 2 == 0:
            caret = font_tiny.render('█', True, (150, 255, 190))
            surf.blit(caret, (14, ty + len(window) * 16))

    total = max(1, len(events))
    done = min(total, shown)
    frac = done / float(total) if events else (1.0 if phase in ('persist', 'done') else 0.0)
    pygame.draw.rect(surf, (20, 36, 28), (14, panel_h - 16, panel_w - 28, 6), border_radius=3)
    glow_w = int((panel_w - 28) * frac)
    pygame.draw.rect(surf, (90, 230, 160), (14, panel_h - 16, glow_w, 6), border_radius=3)
    if glow_w > 4:
        pygame.draw.rect(surf, (200, 255, 210), (14 + glow_w - 4, panel_h - 16, 4, 6))

    world.screen.blit(surf, (px, py))
    # outer bloom
    bloom = pygame.Surface((panel_w + 20, panel_h + 20), pygame.SRCALPHA)
    pygame.draw.rect(bloom, (60, 255, 140, 22), bloom.get_rect(), 8, border_radius=16)
    world.screen.blit(bloom, (px - 10, py - 10))
