"""
Arena presentation facade.

Owns everything drawn around the match:
  background   — starfield + gradient
  audio        — countdown beeps / GO
  overlay      — 3-2-1 count-in
  forts        — draw + intro/outro scale (from fort.py)
  hud          — toolbar + winner banner (from hud.py)

particle.py should import presentation from here, not from hud/fort.
Also owns SurfaceCache, present(), and handle_events().
Do not import particle at module level.
"""

import math
import random
import time
from collections import OrderedDict
import threading

import pygame
pygame.mixer.pre_init(22050, -16, 2, 512)
pygame.init()
try:
    pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
except Exception:
    try:
        pygame.mixer.init()
    except Exception:
        pass

from arena.hud import draw_toolbar, draw_winner_banner
from arena.paths import sound_path, image_path, first_sound

from optimizer.logger import Metrics
from optimizer.engine import StrategyOptimizer
from arena.welcome import draw_welcome
from maths.phys import collide_pair, SpatialHash
from config import Config, ParticleType, MatchPhase, PREY_OF, FEAR_OF
from config import TYPE_DEFAULTS

def _last_prey_contact_was_womble(world, hunter, prey):
    """True if hunter walked into last prey on purpose with eyes open."""
    if getattr(hunter, '_evading', False):
        return False
    if getattr(hunter, '_kick_ttl', 0) > 0:
        return False
    # no LOS / too far to have known
    dx = prey.x - hunter.x
    dy = prey.y - hunter.y
    dist = math.hypot(dx, dy)
    vision = float(getattr(Config, 'VISION_FAR', 30.0)) * max(8.0, float(getattr(hunter, 'size', 20)))
    if dist > vision * 0.95:
        return False
    try:
        from arena.fort import FortLOS
        if FortLOS.occludes(hunter, prey):
            return False
    except Exception:
        pass
    # predator on our tail shoving us in
    fear_t = FEAR_OF.get(hunter.type)
    for q in getattr(world, 'particles', ()) or ():
        if q.type != fear_t:
            continue
        fx, fy = hunter.x - q.x, hunter.y - q.y
        fd = math.hypot(fx, fy)
        if fd < hunter.size * 4.5 + q.size:
            # fear is close; if also behind our motion into prey, this is a shove
            hx, hy = math.sin(hunter.angle), -math.cos(hunter.angle)
            if fd > 1.0 and (fx * hx + fy * hy) > 0:
                return False
    locked = getattr(hunter, '_locked_target', None) is prey
    chasing = getattr(hunter, '_cmd_mode', None) in ('chase', None) or locked
    closing = (math.sin(hunter.angle) * dx + (-math.cos(hunter.angle)) * dy) > 0
    return bool(chasing and closing)


from arena.fort import Fort, place_forts as layout_forts
from arena.fort import fort_occlusion, marble_shadow_clip, light_axes
import uuid


def _sim():
    import particle as _p
    return _p


from arena.fort import (
    draw_forts,
    animate_in as animate_forts_in,
    animate_out as animate_forts_out,
)

__all__ = (
    'load_countdown_sounds',
    'ensure_bg',
    'draw_countdown',
    'play_countdown_sound',
    'draw_toolbar',
    'draw_winner_banner',
    'draw_forts',
    'animate_forts_in',
    'animate_forts_out',
    'SurfaceCache',
    'present',
    'handle_events',
    'toggle_fullscreen',
    'Arena',
)


def _cfg():
    from config import Config
    return Config


def ensure_mixer():
    """Init mixer once. Re-init after pygame.init() kills prior Sounds."""
    info = pygame.mixer.get_init()
    if info:
        return info
    try:
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
    except Exception:
        try:
            pygame.mixer.init()
        except Exception:
            return None
    return pygame.mixer.get_init()


def _mixer_spec():
    info = ensure_mixer()
    if not info:
        return 22050, 2
    freq, _fmt, chans = info
    return int(freq or 22050), int(chans or 2)


def _sound_from_mono(samples, volume=1.0):
    """Build a mixer-compatible Sound from a mono signed-16 list/array."""
    import array
    freq, chans = _mixer_spec()
    if chans >= 2:
        stereo = array.array('h')
        for v in samples:
            v = int(max(-32767, min(32767, v * volume)))
            stereo.append(v)
            stereo.append(v)
        raw = stereo
    else:
        raw = array.array('h', (int(max(-32767, min(32767, v * volume))) for v in samples))
    try:
        snd = pygame.mixer.Sound(buffer=raw)
        snd.set_volume(0.7)
        return snd
    except Exception:
        return None


def synth_beep(freq_hz, duration_ms=280, volume=0.45, sample_rate=None):
    """Generate a short tone Sound matching the mixer format."""
    ensure_mixer()
    freq, _chans = _mixer_spec()
    sample_rate = int(sample_rate or freq)
    n = max(1, int(sample_rate * duration_ms / 1000.0))
    samples = []
    two_pi_f = 2.0 * math.pi * freq_hz
    attack = min(400, n // 6)
    release = min(800, n // 3)
    for i in range(n):
        t = i / float(sample_rate)
        env = 1.0
        if i < attack:
            env = i / float(attack)
        elif i > n - release:
            env = max(0.0, (n - i) / float(release))
        samples.append(int(32767.0 * volume * env * math.sin(two_pi_f * t)))
    return _sound_from_mono(samples)


def synth_click(duration_ms=70, volume=0.55):
    """Short percussive tick for conversions."""
    ensure_mixer()
    freq, _chans = _mixer_spec()
    n = max(1, int(freq * duration_ms / 1000.0))
    samples = []
    for i in range(n):
        t = i / float(freq)
        env = max(0.0, 1.0 - i / float(n))
        env *= env
        # two-partial click
        val = math.sin(2.0 * math.pi * 920 * t) * 0.7 + math.sin(2.0 * math.pi * 1840 * t) * 0.3
        samples.append(int(32767.0 * volume * env * val))
    return _sound_from_mono(samples)


def load_countdown_sounds():
    """Prefer wav files if present; otherwise synthesize arcade-style beeps."""
    names = {
        3: ('three.wav', 'countdown_3.wav', '3.wav'),
        2: ('two.wav', 'countdown_2.wav', '2.wav'),
        1: ('one.wav', 'countdown_1.wav', '1.wav'),
        0: ('go.wav', 'countdown_go.wav', 'go.wav'),
    }
    synth_freq = {3: 440, 2: 554, 1: 659, 0: 880}
    synth_dur = {3: 300, 2: 300, 1: 300, 0: 450}
    out = {}
    for key, files in names.items():
        snd = None
        for fname in files:
            try:
                snd = pygame.mixer.Sound(sound_path(fname))
                break
            except Exception:
                continue
        if snd is None:
            snd = synth_beep(synth_freq[key], synth_dur[key],
                             volume=0.55 if key else 0.65)
        if snd is not None:
            try:
                snd.set_volume(0.75)
            except Exception:
                pass
        out[key] = snd
    return out


def ensure_bg(world):
    """Pre-render gradient + starfield once onto world._bg_surface."""
    if getattr(world, '_bg_surface', None) is not None:
        return
    C = _cfg()
    world._bg_surface = pygame.Surface((world.width, world.height))
    top = getattr(C, 'BG_TOP', (12, 14, 28))
    bot = getattr(C, 'BG_BOT', (24, 32, 58))
    bands = 64
    bh = max(1, world.height // bands)
    for i in range(bands + 1):
        t = i / bands
        col = (
            int(top[0] + (bot[0] - top[0]) * t),
            int(top[1] + (bot[1] - top[1]) * t),
            int(top[2] + (bot[2] - top[2]) * t),
        )
        y0 = i * bh
        pygame.draw.rect(world._bg_surface, col, (0, y0, world.width, bh + 1))
    vig = pygame.Surface((world.width, world.height), pygame.SRCALPHA)
    for i in range(6):
        a = 18 + i * 10
        m = 8 + i * 14
        pygame.draw.rect(vig, (0, 0, 0, a), (0, 0, world.width, m))
        pygame.draw.rect(vig, (0, 0, 0, a), (0, world.height - m, world.width, m))
        pygame.draw.rect(vig, (0, 0, 0, a), (0, 0, m, world.height))
        pygame.draw.rect(vig, (0, 0, 0, a), (world.width - m, 0, m, world.height))
    world._bg_surface.blit(vig, (0, 0))
    rng = random.Random(42)
    nstars = getattr(C, 'BG_STAR_COUNT', 48)
    for _ in range(nstars):
        x = rng.randint(0, world.width - 1)
        y = rng.randint(0, world.height - 1)
        b = rng.randint(140, 220)
        pygame.draw.circle(world._bg_surface, (b, b, min(255, b + 20)), (x, y), rng.choice((1, 1, 1, 2)))


def draw_countdown(world):
    """Big 3-2-1 / GO overlay."""
    C = _cfg()
    val = getattr(world, '_countdown_value', 3)
    el = world._phase_elapsed()
    step = getattr(C, 'COUNTDOWN_STEP_MS', 900)
    local = (el % step) / step
    scale = 1.0 + 0.15 * (1.0 - local)
    alpha = int(255 * (1.0 - local * 0.35))
    label = str(val) if val > 0 else "GO"
    font = pygame.font.Font(None, int(160 * scale))
    text_s = font.render(label, True, (255, 230, 120))
    text_s.set_alpha(alpha)
    rect = text_s.get_rect(center=(world.width // 2, world.height // 2))
    pad = 30
    panel = pygame.Surface((rect.width + pad * 2, rect.height + pad * 2), pygame.SRCALPHA)
    pygame.draw.rect(panel, (10, 12, 24, 120), panel.get_rect(), border_radius=18)
    world.screen.blit(panel, panel.get_rect(center=(world.width // 2, world.height // 2)))
    world.screen.blit(text_s, rect)


def play_countdown_sound(world, value):
    """Play 3/2/1/GO once per value change when audio is on."""
    if not getattr(world, 'audio_enabled', True):
        return
    if getattr(world, '_countdown_sound_played', None) == value:
        return
    world._countdown_sound_played = value
    sounds = getattr(world, 'countdown_sounds', None) or {}
    snd = sounds.get(value)
    if snd is None:
        # rebuild if mixer was re-inited after first load
        world.countdown_sounds = load_countdown_sounds()
        snd = (world.countdown_sounds or {}).get(value)
    if snd is None:
        snd = synth_beep({3: 440, 2: 554, 1: 659, 0: 880}.get(value, 660),
                         320 if value else 450, volume=0.6)
    if snd is not None:
        try:
            ch = pygame.mixer.Channel(0)
            ch.play(snd)
        except Exception:
            try:
                snd.play()
            except Exception:
                pass

# ---------------------------------------------------------------------------
class SurfaceCache:
    """
    Thread-safe surface cache with LRU eviction (OrderedDict + RLock).

    Policy:
      - get: move key to end (most recently used)
      - put: insert/update as MRU; while over capacity, popitem(last=False) drops LRU
    RLock allows re-entrant use from the same thread.
    """
    __slots__ = ('rot', 'glow', 'dot', 'fort', 'marble', 'max_rot', 'max_misc', 'max_marble', '_lock')

    def __init__(self, max_rot=360, max_misc=256, max_marble=512):
        self.rot = OrderedDict()
        self.glow = OrderedDict()
        self.dot = OrderedDict()
        self.fort = OrderedDict()
        self.marble = OrderedDict()
        self.max_rot = int(max_rot)
        self.max_misc = int(max_misc)
        self.max_marble = int(max_marble)
        self._lock = threading.RLock()

    def _get(self, store, key):
        with self._lock:
            if key not in store:
                return None
            store.move_to_end(key)
            return store[key]

    def _put(self, store, key, value, limit):
        with self._lock:
            if key in store:
                store.move_to_end(key)
                store[key] = value
            else:
                store[key] = value
                while len(store) > limit:
                    store.popitem(last=False)  # evict least recently used

    def facing_icon(self, base_images, type_value, angle_rad, size, alpha=165, step_deg=12):
        """Cached type icon rotated to heading, scaled for the marble face."""
        if not base_images:
            return None
        size = max(6, int(size))
        alpha = int(alpha)
        deg = -math.degrees(angle_rad) % 360
        bucket = int(round(deg / step_deg) * step_deg) % 360
        key = ('face', int(type_value), bucket, size, alpha)
        img = self._get(self.rot, key)
        if img is not None:
            return img
        try:
            base = base_images[type_value]
            img = pygame.transform.rotozoom(base, float(bucket), size / max(1, base.get_width()))
            img = img.convert_alpha()
            img.fill((255, 255, 255, alpha), special_flags=pygame.BLEND_RGBA_MULT)
        except Exception:
            return None
        self._put(self.rot, key, img, self.max_rot)
        return img

    def rotated_sprite(self, base_images, type_value, angle_rad, step_deg=6):
        if not base_images:
            return None
        deg = -math.degrees(angle_rad) % 360
        bucket = int(round(deg / step_deg) * step_deg) % 360
        key = (type_value, bucket)
        img = self._get(self.rot, key)
        if img is not None:
            return img
        # Create outside lock (pygame surface work can be slow)
        img = pygame.transform.rotozoom(base_images[type_value], float(bucket), 1.0)
        self._put(self.rot, key, img, self.max_rot)
        return img

    def soft_circle(self, color, radius, alpha=55):
        radius = max(1, int(radius))
        col = (int(color[0]), int(color[1]), int(color[2]), int(alpha))
        key = (col, radius)
        s = self._get(self.glow, key)
        if s is not None:
            return s
        s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, col, (radius, radius), radius)
        self._put(self.glow, key, s, self.max_misc)
        return s

    def trail_dot(self, color, radius):
        radius = max(1, int(radius))
        col = (int(color[0]), int(color[1]), int(color[2]))
        key = (col, radius)
        s = self._get(self.dot, key)
        if s is not None:
            return s
        s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*col, 200), (radius, radius), radius)
        self._put(self.dot, key, s, self.max_misc)
        return s

    def fort_shadow(self, radius, alpha=110):
        """Soft elliptical contact shadow under a fort. Cached."""
        radius = max(6, int(radius))
        alpha = max(20, min(180, int(alpha)))
        key = ('fort_shadow', radius, alpha)
        s = self._get(self.fort, key)
        if s is not None:
            return s
        w = max(8, int(radius * 2.15))
        h = max(6, int(radius * 0.58))
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (0, 0, 0, alpha), s.get_rect())
        # Softer inner core
        inner = pygame.Rect(int(w * 0.12), int(h * 0.18), int(w * 0.76), int(h * 0.64))
        pygame.draw.ellipse(s, (0, 0, 0, min(220, alpha + 40)), inner)
        self._put(self.fort, key, s, self.max_misc)
        return s

    def fort_body(self, radius):
        r = max(8, int(round(radius / 2) * 2))
        s = self._get(self.fort, r)
        if s is not None:
            return s
        pad = 4
        s = pygame.Surface((r * 2 + pad * 2, r * 2 + pad * 2), pygame.SRCALPHA)
        c = (r + pad, r + pad)
        # outer rim
        pygame.draw.circle(s, (55, 62, 88, 255), c, r)
        pygame.draw.circle(s, (100, 115, 150, 255), c, r, 2)
        # inner well
        pygame.draw.circle(s, (40, 46, 68, 255), c, max(2, int(r * 0.55)))
        pygame.draw.circle(s, (70, 80, 110, 220), c, max(2, int(r * 0.28)))
        self._put(self.fort, r, s, self.max_misc)
        return s

    @staticmethod
    def _shade(rgb, k):
        return (
            max(0, min(255, int(rgb[0] * k))),
            max(0, min(255, int(rgb[1] * k))),
            max(0, min(255, int(rgb[2] * k))),
        )

    def get_marble(self, color, radius, light_angle_rad=0.0, icon=None, type_value=None, shaded=False):
        """
        Cached glass/stone marble in TEAM colour.
        Built once per (rgb, radius, light bucket, type, shaded) with a cheap Phong
        sphere. shaded=True kills specular so a fort-occluded marble loses shine
        without going dark.
        """
        radius = max(5, int(radius))
        step = max(8, int(getattr(_cfg(), 'MARBLE_LIGHT_STEP', 22)))
        deg = math.degrees(light_angle_rad) % 360.0
        bucket = int(round(deg / step) * step) % 360
        col = (max(0, min(255, int(color[0]))),
               max(0, min(255, int(color[1]))),
               max(0, min(255, int(color[2]))))
        key = (col, radius, bucket, int(type_value) if type_value is not None else -1, bool(shaded))
        s = self._get(self.marble, key)
        if s is not None:
            return s
        pad = 4
        size = radius * 2 + pad * 2
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        cx = cy = radius + pad
        # World-fixed key light (does not spin with roll)
        lx, ly, lz = -0.32, -0.55, 0.76
        llen = math.sqrt(lx * lx + ly * ly + lz * lz) or 1.0
        lx, ly, lz = lx / llen, ly / llen, lz / llen
        # Jewel-boost the team colour so grey rock / pale paper still read
        def boost(rgb):
            r, g, b = rgb
            mx = max(r, g, b, 1)
            sat = 1.18 if mx < 160 else 1.08
            return (
                max(0, min(255, int(r * sat + 12))),
                max(0, min(255, int(g * sat + 8))),
                max(0, min(255, int(b * sat + 8))),
            )
        cr, cg, cb = boost(col)
        r2 = radius * radius
        # Per-pixel sphere (cached; ~40² on miss only)
        pxarray = pygame.PixelArray(s)
        for iy in range(size):
            dy = iy - cy
            dy2 = dy * dy
            for ix in range(size):
                dx = ix - cx
                d2 = dx * dx + dy2
                if d2 > r2:
                    continue
                # Sphere normal
                nx = dx / float(radius)
                ny = dy / float(radius)
                nz2 = 1.0 - nx * nx - ny * ny
                if nz2 <= 0.0:
                    continue
                nz = math.sqrt(nz2)
                ndotl = nx * lx + ny * ly + nz * lz
                if ndotl < 0.0:
                    ndotl = 0.0
                # Ambient + Lambert + wrap
                amb = 0.28 if shaded else 0.22
                wrap = 0.22 if shaded else 0.18
                diff = (0.62 if shaded else 0.72) * (ndotl * (1.0 - wrap) + wrap)
                # Specular — killed when a fort blocks the key light
                spec_k = 0.12 if shaded else 0.95
                spec = (ndotl ** 14) * spec_k
                # Fresnel rim (glass edge)
                rim = (1.0 - nz) ** 2 * (0.45 if shaded else 1.0)
                tr = cr * (amb + diff) + 255.0 * spec + cr * rim * 0.35
                tg = cg * (amb + diff) + 255.0 * spec + cg * rim * 0.28
                tb = cb * (amb + diff) + 255.0 * spec + cb * rim * 0.22
                # Alpha: solid core, slight edge soften
                aa = 255 if d2 < (radius - 1) ** 2 else int(255 * max(0.0, 1.0 - (math.sqrt(d2) - (radius - 1))))
                pxarray[ix, iy] = (
                    max(0, min(255, int(tr))),
                    max(0, min(255, int(tg))),
                    max(0, min(255, int(tb))),
                    aa,
                )
        del pxarray
        # Team-colour rim ring
        pygame.draw.circle(s, (cr, cg, cb, 220), (cx, cy), radius, max(1, radius // 14))
        self._put(self.marble, key, s, self.max_marble)
        return s

    def shadow_cap_mask(self, radius, angle_rad):
        """Circle ∩ half-plane. White on the shadowed cap, 0 elsewhere. Cached."""
        radius = max(5, int(radius))
        step = 10
        deg = math.degrees(angle_rad) % 360.0
        bucket = int(round(deg / step) * step) % 360
        key = ('cap', radius, bucket)
        s = self._get(self.marble, key)
        if s is not None:
            return s
        pad = 4
        size = radius * 2 + pad * 2
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        cx = cy = radius + pad
        # Local fill: +Y half of the disc, then rotate so +Y = shadow dir
        ang = math.radians(bucket)
        sx, sy = math.sin(ang), -math.cos(ang)
        r2 = radius * radius
        px = pygame.PixelArray(s)
        for iy in range(size):
            dy = iy - cy
            for ix in range(size):
                dx = ix - cx
                if dx * dx + dy * dy > r2:
                    continue
                if dx * sx + dy * sy >= -0.5:
                    px[ix, iy] = (255, 255, 255, 255)
        del px
        self._put(self.marble, key, s, self.max_marble)
        return s

    def get_marble_decal(self, color, radius, roll_rad=0.0, icon=None, type_value=None):
        """Cached rolling overlay: vein + watermark, rotated by travel."""
        radius = max(5, int(radius))
        step = max(6, int(getattr(_cfg(), 'MARBLE_ROLL_STEP', 12)))
        deg = math.degrees(roll_rad) % 360.0
        bucket = int(round(deg / step) * step) % 360
        col = (int(color[0]), int(color[1]), int(color[2]))
        key = ('decal', col, radius, bucket, int(type_value) if type_value is not None else -1)
        s = self._get(self.marble, key)
        if s is not None:
            return s
        pad = 4
        size = radius * 2 + pad * 2
        raw = pygame.Surface((size, size), pygame.SRCALPHA)
        cx = cy = radius + pad
        # Dark vein across the stone (reads as rotation)
        vein = (
            max(0, min(255, int(col[0] * 0.45))),
            max(0, min(255, int(col[1] * 0.45))),
            max(0, min(255, int(col[2] * 0.45))),
            150,
        )
        highlight = (
            max(0, min(255, int(col[0] * 1.25 + 20))),
            max(0, min(255, int(col[1] * 1.25 + 20))),
            max(0, min(255, int(col[2] * 1.25 + 20))),
            90,
        )
        band_h = max(3, int(radius * 0.34))
        pygame.draw.ellipse(raw, vein, (cx - radius + 2, cy - band_h // 2, radius * 2 - 4, band_h))
        pygame.draw.ellipse(raw, highlight, (cx - radius + 6, cy - max(1, band_h // 4), radius * 2 - 12, max(2, band_h // 3)))
        # Two poles so spin direction is obvious
        pygame.draw.circle(raw, vein, (cx, cy - int(radius * 0.55)), max(2, radius // 7))
        pygame.draw.circle(raw, (255, 255, 255, 90), (cx, cy + int(radius * 0.55)), max(2, radius // 8))
        if icon is not None and getattr(_cfg(), 'MARBLE_ICON', True):
            try:
                scale = float(getattr(_cfg(), 'MARBLE_ICON_SCALE', 0.42))
                iw = max(6, int(radius * 2 * scale))
                ic = pygame.transform.smoothscale(icon, (iw, iw)).convert_alpha()
                a = int(getattr(_cfg(), 'MARBLE_ICON_ALPHA', 165))
                ic.fill((255, 255, 255, a), special_flags=pygame.BLEND_RGBA_MULT)
                raw.blit(ic, ic.get_rect(center=(cx, cy)))
            except Exception:
                pass
        # Rotate overlay to current roll bucket
        if bucket:
            raw = pygame.transform.rotozoom(raw, -float(bucket), 1.0)
        # Clip to circle so rotated square corners don't stick out
        s = pygame.Surface(raw.get_size(), pygame.SRCALPHA)
        s.blit(raw, (0, 0))
        mask = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        mx, my = s.get_width() // 2, s.get_height() // 2
        pygame.draw.circle(mask, (255, 255, 255, 255), (mx, my), max(2, radius - 1))
        s.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self._put(self.marble, key, s, self.max_marble)
        return s

    def marble_shadow(self, radius, alpha=70):
        """Cached elliptical contact shadow (world-down, not light-locked)."""
        radius = max(3, int(radius))
        key = ('shadow', radius, int(alpha))
        s = self._get(self.marble, key)
        if s is not None:
            return s
        w = radius * 2
        h = max(4, int(radius * 0.55))
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (0, 0, 0, int(alpha)), s.get_rect())
        self._put(self.marble, key, s, self.max_marble)
        return s

    def clear(self):
        with self._lock:
            self.rot.clear()
            self.glow.clear()
            self.dot.clear()
            self.fort.clear()
            self.marble.clear()

    def stats(self):
        """Snapshot sizes (for debugging)."""
        with self._lock:
            return {
                'rot': len(self.rot),
                'glow': len(self.glow),
                'dot': len(self.dot),
                'fort': len(self.fort),
                'marble': len(self.marble),
            }


# ---------------------------------------------------------------------------
# Spatial hash – O(1) neighbor queries for large teams
# ---------------------------------------------------------------------------


def present(world):
    """Blit background, forts, particles, overlays. Does not run physics/AI."""
    C = _cfg()
    from config import MatchPhase, ParticleType
    world._ensure_bg()
    world.screen.blit(world._bg_surface, (0, 0))
    draw_forts(world)
    phase = getattr(world, 'phase', MatchPhase.PLAYING)
    for p in world.particles:
        p.display(world.screen)
    if phase == MatchPhase.TITLE:
        world.draw_title_screen()
    if phase == MatchPhase.COUNTDOWN:
        draw_countdown(world)
    if phase in (MatchPhase.GAMEOVER, MatchPhase.FORTS_OUT):
        draw_winner_banner(world)
    if phase != MatchPhase.TITLE:
        draw_toolbar(world)
    pygame.display.flip()
    clock = getattr(world, 'clock', None)
    if clock is not None:
        cap = int(getattr(Config, 'TARGET_FPS', 0) or 0)
        if cap > 0:
            clock.tick(cap)
        else:
            clock.tick()


def handle_events(world):
    """Quit, Escape, Alt+Enter, audio toggle."""
    for e in pygame.event.get():
        if e.type == pygame.QUIT:
            world.running = False
        elif e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                world.running = False
                return
            if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and (e.mod & pygame.KMOD_ALT):
                toggle_fullscreen(world)
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if getattr(world, '_audio_btn_rect', None) and world._audio_btn_rect.collidepoint(e.pos):
                world.audio_enabled = not world.audio_enabled



def _open_display(size, fullscreen=False):
    """Open the window. vsync=1 is SDL FIFO pacing when the driver allows it."""
    flags = pygame.FULLSCREEN if fullscreen else 0
    vsync = 1 if getattr(Config, 'VSYNC', True) else 0
    try:
        return pygame.display.set_mode(size, flags, vsync=vsync)
    except TypeError:
        return pygame.display.set_mode(size, flags)
    except pygame.error:
        return pygame.display.set_mode(size, flags)


def toggle_fullscreen(world):
    world._fullscreen = not getattr(world, '_fullscreen', False)
    flags = pygame.FULLSCREEN if world._fullscreen else 0
    world.screen = _open_display((world.width, world.height), world._fullscreen)
    world._bg_surface = None

class Arena:
    def __init__(self, width=1200, height=800) -> None:
        pygame.display.set_caption('Rock Paper Scissors – Forts + Strategy')
        self.width = width
        self.height = height
        self.screen = _open_display((width, height), False)
        self.clock = pygame.time.Clock()
        self._fullscreen = False
        self.background_colour = Config.BG_TOP
        self.screen.fill(self.background_colour)
        self.particles = []
        self.spatial = SpatialHash(_cfg().GRID_CELL)
        self._bg_surface = None  # cached gradient
        self.surfaces = SurfaceCache()
        self._last_sound_ticks = 0
        self.running = True
        self.command = 0
        self.runcount = 0
        self.audio_enabled = True
        self.match_start_ticks = pygame.time.get_ticks()
        self.gameover_start_ticks = None
        ensure_mixer()
        self.collision_sound = None
        for fname in ('collide.wav', 'click.wav', 'hit.wav'):
            try:
                self.collision_sound = pygame.mixer.Sound(sound_path(fname))
                break
            except Exception:
                continue
        if self.collision_sound is None:
            self.collision_sound = synth_click()
        if self.collision_sound is not None:
            try:
                self.collision_sound.set_volume(0.7)
            except Exception:
                pass
        self.countdown_sounds = load_countdown_sounds()
        self._countdown_sound_played = None  # last value we voiced
        self.gameid = uuid.uuid4()
        self.startpos = []
        self.teamSize = 2
        self.forts = 0
        self.fort_list = []
        self._after_match_title = False
        self.teams = {t: _sim().Team(t, self) for t in ParticleType}
        self.type_counts = {t: 0 for t in ParticleType}
        self.metrics = Metrics(self)
        self.optimizer = StrategyOptimizer()
        from optimizer.perf import PerfLog
        self.perf = PerfLog()
        if getattr(Config, 'FAST_SIM', False):
            self.perf._enabled = False
        self.optimizer.w = self
        self._learn = {'phase': 'idle', 'events': [], 'shown': 0}
        self._learn_pending = True   # first TITLE reads any existing logs
        # Toolbar / winner icons
        self.toolbar_icons = {}
        self.winner_icons = {}
        self.toolbar_font = pygame.font.Font(None, 28)
        self.toolbar_font_sm = pygame.font.Font(None, 22)
        self.winner_font = pygame.font.Font(None, 48)
        self.winner_font_sm = pygame.font.Font(None, 26)
        self._audio_btn_rect = None
        try:
            for t, fname in ((ParticleType.ROCK, 'rock.png'),
                             (ParticleType.PAPER, 'paper.png'),
                             (ParticleType.SCISSORS, 'scissors.png')):
                img = pygame.image.load(image_path(fname)).convert_alpha()
                self.toolbar_icons[t] = pygame.transform.smoothscale(img, (28, 28))
                self.winner_icons[t] = pygame.transform.smoothscale(img, (64, 64))
        except Exception:
            self.toolbar_icons = {}
            self.winner_icons = {}

    @staticmethod
    def team_color(ptype):
        name = ptype.name if hasattr(ptype, 'name') else str(ptype)
        return tuple(TYPE_DEFAULTS.get(name, {}).get('color', (180, 180, 200)))[:3]

    def make_team_badge(self, ptype, size, icon=None):
        """Round badge filled with TYPE_DEFAULTS team colour + small watermark icon."""
        size = max(12, int(size))
        col = self.team_color(ptype)
        def shade(rgb, k):
            return (
                max(0, min(255, int(rgb[0] * k))),
                max(0, min(255, int(rgb[1] * k))),
                max(0, min(255, int(rgb[2] * k))),
            )
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        r = size // 2
        cx = cy = r
        pygame.draw.circle(s, shade(col, 0.40) + (255,), (cx, cy), r)
        pygame.draw.circle(s, shade(col, 0.75) + (255,), (cx - 1, cy - 1), max(2, r - 1))
        pygame.draw.circle(s, col + (255,), (cx - max(1, r // 6), cy - max(1, r // 6)), max(2, int(r * 0.72)))
        pygame.draw.circle(s, shade(col, 1.35) + (200,),
                           (cx - max(2, r // 3), cy - max(2, r // 3)), max(2, r // 3))
        pygame.draw.circle(s, (255, 255, 255, 180),
                           (cx - max(2, r // 3), cy - max(2, r // 3)), max(1, r // 8))
        pygame.draw.circle(s, shade(col, 0.55) + (230,), (cx, cy), r, max(1, r // 10))
        if icon is not None:
            try:
                iw = max(8, int(size * 0.52))
                ic = pygame.transform.smoothscale(icon, (iw, iw)).convert_alpha()
                ic.fill((255, 255, 255, 200), special_flags=pygame.BLEND_RGBA_MULT)
                s.blit(ic, ic.get_rect(center=(cx, cy)))
            except Exception:
                pass
        return s

    def place_forts(self):
        layout_forts(self)

    def record_swarm_comps(self, ptype, comps):
        """Accumulate swarm component magnitudes for metrics (per type + global)."""
        if not comps:
            return
        if not hasattr(self, '_swarm_mag_acc'):
            self._swarm_mag_acc = {}
            self._swarm_mag_n = {}
        key = ptype.name if hasattr(ptype, 'name') else str(ptype)
        acc = self._swarm_mag_acc.setdefault(key, {
            'sep_mag': 0.0, 'coh_mag': 0.0, 'ali_mag': 0.0,
            'fear_mag': 0.0, 'prey_mag': 0.0, 'avoid_mag': 0.0, 'mag': 0.0,
        })
        nmap = self._swarm_mag_n
        nmap[key] = nmap.get(key, 0) + 1
        for k in acc:
            acc[k] += float(comps.get(k, 0.0) or 0.0)
        # global
        g = self._swarm_mag_acc.setdefault('_ALL', {
            'sep_mag': 0.0, 'coh_mag': 0.0, 'ali_mag': 0.0,
            'fear_mag': 0.0, 'prey_mag': 0.0, 'avoid_mag': 0.0, 'mag': 0.0,
        })
        nmap['_ALL'] = nmap.get('_ALL', 0) + 1
        for k in g:
            g[k] += float(comps.get(k, 0.0) or 0.0)

    def swarm_mag_averages(self, ptype=None):
        """Return average component magnitudes; optional filter by type name/enum."""
        acc = getattr(self, '_swarm_mag_acc', None) or {}
        nmap = getattr(self, '_swarm_mag_n', None) or {}
        key = '_ALL'
        if ptype is not None:
            key = ptype.name if hasattr(ptype, 'name') else str(ptype)
        a = acc.get(key)
        n = max(1, nmap.get(key, 0))
        if not a:
            return {k: 0.0 for k in ('sep_mag','coh_mag','ali_mag','fear_mag','prey_mag','avoid_mag','mag')}
        return {k: round(v / n, 4) for k, v in a.items()}

    def reset_swarm_mag_acc(self):
        self._swarm_mag_acc = {}
        self._swarm_mag_n = {}

    def update_teams(self):
        self.type_counts = {t: 0 for t in ParticleType}
        for p in self.particles:
            self.type_counts[p.type] += 1
        # Last-man clocks: count==1 until that type dies or match ends
        if getattr(self, 'phase', None) == MatchPhase.PLAYING:
            starts = getattr(self, '_last_man_start_rc', None)
            if not isinstance(starts, dict):
                starts = {}
                self._last_man_start_rc = starts
            frames = getattr(self, '_last_man_frames', None)
            if not isinstance(frames, dict):
                frames = {}
                self._last_man_frames = frames
            hunters = getattr(self, '_last_man_hunter', None)
            if not isinstance(hunters, dict):
                hunters = {}
                self._last_man_hunter = hunters
            dead = getattr(self, '_last_man_dead', None)
            if not isinstance(dead, dict):
                dead = {}
                self._last_man_dead = dead
            for t in ParticleType:
                n = int(self.type_counts.get(t, 0) or 0)
                name = t.name
                if n == 1:
                    if name not in starts:
                        starts[name] = self.runcount
                        hunters[name] = FEAR_OF[t].name if FEAR_OF.get(t) else None
                    frames[name] = self.runcount - starts[name]
                elif n == 0 and name in starts and name not in dead:
                    dead[name] = frames.get(name, self.runcount - starts.get(name, self.runcount))

        # Endgame clock: first frame any type has no predators but still has prey
        if getattr(self, 'phase', None) == MatchPhase.PLAYING:
            clear_active = False
            for t in ParticleType:
                fear_t = FEAR_OF.get(t)
                prey_t = PREY_OF.get(t)
                if fear_t is None or prey_t is None:
                    continue
                if self.type_counts.get(t, 0) > 0 and self.type_counts.get(fear_t, 0) <= 0 and self.type_counts.get(prey_t, 0) > 0:
                    clear_active = True
                    if getattr(self, '_endgame_start_rc', None) is None:
                        self._endgame_start_rc = self.runcount
                        self._endgame_prey_start = self.type_counts.get(prey_t, 0)
                        self._endgame_type = t
                    break
            if clear_active:
                self._endgame_split_events = getattr(self, '_endgame_split_events', 0)
                # Count simultaneous prey under pressure (hunters within clear_reassign of each prey)
                prey_t = PREY_OF.get(getattr(self, '_endgame_type', None))
                if prey_t is not None:
                    prey_units = [q for q in self.particles if q.type == prey_t]
                    hunt_t = getattr(self, '_endgame_type', None)
                    hunters = [q for q in self.particles if q.type == hunt_t]
                    engaged = 0
                    for pr in prey_units:
                        if any(math.hypot(h.x - pr.x, h.y - pr.y) < 8 * h.size for h in hunters):
                            engaged += 1
                    self._endgame_simultaneous = max(getattr(self, '_endgame_simultaneous', 0), engaged)
                    # Voronoi imbalance snapshot
                    try:
                        st0 = VoronoiEndgame.stats()
                        self._endgame_voronoi_imbalance = max(
                            getattr(self, '_endgame_voronoi_imbalance', 0), st0.get('voronoi_imbalance', 0))
                        self._endgame_voronoi_reassign = getattr(self, '_endgame_voronoi_reassign', 0) + st0.get('voronoi_reassign', 0)
                        self._endgame_voronoi_cells = st0.get('voronoi_cells', 0)
                    except Exception:
                        pass
                # Accumulate split events from particles
                for q in self.particles:
                    if getattr(q, '_clear_split_event', 0):
                        self._endgame_split_events = getattr(self, '_endgame_split_events', 0) + 1
                        q._clear_split_event = 0
        for t in self.teams.values():
            t.update()

    def all_same_type(self):
        if not self.particles:
            return False
        first = self.particles[0].type
        return all(p.type == first for p in self.particles)

    def gameover(self):
        """True only after TITLE has played – outer loop can reset into next match."""
        if getattr(Config, 'FAST_SIM', False) and getattr(self, '_js_match_over', False):
            return True
        return getattr(self, 'phase', MatchPhase.PLAYING) == MatchPhase.READY

    def visible_type_counts(self):
        """Counts for toolbar: only fully-grown particles (scale ~1) during intro."""
        phase = getattr(self, 'phase', MatchPhase.PLAYING)
        counts = {t: 0 for t in ParticleType}
        if phase in (MatchPhase.TITLE, MatchPhase.FORTS_IN):
            return counts
        if not self.particles:
            return counts
        # During rise / fall, only count fully visible units
        if phase in (MatchPhase.PARTICLES_IN, MatchPhase.COUNTDOWN,
                     MatchPhase.PARTICLES_OUT, MatchPhase.DONE, MatchPhase.READY):
            for p in self.particles:
                if getattr(p, '_vis_scale', 1.0) >= 0.98:
                    counts[p.type] = counts.get(p.type, 0) + 1
            return counts
        # PLAYING / GAMEOVER / FORTS_OUT – full live counts
        for p in self.particles:
            counts[p.type] = counts.get(p.type, 0) + 1
        return counts

    def nearby(self, x, y, radius, distance_filter=True):
        """Neighbors within radius via spatial hash (fallback: all particles)."""
        if not hasattr(self, 'spatial') or self.spatial.count == 0:
            return self.particles
        return self.spatial.query(x, y, radius, distance_filter=distance_filter)

    def _ensure_bg(self):
        ensure_bg(self)

    def _light_axes(self):
        return light_axes(self)

    def fort_occlusion(self, x, y, pr=0.0):
        return fort_occlusion(self, x, y, pr=pr)

    def marble_shadow_clip(self, x, y, radius):
        return marble_shadow_clip(self, x, y, radius)

    def draw(self):
        perf = getattr(self, 'perf', None)
        if perf is not None:
            perf.begin('frame')
        # Phase machine (fort intro → particles → countdown → play → outro)
        if hasattr(self, 'update_match_phase'):
            perf and perf.begin('phase')
            self.update_match_phase()
            perf and perf.end('phase')
        phase = getattr(self, 'phase', MatchPhase.PLAYING)
        # Keep swimming after match ends until fall starts
        playing = phase in (MatchPhase.PLAYING, MatchPhase.GAMEOVER, MatchPhase.FORTS_OUT)
        countdown = phase == MatchPhase.COUNTDOWN

        if self.particles:
            if self.runcount % max(1, getattr(Config, 'TEAM_UPDATE_EVERY', 3)) == 0:
                perf and perf.begin('teams')
                self.update_teams()
                perf and perf.end('teams')
            else:
                for t in ParticleType:
                    team = self.teams[t]
                    team.members = [p for p in self.particles if p.type == t]
                    team.count = len(team.members)
                self.type_counts = {t: self.teams[t].count for t in ParticleType}
            perf and perf.begin('spatial')
            self.spatial.rebuild(self.particles)
            perf and perf.end('spatial')

        # Physics + AI: JS-identical tick (arena/js_tick.py).
        if playing and self.particles:
            perf and perf.begin('physics')
            from arena import js_tick
            js_tick.step(self, move=True)
            perf and perf.end('physics')
        elif countdown and self.particles:
            from arena import js_tick
            js_tick.step(self, move=False)

        # Presentation (arena.py)
        if not getattr(Config, 'FAST_SIM', False):
            if perf is not None:
                perf.begin('present')
            present(self)
            if perf is not None:
                perf.end('present')
        else:
            # Headless: never wait on the clock.
            pass
        sample_every = 20 if getattr(Config, 'FAST_SIM', False) else 5
        if hasattr(self, 'metrics') and self.runcount % sample_every == 0 and not self.gameover():
            self.metrics.sample_modes()
        self.runcount += 1
        if perf is not None:
            perf.end('frame')
            perf.frame_done()


    def draw_title_screen(self):
        """Flashy Sega / C64 style inter-match title card (welcome.py)."""
        draw_welcome(self, getattr(Config, 'TITLE_MS', 4400))

    def draw_countdown(self):
        draw_countdown(self)

    def draw_winner_banner(self):
        """Winner panel — implemented in hud.py."""
        draw_winner_banner(self)

    def draw_toolbar(self):
        """Counts / timer / audio — implemented in hud.py."""
        draw_toolbar(self)

    def collide(self, p1, p2):
        kind = collide_pair(p1, p2)
        if kind is None:
            return
        if kind == 'same':
            return
        # Opposite types: sound + RPS conversion
        if self.audio_enabled:
            now = pygame.time.get_ticks()
            last = getattr(self, '_last_sound_ticks', 0)
            if now - last >= getattr(Config, 'SOUND_COOLDOWN_MS', 80):
                snd = self.collision_sound or synth_click()
                self.collision_sound = snd
                if snd is not None:
                    try:
                        pygame.mixer.Channel(1).play(snd)
                    except Exception:
                        try:
                            snd.play()
                        except Exception:
                            pass
                    self._last_sound_ticks = now
        # RPS conversion
        if (p1.type == ParticleType.ROCK and p2.type == ParticleType.SCISSORS) or \
           (p1.type == ParticleType.PAPER and p2.type == ParticleType.ROCK) or \
           (p1.type == ParticleType.SCISSORS and p2.type == ParticleType.PAPER):
            win, lose = p1, p2
        else:
            win, lose = p2, p1
        lose_was_type = lose.type
        prey_left = sum(1 for q in self.particles if q.type == lose_was_type)
        fear_alive = self.type_counts.get(FEAR_OF.get(win.type), 0) > 0
        # Convert is always legal. Last prey + living predators = automatic
        # lose for the hunter — they must learn not to take that contact.
        lose.type = win.type
        lose.enforce_speed(source='convert')
        win.wins += 1
        lose.losses += 1
        win.turn = lose.turn = 0
        lose.assign_role()
        lose._vision_dirty = True
        if hasattr(self, 'metrics'):
            self.metrics.log_conversion(win, lose, loser_type_before=lose_was_type)
        win.get_team().register_conversion()
        win.get_team().set_alert(lose, Config.ALERT_TTL_KILL)
        if prey_left <= 1 and fear_alive:
            predator = FEAR_OF.get(win.type)
            self._last_prey_foul = True
            self._last_prey_fouler = win.type
            if hasattr(self, 'metrics'):
                try:
                    self.metrics.wipe_risk_events = getattr(self.metrics, 'wipe_risk_events', [])
                    self.metrics.wipe_risk_events.append({
                        'blocked': 0, 'womble': 1, 'auto_lose': 1,
                        'winner_type': win.type.name,
                        'awarded_to': predator.name if predator else '',
                        'fear_left': self.type_counts.get(predator, 0) if predator else 0,
                        'runcount': self.runcount,
                    })
                except Exception:
                    pass
            # Do not stop the match. Play until one type remains.
        # Replay seed when match is decided (metrics via GAMEOVER phase)
        if self.all_same_type() and self.startpos:
            try:
                forts_data = [(round(f.x, 1), round(f.y, 1), round(f.radius, 1)) for f in self.fort_list]
                with open('gameover.txt', 'a', encoding='utf-8') as f:
                    f.write(f'{self.gameid}|{sum(p.wins for p in self.particles)}|{self.teamSize}|{forts_data}|{self.startpos}\n')
            except Exception:
                pass

    def events(self):
        handle_events(self)

    def toggle_fullscreen(self):
        toggle_fullscreen(self)

    def reset(self, gameid=None):
        try:
            import strategies.playbook as _pb
            _pb.set_match_context(getattr(self, 'teamSize', None))
        except Exception:
            pass
        # Flush last match BEFORE wipe. Title-phase flush used to run after
        # reset_match() which zeroed conversions — brief stats stayed empty
        # and the first TITLE frame paid for a 2–5s optimise+persist.
        pending = getattr(self, '_pending_gameover_type', None)
        if pending is not None and hasattr(self, 'metrics'):
            try:
                self.metrics.log_gameover(pending)
            except Exception:
                pass
            self._pending_gameover_type = None
            # Heavy learn runs on the TITLE screen so the player can watch it.
            self._learn_pending = True
        self.particles = []
        self.startpos = []
        self.fort_list = []
        self.match_end_ticks = None
        self.frozen_match_ms = 0
        self.gameover_start_ticks = None
        self._particles_placed = False
        self._countdown_value = 3
        self.runcount = 0
        self.command = 0
        self._ai_cursor = 0
        self._js_hold = {
            'ROCK': {'card': None, 'frames': 0},
            'PAPER': {'card': None, 'frames': 0},
            'SCISSORS': {'card': None, 'frames': 0},
        }
        self._js_voronoi = {'key': '', 'map': {}}
        self._js_tick_i = 0
        self._js_sized = False
        self._js_alive_one = False
        self._js_winner_seen = False
        self._js_match_over = False
        self._layout_rng = None
        pinned = getattr(self, '_pin_match_seed', None)
        self.match_seed = int(pinned) if pinned else random.randint(1, 2 ** 31 - 1)
        self._last_man_start_rc = {}
        self._last_man_frames = {}
        self._last_man_hunter = {}
        self._last_man_dead = {}
        self._endgame_start_rc = None
        self._endgame_type = None
        self._after_match_title = False  # obsolete; TITLE always starts a match
        if hasattr(self, 'metrics'):
            self.metrics.reset_match()
        saved = self.get_values(gameid) if gameid is not None else None
        if saved is None:
            self.gameid = uuid.uuid4()
            # Forts first (scale 0 – animated in); particles after intro
            # Welcome title, then forts using teamSize/forts set by caller before reset()
            self.fort_list = []
            self.phase = MatchPhase.TITLE
            self.phase_start_ticks = pygame.time.get_ticks()
            self.match_start_ticks = None
        else:
            self.gameid = gameid
            self.teamSize = saved.get('teamSize', self.teamSize)
            for (x, y, r) in saved.get('forts', []):
                f = Fort(x, y, r)
                f.scale = 0.0
                self.fort_list.append(f)
            self._replay_startpos = saved.get('startpos', [])
            self.phase = MatchPhase.TITLE
            self.phase_start_ticks = pygame.time.get_ticks()
            self.match_start_ticks = None
        self.update_teams()

    def _place_particles_now(self):
        """Spawn particles after forts are up."""
        if self._particles_placed:
            return
        self.particles = []
        self.startpos = []
        replay = getattr(self, '_replay_startpos', None)
        if replay:
            for entry in replay:
                if isinstance(entry, str):
                    parts = entry.replace('(', '').replace(')', '').split(',')
                    tval, x, y, ang = int(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                else:
                    tval, x, y, ang = entry
                p = _sim().Particle(self, ParticleType(tval))
                p.x, p.y, p.angle = x, y, ang
                p.type = p.starttype
                d = TYPE_DEFAULTS[p.type.name]
                p.size = d.get("size", 20)
                sr, ar, br = d["strength_range"], d["agility_range"], d["bravery_range"]
                p.strength = random.uniform(sr[0], sr[1])
                p.agility = random.uniform(ar[0], ar[1])
                p.bravery = random.uniform(br[0], br[1])
                p.speed = p.maxspeed()
                p.assign_role()
                self.particles.append(p)
                self.startpos.append((tval, x, y, ang))
            self._replay_startpos = None
        else:
            from arena.layout import world_metrics, spawn_particles, make_rand, mulberry32
            from config import TYPE_DEFAULTS as _TD
            m = world_metrics(self.width, self.height)
            rng = getattr(self, '_layout_rng', None)
            if rng is None:
                seed = int(getattr(self, 'match_seed', 0) or 0) or random.randint(1, 2 ** 31 - 1)
                self.match_seed = seed
                rng = mulberry32(seed)
                self._layout_rng = rng
            forts = [{'x': f.x, 'y': f.y, 'r': f.radius} for f in self.fort_list]
            laid = spawn_particles(
                m['W'], m['H'], self.teamSize, forts, m['pad'], m['body'], make_rand(rng))
            for row in laid:
                p = _sim().Particle(self, ParticleType[row['type']])
                p.id = int(row['id'])
                p.x = float(row['x'])
                p.y = float(row['y'])
                p.angle = float(row['angle'])
                p.type = p.starttype
                p.size = m['body']
                d = _TD[p.type.name]
                sr, ar, br = d['strength_range'], d['agility_range'], d['bravery_range']
                p.strength = random.uniform(sr[0], sr[1])
                p.agility = random.uniform(ar[0], ar[1])
                p.bravery = random.uniform(br[0], br[1])
                from arena.js_tick import DEFAULT_MOTION, CRUISE_MULT
                mot = float((DEFAULT_MOTION.get(p.type.name) or {}).get('speed') or 1.3)
                p.speed = mot * CRUISE_MULT * 0.1 * m['worldK']
                p.assign_role()
                self.particles.append(p)
                self.startpos.append((p.type.value, p.x, p.y, p.angle))
        rise = getattr(Config, 'PARTICLE_RISE_PX', 220)
        base = getattr(Config, 'PARTICLE_STAGGER_MS', 40)
        for i, p in enumerate(self.particles):
            p._intro_delay_ms = (i % 3) * 70 + (i // 3) * base
            p._vis_y_offset = float(rise)
            p._vis_scale = 0.05
        self._particles_placed = True
        self.update_teams()

    def _play_countdown_sound(self, value):
        play_countdown_sound(self, value)

    def _set_phase(self, phase):
        self.phase = phase
        self.phase_start_ticks = pygame.time.get_ticks()
        if phase == MatchPhase.COUNTDOWN:
            self._countdown_sound_played = None  # allow 3 to play fresh

    def _phase_elapsed(self):
        return max(0, pygame.time.get_ticks() - (self.phase_start_ticks or pygame.time.get_ticks()))

    def _start_learn_thread(self):
        """Deprecated — learning is visible on TITLE. Kept as no-op."""
        return

    def _end_match_now(self, winner_type):
        """Stop the clock and hand the match to winner_type (enum or None)."""
        now = pygame.time.get_ticks()
        self.gameover_start_ticks = now
        if self.match_start_ticks:
            self.frozen_match_ms = now - self.match_start_ticks
        self.match_end_ticks = now
        self._pending_gameover_type = winner_type
        if getattr(Config, 'FAST_SIM', False):
            self._set_phase(MatchPhase.READY)
        else:
            self._set_phase(MatchPhase.GAMEOVER)

    def _begin_title_learn(self):
        opt = getattr(self, 'optimizer', None)
        self._learn = {
            'phase': 'compute',
            'events': [],
            'shown': 0,
            'gen': int(getattr(opt, 'GENERATION', 0) or 0) if opt else 0,
            'games': int(getattr(opt, 'games_seen', 0) or 0) if opt else 0,
            'fitness': {},
            'share': {},
            'status': 'READING',
            'started_ticks': pygame.time.get_ticks(),
            'last_reveal': pygame.time.get_ticks(),
        }
        self._learn_pending = False

    def _run_title_learn_compute(self):
        opt = getattr(self, 'optimizer', None)
        feed = self._learn
        if opt is None:
            feed['phase'] = 'done'
            feed['status'] = 'IDLE'
            return
        try:
            snap = opt.start_visible_pass()
            feed.update({
                'gen': snap.get('gen', feed.get('gen', 0)),
                'games': snap.get('games', 0),
                'window': snap.get('window', 0),
                'wins': snap.get('wins') or {},
                'simplex': snap.get('simplex') or {},
                'fitness': snap.get('fitness') or {},
                'fbar': snap.get('fbar', 0),
                'share': snap.get('share') or {},
                'lr': snap.get('lr') or {},
                'events': (snap.get('events') or [])[:60],
                'shown': 0,
                'phase': 'show',
                'status': snap.get('status') or 'TUNING',
                'last_reveal': pygame.time.get_ticks(),
            })
        except Exception:
            feed['phase'] = 'done'
            feed['status'] = 'ERROR'

    def _pump_title_learn(self):
        if getattr(self, '_learn_pending', False):
            self._begin_title_learn()
        feed = getattr(self, '_learn', None)
        if not feed:
            return
        phase = feed.get('phase')
        now = pygame.time.get_ticks()
        if phase == 'compute':
            # Hold the READING card on screen for a beat, then compute.
            if now - int(feed.get('started_ticks', now)) >= 280:
                self._run_title_learn_compute()
        elif phase == 'show':
            step = int(getattr(Config, 'LEARN_REVEAL_MS', 70))
            events = feed.get('events') or []
            if not events:
                feed['phase'] = 'persist'
                feed['status'] = 'WRITE'
                return
            if now - int(feed.get('last_reveal', now)) >= step:
                feed['shown'] = min(len(events), int(feed.get('shown', 0)) + 1)
                feed['last_reveal'] = now
                if feed['shown'] >= len(events):
                    feed['phase'] = 'persist'
                    feed['status'] = 'WRITE'
        elif phase == 'persist':
            opt = getattr(self, 'optimizer', None)
            if opt is not None:
                try:
                    opt._persist_type_config(force=False)
                except Exception:
                    pass
            feed['phase'] = 'done'
            feed['status'] = 'READY'

    def _fast_sim_phase(self):
        """No intros: learn once on TITLE, then play until READY."""
        if self.phase == MatchPhase.TITLE:
            self._learn_pending = False
            self._learn = {'phase': 'done', 'events': [], 'shown': 0, 'status': 'FAST'}
            if not getattr(self, 'teamSize', None) or int(self.teamSize) < 1:
                self.teamSize = random.randint(5, 20)
            if not hasattr(self, 'forts') or self.forts is None:
                self.forts = random.randint(4, 10)
            self.teamSize = max(1, int(self.teamSize))
            self.forts = max(0, int(self.forts))
            self.place_forts()
            for f in self.fort_list:
                f.scale = 1.0
            self._place_particles_now()
            for p in self.particles:
                p._vis_y_offset = 0.0
                p._vis_scale = 1.0
            self.match_start_ticks = pygame.time.get_ticks()
            self.match_end_ticks = None
            self.frozen_match_ms = 0
            self._set_phase(MatchPhase.PLAYING)
        elif self.phase == MatchPhase.PLAYING:
            if getattr(self, '_js_match_over', False):
                now = pygame.time.get_ticks()
                self.gameover_start_ticks = now
                self.frozen_match_ms = (now - self.match_start_ticks) if self.match_start_ticks else 0
                self.match_end_ticks = now
                self._pending_gameover_type = self.particles[0].type if self.particles else None
                self._set_phase(MatchPhase.READY)

    def update_match_phase(self):
        """Advance intro/outro state machine."""
        if getattr(Config, 'FAST_SIM', False):
            self._fast_sim_phase()
            return
        el = self._phase_elapsed()
        if self.phase == MatchPhase.TITLE:
            self._pump_title_learn()
            learn = getattr(self, '_learn', {}) or {}
            learn_done = learn.get('phase') in ('done', 'idle')
            min_ms = getattr(Config, 'TITLE_MS', 5600)
            cap_ms = getattr(Config, 'LEARN_MAX_MS', 9000)
            if (el >= min_ms and learn_done) or el >= cap_ms:
                # Always start the match after welcome – no blank / READY branch
                self.particles = []
                self._particles_placed = False
                self.startpos = []
                # Honour caller randoms; if missing, roll here
                if not getattr(self, 'teamSize', None) or int(self.teamSize) < 1:
                    self.teamSize = random.randint(5, 20)
                if not hasattr(self, 'forts') or self.forts is None:
                    self.forts = random.randint(4, 10)
                self.teamSize = max(1, int(self.teamSize))
                self.forts = max(0, int(self.forts))
                self.place_forts()
                for f in self.fort_list:
                    f.scale = 0.0
                self._set_phase(MatchPhase.FORTS_IN)
        elif self.phase == MatchPhase.FORTS_IN:
            if animate_forts_in(self, el) or not self.fort_list:
                for f in self.fort_list:
                    f.scale = 1.0
                self._set_phase(MatchPhase.PARTICLES_IN)
                self._place_particles_now()
        elif self.phase == MatchPhase.PARTICLES_IN:
            self._animate_particles_in(el)
            intro = getattr(Config, 'PARTICLE_INTRO_MS', 1100)
            max_delay = max((getattr(p, '_intro_delay_ms', 0) for p in self.particles), default=0)
            rise_done_at = intro + max_delay
            hold = getattr(Config, 'PARTICLE_HOLD_MS', 1000)
            if el >= rise_done_at:
                # Snap everyone to final pose while we hold
                for p in self.particles:
                    p._vis_y_offset = 0.0
                    p._vis_scale = 1.0
            if el >= rise_done_at + hold:
                self._countdown_value = 3
                self._countdown_sound_played = None
                self._set_phase(MatchPhase.COUNTDOWN)
        elif self.phase == MatchPhase.COUNTDOWN:
            step = getattr(Config, 'COUNTDOWN_STEP_MS', 900)
            # 3,2,1 over three steps; then GO at end of third step
            if el >= step * 3:
                self._play_countdown_sound(0)  # GO
                self.match_start_ticks = pygame.time.get_ticks()
                self.match_end_ticks = None
                self.frozen_match_ms = 0
                self._set_phase(MatchPhase.PLAYING)
            else:
                self._countdown_value = max(1, 3 - int(el // step))
                self._play_countdown_sound(self._countdown_value)
        elif self.phase == MatchPhase.PLAYING:
            if self.all_same_type():
                now = pygame.time.get_ticks()
                self.gameover_start_ticks = now
                if self.match_start_ticks is not None:
                    self.frozen_match_ms = now - self.match_start_ticks
                else:
                    self.frozen_match_ms = 0
                self.match_end_ticks = now
                # metrics once (particles keep swimming with trails through dialog)
                self._pending_gameover_type = self.particles[0].type if self.particles else None
                self._set_phase(MatchPhase.GAMEOVER)
        elif self.phase == MatchPhase.GAMEOVER:
            # Particles keep normal movement (playing flag includes GAMEOVER)
            if el >= getattr(Config, 'GAMEOVER_HOLD_MS', 1200):
                self._set_phase(MatchPhase.FORTS_OUT)
        elif self.phase == MatchPhase.FORTS_OUT:
            # Forts dissolve; particles still swim. No particle drop.
            if animate_forts_out(self, el):
                # Dialog ends with forts; reset timer and hand off to outer loop
                self.frozen_match_ms = 0
                self.match_start_ticks = None
                self.match_end_ticks = None
                self.gameover_start_ticks = None
                for p in self.particles:
                    if getattr(p, '_trail', None) is not None:
                        p._trail.clear()
                self._set_phase(MatchPhase.READY)

    def _animate_particles_in(self, el_ms):
        """Rise from below + grow; order is interleaved R-P-S so types alternate."""
        rise = getattr(Config, 'PARTICLE_RISE_PX', 220)
        intro = getattr(Config, 'PARTICLE_INTRO_MS', 1100)
        # Per-particle delay stored at place time (random-ish stagger)
        for p in self.particles:
            delay = getattr(p, '_intro_delay_ms', 0)
            local = el_ms - delay
            if local <= 0:
                p._vis_y_offset = float(rise)
                p._vis_scale = 0.05
                continue
            t = min(1.0, local / max(1.0, float(intro)))
            e = 1.0 - (1.0 - t) ** 3
            p._vis_y_offset = rise * (1.0 - e)
            p._vis_scale = 0.05 + 0.95 * e

    def _animate_particles_out(self, el_ms):
        """Fall downward off the viewpoint (staggered). Full outro per particle."""
        fall = getattr(Config, 'PARTICLE_FALL_PX', 280)
        outro = getattr(Config, 'PARTICLE_OUTRO_MS', 1000)
        stagger = getattr(Config, 'PARTICLE_STAGGER_MS', 40)
        for i, p in enumerate(self.particles):
            local = el_ms - i * stagger
            if local <= 0:
                p._vis_y_offset = 0.0
                p._vis_scale = 1.0
                continue
            t = min(1.0, local / max(1.0, float(outro)))
            # ease in cubic – accelerate downward
            e = t * t * t
            p._vis_y_offset = fall * e
            p._vis_scale = max(0.0, 1.0 - e)

    def newGame(self):
        """Spawn teamSize of each type interleaved: R, P, S, R, P, S, …"""
        n = max(1, int(getattr(self, 'teamSize', 2) or 2))
        self.teamSize = n
        for i in range(n):
            self.particles.append(_sim().Particle(self, ParticleType.ROCK))
            self.particles.append(_sim().Particle(self, ParticleType.PAPER))
            self.particles.append(_sim().Particle(self, ParticleType.SCISSORS))

    def get_values(self, gameid):
        """Return dict with teamSize, forts, startpos for a given gameid, or None."""
        try:
            with open('gameover.txt') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # New format: gameid|wins|teamSize|forts|startpos
                    if '|' in line:
                        parts = line.split('|', 4)
                        if str(parts[0]) == str(gameid):
                            import ast
                            return {
                                'wins': int(parts[1]),
                                'teamSize': int(parts[2]),
                                'forts': ast.literal_eval(parts[3]),
                                'startpos': ast.literal_eval(parts[4]),
                            }
                    # Legacy format fallback
                    elif line.split(', ')[0] == str(gameid):
                        try:
                            start = line.split('[(')[1].split(')]')[0].split('), (')
                            return {'startpos': start, 'forts': [], 'teamSize': self.teamSize}
                        except Exception:
                            pass
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Particle
# ---------------------------------------------------------------------------

world = Arena  # backward alias
