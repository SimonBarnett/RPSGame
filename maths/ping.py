"""
Sector vision / ping identification for Rock-Paper-Scissors particles.

Classifies visible units into 360° sectors as FRIEND / FEAR / PREY.
particle.py imports this module — do not import particle at module level.
"""

import math
from enum import Enum


def _P():
    import particle as _p
    return _p


def _cfg():
    from config import Config
    return Config


def _TR():
    from config import TurnRelative
    return TurnRelative


def _centres():
    from config import SECTOR_CENTRES
    return SECTOR_CENTRES


def _all_dirs():
    from config import ALL_VISION_DIRS
    return ALL_VISION_DIRS


def _los():
    from arena.fort import FortLOS
    return FortLOS


class Pinged:
    __slots__ = ('distance', 'relative', 'factor', '_risk', '_reward')
    def __init__(self, relative, distance, factor):
        self.distance = distance
        self.relative = relative
        self.factor = factor
        self._risk = 0.0
        self._reward = 0.0
    @property
    def risk(self): return self._risk
    @risk.setter
    def risk(self, v): self._risk = v
    @property
    def reward(self): return self._reward
    @reward.setter
    def reward(self, v): self._reward = v


class Direction:
    __slots__ = ('direction', '_drag', '_risk', '_reward', '_confidence',
                 'ping', 'cohesion', 'pack_bonus', 'flank_bonus')
    def __init__(self, direction):
        self.direction = direction
        self._drag = self._risk = self._reward = self._confidence = 0.0
        self.ping = []
        self.cohesion = self.pack_bonus = self.flank_bonus = 0.0
    @property
    def risk(self): return self._risk
    @risk.setter
    def risk(self, v): self._risk = v
    @property
    def reward(self): return self._reward
    @reward.setter
    def reward(self, v): self._reward = v
    @property
    def confidence(self): return self._confidence * self._drag
    @confidence.setter
    def confidence(self, v): self._confidence = v
    @property
    def drag(self): return self._drag
    @drag.setter
    def drag(self, v): self._drag = v
    def CostBenefit(self):
        e = self._reward + self.cohesion + self.pack_bonus + self.flank_bonus
        return self._drag * (e - self._risk) if e > self._risk else 0.0


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ParticleRelative(Enum):
    FRIEND = 0
    FEAR = 1
    PREY = 2


class SectorLogic:
    """Pure helpers for full-circle sector assignment and fear/prey orientation."""

    @staticmethod
    def wrap_angle(a):
        return (a + math.pi) % (2 * math.pi) - math.pi

    @staticmethod
    def bearing(from_x, from_y, from_angle, to_x, to_y):
        """Relative bearing of point from a facing pose. Range (-π, π]."""
        return SectorLogic.wrap_angle(
            math.atan2(to_x - from_x, -(to_y - from_y)) - from_angle
        )

    @staticmethod
    def sector_for_bearing(rel):
        """Map a relative bearing to a TurnRelative sector (full 360°)."""
        if abs(rel) >= math.radians(165):
            return _TR().BACK
        for d in _all_dirs():
            if d == _TR().BACK:
                continue
            lo, hi = _cfg().SECTOR_BOUNDS[d]
            if lo <= rel <= hi:
                return d
        best, best_ad = _TR().FRONT, 99.0
        for d in _all_dirs():
            c = _centres()[d]
            ad = abs(SectorLogic.wrap_angle(rel - c))
            if ad < best_ad:
                best, best_ad = d, ad
        return best

    @staticmethod
    def sector_centre(sector):
        if isinstance(sector, _TR()):
            return _centres()[sector]
        return _centres().get(_TR()(sector), 0.0)

    @staticmethod
    def world_heading(face_angle, sector):
        return (face_angle + SectorLogic.sector_centre(sector)) % (2 * math.pi)

    @staticmethod
    def distance_factor(dist, size, near=None, far=None):
        near = (near if near is not None else _cfg().VISION_NEAR) * size
        far = (far if far is not None else _cfg().VISION_FAR) * size
        if dist <= near:
            return 1.0
        if dist >= far:
            return 0.0
        return 1.0 - (dist - near) / (far - near)

    @staticmethod
    def scan(particle, others=None):
        """
        Classify particles in vision into 360° sectors.
        `others` may be a pre-filtered spatial-hash neighborhood.
        """
        by_sector = {d.value: [] for d in _all_dirs()}
        nearest = {'FEAR': None, 'PREY': None, 'FRIEND': None}
        totals = {'FEAR': 0, 'PREY': 0, 'FRIEND': 0}
        far = _cfg().VISION_FAR * particle.size
        if others is None:
            others = particle.w.particles
        for other in others:
            if other is particle:
                continue
            dist = math.hypot(other.x - particle.x, other.y - particle.y)
            if dist > far:
                continue
            # Cannot see through forts
            if _los().occludes(particle.w, particle, other):
                continue
            rel = SectorLogic.bearing(
                particle.x, particle.y, particle.angle, other.x, other.y
            )
            sector = SectorLogic.sector_for_bearing(rel)
            kind = particle.Identify(other)
            key = kind.name
            by_sector[sector.value].append([dist, kind, other])
            totals[key] = totals.get(key, 0) + 1
            prev = nearest.get(key)
            if prev is None or dist < prev[0]:
                nearest[key] = (dist, other)
        for k in by_sector:
            by_sector[k].sort(key=lambda x: x[0])
        return by_sector, nearest, totals

    @staticmethod
    def escape_heading(particle, fear_other, lookahead=12.0):
        if fear_other is None:
            return None
        fx = fear_other.x + math.sin(fear_other.angle) * fear_other.speed * lookahead
        fy = fear_other.y - math.cos(fear_other.angle) * fear_other.speed * lookahead
        to_fear = math.atan2(fx - particle.x, -(fy - particle.y))
        return (to_fear + math.pi) % (2 * math.pi)

    @staticmethod
    def chase_heading(particle, prey_other, lookahead=12.0):
        if prey_other is None:
            return None
        px = prey_other.x + math.sin(prey_other.angle) * prey_other.speed * lookahead
        py = prey_other.y - math.cos(prey_other.angle) * prey_other.speed * lookahead
        h = math.atan2(px - particle.x, -(py - particle.y)) % (2 * math.pi)
        # When predators exist, avoid herding prey into corners
        try:
            st = particle.strat() if hasattr(particle, 'strat') else {}
            if particle.fearCount() > 0 and float(st.get('no_corner_herd', 1.0)) > 0.05:
                h = SectorLogic.anti_corner_herd_heading(particle, prey_other, h, st)
        except Exception:
            pass
        return h

    @staticmethod
    def corner_score(x, y, w, h, margin):
        """0 = open field, 1 = deep in a corner (near two edges)."""
        dl, dr = x, w - x
        dt, db = y, h - y
        edge_x = max(0.0, 1.0 - min(dl, dr) / margin)
        edge_y = max(0.0, 1.0 - min(dt, db) / margin)
        # Corner = both edges close
        return min(1.0, edge_x * edge_y * 1.4 + 0.35 * max(edge_x, edge_y) * min(edge_x, edge_y))

    @staticmethod
    def anti_corner_herd_heading(particle, prey, chase_h, st):
        """
        If pursuit would drive prey deeper into a corner while predators exist,
        bias heading toward open field / cut off less hard.
        """
        w = float(getattr(particle.w, 'width', 800))
        h = float(getattr(particle.w, 'height', 600))
        margin = float(st.get('corner_zone_margin', 120.0))
        weight = float(st.get('no_corner_herd', 1.0))
        open_bias = float(st.get('open_field_bias', 0.7))
        cs = SectorLogic.corner_score(prey.x, prey.y, w, h, margin)
        if cs < 0.25:
            return chase_h
        # Would chase push prey further into corner?
        look = 18.0
        nx = prey.x + math.sin(chase_h) * particle.speed * look * 0.15
        ny = prey.y + (-math.cos(chase_h)) * particle.speed * look * 0.15
        # Approximate prey displacement if pressed along hunter approach
        to_prey_x = prey.x - particle.x
        to_prey_y = prey.y - particle.y
        td = math.hypot(to_prey_x, to_prey_y) + 1e-6
        press_x = prey.x + (to_prey_x / td) * 40
        press_y = prey.y + (to_prey_y / td) * 40
        cs2 = SectorLogic.corner_score(press_x, press_y, w, h, margin)
        if cs2 <= cs * 1.05 and cs < 0.55:
            return chase_h
        # Open-field target: map centre biased
        cx, cy = w * 0.5, h * 0.5
        open_h = math.atan2(cx - particle.x, -(cy - particle.y)) % (2 * math.pi)
        # Blend: stronger when deeper in corner
        blend = min(1.0, weight * open_bias * cs)
        # Also leave an escape corridor: aim slightly past prey toward open, not pin
        past_x = prey.x + (cx - prey.x) * 0.35
        past_y = prey.y + (cy - prey.y) * 0.35
        past_h = math.atan2(past_x - particle.x, -(past_y - particle.y)) % (2 * math.pi)
        # Mix chase → past → open
        def blend_h(a, b, t):
            ax, ay = math.sin(a), -math.cos(a)
            bx, by = math.sin(b), -math.cos(b)
            x, y = ax * (1 - t) + bx * t, ay * (1 - t) + by * t
            return math.atan2(x, -y) % (2 * math.pi)
        h1 = blend_h(chase_h, past_h, blend * 0.7)
        h2 = blend_h(h1, open_h, blend * 0.35)
        particle._corner_herd_avoid = getattr(particle, '_corner_herd_avoid', 0) + 1
        return h2

    @staticmethod
    def hide_among_prey_heading(particle, st):
        """Steer into a cluster of OUR PREY so the predator must enter its own fear."""
        st = st or {}
        w = float(st.get('hide_among_prey_weight', 0.0) or 0.0)
        if w < 0.05:
            return None, 0.0
        if particle.fearCount() <= 0 or particle.preyCount() <= 0:
            return None, 0.0
        prey_type = __import__("config", fromlist=["PREY_OF"]).PREY_OF.get(particle.type)
        if prey_type is None:
            return None, 0.0
        team = particle.w.teams.get(prey_type)
        members = getattr(team, 'members', None) if team is not None else None
        if not members:
            return None, 0.0
        size = float(getattr(particle, 'size', 20) or 20)
        radius = float(st.get('hide_among_prey_radius', 16.0)) * size
        min_n = max(2, int(st.get('hide_among_prey_min', 3)))
        nearby = []
        px, py = particle.x, particle.y
        for q in members:
            d = math.hypot(q.x - px, q.y - py)
            if d < radius:
                nearby.append((d, q))
        if len(nearby) < min_n:
            # Fall back: k nearest prey as a pocket to run toward
            allp = sorted(((math.hypot(q.x - px, q.y - py), q) for q in members), key=lambda t: t[0])
            nearby = allp[:min_n]
            if len(nearby) < min_n:
                return None, 0.0
        cx = sum(q.x for _, q in nearby) / len(nearby)
        cy = sum(q.y for _, q in nearby) / len(nearby)
        heading = math.atan2(cx - px, -(cy - py)) % (2 * math.pi)
        dens = min(1.0, len(nearby) / float(min_n + 2))
        score = w * dens
        return heading, score

    @staticmethod
    def orient(particle, nearest, st, fear_close=False):
        """
        Desired heading from FEAR/PREY contacts.
        HARD RULE: never drive toward a FEAR that is in front or nearer than prey.
        Priority: evade threatening FEAR > chase safe PREY > mild lean away from distant FEAR > idle.
        """
        fear = nearest.get('FEAR')
        prey = nearest.get('PREY')
        st = st or {}
        size = getattr(particle, 'size', 20)

        must_evade = fear_close
        if fear is not None:
            fd, fobj = fear
            # FEAR in front hemisphere (±90°) → always evade
            fb = SectorLogic.bearing(particle.x, particle.y, particle.angle, fobj.x, fobj.y)
            if abs(fb) < math.radians(90):
                must_evade = True
            # FEAR closer than PREY → evade
            if prey is None or fd <= prey[0] * 1.15:
                must_evade = True
            # FEAR within medium range → evade
            if fd < 18 * size:
                must_evade = True

        if must_evade and fear is not None:
            # Prefer fort cover if available (hide behind fort from predator)
            cover_w = float(st.get('fort_cover_weight', 1.0))
            if cover_w > 0.05:
                ch, cs = _los().cover_heading(particle, fear[1], st)
                if ch is not None and cs * cover_w > 0.12:
                    return ch, 'evade'
            look = st.get('evade_predict', 12.0)
            hh, hs = SectorLogic.hide_among_prey_heading(particle, st)
            if hh is not None and hs > 0.12:
                particle._hide_among_frames = getattr(particle, '_hide_among_frames', 0) + 1
                return hh, 'hide'
            return SectorLogic.escape_heading(particle, fear[1], look), 'evade'

        if prey is not None:
            # Refuse chase if the prey heading points near a FEAR
            look = st.get('predict_lookahead', 12.0)
            chase_h = SectorLogic.chase_heading(particle, prey[1], look)
            if fear is not None and chase_h is not None:
                fobj = fear[1]
                # Angle between chase heading and vector to fear
                to_f = math.atan2(fobj.x - particle.x, -(fobj.y - particle.y))
                diff = abs(SectorLogic.wrap_angle(chase_h - to_f))
                if diff < math.radians(40) and fear[0] < 22 * size:
                    look_e = st.get('evade_predict', 12.0)
                    return SectorLogic.escape_heading(particle, fobj, look_e), 'evade'
            return chase_h, 'chase'

        if fear is not None:
            hh, hs = SectorLogic.hide_among_prey_heading(particle, st)
            if hh is not None and hs > 0.12:
                particle._hide_among_frames = getattr(particle, '_hide_among_frames', 0) + 1
                return hh, 'hide'
            look = st.get('evade_predict', 12.0)
            return SectorLogic.escape_heading(particle, fear[1], look), 'evade'
        return None, 'idle'

    @staticmethod
    def sector_threat_score(sector_pings, size):
        t = 0.0
        for dist, rel, _ in sector_pings:
            if rel == ParticleRelative.FEAR:
                t += SectorLogic.distance_factor(dist, size)
        return t

    @staticmethod
    def sector_prey_score(sector_pings, size):
        t = 0.0
        for dist, rel, _ in sector_pings:
            if rel == ParticleRelative.PREY:
                t += SectorLogic.distance_factor(dist, size)
        return t



# ---------------------------------------------------------------------------
# Swarm intelligence – Reynolds forces + collective hunt/flee
# ---------------------------------------------------------------------------

def _boids():
    from maths.boids import SwarmIntelligence
    return SwarmIntelligence


class Steer:
    """Heading / speed damping, wall/fort slide, pincer offset (Reynolds)."""

    def adaptive_speed_damp(particle, target):
        # Speed matching with flock neighbors (Reynolds velocity match)
        sm = getattr(particle, '_speed_match_target', None)
        if sm is not None:
            target = target * 0.55 + float(sm) * 0.45
        # CLEAR_HUNT finish speed boost
        if particle.fearCount() <= 0 and particle.preyCount() > 0:
            target = target * float(particle.strat().get('clear_finish_speed', 1.15))
        # Arrive (Reynolds): slow near ambush hold point / fort
        if getattr(particle, '_ambush_mode', None) == 'hold':
            st = particle.strat()
            ar = float(st.get('arrive_radius', 3.5)) * particle.size
            slow = float(st.get('arrive_slow', 0.45))
            fort = getattr(particle, '_ambush_fort', None)
            if fort is not None and ar > 1:
                d = math.hypot(particle.x - fort.x, particle.y - fort.y)
                if d < ar:
                    t = max(0.0, d / ar)
                    # quadratic arrive curve
                    target = target * (slow + (1.0 - slow) * t * t)
                    particle._arrive_active = 1
                else:
                    particle._arrive_active = 0
            else:
                particle._arrive_active = 0
        else:
            particle._arrive_active = 0
        """Smoothly approach target speed; rate depends on delta and state."""
        cur = particle.speed
        delta = target - cur
        if abs(delta) < 1e-5:
            return cur
        ms = max(1e-6, particle.maxspeed())
        ratio = abs(delta) / ms
        if particle._evading:
            base = getattr(_cfg(), 'DAMP_SPEED_EVADE', 0.28)
        elif delta < 0:
            base = getattr(_cfg(), 'DAMP_SPEED_DOWN', 0.18)
        else:
            base = getattr(_cfg(), 'DAMP_SPEED_UP', 0.12)
        # Larger gaps → slightly faster catch-up (still damped)
        rate = base * (0.55 + 0.45 * min(1.0, ratio * 2.0))
        # Turning: damp accel harder for stability
        if particle.turn != 0 and delta > 0:
            rate *= 0.65
        return cur + delta * rate

    def adaptive_heading_damp(particle, desired, mode='idle'):
        """Blend new desired heading with previous to avoid twitchy turns."""
        if desired is None:
            return None
        prev = getattr(particle, '_prev_desired', None)
        if prev is None:
            particle._prev_desired = desired
            return desired
        if mode == 'evade':
            b = getattr(_cfg(), 'DAMP_HEADING_EVADE', 0.55)
        elif mode == 'chase':
            b = getattr(_cfg(), 'DAMP_HEADING', 0.35)
        else:
            b = getattr(_cfg(), 'DAMP_HEADING_IDLE', 0.22)
        # Angular slerp via unit vectors
        px, py = math.sin(prev), -math.cos(prev)
        dx, dy = math.sin(desired), -math.cos(desired)
        # If almost opposite, bias toward desired more to not stall
        dot = px * dx + py * dy
        if dot < -0.2:
            b = min(0.85, b + 0.25)
        x = px * (1 - b) + dx * b
        y = py * (1 - b) + dy * b
        if abs(x) + abs(y) < 1e-9:
            smoothed = desired
        else:
            smoothed = math.atan2(x, -y) % (2 * math.pi)
        particle._prev_desired = smoothed
        return smoothed

    def adaptive_turn_damp(particle, turn_amt):
        """Limit how fast the commanded turn magnitude changes."""
        prev = getattr(particle, '_prev_turn_cmd', 0.0) or 0.0
        rate = getattr(_cfg(), 'DAMP_TURN_RATE', 0.40)
        # Evade allows faster turn ramp-up
        if particle._evading:
            rate = min(0.75, rate + 0.25)
        smoothed = prev + (turn_amt - prev) * rate
        particle._prev_turn_cmd = smoothed
        return smoothed

    def _pincer_offset_point(particle, prey, role):
        """Offset pursue point beside prey for L/R flanks (Reynolds offset pursue)."""
        st = particle.strat()
        dist = float(st.get('offset_pursue_dist', 2.8)) * particle.size
        gain = float(st.get('offset_pursue_gain', 1.0))
        # Side perpendicular to prey velocity (or to me→prey)
        pvx = math.sin(prey.angle) * max(0.15, prey.speed)
        pvy = -math.cos(prey.angle) * max(0.15, prey.speed)
        pl = math.hypot(pvx, pvy) + 1e-6
        # Lateral
        lx, ly = -pvy / pl, pvx / pl
        if role == 'L':
            side = 1.0
        elif role == 'R':
            side = -1.0
        else:
            # DRIVE: slightly behind prey along its velocity
            return (prey.x - pvx / pl * dist * 0.6 * gain,
                    prey.y - pvy / pl * dist * 0.6 * gain)
        return (prey.x + lx * side * dist * gain,
                prey.y + ly * side * dist * gain)

    def _steer_past_friends(particle, desired):
        """If a same-type particle is close and nearly ahead, bias heading sideways."""
        if desired is None:
            return desired
        r = particle.size * 4.5
        others = particle.w.nearby(particle.x, particle.y, r) if hasattr(particle.w, 'nearby') else particle.w.particles
        hx, hy = math.sin(desired), -math.cos(desired)
        best_w = 0.0
        sx = sy = 0.0
        for o in others:
            if o is particle or o.type != particle.type:
                continue
            dx, dy = o.x - particle.x, o.y - particle.y
            dist = math.hypot(dx, dy)
            if dist < 1e-6 or dist > r:
                continue
            # Ahead if dot with desired heading is positive and large
            ux, uy = dx / dist, dy / dist
            dot = hx * ux + hy * uy
            if dot < 0.35:
                continue  # not really in front
            w = (1.0 - dist / r) * (dot ** 2)
            # Lateral direction: prefer consistent side from id
            side = 1.0 if (hash(getattr(particle, 'id', id(particle))) & 1) else -1.0
            lx, ly = -uy * side, ux * side
            sx += lx * w
            sy += ly * w
            best_w += w
        if best_w < 0.08:
            return desired
        # Blend lateral into desired
        blend = min(0.55, 0.25 + best_w * 0.35)
        dx = hx * (1 - blend) + sx / best_w * blend
        dy = hy * (1 - blend) + sy / best_w * blend
        if abs(dx) + abs(dy) < 1e-9:
            return desired
        return math.atan2(dx, -dy) % (2 * math.pi)

    def _steer_around_forts(particle, desired):
        """If heading `desired` would hit a fort, bias heading tangent around it."""
        if not particle.w.fort_list:
            return desired
        look = _cfg().FORT_LOOK
        margin = _cfg().FORT_MARGIN
        hx, hy = math.sin(desired), -math.cos(desired)
        best_desired = desired
        best_clearance = float('inf')
        hit = False
        for f in particle.w.fort_list:
            clear = f.radius + particle.size + margin
            to_fx, to_fy = f.x - particle.x, f.y - particle.y
            proj = to_fx * hx + to_fy * hy
            if proj < 0 or proj > look:
                continue
            closest_x = particle.x + hx * proj
            closest_y = particle.y + hy * proj
            d = math.hypot(closest_x - f.x, closest_y - f.y)
            if d >= clear:
                continue
            hit = True
            # Tangent deflection: offset desired by angle that clears the fort
            # Prefer the side that requires smaller turn from current heading
            bearing_to_f = math.atan2(f.x - particle.x, -(f.y - particle.y))
            # Angular half-width of fort as seen from self
            dist_f = math.hypot(f.x - particle.x, f.y - particle.y) + 1e-6
            half = math.asin(min(1.0, clear / dist_f)) + math.radians(6)
            cand_l = (bearing_to_f - half) % (2 * math.pi)
            cand_r = (bearing_to_f + half) % (2 * math.pi)
            err_l = abs((cand_l - particle.angle + math.pi) % (2 * math.pi) - math.pi)
            err_r = abs((cand_r - particle.angle + math.pi) % (2 * math.pi) - math.pi)
            cand = cand_l if err_l <= err_r else cand_r
            # Prefer the fort that is closest along path
            if proj < best_clearance:
                best_clearance = proj
                best_desired = cand
        return best_desired if hit else desired

    def wall_repulsion_scale(particle, heading=None):
        """
        Dynamic wall repulsion multiplier from proximity, speed, and approach angle.
        Returns value in [WALL_SCALE_MIN, WALL_SCALE_MAX].
        """
        margin = _cfg().WALL_MARGIN + particle.size
        # Distance to nearest wall (0 at contact margin, 1 when deep inside)
        dx = min(particle.x - particle.size, particle.w.width - particle.size - particle.x)
        dy = min(particle.y - particle.size, particle.w.height - particle.size - particle.y)
        dist = max(0.0, min(dx, dy))
        # Normalise: full strength near edge, fades by ~WALL_LOOK
        reach = _cfg().WALL_LOOK * 0.85
        prox = 1.0 - min(1.0, dist / max(reach, 1.0))  # 1 = at wall, 0 = far
        prox = prox * prox  # quadratic – gentle far away, sharp near edge

        ms = max(1e-6, particle.maxspeed())
        spd = min(1.35, particle.speed / ms)  # >1 if somehow overspeed

        # Approach: how much current (or given) heading points outward into nearest wall
        h = particle.angle if heading is None else heading
        hx, hy = math.sin(h), -math.cos(h)
        approach = 0.0
        if particle.x < margin * 2 and hx < 0:
            approach = max(approach, -hx)
        if particle.x > particle.w.width - margin * 2 and hx > 0:
            approach = max(approach, hx)
        if particle.y < margin * 2 and hy < 0:
            approach = max(approach, -hy)
        if particle.y > particle.w.height - margin * 2 and hy > 0:
            approach = max(approach, hy)
        approach = max(0.0, min(1.0, approach))

        raw = (
            1.0
            + _cfg().WALL_SCALE_DIST * prox
            + _cfg().WALL_SCALE_SPEED * spd * (0.4 + 0.6 * prox)
            + _cfg().WALL_SCALE_APPROACH * approach * (0.5 + 0.5 * prox)
        )
        # Stronger while actively evading toward edges
        if getattr(particle, '_evading', False):
            raw *= 1.15
        return max(_cfg().WALL_SCALE_MIN, min(_cfg().WALL_SCALE_MAX, raw))

    def _steer_around_walls(particle, desired):
        """If heading `desired` would hit a wall soon, deflect parallel/inward (like forts)."""
        look = _cfg().WALL_LOOK
        margin = _cfg().WALL_MARGIN + particle.size
        scale = Steer.wall_repulsion_scale(particle, desired)
        hx, hy = math.sin(desired), -math.cos(desired)
        # Sample points along desired path
        hit_wall = None  # 'left','right','top','bottom'
        hit_proj = look
        steps = 6
        for i in range(1, steps + 1):
            t = look * i / steps
            ax = particle.x + hx * t
            ay = particle.y + hy * t
            if ax < margin:
                if t < hit_proj:
                    hit_proj, hit_wall = t, 'left'
            elif ax > particle.w.width - margin:
                if t < hit_proj:
                    hit_proj, hit_wall = t, 'right'
            if ay < margin:
                if t < hit_proj:
                    hit_proj, hit_wall = t, 'top'
            elif ay > particle.w.height - margin:
                if t < hit_proj:
                    hit_proj, hit_wall = t, 'bottom'
        if hit_wall is None:
            return desired
        # Deflect: prefer direction parallel to the wall, choosing the side
        # that stays more inside the arena and closer to current heading
        if hit_wall in ('left', 'right'):
            # wall is vertical → prefer up or down
            cand_a = 0.0            # up (angle 0 in this coord system: -y)
            cand_b = math.pi        # down
            # slight inward bias
            inward = math.radians(25) if hit_wall == 'left' else -math.radians(25)
            # angle 0 is up (-y), pi is down; left wall want +x component
            if hit_wall == 'left':
                cand_a = math.radians(30)
                cand_b = math.pi - math.radians(30)
            else:
                cand_a = -math.radians(30)
                cand_b = math.pi + math.radians(30)
        else:
            # wall is horizontal → prefer left or right
            if hit_wall == 'top':
                cand_a = math.radians(90)   # right-ish
                cand_b = -math.radians(90)  # left-ish
            else:
                cand_a = math.radians(60)
                cand_b = -math.radians(60)
        err_a = abs((cand_a - particle.angle + math.pi) % (2 * math.pi) - math.pi)
        err_b = abs((cand_b - particle.angle + math.pi) % (2 * math.pi) - math.pi)
        best = cand_a if err_a <= err_b else cand_b
        # Blend toward parallel more strongly when impact is soon / repulsion high
        urgency = max(0.35, 1.0 - hit_proj / look) * min(1.0, 0.55 + 0.45 * scale)
        urgency = max(0.25, min(0.95, urgency))
        # slerp-ish: mix desired with wall-parallel heading
        px, py = math.sin(desired), -math.cos(desired)
        bx, by = math.sin(best), -math.cos(best)
        x = px * (1 - urgency) + bx * urgency
        y = py * (1 - urgency) + by * urgency
        if abs(x) + abs(y) < 1e-9:
            return best % (2 * math.pi)
        return math.atan2(x, -y) % (2 * math.pi)

    def apply_wall_bias(particle, ds):
        """Add risk to directions that head into walls (mirrors apply_fort_bias)."""
        try:
            cone_c = _centres().get(_TR()(ds.direction), 0.0)
        except Exception:
            cone_c = 0.0
        look = _cfg().WALL_LOOK
        margin = _cfg().WALL_MARGIN + particle.size
        hx = math.sin(particle.angle + cone_c)
        hy = -math.cos(particle.angle + cone_c)
        scale = Steer.wall_repulsion_scale(particle, particle.angle + cone_c)
        wall_avoid = _cfg().WALL_AVOID * scale * (0.35 if particle.fearCount() <= 0 and particle.preyCount() > 0 else 1.0)
        # Sample along cone ray
        for frac, w in ((0.35, 0.5), (0.65, 0.85), (1.0, 1.0)):
            ax = particle.x + hx * look * frac
            ay = particle.y + hy * look * frac
            pen = 0.0
            if ax < margin:
                pen = max(pen, (margin - ax) / margin)
            elif ax > particle.w.width - margin:
                pen = max(pen, (ax - (particle.w.width - margin)) / margin)
            if ay < margin:
                pen = max(pen, (margin - ay) / margin)
            elif ay > particle.w.height - margin:
                pen = max(pen, (ay - (particle.w.height - margin)) / margin)
            if pen > 0:
                near = 1.0 - 0.5 * frac  # sooner hits cost more
                ds.risk += wall_avoid * min(1.0, pen) * w * near
        # Extra: already very close to a wall → penalise outward cones
        edge = margin * 1.4
        if particle.x < edge and hx < 0:
            ds.risk += wall_avoid * 0.8 * (1.0 - particle.x / edge)
        if particle.x > particle.w.width - edge and hx > 0:
            ds.risk += wall_avoid * 0.8 * (1.0 - (particle.w.width - particle.x) / edge)
        if particle.y < edge and hy < 0:
            ds.risk += wall_avoid * 0.8 * (1.0 - particle.y / edge)
        if particle.y > particle.w.height - edge and hy > 0:
            ds.risk += wall_avoid * 0.8 * (1.0 - (particle.w.height - particle.y) / edge)

    def _predicted_pos(particle, p, la=None):
        if la is None:
            try:
                la = particle.strat().get("predict_lookahead", _cfg().PREDICT_LOOKAHEAD)
            except Exception:
                la = _cfg().PREDICT_LOOKAHEAD
        return (p.x + math.sin(p.angle)*p.speed*la, p.y - math.cos(p.angle)*p.speed*la)

    def apply_fort_bias(particle, ds):
        from config import TeamMode, Role
        if not particle.w.fort_list:
            return
        cone_c = {0:0,1:-math.radians(30),2:math.radians(30),
                  3:-math.radians(60),4:math.radians(60),
                  5:-math.radians(90),6:math.radians(90),
                  7:-math.radians(120),8:math.radians(120)}.get(ds.direction, 0)
        # Strong avoid: sample several points along the cone heading
        fort_avoid = _cfg().FORT_AVOID * (0.55 if particle.fearCount() <= 0 else 1.0)
        look = _cfg().FORT_LOOK
        margin = _cfg().FORT_MARGIN
        hx = math.sin(particle.angle + cone_c)
        hy = -math.cos(particle.angle + cone_c)
        for f in particle.w.fort_list:
            clear = f.radius + particle.size + margin
            # Distance from fort centre to the ray (particle -> cone direction)
            # Closest approach along the forward ray
            to_fx, to_fy = f.x - particle.x, f.y - particle.y
            proj = to_fx * hx + to_fy * hy
            if proj < 0:
                continue  # fort is behind this heading
            if proj > look:
                continue
            closest_x = particle.x + hx * proj
            closest_y = particle.y + hy * proj
            d = math.hypot(closest_x - f.x, closest_y - f.y)
            if d < clear:
                # Stronger when impact is sooner / more head-on
                sev = max(0.0, 1.0 - d / clear)
                near = max(0.0, 1.0 - proj / look)
                ds.risk += fort_avoid * sev * (0.45 + 0.55 * near)
            # Also penalise if endpoint sits inside fort
            ax = particle.x + hx * look
            ay = particle.y + hy * look
            if math.hypot(ax - f.x, ay - f.y) < clear:
                ds.risk += fort_avoid * 0.6

        # 2. Cover – fort between self and a nearby fear
        for other in particle.w.particles:
            if other is particle or particle.Identify(other) != ParticleRelative.FEAR: continue
            if math.hypot(other.x-particle.x, other.y-particle.y) > _cfg().VISION_FAR*particle.size*0.65: continue
            for f in particle.w.fort_list:
                d1 = math.hypot(particle.x-f.x, particle.y-f.y)
                d2 = math.hypot(other.x-f.x, other.y-f.y)
                d3 = math.hypot(particle.x-other.x, particle.y-other.y)
                if d1 + d2 < d3 + f.radius*1.7 and d1 > f.radius:
                    ds.risk = max(0.0, ds.risk - _cfg().FORT_COVER*0.75)
                    ds.confidence = min(1.0, ds.confidence + _cfg().FORT_COVER*0.25)
                    break

        # 3. Herding – push suggested target toward a fort
        focus = particle.get_team().suggested_target
        if focus is not None:
            for f in particle.w.fort_list:
                if math.hypot(focus.x-f.x, focus.y-f.y) < f.radius + 75:
                    fdx, fdy = f.x-particle.x, f.y-particle.y
                    fdes = math.atan2(fdx, -fdy)
                    fdiff = (fdes - particle.angle + math.pi)%(2*math.pi) - math.pi
                    if abs((fdiff - cone_c + math.pi)%(2*math.pi) - math.pi) < math.radians(48):
                        ds.reward += _cfg().FORT_HERD * 0.85
                        break

        # 4. Mild choke preference
        if len(particle.w.fort_list) >= 2 and particle.get_team().mode == TeamMode.HUNT:
            for i, f1 in enumerate(particle.w.fort_list):
                for f2 in particle.w.fort_list[i+1:]:
                    gap = math.hypot(f1.x-f2.x, f1.y-f2.y) - f1.radius - f2.radius
                    if 35 < gap < 150:
                        mx, my = (f1.x+f2.x)/2, (f1.y+f2.y)/2
                        mdes = math.atan2(mx-particle.x, -(my-particle.y))
                        mdiff = (mdes - particle.angle + math.pi)%(2*math.pi) - math.pi
                        if abs((mdiff - cone_c + math.pi)%(2*math.pi) - math.pi) < math.radians(38):
                            ds.reward += _cfg().FORT_CHOKE
                            break

        # 5. Defender anchor to nearest fort
        if particle.role == Role.DEFENDER and particle.get_team().mode in (TeamMode.DEFEND, TeamMode.REGROUP):
            nearest = min(particle.w.fort_list, key=lambda f: math.hypot(particle.x-f.x, particle.y-f.y), default=None)
            if nearest:
                ndes = math.atan2(nearest.x-particle.x, -(nearest.y-particle.y))
                ndiff = (ndes - particle.angle + math.pi)%(2*math.pi) - math.pi
                if abs((ndiff - cone_c + math.pi)%(2*math.pi) - math.pi) < math.radians(45):
                    ds.cohesion += _cfg().FORT_ANCHOR

        # Cover: reward directions that put a fort between self and nearest visible fear
        if particle.fearCount() > 0:
            st = particle.strat()
            cw = float(st.get('fort_cover_weight', 1.0))
            if cw > 0.05:
                # Find nearest fear with LOS (if already occluded we are safe)
                nearest_fear = None
                nd = 1e18
                for o in (particle.w.nearby(particle.x, particle.y, 22 * particle.size) if hasattr(particle.w, 'nearby') else particle.w.particles):
                    if o is particle:
                        continue
                    if particle.Identify(o) != ParticleRelative.FEAR:
                        continue
                    if _los().occludes(particle.w, particle, o):
                        continue
                    d = math.hypot(o.x - particle.x, o.y - particle.y)
                    if d < nd:
                        nd = d
                        nearest_fear = o
                if nearest_fear is not None:
                    ch, cs = _los().cover_heading(particle, nearest_fear, st)
                    if ch is not None and cs > 0.08:
                        try:
                            cone_c = _centres().get(_TR()(ds.direction), 0.0)
                        except Exception:
                            cone_c = 0.0
                        desired = particle.angle + cone_c
                        ad = abs((ch - desired + math.pi) % (2 * math.pi) - math.pi)
                        if ad < math.radians(50):
                            ds.reward += cw * cs * st.get('fort_hide_bias', 1.0) * (1.0 - ad / math.radians(50))
                            ds.risk *= 0.85

    def pincer_heading(team, particle, target=None):
        """Desired world heading for this particle's pincer role."""
        role = team.pincer_assignments.get(particle.id)
        if role is None:
            return None
        target = target or (team.alert_target if (team.alert_target and team.alert_ttl > 0) else team.suggested_target)
        if target is None:
            return None
        st = particle.strat()
        spread = float(st.get('pincer_spread', 0.85))  # radians scale
        # Base vector to prey
        dx, dy = target.x - particle.x, target.y - particle.y
        dist = math.hypot(dx, dy) + 1e-6
        # Tighten as we close in
        tight = max(0.35, min(1.0, dist / (14 * particle.size)))
        angle_off = spread * tight
        if role == 'left':
            ang = math.atan2(dx, -dy) - angle_off
        elif role == 'right':
            ang = math.atan2(dx, -dy) + angle_off
        else:  # drive — straight in
            ang = math.atan2(dx, -dy)
        # Aim at offset point beside prey, not through it when far
        if role != 'drive' and dist > 4 * particle.size:
            # Lateral offset point near prey
            side = -1.0 if role == 'left' else 1.0
            # perpendicular in world
            base = math.atan2(target.x - particle.x, -(target.y - particle.y))
            ox = target.x + math.sin(base + side * math.pi / 2) * (3.2 * particle.size * tight)
            oy = target.y - math.cos(base + side * math.pi / 2) * (3.2 * particle.size * tight)
            ang = math.atan2(ox - particle.x, -(oy - particle.y))
        return ang % (2 * math.pi)

