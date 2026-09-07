"""
Shared simulation constants and enums.

Imported by particle, arena, phys, ping, fort, marble, logger.
Does not import those modules.
"""

import math
from enum import Enum


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class Config:
    TARGET_FPS = 60            # FIFO-style cap (Vulkan mailbox analog = 0)
    VSYNC = True               # SDL present wait; like VK_PRESENT_MODE_FIFO
    VISION_NEAR = 5.0
    VISION_FAR = 30.0   # 30 * size(20) = 600 px max vision
    CONE_OFFSETS = [15, 45, 75, 105, 135]
    SECTOR_BOUNDS = None

    COHESION_WEIGHT = 0.55
    PACK_HUNT_MULT = 1.9
    ISOLATION_RISK = 0.45
    ISOLATED_PREY_BONUS = 0.85
    FOCUS_TARGET_BONUS = 0.70
    DEFEND_COHESION_BOOST = 1.7
    HUNT_AGGRESSION = 1.35

    FLANK_BONUS = 0.65
    PREDICT_LOOKAHEAD = 12.0
    SEPARATION_DIST = 3.0
    SEPARATION_RISK = 0.32
    ALIGNMENT_WEIGHT = 0.28
    # Swarm intelligence (Reynolds-style forces blended into steering)
    SWARM_SEP_WEIGHT = 1.15       # push away from nearby friends
    SWARM_COH_WEIGHT = 0.55       # pull toward local friend centroid
    SWARM_ALI_WEIGHT = 0.40       # match local friend velocity
    SWARM_FEAR_WEIGHT = 1.80      # collective flee from predators
    SWARM_PREY_WEIGHT = 1.10      # collective hunt toward prey
    SWARM_RADIUS_FRIEND = 10.0    # * size – local neighborhood
    SWARM_RADIUS_FEAR = 22.0      # * size
    SWARM_RADIUS_PREY = 20.0      # * size
    SWARM_BLEND = 0.55            # how much swarm heading mixes with AI orient (0=ignore swarm)
    SWARM_AVOID_WEIGHT = 1.60     # predictive collision avoidance strength
    SWARM_AVOID_LOOKAHEAD = 18.0  # frames of travel to project
    SWARM_AVOID_RADIUS = 4.5      # * size – consider collision if paths come within this
    # Performance
    GRID_CELL = 80.0              # spatial hash cell size (px)
    AI_IDLE_EVERY = 3             # frames between AI ticks when idle
    AI_NORMAL_EVERY = 2           # frames when active but not urgent
    AI_URGENT_EVERY = 1           # near FEAR/PREY
    ROT_CACHE_STEP = 6            # degrees – cache rotated sprites
    TRAIL_LEN = 5                 # cached trail dots
    ENABLE_GLOW = True            # cached soft glow under each marble
    MARBLE_CAP_SHADOW = False    # per-pixel cap smear stays off
    MARBLE_OCCLUSION = True      # forts dim a marble when they block the key light
    ENABLE_MARBLE = True          # shaded 2.5D marble body (cached)
    MARBLE_LIGHT_STEP = 22        # degrees – cache highlight buckets
    MARBLE_ICON = True            # small watermark icon only (not the whole face)
    MARBLE_ICON_SCALE = 0.42      # icon size vs marble radius
    MARBLE_ICON_ALPHA = 165
    MARBLE_ROLL_STEP = 12         # degrees – cached roll buckets
    MARBLE_ROLL_GAIN = 1.0        # roll radians = gain * distance / radius
    # Match the FLAT HUD icons (rock=yellow, paper=blue, scissors=red)
    # Must match the FLAT HUD icons (top→bottom = ROCK, PAPER, SCISSORS)
    MARBLE_COLORS = {
        'ROCK': (236, 78, 108),      # red / pink
        'PAPER': (247, 196, 48),     # yellow
        'SCISSORS': (70, 178, 230),  # blue
    }
    ENABLE_FORT_GLOW = True
    GLOW_ALPHA = 70
    # World key light (matches marble Phong: upper-left)
    LIGHT_DX = -0.32
    LIGHT_DY = -0.55
    FORT_SHADOW_LEN = 5.5         # how far shadow reaches, in fort radii
    FORT_SHADOW_STRENGTH = 0.48   # max dim — keep team colour readable
    FORT_SHADOW_PENUMBRA = 0.55
    FORT_SHADOW_GROUND = False    # no smear volumes
    BG_TOP = (12, 14, 28)
    BG_BOT = (24, 32, 58)
    BG_STAR_COUNT = 48            # tiny stars on gradient (cached once)
    SOUND_COOLDOWN_MS = 120
    AI_BUDGET = 6                 # max full AI decisions per frame (hard cap)
    AI_IDLE_EVERY = 5
    AI_NORMAL_EVERY = 3
    AI_URGENT_EVERY = 2
    SWARM_EVERY = 1               # base swarm tick (sep / fear-prey path)
    SWARM_SEP_EVERY = 1           # separation every frame (anti head-lock)
    SWARM_ALI_COH_EVERY = 3       # alignment+cohesion every N frames (smoother large teams)
    SWARM_FEAR_PREY_EVERY = 1     # fear/prey forces cadence (keep responsive)
    MAX_SWARM_NEIGHBORS = 8
    TEAM_UPDATE_EVERY = 5          # frames between full team.mode/role updates
    VISION_AI_FAR = 18.0          # shorter vision for AI scans (* size)
    # Beauty
    BG_TOP = (18, 20, 32)
    BG_BOT = (28, 32, 48)
    GLOW_ALPHA = 55
    INTERPOSE_BONUS = 0.50
    ROLE_HUNTER_PURSUIT = 1.30
    ROLE_FLANKER_SIDE = 1.40
    ROLE_DEFENDER_COHESION = 1.55
    LAST_SURVIVOR_FINISH = 1.8

    # Self-preservation & small-team scatter / raid
    FEAR_CLOSE_MULT = 2.10          # stronger risk when FEAR is close
    FEAR_OUTNUMBERED_MULT = 1.80    # extra risk when fearCount >= selfcount
    SCATTER_COUNT_THRESHOLD = 4     # at or below this → scatter / disperse
    SCATTER_COHESION = 0.02         # almost zero cohesion when scattering
    SCATTER_SEPARATION = 0.55       # strong push away from friends when few left
    RAID_ISOLATED_BONUS = 1.90      # prefer isolated prey when small
    ESCAPE_BONUS_WEIGHT = 0.65      # stronger preference for escape directions
    NEAR_TARGET_AGGRO = 2.40        # strong reward when PREY is close – must chase
    CLUSTER_BONUS = 0.95            # strong preference for groups of PREY (targets of opportunity)

    # Dynamic fear decay
    FEAR_DECAY_RATE = 0.04          # residual fear fades per decision when no FEAR in sight
    FEAR_DECAY_FAST = 0.18          # faster fade when predator type is extinct
    FEAR_BUILD_RATE = 0.35          # residual jumps up when FEAR is seen
    FEAR_POP_SCALE = 0.55           # how much predator scarcity reduces fear (0=ignore count, 1=full)

    # Expanded team strategy
    MODE_HYSTERESIS = 8             # frames a mode condition must hold before switching
    ALERT_TTL_KILL = 22             # longer callout after a conversion
    ALERT_TTL_SPOT = 14             # callout when spotting a high-value target
    FOCUS_FIRE_MULT = 1.55          # extra reward when chasing the team alert target
    MOMENTUM_WINDOW = 40            # frames to track recent conversions
    MOMENTUM_HUNT_BIAS = 0.25       # extra hunt aggressiveness when on a streak
    SUPPORT_JOIN_BONUS = 0.55       # pile-on when a friend is already on a PREY
    FINISH_BONUS = 1.10             # extra aggression on nearly-caught PREY

    # Individual tactics
    COMMIT_FRAMES = 10              # stick with pursue/evade decision this many frames
    COMMIT_BREAK_RISK = 1.55        # only break commitment if risk jumps by this factor
    ROLE_REEVAL_EVERY = 12          # re-score roles periodically
    TARGET_LOCK_BONUS = 1.45        # score mult while locked on a PREY
    TARGET_SWITCH_MARGIN = 1.40     # new PREY must be this much better to steal the lock
    TARGET_LOCK_TTL = 45            # frames to keep hunting same target without re-seeing it

    # Forts
    FORT_MIN_R = 26
    FORT_MAX_R = 46
    FORT_EDGE = 85
    FORT_MIN_SEP = 100
    FORT_AVOID = 2.8            # strong risk for paths into forts
    FORT_LOOK = 110.0           # how far ahead to test for forts
    FORT_MARGIN = 28.0          # extra clearance beyond fort radius
    FORT_COVER = 0.55
    FORT_HERD = 0.50
    FORT_CHOKE = 0.28
    FORT_ANCHOR = 0.35

    DRAG = {"FRONT": 1.0, "SIDE": 0.9, "30": 0.8, "60": 0.7, "90": 0.6}
    SPEED_PENALTY_STEP = 0.1
    OVERSPEED_DECAY = 0.28          # fraction of excess speed bled off each move frame
    OVERSPEED_HARD_RATIO = 1.0  # hard ceiling at maxspeed after decay
    DEBUG_SPEED = True          # log overspeed events to speed_debug.log
    DEBUG_SPEED_EVERY = 15      # min frames between logs per particle
    # Physics
    RESTITUTION = 0.72          # particle bounce energy (0=stick, 1=elastic)
    FORT_RESTITUTION = 0.65
    WALL_RESTITUTION = 0.80
    WALL_AVOID = 2.6            # base risk weight for paths into walls
    WALL_LOOK = 120.0           # look-ahead distance for wall avoidance
    WALL_MARGIN = 22.0          # soft clearance beyond particle size
    WALL_SCALE_DIST = 1.0       # weight of proximity in dynamic scale
    WALL_SCALE_SPEED = 0.85     # weight of speed ratio in dynamic scale
    WALL_SCALE_APPROACH = 0.75  # weight of head-on approach in dynamic scale
    WALL_SCALE_MIN = 0.35       # floor multiplier
    WALL_SCALE_MAX = 2.40       # ceiling multiplier
    COLLISION_SPEED_KEEP = 0.50 # post-hit fraction; recover to cruise in move()
    # Match intro / outro timing (ms)
    FAST_SIM = False             # batch / dry-run: skip intros, presentation, clock
    FAST_SIM_PHYS_STEPS = 3      # physics substeps per batch frame
    FAST_SIM_AI_EVERY = 2        # command at most every N batch frames
    TITLE_MS = 5600              # welcome + visible learn pass
    LEARN_REVEAL_MS = 70         # ms between typed knob lines on TITLE
    LEARN_MAX_MS = 9000          # never hold TITLE longer than this for learning
    TITLE_DELAY_MS = 0           # no gap after winner dismissed → READY → next TITLE
    FORT_INTRO_MS = 900
    FORT_STAGGER_MS = 90
    PARTICLE_INTRO_MS = 1100
    PARTICLE_STAGGER_MS = 40
    PARTICLE_RISE_PX = 220
    PARTICLE_OUTRO_MS = 1000
    PARTICLE_FALL_PX = 280
    PARTICLE_HOLD_MS = 1000       # pause after all risen, before 3-2-1
    PARTICLE_TYPE_WAVE_GAP_MS = 350  # pause between type waves (R then P then S)
    COUNTDOWN_STEP_MS = 900
    FORT_OUTRO_MS = 800
    GAMEOVER_HOLD_MS = 3200
    SEPARATION_SLOP = 0.5       # push-out padding on overlap
    ACCEL_RATE = 0.04           # fraction of maxspeed gained per frame
    # Fixed cruise – independent of collisions / remaining units / teamSize
    CRUISE_MULT = 5.5           # maxspeed = (speed_base + strength) * CRUISE_MULT
    LAST_MAN_FEAR_SPEED = 1.25  # last unit on a team, while predators remain
    SPEED_TEAM_FACTOR = 0.0     # 0 = teamSize does not affect speed
    LATE_SPEED_ENABLED = False  # no late-game speed boost when few left
    TURN_DRAG = 0.012           # extra speed loss while turning
    # Adaptive damping – smoother speed / heading transitions
    DAMP_SPEED_UP = 0.22        # snappier accel – keep swimming
    DAMP_SPEED_DOWN = 0.20      # base decel smoothing
    DAMP_SPEED_EVADE = 0.35     # faster response while fleeing
    DAMP_HEADING = 0.45         # blend AI desired heading updates
    DAMP_HEADING_EVADE = 0.65
    DAMP_HEADING_IDLE = 0.30
    DAMP_TURN_RATE = 0.55
    # Continuous swim – degrees of turn applied per frame toward desired heading
    SWIM_TURN_RATE = 0.12       # fraction of angular error closed each frame (EMA)
    SWIM_TURN_RATE_EVADE = 0.20
    SWIM_TURN_MAX = 0.18        # max radians turned per frame (~10°)
    SWIM_TURN_MAX_EVADE = 0.28  # ~16° while fleeing
    AI_IDLE_EVERY = 2           # still throttle AI, never throttle motion
    AI_NORMAL_EVERY = 1
    AI_URGENT_EVERY = 1
    EVADE_THRESHOLD_BASE = 1.0
    MIN_SPEED_FOR_AI = 0.25
    HUNT_ADVANTAGE = 1.15
    DEFEND_RATIO = 0.75
    VISION_DIRTY_THRESHOLD = 0.03
    ISOLATION_UPDATE_EVERY = 3


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
class ParticleType(Enum):
    ROCK = 0
    PAPER = 1
    SCISSORS = 2

class TurnRelative(Enum):
    FRONT = 0
    LEFT = 1
    RIGHT = 2
    LEFT30 = 3
    RIGHT30 = 4
    LEFT60 = 5
    RIGHT60 = 6
    LEFT90 = 7
    RIGHT90 = 8
    LEFT135 = 9
    RIGHT135 = 10
    BACK = 11

class MatchPhase(Enum):
    TITLE = 0
    FORTS_IN = 1
    PARTICLES_IN = 2
    COUNTDOWN = 3
    PLAYING = 4
    GAMEOVER = 5
    FORTS_OUT = 6
    PARTICLES_OUT = 7
    DONE = 8          # 1s hold after winner dismissed, then TITLE
    READY = 9         # TITLE finished – gameover() True so outer loop can reset


class TeamMode(Enum):
    HUNT = 0
    DEFEND = 1
    REGROUP = 2
    SCATTER = 3   # small team: spread out and raid isolated enemies

class Role(Enum):
    HUNTER = 0
    FLANKER = 1
    DEFENDER = 2



# Frozen per-type identity. Tunables live in strategies/ JSON, not here.
TYPE_IDENTITY = {
    "ROCK": {
        "speed_base": 1.0946,
        "turn_base": 13.7875,
        "size": 20,
        "strength_range": (-0.2, 0.3),
        "agility_range": (-2.0, 4.0),
        "bravery_range": (-0.2, 0.3),
        "prey": "SCISSORS",
        "fear": "PAPER",
        "display_name": "Rock",
        "icon": "rock.png",
        "color": (236, 78, 108),
    },
    "PAPER": {
        "speed_base": 1.8800,
        "turn_base": 13.0000,
        "size": 20,
        "strength_range": (-0.25, 0.25),
        "agility_range": (-4.0, 2.0),
        "bravery_range": (-0.25, 0.25),
        "prey": "ROCK",
        "fear": "SCISSORS",
        "display_name": "Paper",
        "icon": "paper.png",
        "color": (247, 196, 48),
    },
    "SCISSORS": {
        "speed_base": 1.2200,
        "turn_base": 13.3500,
        "size": 20,
        "strength_range": (-0.22, 0.28),
        "agility_range": (-3.0, 3.0),
        "bravery_range": (-0.22, 0.28),
        "prey": "PAPER",
        "fear": "ROCK",
        "display_name": "Scissors",
        "icon": "scissors.png",
        "color": (70, 178, 230),
    },
}

PREY_OF = {
    ParticleType[name]: ParticleType[d["prey"]]
    for name, d in TYPE_IDENTITY.items()
}
FEAR_OF = {
    ParticleType[name]: ParticleType[d["fear"]]
    for name, d in TYPE_IDENTITY.items()
}


# ---------------------------------------------------------------------------
# Learned defaults + effective_strategy (was type_config.py)
# Tunables live in strategies/types JSON. This only loads them.
# ---------------------------------------------------------------------------
import json
import os

REF_TEAM_SIZE = 20
IDENTITY_KEYS = (
    'speed_base', 'turn_base', 'size',
    'strength_range', 'agility_range', 'bravery_range',
    'prey', 'fear', 'display_name', 'icon', 'color',
)


def _bounds_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, 'strategies', 'bounds.json')


def _load_bounds():
    path = _bounds_path()
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
        out = {}
        for k, v in raw.items():
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                out[k] = (float(v[0]), float(v[1]), float(v[2]))
        return out
    except Exception:
        return {}


STRATEGY_BOUNDS = _load_bounds()
STRATEGY_KEYS = list(STRATEGY_BOUNDS.keys())


def _load_strategy_knobs(type_name):
    """Pull learned weights/base from types/{TYPE}/*.json (no _profile)."""
    here = os.path.dirname(os.path.abspath(__file__))
    tdir = os.path.join(here, 'strategies', 'types', type_name)
    knobs = {}
    try:
        names = sorted(fn for fn in os.listdir(tdir)
                       if fn.endswith('.json') and not fn.startswith('_'))
    except Exception:
        names = []
    # Last-writer-wins by filename; PACK_HUNT applied last if present.
    if 'PACK_HUNT.json' in names:
        names = [n for n in names if n != 'PACK_HUNT.json'] + ['PACK_HUNT.json']
    for fn in names:
        try:
            with open(os.path.join(tdir, fn), encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        for src in (data.get('base') or {}, data.get('weights') or {}):
            for k, v in src.items():
                knobs[k] = v
    return knobs


def _build_defaults():
    out = {}
    for name, ident in TYPE_IDENTITY.items():
        d = dict(ident)
        d.update(_load_strategy_knobs(name))
        out[name] = d
    return out


def _apply_learned_motion():
    """Overlay learned speed/turn from optimizer/metrics/motion_identity.json."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'optimizer', 'metrics', 'motion_identity.json')
    try:
        data = json.load(open(path, encoding='utf-8'))
    except Exception:
        return
    ident = data.get('identity') or {}
    for name, d in ident.items():
        if name not in TYPE_IDENTITY or not isinstance(d, dict):
            continue
        try:
            if 'speed_base' in d:
                TYPE_IDENTITY[name]['speed_base'] = float(d['speed_base'])
            if 'turn_base' in d:
                TYPE_IDENTITY[name]['turn_base'] = float(d['turn_base'])
        except Exception:
            pass


_apply_learned_motion()

TYPE_DEFAULTS = _build_defaults()


TYPE_MOTION = {
    name: {"speed_base": d["speed_base"], "turn_base": d["turn_base"]}
    for name, d in TYPE_IDENTITY.items()
}


def team_scale_factor(team_size, scale_coeff, ref=REF_TEAM_SIZE):
    if ref <= 1:
        return 1.0
    return 1.0 + scale_coeff * (math.log1p(max(0, team_size)) / math.log1p(ref) - 1.0)


def effective_strategy(type_name, team_size, self_count=None, fear_count=None, prey_count=None,
                       strategy_id=None):
    """CLEAR_HUNT when fear==0; NEAR_WIPE last-stand; LAST_PREY no-corner boost."""
    d = dict(TYPE_DEFAULTS.get(type_name) or {})
    if strategy_id:
        try:
            import strategies.playbook as pb
            ov = (pb.TEAM_OVERLAYS.get(type_name) or {}).get(strategy_id) or {}
            d.update(ov.get('base') or {})
            d.update(ov.get('weights') or {})
        except Exception:
            pass
    ts = max(1, int(team_size))
    out = dict(d)
    out["near_target_aggro"] = float(d["near_target_aggro"]) * team_scale_factor(ts, d.get("team_scale_aggro", 0))
    out["cohesion_weight"] = float(d["cohesion_weight"]) * team_scale_factor(ts, d.get("team_scale_cohesion", 0))
    out["fear_close_mult"] = float(d["fear_close_mult"]) * team_scale_factor(ts, d.get("team_scale_fear", 0))
    out["pack_hunt_mult"] = float(d["pack_hunt_mult"]) * team_scale_factor(ts, d.get("team_scale_pack", 0))
    out["target_lock_ttl"] = int(d["target_lock_ttl"])
    out["scatter_threshold"] = int(d["scatter_threshold"])
    out["small_unit_threshold"] = int(d.get("small_unit_threshold", 3))
    out["prey_reserve"] = int(d.get("prey_reserve", 3))
    out["late_count_threshold"] = int(d.get("late_count_threshold", 2))
    out["fort_cover_weight"] = max(0.4, min(1.8, float(d.get("fort_cover_weight", 1.0))))
    out["fort_hide_bias"] = max(0.4, min(1.8, float(d.get("fort_hide_bias", 1.0))))
    out["fort_ambush_bonus"] = max(0.3, min(1.5, float(d.get("fort_ambush_bonus", 0.85))))
    out["_team_size"] = ts
    out["_is_small_unit"] = False
    out["_near_wipe"] = False
    out["_game_state"] = "CONTESTED"
    wipe_th = int(d.get("near_wipe_threshold", 2))
    out["near_wipe_threshold"] = wipe_th
    if self_count is not None and self_count <= out["small_unit_threshold"]:
        out["_is_small_unit"] = True
        out["near_target_aggro"] *= d.get("small_aggro_mult", 1.0)
        out["escape_bonus"] = float(d["escape_bonus"]) * d.get("small_escape_mult", 1.0)
        out["_game_state"] = "SMALL_UNIT"
    if fear_count is not None and prey_count is not None:
        if fear_count <= 0 and prey_count > 0:
            out["_game_state"] = "CLEAR_HUNT"
            m = max(1.4, float(d.get("state_clear_hunt", 2.0)))
            cf = max(2.2, float(d.get("clear_finish_mult", 2.2)))
            out["prey_reserve"] = 0
            out["prey_reserve_penalty"] = 1.0
            out["finish_bonus"] = max(1.4, float(d["finish_bonus"])) * m
            out["near_target_aggro"] = max(2.2, float(d["near_target_aggro"])) * m * (0.45 + 0.2 * cf)
            out["clear_finish_mult"] = cf * m
            out["focus_bonus"] = max(float(d.get("focus_bonus", 1.0)), 1.4) * m
            out["target_lock_bonus"] = max(float(d.get("target_lock_bonus", 1.4)), 1.7)
            out["pack_hunt_mult"] = max(0.2, float(d.get("pack_hunt_mult", 1.0)) * 0.35)
            out["cohesion_weight"] = 0.0
            out["speed_match_weight"] = 0.0
            out["clear_spread_weight"] = 1.0
            out["voronoi_weight"] = 1.0
            out["voronoi_balance"] = 1.0
            out["clear_voronoi_cap_slack"] = 0
            out["fort_cover_weight"] = min(out["fort_cover_weight"], 0.3)
            out["hide_among_prey_weight"] = 0.0
        elif fear_count > 0 and prey_count <= 0:
            out["_game_state"] = "NO_PREY_FEAR_ALIVE"
            m = float(d.get("state_no_prey_fear", 0.2))
            out["finish_bonus"] = float(d["finish_bonus"]) * m
            out["near_target_aggro"] *= m
            out["hide_among_prey_weight"] = 0.0
        elif fear_count > 0 and prey_count <= max(3, out["prey_reserve"]):
            out["_game_state"] = "LAST_PREY_RISK"
            # caution: 3 left → 1/3, 2 left → 2/3, 1 left → 1
            left = max(1, min(3, int(prey_count)))
            caution = (4.0 - left) / 3.0
            out["_last_meal_caution"] = caution
            out["_prey_left"] = int(prey_count)
            out["finish_bonus"] = float(out["finish_bonus"]) * max(0.0, 1.0 - 0.95 * caution)
            out["near_target_aggro"] = float(out["near_target_aggro"]) * max(0.06, 1.0 - 0.88 * caution)
            out["pack_hunt_mult"] = float(out.get("pack_hunt_mult", 1.0)) * max(0.08, 1.0 - 0.85 * caution)
            out["clear_finish_mult"] = float(out.get("clear_finish_mult", 1.0)) * max(0.05, 1.0 - 0.9 * caution)
            out["focus_fire_mult"] = float(out.get("focus_fire_mult", 1.0)) * max(0.15, 1.0 - 0.8 * caution)
            out["prey_reserve_penalty"] = max(0.0, 1.0 - caution)
            out["no_corner_herd"] = max(float(d.get("no_corner_herd", 1.0)), 1.0) * (1.0 + 0.8 * caution)
            out["open_field_bias"] = max(float(d.get("open_field_bias", 0.7)), 0.7) * (1.0 + 0.4 * caution)
            out["escape_bonus"] = float(out.get("escape_bonus", 1.0)) * (1.0 + 0.45 * caution)
            out["fort_cover_weight"] = min(1.8, float(out.get("fort_cover_weight", 1.0)) * (1.0 + 0.35 * caution))
        elif self_count is not None and fear_count > self_count:
            out["_game_state"] = "OUTNUMBERED"
            m = float(d.get("state_outnumbered", 1.25))
            out["escape_bonus"] = float(d["escape_bonus"]) * m
            out["fear_close_mult"] *= m
            out["hide_among_prey_weight"] = min(2.2, float(out.get("hide_among_prey_weight", 1.0)) * 1.25)
        else:
            out["_game_state"] = "CONTESTED"
            out["near_target_aggro"] *= float(d.get("state_contested", 1.0))
    if (self_count is not None and self_count == 1
            and (fear_count is None or fear_count > 0)
            and out.get("_game_state") != "CLEAR_HUNT"):
        out["_near_wipe"] = True
        out["_last_man"] = True
        out["_game_state"] = "LAST_MAN"
        nw = float(d.get("state_near_wipe", 1.35))
        out["cohesion_weight"] = 0.0
        out["escape_bonus"] = float(d["escape_bonus"]) * float(d.get("near_wipe_evade_mult", 1.6)) * nw * 1.15
        out["fear_close_mult"] = float(out["fear_close_mult"]) * float(d.get("near_wipe_evade_mult", 1.6))
        out["sep_distance"] = float(d.get("sep_distance", 5.0)) * float(d.get("near_wipe_sep_mult", 2.2))
        out["fort_cover_weight"] = min(1.8, float(out.get("fort_cover_weight", 1.0)) * float(d.get("near_wipe_fort_mult", 1.5)))
        out["fort_hide_bias"] = min(1.8, float(out.get("fort_hide_bias", 1.0)) * float(d.get("near_wipe_fort_mult", 1.5)))
        out["pack_hunt_mult"] = max(0.1, float(out.get("pack_hunt_mult", 1.0)) * 0.1)
        out["near_target_aggro"] = float(out["near_target_aggro"]) * 0.25
        return out
    if (self_count is not None and self_count <= wipe_th
            and (fear_count is None or fear_count > 0)
            and out.get("_game_state") != "CLEAR_HUNT"):
        out["_near_wipe"] = True
        out["_game_state"] = "NEAR_WIPE"
        nw = float(d.get("state_near_wipe", 1.35))
        out["cohesion_weight"] = float(d.get("near_wipe_cohesion", 0.0))
        out["escape_bonus"] = float(d["escape_bonus"]) * float(d.get("near_wipe_evade_mult", 1.6)) * nw
        out["fear_close_mult"] = float(out["fear_close_mult"]) * float(d.get("near_wipe_evade_mult", 1.6))
        out["sep_distance"] = float(d.get("sep_distance", 5.0)) * float(d.get("near_wipe_sep_mult", 2.2))
        out["fort_cover_weight"] = min(1.8, float(out.get("fort_cover_weight", 1.0)) * float(d.get("near_wipe_fort_mult", 1.5)))
        out["fort_hide_bias"] = min(1.8, float(out.get("fort_hide_bias", 1.0)) * float(d.get("near_wipe_fort_mult", 1.5)))
        out["hide_among_prey_weight"] = min(2.2, float(out.get("hide_among_prey_weight", 1.0)) * 1.35)
        out["pack_hunt_mult"] = max(0.1, float(out.get("pack_hunt_mult", 1.0)) * 0.15)
        out["near_target_aggro"] = float(out["near_target_aggro"]) * 0.4
    return out


SECTOR_CENTRES = {
    TurnRelative.FRONT: 0.0,
    TurnRelative.LEFT: -math.radians(30),
    TurnRelative.RIGHT: math.radians(30),
    TurnRelative.LEFT30: -math.radians(60),
    TurnRelative.RIGHT30: math.radians(60),
    TurnRelative.LEFT60: -math.radians(90),
    TurnRelative.RIGHT60: math.radians(90),
    TurnRelative.LEFT90: -math.radians(120),
    TurnRelative.RIGHT90: math.radians(120),
    TurnRelative.LEFT135: -math.radians(150),
    TurnRelative.RIGHT135: math.radians(150),
    TurnRelative.BACK: math.pi,
}
ALL_VISION_DIRS = list(TurnRelative)
# Reduced sector set for non-urgent AI (much cheaper)
FAST_VISION_DIRS = [
    TurnRelative.FRONT, TurnRelative.LEFT, TurnRelative.RIGHT,
    TurnRelative.LEFT60, TurnRelative.RIGHT60, TurnRelative.BACK,
]

# Full 360° coverage in 30° sectors (BACK wraps across ±π)
Config.SECTOR_BOUNDS = {
    TurnRelative.FRONT:   (-math.radians(15),  math.radians(15)),
    TurnRelative.LEFT:    (-math.radians(45), -math.radians(15)),
    TurnRelative.RIGHT:   ( math.radians(15),  math.radians(45)),
    TurnRelative.LEFT30:  (-math.radians(75), -math.radians(45)),
    TurnRelative.RIGHT30: ( math.radians(45),  math.radians(75)),
    TurnRelative.LEFT60:  (-math.radians(105),-math.radians(75)),
    TurnRelative.RIGHT60: ( math.radians(75),  math.radians(105)),
    TurnRelative.LEFT90:  (-math.radians(135),-math.radians(105)),
    TurnRelative.RIGHT90: ( math.radians(105), math.radians(135)),
    TurnRelative.LEFT135: (-math.radians(165),-math.radians(135)),
    TurnRelative.RIGHT135:( math.radians(135), math.radians(165)),
    TurnRelative.BACK:    ( math.radians(165), math.radians(180)),  # + wrap handled in find
}


# ---------------------------------------------------------------------------
# Surface cache – never allocate Surfaces in the per-frame hot path
