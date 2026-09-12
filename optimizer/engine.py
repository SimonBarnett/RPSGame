"""
Strategy optimiser for Rock / Paper / Scissors.

Reads metrics CSVs, runs replicator / strategy-island GA / MAP-Elites /
coevolutionary play / PSO. Learned knobs persist into
strategies/types/{TYPE}/{ID}.json via playbook overlays.

Imported by particle.py — do not import particle at module level
(particle imports this file).
"""

import math
import os
import random
import datetime
from optimizer.paths import log_path

from config import (
    TYPE_DEFAULTS, STRATEGY_KEYS, STRATEGY_BOUNDS,
    effective_strategy, REF_TEAM_SIZE,
)


def _config():
    """Late import from config.py."""
    from config import Config
    return Config


# ---------------------------------------------------------------------------
# Strategy optimiser – reads metrics history and nudges Config
# ---------------------------------------------------------------------------
class StrategyOptimizer:
    """
    Loads metrics_games.csv, measures type win imbalance + game length,
    then adjusts Config knobs toward more balanced, decisive matches.
    """

    MIN_GAMES = 1
    MIN_GAMES_GA = 8
    LEARN_EVERY_HEAVY = 10        # GA/PSO/mutation only every N finished games
    LOG_FILE = log_path('metrics_optimize.log')
    GAMES_CSV = 'metrics_games.csv'
    CONV_CSV = 'metrics_conversions.csv'

    BOUNDS = {
        'NEAR_TARGET_AGGRO': (1.4, 3.2, 0.12),
        'FINISH_BONUS': (0.6, 1.8, 0.08),
        'CLUSTER_BONUS': (0.4, 1.5, 0.08),
        'FEAR_CLOSE_MULT': (1.3, 2.8, 0.10),
        'ESCAPE_BONUS_WEIGHT': (0.35, 1.0, 0.06),
        'COHESION_WEIGHT': (0.25, 0.85, 0.05),
        'PACK_HUNT_MULT': (1.2, 2.6, 0.10),
        'FOCUS_TARGET_BONUS': (0.4, 1.2, 0.06),
        'TARGET_LOCK_TTL': (25, 70, 4),
        'TARGET_SWITCH_MARGIN': (1.15, 1.8, 0.05),
        'HUNT_ADVANTAGE': (0.9, 1.5, 0.05),
        'SCATTER_COUNT_THRESHOLD': (2, 6, 1),
        'VISION_FAR': (22.0, 40.0, 1.0),
        'FEAR_POP_SCALE': (0.3, 0.8, 0.05),
        'SUPPORT_JOIN_BONUS': (0.3, 0.9, 0.05),
        'FOCUS_FIRE_MULT': (1.2, 2.0, 0.08),
    }

    def __init__(self):
        self.last_changes = []
        self.games_seen = 0
        self._ga_pop = None          # legacy type-wide (unused)
        self._ga_fitness = None
        self._ga_gen = 0
        self._ga_best = {}           # {type: (fitness, genome)}
        self._ga_islands = None      # {(type, sid): {pop, fit, tun, bounds}}
        self._map_elites = {}        # {niche: {fitness, type, sid, genome, visits}}
        self._coevo_payoff = {}      # {(wt,ws,lt,ls): {for, against, games}}
        # PSO state
        self._pso_pos = None         # {type: [pos dict, ...]}
        self._pso_vel = None         # {type: [vel dict, ...]}
        self._pso_pbest = None       # {type: [pos dict, ...]}
        self._pso_pbest_f = None     # {type: [float, ...]}
        self._pso_gbest = None       # {type: pos dict}
        self._pso_gbest_f = None     # {type: float}
        self._pso_gen = 0
        self._pso_gbest_f_prev = {}  # for stagnation detection
        self._pso_stag_count = {}    # gens since last gbest improve per type
        self._simplex = {'ROCK': 1.0 / 3.0, 'PAPER': 1.0 / 3.0, 'SCISSORS': 1.0 / 3.0}
        self._load_simplex()

    def _metrics_path(self, filename):
        """Resolve a metrics CSV in optimizer/metrics/, then older locations."""
        import os
        from optimizer.paths import log_path, METRICS, ROOT
        if os.path.isabs(filename):
            return filename
        here = os.path.dirname(os.path.abspath(__file__))
        tried = [
            os.path.join(METRICS, filename),
            os.path.join(here, filename),
            os.path.join(os.getcwd(), 'optimizer', 'metrics', filename),
            os.path.join(os.getcwd(), filename),
            os.path.join(os.getcwd(), 'optimizer', filename),
        ]
        try:
            import config as _tc
            tried.append(os.path.join(os.path.dirname(os.path.abspath(_tc.__file__)), filename))
        except Exception:
            pass
        seen = set()
        for path in tried:
            path = os.path.normpath(path)
            if path in seen:
                continue
            seen.add(path)
            if os.path.exists(path):
                return path
        return log_path(filename)

    def _tail_csv_lines(self, path, window, byte_window=250000):
        """Header + last `window` rows without reading the whole NAS file."""
        import os
        if not path or not os.path.exists(path):
            return [], []
        try:
            with open(path, 'rb') as f:
                header_line = f.readline().decode('utf-8', 'ignore').strip()
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - int(byte_window)), 0)
                raw = f.read().decode('utf-8', 'ignore')
        except Exception:
            return [], []
        headers = [h.strip() for h in header_line.split(',') if h.strip()]
        lines = raw.strip().split('\n')
        if not lines:
            return headers, []
        if headers and lines[0].split(',')[0] != headers[0]:
            lines = lines[1:]
        elif headers and lines[0].split(',')[0] == headers[0]:
            lines = lines[1:]
        return headers, lines[-int(window):]

    def _load_games(self):
        path = self._metrics_path(StrategyOptimizer.GAMES_CSV)
        window = max(50, int(self.SAMPLE_WINDOW))
        headers, lines = self._tail_csv_lines(path, window, byte_window=400000)
        games = []
        for line in lines:
            parts = line.split(',')
            if len(parts) < 6:
                continue
            g = dict(zip(headers, parts)) if headers else {}
            if not g:
                continue
            try:
                g['_duration'] = float(g.get('duration_s', 0))
                g['_conversions'] = int(float(g.get('total_conversions', 0)))
                g['endgame_seconds'] = float(g.get('endgame_seconds', 0) or 0)
                g['endgame_frames'] = float(g.get('endgame_frames', 0) or 0)
            except Exception:
                continue
            games.append(g)
        return games

    def _overlay_eligible(self, used, ov, min_used=8, min_games=4):
        """Played this match enough, or a lifetime card that showed up at all."""
        u = int(used or 0)
        st = (ov or {}).get('stats') or {}
        life = int(st.get('ticks') or 0)
        games = int(st.get('games') or 0)
        sid = str((ov or {}).get('id') or '')
        if sid in self._CARE_SIDS:
            min_used = 1
        else:
            try:
                states = list(((ov or {}).get('when') or {}).get('states') or [])
                primary = str(states[0]).upper() if states else ''
                if primary in (
                        'LAST_PREY_RISK', 'LAST_MAN', 'NO_PREY_FEAR_ALIVE',
                        'NEAR_WIPE', 'OUTNUMBERED'):
                    min_used = 1
            except Exception:
                pass
        return u >= int(min_used) or (u >= 1 and (life >= 60 or games >= int(min_games)))

    def _overlay_dom_state(self, tname, sid, ov=None):
        """State this card occupied most this match, else its primary when.states."""
        metrics = getattr(getattr(self, 'w', None), 'metrics', None)
        bag = {}
        if metrics is not None:
            bag = ((getattr(metrics, 'strategy_state_ticks', {}) or {}).get(tname) or {}).get(sid) or {}
        if isinstance(bag, dict) and bag:
            try:
                return str(max(bag.items(), key=lambda kv: int(kv[1] or 0))[0]).upper()
            except Exception:
                pass
        if ov:
            return self._map_state_for(ov)
        return 'CONTESTED'


    def _adaptive_learning_rates(self, fitness, f_bar, share=None):
        """
        Per-type learning-rate multipliers for this generation.
        Combines payoff-convergence status, fitness pressure, ΔF trend,
        and bound-saturation. Returns (lr_by_type, meta_dict).
        """
        types = ('ROCK', 'PAPER', 'SCISSORS')
        base = float(getattr(self, 'LR_BASE', 1.0))
        lo = float(getattr(self, 'LR_MIN', 0.35))
        hi = float(getattr(self, 'LR_MAX', 2.2))
        status_mults = getattr(self, 'LR_STATUS_MULT', {}) or {}
        conv = getattr(self, '_last_payoff_convergence', None) or {}
        status = conv.get('status', 'TRANSITIONAL')
        status_m = float(status_mults.get(status, 1.0))
        delta_mean = float(conv.get('delta_mean16', 0.0) or 0.0)
        efit_spread = float(conv.get('efit_spread', 0.0) or 0.0)
        # Global factor from matrix motion + imbalance
        global_m = status_m
        # High matrix motion → allow slightly larger steps; very low → shrink
        if delta_mean > 0.25:
            global_m *= 1.0 + min(0.5, float(getattr(self, 'LR_DELTA_GAIN', 0.9)) * (delta_mean - 0.25))
        elif delta_mean < 0.06 and status in ('SETTLING', 'CYCLE_OK'):
            global_m *= 0.85
        if efit_spread > 0.35:
            global_m *= 1.15  # uneven efit — push harder toward balance

        lr = {}
        sat_frac = {}
        for t in types:
            pressure = abs(float(fitness.get(t, 0.0)) - float(f_bar))
            # pressure term: 0 → ~0.75x, 0.2 → ~1.35x
            p_gain = float(getattr(self, 'LR_PRESSURE_GAIN', 1.8))
            p_m = 0.75 + p_gain * min(0.35, pressure)
            # Bound saturation on played overlay tunables, not TYPE_DEFAULTS.
            sat = 0.0
            try:
                import strategies.playbook as _pb
                metrics = getattr(getattr(self, 'w', None), 'metrics', None)
                used = {}
                if metrics is not None:
                    used = (getattr(metrics, 'strategy_ticks', {}) or {}).get(t) or {}
                n_keys = 0
                n_sat = 0
                for sid, ov in (_pb.TEAM_OVERLAYS.get(t) or {}).items():
                    if not self._overlay_eligible(used.get(sid, 0), ov):
                        continue
                    tun = _pb.tunables_for(t, sid) or {}
                    wts = dict(ov.get('weights') or {})
                    for path, bounds in tun.items():
                        if str(path).startswith('switch.') or str(path).startswith('when.') or str(path).startswith('movement['):
                            continue
                        if not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
                            continue
                        v = wts.get(path)
                        if v is None:
                            continue
                        try:
                            v = float(v)
                            blo, bhi = float(bounds[0]), float(bounds[1])
                        except Exception:
                            continue
                        n_keys += 1
                        span = max(1e-9, bhi - blo)
                        if (v - blo) / span <= 0.02 or (bhi - v) / span <= 0.02:
                            n_sat += 1
                sat = (n_sat / n_keys) if n_keys else 0.0
            except Exception:
                sat = 0.0
            sat_frac[t] = round(sat, 3)
            sat_m = 1.0
            if sat > 0.35:
                sat_m = float(getattr(self, 'LR_BOUND_SAT_MULT', 0.55)) + (1.0 - float(getattr(self, 'LR_BOUND_SAT_MULT', 0.55))) * (1.0 - min(1.0, sat))
            # Share: very rare types get a mild boost to recover
            sh_m = 1.0
            if share is not None:
                sh = float(share.get(t, 0.33))
                if sh < 0.18:
                    sh_m = 1.2
                elif sh > 0.45:
                    sh_m = 0.9
            val = base * global_m * p_m * sat_m * sh_m
            lr[t] = max(lo, min(hi, val))

        meta = {
            'status': status,
            'status_m': round(status_m, 3),
            'global_m': round(global_m, 3),
            'delta_mean16': round(delta_mean, 4),
            'efit_spread': round(efit_spread, 4),
            'sat_frac': sat_frac,
            'lr': {t: round(lr[t], 3) for t in types},
        }
        self._last_lr = lr
        self._last_lr_meta = meta
        return lr, meta


    def _nudge_type(self, type_name, key, direction, reason, strength=1.0):
        """Nudge a per-type strategy key; strength scales step (replicator weight)."""
        # Type identity (prey/fear/colour) stays frozen. speed/turn live on
        # strategy.base and may be tuned when that strategy lists them.
        if getattr(self, 'SINGLE_KNOB_WRITER', True):
            return
        if key in ('strength_range', 'agility_range',
                   'bravery_range', 'prey', 'fear', 'display_name', 'icon', 'color'):
            return
        lo = hi = step = None
        sid = None
        try:
            import strategies.playbook as playbook
            ww = getattr(self, 'w', None)
            if ww is not None:
                from config import ParticleType
                team = ww.teams.get(getattr(ParticleType, type_name, None))
                sid = getattr(team, 'strategy_id', None) if team is not None else None
            if sid:
                b = playbook.strategy_bounds(type_name, sid, key)
                if b:
                    lo, hi, step = b
        except Exception:
            sid = None
        if lo is None:
            if key not in STRATEGY_BOUNDS or type_name not in TYPE_DEFAULTS:
                return
            lo, hi, step = STRATEGY_BOUNDS[key]
        cur = TYPE_DEFAULTS[type_name].get(key)
        if cur is None:
            return
        try:
            lo, hi, step = float(lo), float(hi), float(step)
            cur_f = float(cur)
        except Exception:
            return
        # Replicator: step size proportional to |fitness advantage| × adaptive LR
        mag = max(0.25, min(3.0, abs(float(strength))))
        lr_map = getattr(self, '_last_lr', None) or {}
        lr = float(lr_map.get(type_name, 1.0))
        # Mutations use sqrt(lr) so exploration shrinks slower than selection
        if isinstance(reason, str) and reason.startswith('mutation'):
            lr = lr ** 0.5
        mag = max(0.15, min(3.5, mag * lr))
        delta = direction * step * mag
        new = cur_f + delta
        if isinstance(cur, int) or key in (
            'target_lock_ttl', 'scatter_threshold', 'prey_reserve',
            'small_unit_threshold', 'late_count_threshold',
            'clear_split_threshold', 'voronoi_recompute_interval',
            'voronoi_overflow_threshold', 'clear_voronoi_cap_slack',
            'delaunay_k', 'pincer_min_friends', 'pincer_switch_cooldown',
            'overcrowd_threshold', 'near_wipe_threshold'):
            new = int(round(new))
        new = max(lo, min(hi, new))
        # Absolute safety clamp — never allow negative combat or runaway values
        ABS = {
            'near_target_aggro': (1.0, 4.5), 'finish_bonus': (0.3, 2.5),
            'cluster_bonus': (0.2, 2.2), 'pack_hunt_mult': (0.5, 3.5),
            'clear_finish_mult': (1.2, 4.0), 'focus_bonus': (0.25, 1.8),
            'focus_fire_mult': (1.0, 2.6), 'small_raid_bonus': (1.0, 3.0),
            'solo_finish_mult': (1.0, 3.0), 'small_aggro_mult': (0.8, 1.8),
            'support_join': (0.15, 1.2), 'hunt_advantage': (0.7, 1.8),
            'flank_bias': (0.2, 1.4), 'state_clear_hunt': (0.8, 2.8),
            'predict_lookahead': (4.0, 28.0), 'avoid_lookahead': (5.0, 40.0),
            'sep_distance': (1.2, 10.0), 'target_lock_ttl': (12, 120),
            'fear_close_mult': (1.0, 3.8), 'escape_bonus': (0.2, 1.5),
            'cohesion_weight': (0.1, 1.1), 'outnumbered_fear_mult': (1.0, 2.8),
        }
        if key in ABS:
            alo, ahi = ABS[key]
            new = max(alo, min(ahi, new))
        if abs(new - cur_f) < abs(step) * 0.05:
            return
        TYPE_DEFAULTS[type_name][key] = new
        try:
            import strategies.playbook as playbook
            sid = None
            ww = getattr(self, 'w', None)
            if ww is not None:
                from config import ParticleType
                team = ww.teams.get(getattr(ParticleType, type_name, None))
                sid = getattr(team, 'strategy_id', None) if team is not None else None
            playbook.apply_learned(type_name, key, new)
            if sid:
                playbook.nudge_weight(type_name, sid, key, new)
        except Exception:
            pass
        self.last_changes.append(
            f'{type_name}.{key}: {cur} -> {new}  ({reason}, w={mag:.2f})'
        )

    def _nudge_global(self, attr, direction, reason):
        if attr not in self.BOUNDS:
            return
        lo, hi, step = self.BOUNDS[attr]
        cur = getattr(_config(), attr, None)
        if cur is None:
            return
        new = cur + direction * step
        if isinstance(cur, int):
            new = int(round(new))
        new = max(lo, min(hi, new))
        if new == cur:
            return
        setattr(_config(), attr, new)
        self.last_changes.append(f'Config.{attr}: {cur} -> {new}  ({reason})')


    # Larger sample window for stable signal; bounds drift slowly across generations
    SAMPLE_WINDOW = 80
    BOUND_EXPAND = 0.015         # slow expand only
    BOUND_CONTRACT = 0.01
    BOUND_MAX_SPAN_MULT = 2.5    # never expand beyond 2.5x original span from HARD floors
    GENERATION = 0
    # Evolutionary noise: small trait mutation each generation (EGT exploration)
    MUTATION_RATE = 0.12         # fraction of STRATEGY_KEYS mutated per type per pass
    MUTATION_STRENGTH = 0.35     # relative to bound step (keep << selection strength)
    MUTATION_MIN_KEYS = 2        # at least this many keys per type
    # --- Genetic algorithm (per-type × per-strategy islands) ---
    GA_ENABLED = True
    GA_POP_SIZE = 6              # clones per (type, strategy) island
    GA_ELITE = 1                 # keep island champion
    GA_TOURNAMENT_K = 3
    GA_CROSSOVER_RATE = 0.7
    GA_MUTATION_RATE = 0.14      # per-gene mutation probability
    GA_MUTATION_SIGMA = 0.45     # fraction of bound step for Gaussian noise
    GA_BLEND_ALPHA = 0.35        # blend crossover weight toward fitter parent
    GA_DEPLOY_ELITE = False      # islands are unevaluated — archive only, do not write overlays
    GA_CROSS_TYPE = True         # coevolve: same strategy_id may breed across types
    GA_CROSS_TYPE_RATE = 0.22
    GA_MAX_ISLANDS = 36          # cap work per pass (3 types × top used cards)
    # --- MAP-Elites ---
    MAP_ELITES_ENABLED = True
    MAP_TEAM_BUCKETS = (8, 12, 16, 24)  # teamSize upper edges
    # --- Coevolutionary play (surrogate from conversion matchups) ---
    COEVO_ENABLED = True
    COEVO_WINDOW = 400           # recent conversion rows
    COEVO_WEIGHT = 0.22          # mix into strategy fitness
    # --- Particle Swarm Optimization (per-type swarms) ---
    PSO_ENABLED = False          # deferred 100-D swarm never evaluates non-deployed particles
    PSO_SWARM_SIZE = 12          # particles per type
    PSO_W_MAX = 0.9              # inertia start (explore)
    PSO_W_MIN = 0.35             # inertia floor (exploit) — slightly lower for high-D polish
    PSO_W_DECAY_GENS = 50        # horizon for scheduled decay
    # Schedule: "cosine" (default) | "linear" | "exp" | "sigmoid" | "adaptive"
    # cosine: slow early drop, faster mid, soft landing — good for ~100-D STRATEGY_KEYS
    # adaptive: cosine base + raise w on gbest stagnation / low swarm diversity
    PSO_W_SCHEDULE = "adaptive"
    PSO_W_EXP_K = 4.0            # exp curve steepness (higher = faster early drop)
    PSO_W_SIGMOID_K = 10.0       # sigmoid steepness around midpoint
    PSO_W_STAGNATION_GENS = 5    # adaptive: gens without gbest improve → boost w
    PSO_W_STAG_BOOST = 0.12      # adaptive: add to w when stagnating (clamped to W_MAX)
    PSO_W_DIVERSITY_BOOST = 0.08 # adaptive: add when swarm spread is low
    # Cognitive / social (scheduled). c1 decays, c2 grows over PSO_W_DECAY_GENS.
    PSO_C1 = 1.8                 # fallback if schedule=fixed
    PSO_C2 = 1.3                 # fallback if schedule=fixed (cognitive-biased)
    PSO_C1_MAX = 2.0             # early cognitive (self-best)
    PSO_C1_MIN = 1.2             # late cognitive
    PSO_C2_MIN = 1.2             # early social
    PSO_C2_MAX = 2.0             # late social (swarm-best)
    PSO_C_SCHEDULE = "adaptive"  # linear | cosine | fixed | adaptive
    PSO_C_STAG_C1_BOOST = 0.25   # adaptive: extra c1 when gbest stagnates
    PSO_C_STAG_C2_CUT = 0.20     # adaptive: reduce c2 when stagnating
    PSO_C_DIV_C1_BOOST = 0.15    # adaptive: extra c1 when diversity collapses
    PSO_USE_CONSTRICTION = False # Clerc χ≈0.729; uses φ = c1+c2 (or 4.1)
    PSO_CHI = 0.729843788128     # 2/|2-φ-sqrt(φ(φ-2))| at φ=4.1
    PSO_VMAX_FRAC = 0.2          # |v| ≤ frac * (hi-lo) per dim
    PSO_REINIT_FRAC = 0.08       # chance worst particle re-spawns
    PSO_DEPLOY_GBEST = False     # do not write unevaluated swarm gbest
    SINGLE_KNOB_WRITER = True    # one of GP-EI / playbook per generation; no replicator spray
    EXTRA_KNOB_WRITERS = False   # last-man / strike / ally / threat / unherd type-wide nudges
    BO_MAX_PER_TYPE = 2          # EI writes at most this many played cards per type
    PAYOFF_CSV = log_path('metrics_payoff.csv')
    # Adaptive learning rates (selection + mutation scaled each generation)
    LR_BASE = 1.0
    LR_MIN = 0.35
    LR_MAX = 2.2
    LR_STATUS_MULT = {
        'SETTLING': 0.55,      # fine-tune near equilibrium
        'CYCLE_OK': 0.85,      # healthy cycle — modest steps
        'TRANSITIONAL': 1.15,  # still moving
        'HIERARCHY': 1.55,     # escape lock-in
        'CYCLE_REV': 1.25,     # wrong orientation — push harder
        'SPARSE': 0.50,        # avoid chasing noise
    }
    LR_PRESSURE_GAIN = 1.8       # extra scale from |f_i - f_bar|
    LR_DELTA_GAIN = 0.9          # if Δmean16 high, allow larger steps
    LR_BOUND_SAT_MULT = 0.55     # type with many keys at bounds → slower selection


    def _load_conversion_rows(self, limit=None):
        import os
        path = self._metrics_path(getattr(self, 'CONV_CSV', 'metrics_conversions.csv'))
        rows = []
        window = limit or max(50, self.SAMPLE_WINDOW * 15)
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    header_line = f.readline().decode('utf-8', 'ignore').strip()
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - 700000), 0)
                    raw = f.read().decode('utf-8', 'ignore')
                headers = [h.strip() for h in header_line.split(',') if h.strip()]
                lines = raw.strip().split('\n')
                if lines and headers and lines[0].split(',')[0] != headers[0]:
                    lines = lines[1:]
                for line in lines[-window:]:
                    parts = line.split(',')
                    if len(parts) < 6:
                        continue
                    rows.append(dict(zip(headers, parts)))
            except Exception as e:
                self._log_raw(f'payoff: conversions read failed: {e}')
        metrics = getattr(getattr(self, 'w', None), 'metrics', None)
        if metrics is not None and getattr(metrics, 'conversions', None):
            for c in metrics.conversions[-window:]:
                if isinstance(c, dict):
                    rows.append(c)
        return rows

    def _payoff_from_rows(self, rows):
        types = ('ROCK', 'PAPER', 'SCISSORS')
        A = {a: {b: 0.0 for b in types} for a in types}
        counts = {a: {b: 0 for b in types} for a in types}
        for row in rows:
            w = row.get('winner_type') or row.get('winner') or ''
            lose = (row.get('loser_was') or row.get('loser_type_before') or row.get('loser_type') or row.get('loser') or '')
            if hasattr(w, 'name'):
                w = w.name
            if hasattr(lose, 'name'):
                lose = lose.name
            w, lose = str(w).upper(), str(lose).upper()
            if w not in types or lose not in types or w == lose:
                continue
            # row player w scores +1 against lose; lose scores -1 against w
            A[w][lose] += 1.0
            A[lose][w] -= 1.0
            counts[w][lose] += 1
            counts[lose][w] += 1
        # Average
        for a in types:
            for b in types:
                if a == b:
                    A[a][b] = 0.0
                elif counts[a][b] > 0:
                    A[a][b] = A[a][b] / counts[a][b]
                else:
                    A[a][b] = 0.0
        # Expected fitness under uniform opponent mix (optional signal)
        e_fit = {}
        for a in types:
            e_fit[a] = sum(A[a][b] for b in types if b != a) / 2.0
        lines = ['empirical payoff A (row vs col), +1=row wins:']
        hdr = '      ' + '  '.join(f'{t:>8}' for t in types)
        lines.append(hdr)
        for a in types:
            lines.append(f'{a:>5} ' + '  '.join(f'{A[a][b]:+8.3f}' for b in types))
        lines.append('counts:')
        for a in types:
            lines.append(f'{a:>5} ' + '  '.join(f'{counts[a][b]:8d}' for b in types))
        lines.append('E[fit|uniform]: ' + ', '.join(f'{t}={e_fit[t]:+.3f}' for t in types))
        summary = '\n'.join(lines)
        return A, counts, e_fit, summary

    def _empirical_payoff_matrix(self, sample_games=None, states=None):
        rows = self._load_conversion_rows()
        if states:
            want = {str(s).upper() for s in states}
            rows = [r for r in rows if str(r.get('game_state') or '').upper() in want]
        return self._payoff_from_rows(rows)

    def _state_payoff_bundle(self):
        rows = self._load_conversion_rows()
        buckets = {
            'ALL': rows,
            'CONTESTED': [r for r in rows if str(r.get('game_state') or '') in
                          ('CONTESTED', 'OUTNUMBERED', '')],
            'CARE': [r for r in rows if str(r.get('game_state') or '') in
                     ('LAST_PREY_RISK', 'NO_PREY_FEAR_ALIVE', 'NEAR_WIPE')],
            'CLEAR': [r for r in rows if str(r.get('game_state') or '') == 'CLEAR_HUNT'],
        }
        out = {}
        for name, bag in buckets.items():
            A, counts, e_fit, summary = self._payoff_from_rows(bag)
            n = sum(sum(v.values()) for v in counts.values()) // 2
            pr = float(A['PAPER']['ROCK'])
            sp = float(A['SCISSORS']['PAPER'])
            rs = float(A['ROCK']['SCISSORS'])
            cycle_ok = (pr > 0) + (sp > 0) + (rs > 0)
            out[name] = {
                'A': A, 'counts': counts, 'e_fit': e_fit, 'summary': summary,
                'n': n, 'signs': (pr, sp, rs), 'cycle_ok': cycle_ok,
            }
            self._log_raw(
                'A_%s n=%d cycle=%d/3 P>R=%+.2f S>P=%+.2f R>S=%+.2f' % (
                    name, n, cycle_ok, pr, sp, rs))
        self._last_state_A = out
        return out

    def _match_payoff_matrix(self, sample_games):
        """A from match winners. Conversion A is ±1 by RPS rule, so uninformative."""
        types = ('ROCK', 'PAPER', 'SCISSORS')
        A = {a: {b: 0.0 for b in types} for a in types}
        counts = {a: {b: 0 for b in types} for a in types}
        for g in sample_games or []:
            w = str(g.get('winner') or '').upper()
            if w not in types:
                continue
            for o in types:
                if o == w:
                    continue
                A[w][o] += 1.0
                A[o][w] -= 1.0
                counts[w][o] += 1
                counts[o][w] += 1
        for a in types:
            for b in types:
                if a == b:
                    A[a][b] = 0.0
                elif counts[a][b] > 0:
                    A[a][b] /= float(counts[a][b])
        pr = float(A['PAPER']['ROCK'])
        sp = float(A['SCISSORS']['PAPER'])
        rs = float(A['ROCK']['SCISSORS'])
        self._log_raw(
            'A_MATCH n=%d cycle=%d/3 P>R=%+.2f S>P=%+.2f R>S=%+.2f' % (
                len(sample_games or []), (pr > 0) + (sp > 0) + (rs > 0), pr, sp, rs))
        self._last_match_A = A
        return A, counts

    def _payoff_convergence_metrics(self, A, counts, e_fit):
        """
        Automated convergence diagnostics for empirical payoff matrix A.
        Returns dict of metrics + human summary line.
        """
        import math
        types = ('ROCK', 'PAPER', 'SCISSORS')
        # Frobenius delta vs previous generation
        prev = getattr(self, '_prev_payoff_A', None)
        delta_f = 0.0
        if prev is not None:
            s = 0.0
            for a in types:
                for b in types:
                    s += (float(A[a][b]) - float(prev.get(a, {}).get(b, 0.0))) ** 2
            delta_f = math.sqrt(s)
        # Antisymmetry error: sum |A_ij + A_ji| over i<j
        anti_err = 0.0
        pairs = (('ROCK', 'PAPER'), ('ROCK', 'SCISSORS'), ('PAPER', 'SCISSORS'))
        for a, b in pairs:
            anti_err += abs(float(A[a][b]) + float(A[b][a]))
        # Cycle strength: R≻S + S≻P + P≻R  (positive => classic RPS orientation)
        cycle = float(A['ROCK']['SCISSORS']) + float(A['SCISSORS']['PAPER']) + float(A['PAPER']['ROCK'])
        # Reverse cycle (wrong orientation)
        cycle_rev = float(A['SCISSORS']['ROCK']) + float(A['PAPER']['SCISSORS']) + float(A['ROCK']['PAPER'])
        # Hierarchy: max over i of min_j≠i A_ij  (>>0 => type beats both others)
        hierarchy = -1e9
        hierarchy_type = ''
        for a in types:
            others = [float(A[a][b]) for b in types if b != a]
            m = min(others) if others else 0.0
            if m > hierarchy:
                hierarchy = m
                hierarchy_type = a
        # Pair coverage
        pair_counts = {
            'RP': int(counts['ROCK']['PAPER']),
            'RS': int(counts['ROCK']['SCISSORS']),
            'PR': int(counts['PAPER']['ROCK']),
            'PS': int(counts['PAPER']['SCISSORS']),
            'SR': int(counts['SCISSORS']['ROCK']),
            'SP': int(counts['SCISSORS']['PAPER']),
        }
        min_n = min(pair_counts.values()) if pair_counts else 0
        total_n = sum(pair_counts.values())
        # efit spread (all near 0 under balanced uniform mix)
        efit_vals = [float(e_fit.get(t, 0.0)) for t in types]
        efit_spread = max(efit_vals) - min(efit_vals) if efit_vals else 0.0
        efit_max = max(efit_vals) if efit_vals else 0.0
        # Rolling delta history for trend
        hist = getattr(self, '_payoff_delta_hist', [])
        hist = list(hist) + [delta_f]
        hist = hist[-16:]  # last 16 generations
        self._payoff_delta_hist = hist
        delta_mean = sum(hist) / len(hist) if hist else 0.0
        # Simple status label
        if total_n < 30:
            status = 'SPARSE'
        elif hierarchy > 0.35 and min_n >= 10:
            status = 'HIERARCHY'
        elif cycle > 0.15 and cycle > cycle_rev:
            status = 'CYCLE_OK'
        elif cycle_rev > 0.15 and cycle_rev > cycle:
            status = 'CYCLE_REV'
        elif delta_f < 0.08 and anti_err < 0.25 and efit_spread < 0.2:
            status = 'SETTLING'
        else:
            status = 'TRANSITIONAL'
        metrics = {
            'delta_f': round(delta_f, 5),
            'delta_mean16': round(delta_mean, 5),
            'anti_err': round(anti_err, 5),
            'cycle': round(cycle, 5),
            'cycle_rev': round(cycle_rev, 5),
            'hierarchy': round(hierarchy, 5),
            'hierarchy_type': hierarchy_type,
            'min_pair_n': min_n,
            'total_pair_n': total_n,
            'efit_spread': round(efit_spread, 5),
            'efit_max': round(efit_max, 5),
            'status': status,
        }
        summary = (
            f"payoff_convergence gen={getattr(self, 'GENERATION', 0)} "
            f"status={status} ΔF={metrics['delta_f']:.4f} Δmean16={metrics['delta_mean16']:.4f} "
            f"anti={metrics['anti_err']:.4f} cycle={metrics['cycle']:+.3f} "
            f"cycle_rev={metrics['cycle_rev']:+.3f} hierarchy={metrics['hierarchy']:+.3f}"
            f"({hierarchy_type}) min_n={min_n} efit_spread={metrics['efit_spread']:.3f}"
        )
        return metrics, summary


    def _nash_mixed(self, A, share=None):
        """Symmetric 3-strategy Nash: exploitability of x, interior p*, ||x-p*||."""
        types = ('ROCK', 'PAPER', 'SCISSORS')
        def matvec(p):
            return {i: sum(float(A[i][j]) * float(p[j]) for j in types) for i in types}
        def exploit(p):
            f = matvec(p)
            avg = sum(f[i] * float(p[i]) for i in types)
            br = max(f.values()) if f else 0.0
            return max(0.0, br - avg), f, avg, br
        # current population share (or uniform)
        x = {k: 1.0/3.0 for k in types}
        if share:
            s = sum(max(0.0, float(share.get(k, 0.0))) for k in types) or 1.0
            x = {k: max(0.0, float(share.get(k, 0.0))) / s for k in types}
        exp_x, f_x, avg_x, br_x = exploit(x)
        # interior equal-fitness: f_R=f_P and f_P=f_S, p sum 1
        # 2x2 on (pP, pS) with pR = 1-pP-pS
        def coeff(i, j):
            return float(A[i][j])
        # f_i - f_k = sum_j (A_ij - A_kj) p_j = 0
        def rowdiff(ia, ib):
            return [coeff(ia, j) - coeff(ib, j) for j in types]
        dRP = rowdiff('ROCK', 'PAPER')
        dPS = rowdiff('PAPER', 'SCISSORS')
        # substitute pR = 1-pP-pS
        # d0*pR + d1*pP + d2*pS = 0
        # d0 + (d1-d0)pP + (d2-d0)pS = 0
        def reduce(d):
            return (d[1]-d[0], d[2]-d[0], -d[0])
        a11, a12, b1 = reduce(dRP)
        a21, a22, b2 = reduce(dPS)
        det = a11*a22 - a12*a21
        p_star = {k: 1.0/3.0 for k in types}
        support = 'interior'
        if abs(det) > 1e-9:
            pP = (b1*a22 - b2*a12) / det
            pS = (a11*b2 - a21*b1) / det
            pR = 1.0 - pP - pS
            cand = {'ROCK': pR, 'PAPER': pP, 'SCISSORS': pS}
            if all(v >= -1e-6 for v in cand.values()):
                tot = sum(max(0.0, v) for v in cand.values()) or 1.0
                p_star = {k: max(0.0, cand[k]) / tot for k in types}
            else:
                support = 'boundary'
                # fall back to uniform (classic RPS Nash) if interior invalid
                p_star = {k: 1.0/3.0 for k in types}
        else:
            support = 'singular'
        exp_star, _, _, _ = exploit(p_star)
        l1 = sum(abs(x[k] - p_star[k]) for k in types)
        l2 = (sum((x[k] - p_star[k])**2 for k in types)) ** 0.5
        return {
            'exploit_share': round(exp_x, 5),
            'exploit_nash': round(exp_star, 5),
            'nash_l1': round(l1, 5),
            'nash_l2': round(l2, 5),
            'nash_p_ROCK': round(p_star['ROCK'], 4),
            'nash_p_PAPER': round(p_star['PAPER'], 4),
            'nash_p_SCISSORS': round(p_star['SCISSORS'], 4),
            'share_ROCK': round(x['ROCK'], 4),
            'share_PAPER': round(x['PAPER'], 4),
            'share_SCISSORS': round(x['SCISSORS'], 4),
            'br_share': round(br_x, 5),
            'avg_share': round(avg_x, 5),
            'support': support,
        }

    def _log_payoff_matrix(self, A, counts, e_fit, summary, share=None):
        """Append payoff snapshot + convergence metrics to log + CSV."""
        import os, datetime, copy
        self._log_raw(summary)
        # Convergence block
        try:
            conv, conv_line = self._payoff_convergence_metrics(A, counts, e_fit)
            self._log_raw(conv_line)
            self._last_payoff_convergence = conv
        except Exception as e:
            conv = {}
            self._log_raw(f'payoff convergence failed: {e}')
        nash = {}
        try:
            nash = self._nash_mixed(A, share=share or getattr(self, '_last_share', None))
            self._last_nash = nash
            self._log_raw(
                f"nash p*=[{nash['nash_p_ROCK']:.3f},{nash['nash_p_PAPER']:.3f},{nash['nash_p_SCISSORS']:.3f}] "
                f"x=[{nash['share_ROCK']:.3f},{nash['share_PAPER']:.3f},{nash['share_SCISSORS']:.3f}] "
                f"||x-p*||_1={nash['nash_l1']:.3f} exploit={nash['exploit_share']:.3f} "
                f"support={nash['support']}"
            )
        except Exception as e:
            self._log_raw(f'nash failed: {e}')
        # Remember A for next generation ΔF
        try:
            self._prev_payoff_A = {a: dict(A[a]) for a in A}
        except Exception:
            self._prev_payoff_A = copy.deepcopy(A)

        path = getattr(self, 'PAYOFF_CSV', 'metrics_payoff.csv')
        types = ('ROCK', 'PAPER', 'SCISSORS')
        header = (
            'timestamp,generation,'
            'A_RR,A_RP,A_RS,A_PR,A_PP,A_PS,A_SR,A_SP,A_SS,'
            'n_RP,n_RS,n_PR,n_PS,n_SR,n_SP,'
            'efit_ROCK,efit_PAPER,efit_SCISSORS,'
            'delta_f,delta_mean16,anti_err,cycle,cycle_rev,'
            'hierarchy,hierarchy_type,min_pair_n,total_pair_n,'
            'efit_spread,efit_max,status,'
            'nash_l1,nash_l2,exploit_share,exploit_nash,'
            'nash_p_ROCK,nash_p_PAPER,nash_p_SCISSORS,nash_support\n'
        )
        need_header = not os.path.exists(path) or os.path.getsize(path) == 0
        # If old header without convergence cols, still append — user can reset CSV
        ts = datetime.datetime.now().isoformat(timespec='seconds')
        gen = getattr(self, 'GENERATION', 0)
        vals = [
            ts, gen,
            A['ROCK']['ROCK'], A['ROCK']['PAPER'], A['ROCK']['SCISSORS'],
            A['PAPER']['ROCK'], A['PAPER']['PAPER'], A['PAPER']['SCISSORS'],
            A['SCISSORS']['ROCK'], A['SCISSORS']['PAPER'], A['SCISSORS']['SCISSORS'],
            counts['ROCK']['PAPER'], counts['ROCK']['SCISSORS'],
            counts['PAPER']['ROCK'], counts['PAPER']['SCISSORS'],
            counts['SCISSORS']['ROCK'], counts['SCISSORS']['PAPER'],
            e_fit.get('ROCK', 0), e_fit.get('PAPER', 0), e_fit.get('SCISSORS', 0),
            conv.get('delta_f', ''),
            conv.get('delta_mean16', ''),
            conv.get('anti_err', ''),
            conv.get('cycle', ''),
            conv.get('cycle_rev', ''),
            conv.get('hierarchy', ''),
            conv.get('hierarchy_type', ''),
            conv.get('min_pair_n', ''),
            conv.get('total_pair_n', ''),
            conv.get('efit_spread', ''),
            conv.get('efit_max', ''),
            conv.get('status', ''),
            nash.get('nash_l1', ''), nash.get('nash_l2', ''),
            nash.get('exploit_share', ''), nash.get('exploit_nash', ''),
            nash.get('nash_p_ROCK', ''), nash.get('nash_p_PAPER', ''),
            nash.get('nash_p_SCISSORS', ''), nash.get('support', ''),
        ]
        line = ','.join(str(v) for v in vals) + '\n'
        try:
            with open(path, 'a', encoding='utf-8') as f:
                if need_header:
                    f.write(header)
                f.write(line)
        except Exception as e:
            self._log_raw(f'payoff CSV write failed: {e}')

    def _mutate_traits(self, fitness=None, f_bar=None):
        """
        Small EGT mutation: random trait jitter so cycles do not stick on bounds
        and under-explored keys keep moving. Strength << selection pressure.
        """
        import random
        types = ('ROCK', 'PAPER', 'SCISSORS')
        keys = [k for k in STRATEGY_KEYS if k in STRATEGY_BOUNDS]
        if not keys:
            return
        rate = float(getattr(self, 'MUTATION_RATE', 0.12))
        strength = float(getattr(self, 'MUTATION_STRENGTH', 0.35))
        min_keys = int(getattr(self, 'MUTATION_MIN_KEYS', 2))
        n_mut = max(min_keys, int(round(rate * len(keys))))
        n_mut = min(n_mut, len(keys))
        for t in types:
            # Slightly more mutation for types near average fitness (neutral drift zone)
            local_strength = strength
            if fitness is not None and f_bar is not None:
                p = abs(float(fitness.get(t, 0)) - float(f_bar))
                if p < 0.05:
                    local_strength = strength * 1.4  # more exploration when neutral
                elif p > 0.15:
                    local_strength = strength * 0.7  # less noise when selection is clear
            chosen = random.sample(keys, n_mut)
            for key in chosen:
                direction = random.choice((-1, +1))
                self._nudge_type(
                    t, key, direction,
                    f'mutation {t}.{key}',
                    strength=local_strength,
                )



    # ------------------------------------------------------------------
    # Genetic algorithm: one island per (type, strategy_id)
    # Genome = tunables declared on that strategy JSON (weights/switch/when).
    # Fitness = overlay stats + replicator type-fit + coevo matchup payoff
    #           + role terms (short CLEAR_HUNT, long LAST_MAN, last-prey fine).
    # MAP-Elites archives the best genome per (state, team-bucket, type).
    # Coevolution: empirical card-vs-card payoff from conversions +
    #              same-id crossover across types.
    # Deploy writes the island champion into strategies/types/{T}/{ID}.json
    # ------------------------------------------------------------------

    def _ga_keys(self):
        return [k for k in STRATEGY_KEYS if k in STRATEGY_BOUNDS]

    def _ga_clip(self, key, val):
        lo, hi, step = STRATEGY_BOUNDS[key]
        try:
            v = float(val)
        except Exception:
            v = float(lo)
        if key in (
            'target_lock_ttl', 'scatter_threshold', 'prey_reserve',
            'small_unit_threshold', 'late_count_threshold',
            'clear_split_threshold', 'voronoi_recompute_interval',
            'voronoi_overflow_threshold', 'clear_voronoi_cap_slack',
            'delaunay_k', 'pincer_min_friends', 'pincer_switch_cooldown',
            'overcrowd_threshold', 'near_wipe_threshold',
        ):
            v = int(round(v))
        return max(lo, min(hi, v))

    def _ga_genome_from_defaults(self, type_name, jitter=0.0):
        import random
        g = {}
        d = TYPE_DEFAULTS.get(type_name, {})
        for k in self._ga_keys():
            base = d.get(k, STRATEGY_BOUNDS[k][0])
            try:
                base = float(base)
            except Exception:
                base = float(STRATEGY_BOUNDS[k][0])
            if jitter > 0:
                lo, hi, step = STRATEGY_BOUNDS[k]
                noise = random.gauss(0, jitter * abs(step))
                base = base + noise
            g[k] = self._ga_clip(k, base)
        return g

    def _ga_ensure_population(self):
        import random
        if self._ga_pop is not None and self._ga_fitness is not None:
            return
        types = ('ROCK', 'PAPER', 'SCISSORS')
        n = int(getattr(self, 'GA_POP_SIZE', 12))
        self._ga_pop = {}
        self._ga_fitness = {}
        for t in types:
            pop = [self._ga_genome_from_defaults(t, jitter=0.0)]  # elite seed = current
            for _ in range(n - 1):
                pop.append(self._ga_genome_from_defaults(t, jitter=1.2))
            self._ga_pop[t] = pop
            self._ga_fitness[t] = [0.0] * n
        self._ga_gen = 0
        self._log_raw(f'GA init: pop={n} types={list(types)} keys={len(self._ga_keys())}')

    def _ga_score_types(self, fitness_map, wipe_risk, share=None):
        """
        Assign fitness to the currently deployed (index-0 / elite) genome for each type
        using replicator fitness + wipe / endgame adjustments.
        Other individuals keep prior fitness (stale until deployed).
        """
        self._ga_ensure_population()
        types = ('ROCK', 'PAPER', 'SCISSORS')
        for t in types:
            base = float(fitness_map.get(t, 0.33))
            # Penalize wipe risk strongly (last-prey kill while predators exist)
            wr = float(wipe_risk.get(t, 0) or 0)
            score = base - 0.12 * min(3.0, wr)
            # Slight reward for balanced share (avoid monopoly → arms race)
            if share is not None:
                sh = float(share.get(t, 0.33))
                score -= 0.05 * abs(sh - 0.333)
            # Store on elite (index 0 is always the deployed genome after each gen)
            if self._ga_fitness[t]:
                self._ga_fitness[t][0] = score
            prev = self._ga_best.get(t)
            if prev is None or score > prev[0]:
                self._ga_best[t] = (score, dict(self._ga_pop[t][0]))

    def _ga_tournament(self, type_name):
        import random
        pop = self._ga_pop[type_name]
        fit = self._ga_fitness[type_name]
        k = int(getattr(self, 'GA_TOURNAMENT_K', 3))
        k = max(2, min(k, len(pop)))
        idxs = random.sample(range(len(pop)), k)
        best = max(idxs, key=lambda i: fit[i])
        return best

    def _ga_crossover(self, g1, g2, f1, f2):
        import random
        if random.random() > float(getattr(self, 'GA_CROSSOVER_RATE', 0.7)):
            return dict(g1 if f1 >= f2 else g2)
        child = {}
        # Blend toward fitter parent
        if f1 >= f2:
            a = float(getattr(self, 'GA_BLEND_ALPHA', 0.35))
            primary, secondary = g1, g2
        else:
            a = float(getattr(self, 'GA_BLEND_ALPHA', 0.35))
            primary, secondary = g2, g1
        for k in self._ga_keys():
            if random.random() < 0.5:
                # uniform gene pick
                child[k] = primary[k] if random.random() < (0.5 + a * 0.5) else secondary[k]
            else:
                # arithmetic blend
                try:
                    v = (1.0 - a) * float(primary[k]) + a * float(secondary[k])
                except Exception:
                    v = primary[k]
                child[k] = self._ga_clip(k, v)
        return child

    def _ga_mutate(self, genome):
        import random
        rate = float(getattr(self, 'GA_MUTATION_RATE', 0.12))
        sigma = float(getattr(self, 'GA_MUTATION_SIGMA', 0.4))
        out = dict(genome)
        for k in self._ga_keys():
            if random.random() > rate:
                continue
            lo, hi, step = STRATEGY_BOUNDS[k]
            try:
                noise = random.gauss(0, sigma * abs(step))
                out[k] = self._ga_clip(k, float(out[k]) + noise)
            except Exception:
                pass
        return out

    def _ga_evolve(self):
        """One generational step: elitism + tournament + crossover + mutate."""
        import random
        self._ga_ensure_population()
        types = ('ROCK', 'PAPER', 'SCISSORS')
        elite_n = int(getattr(self, 'GA_ELITE', 2))
        self._ga_gen += 1
        summary = []
        for t in types:
            pop = self._ga_pop[t]
            fit = self._ga_fitness[t]
            n = len(pop)
            # Rank by fitness
            order = sorted(range(n), key=lambda i: fit[i], reverse=True)
            new_pop = []
            new_fit = []
            # Elitism
            for i in order[:elite_n]:
                new_pop.append(dict(pop[i]))
                new_fit.append(fit[i])
            # Fill rest
            while len(new_pop) < n:
                i1 = self._ga_tournament(t)
                i2 = self._ga_tournament(t)
                child = self._ga_crossover(pop[i1], pop[i2], fit[i1], fit[i2])
                child = self._ga_mutate(child)
                new_pop.append(child)
                # Offspring inherit average parent fitness * slight discount until re-evaluated
                new_fit.append(0.5 * (fit[i1] + fit[i2]) * 0.9)
            self._ga_pop[t] = new_pop
            self._ga_fitness[t] = new_fit
            best_f = new_fit[0]
            summary.append(f'{t}:{best_f:.3f}')
        self._log_raw(
            f'GA gen={self._ga_gen} elite_fitness=[{", ".join(summary)}] '
            f'pop={getattr(self, "GA_POP_SIZE", 12)} elite={elite_n}'
        )
        return summary

    def _ga_deploy_elite(self):
        """Write elite genomes (index 0 after sort) into TYPE_DEFAULTS."""
        if not getattr(self, 'GA_DEPLOY_ELITE', True):
            return 0
        self._ga_ensure_population()
        n_chg = 0
        types = ('ROCK', 'PAPER', 'SCISSORS')
        for t in types:
            # Ensure index 0 is true elite
            order = sorted(range(len(self._ga_pop[t])), key=lambda i: self._ga_fitness[t][i], reverse=True)
            elite = self._ga_pop[t][order[0]]
            # Keep pop ordered with elite first
            self._ga_pop[t] = [self._ga_pop[t][i] for i in order]
            self._ga_fitness[t] = [self._ga_fitness[t][i] for i in order]
            for k, v in elite.items():
                if k not in TYPE_DEFAULTS[t]:
                    continue
                old = TYPE_DEFAULTS[t][k]
                try:
                    if abs(float(old) - float(v)) < 1e-9:
                        continue
                except Exception:
                    if old == v:
                        continue
                TYPE_DEFAULTS[t][k] = v
                self.last_changes.append(
                    f'{t}.{k}: {old} -> {v}  (GA elite gen={self._ga_gen})'
                )
                n_chg += 1
        if n_chg:
            self._log_raw(f'GA deploy: {n_chg} trait updates from elite genomes')
        return n_chg

    def _ga_step(self, fitness_map, wipe_risk, share=None):
        """Strategy-island GA + MAP-Elites + coevolutionary fitness."""
        if not getattr(self, 'GA_ENABLED', True):
            return
        try:
            self._ga_strategy_step(fitness_map, wipe_risk, share)
        except Exception as e:
            try:
                self._log_raw(f'GA step failed: {e}')
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Strategy islands
    # ------------------------------------------------------------------

    _GA_INT_SUFFIX = (
        'hold_frames', 'priority', 'ttl', 'threshold', 'k',
        'cooldown', 'slack', 'interval', 'friends',
    )

    def _ga_is_int_path(self, path):
        p = path.split('.')[-1]
        if p.endswith('ttl') or p.endswith('frames') or p.endswith('priority'):
            return True
        return any(p.endswith(s) for s in self._GA_INT_SUFFIX)

    def _ga_clip_bounds(self, path, val, bounds):
        lo, hi, step = bounds
        try:
            v = float(val)
        except Exception:
            v = float(lo)
        if self._ga_is_int_path(path):
            v = int(round(v))
        return max(float(lo), min(float(hi), v))

    def _ga_pb(self):
        import strategies.playbook as playbook
        if not getattr(playbook, 'STRATEGY_IDS', None):
            playbook.reload()
        return playbook

    def _ga_read_genome(self, pb, type_name, sid):
        tun = pb.tunables_for(type_name, sid) or {}
        ov = (pb.TEAM_OVERLAYS.get(type_name) or {}).get(sid) or {}
        g = {}
        for path, bounds in tun.items():
            val = pb._get_path(ov, path)
            if val is None:
                lo, hi, _ = bounds
                val = (float(lo) + float(hi)) * 0.5
            g[path] = self._ga_clip_bounds(path, val, bounds)
        return g, tun

    def _ga_mutate_genome(self, genome, tun):
        import random
        rate = float(getattr(self, 'GA_MUTATION_RATE', 0.14))
        sigma = float(getattr(self, 'GA_MUTATION_SIGMA', 0.45))
        out = dict(genome)
        for path, bounds in tun.items():
            if random.random() > rate:
                continue
            lo, hi, step = bounds
            try:
                noise = random.gauss(0, sigma * abs(float(step)))
                out[path] = self._ga_clip_bounds(path, float(out.get(path, lo)) + noise, bounds)
            except Exception:
                pass
        return out

    def _ga_crossover_genomes(self, g1, g2, tun, f1, f2):
        import random
        if random.random() > float(getattr(self, 'GA_CROSSOVER_RATE', 0.7)):
            return dict(g1 if f1 >= f2 else g2)
        a = float(getattr(self, 'GA_BLEND_ALPHA', 0.35))
        primary, secondary = (g1, g2) if f1 >= f2 else (g2, g1)
        child = {}
        for path, bounds in tun.items():
            v1 = primary.get(path, secondary.get(path))
            v2 = secondary.get(path, v1)
            if random.random() < 0.5:
                child[path] = v1 if random.random() < (0.55 + a * 0.3) else v2
            else:
                try:
                    v = (1.0 - a) * float(v1) + a * float(v2)
                except Exception:
                    v = v1
                child[path] = self._ga_clip_bounds(path, v, bounds)
        return child

    def _ga_pick_islands(self, pb):
        """Prefer cards that actually played; cap work per pass."""
        scored = []
        for t in ('ROCK', 'PAPER', 'SCISSORS'):
            bag = pb.TEAM_OVERLAYS.get(t) or {}
            for sid, ov in bag.items():
                if ov.get('enabled', True) is False:
                    continue
                st = ov.get('stats') or {}
                ticks = int(st.get('ticks') or 0)
                games = int(st.get('games') or 0)
                scored.append((ticks + games * 8, t, sid))
        scored.sort(reverse=True)
        cap = int(getattr(self, 'GA_MAX_ISLANDS', 36))
        picked = [(t, sid) for _, t, sid in scored[:cap]]
        if len(picked) < 6:
            for t in ('ROCK', 'PAPER', 'SCISSORS'):
                for sid in list(pb.STRATEGY_IDS or [])[:4]:
                    key = (t, sid)
                    if key not in picked:
                        picked.append(key)
                    if len(picked) >= cap:
                        break
        return picked

    def _ga_ensure_islands(self):
        import random
        pb = self._ga_pb()
        if self._ga_islands is None:
            self._ga_islands = {}
        n = max(3, int(getattr(self, 'GA_POP_SIZE', 6)))
        for t, sid in self._ga_pick_islands(pb):
            key = (t, sid)
            if key in self._ga_islands and self._ga_islands[key].get('pop'):
                # refresh champion from disk (replicator / playbook may have nudged)
                live, tun = self._ga_read_genome(pb, t, sid)
                island = self._ga_islands[key]
                island['tun'] = tun
                if island['pop']:
                    island['pop'][0] = live
                continue
            live, tun = self._ga_read_genome(pb, t, sid)
            if not tun:
                continue
            pop = [dict(live)]
            while len(pop) < n:
                pop.append(self._ga_mutate_genome(live, tun))
            self._ga_islands[key] = {
                'pop': pop,
                'fit': [0.0] * n,
                'tun': tun,
            }
        return pb

    # ------------------------------------------------------------------
    # Coevolutionary play (card vs card from conversions)
    # ------------------------------------------------------------------

    def _coevo_load_payoff(self):
        if not getattr(self, 'COEVO_ENABLED', True):
            self._coevo_payoff = {}
            return self._coevo_payoff
        path = self._metrics_path(self.CONV_CSV)
        payoff = {}
        window = int(getattr(self, 'COEVO_WINDOW', 400))
        try:
            import os
            if not os.path.exists(path):
                self._coevo_payoff = {}
                return payoff
            with open(path, encoding='utf-8', errors='replace') as f:
                header = f.readline()
                cols = [c.strip() for c in header.split(',')]
                try:
                    i_wt = cols.index('winner_type')
                    i_lt = cols.index('loser_was')
                    i_ws = cols.index('winner_strategy')
                    i_ls = cols.index('loser_strategy')
                except ValueError:
                    self._coevo_payoff = {}
                    return payoff
                # tail only — conversions.csv can be tens of MB
                try:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - min(size, window * 900 + 2048)))
                    if size > 4096:
                        f.readline()
                    rows = f.readlines()
                except Exception:
                    rows = f.readlines()
            rows = rows[-window:]
            for line in rows:
                parts = line.rstrip('\n').split(',')
                if len(parts) <= max(i_wt, i_lt, i_ws, i_ls):
                    continue
                wt, lt = parts[i_wt].strip().upper(), parts[i_lt].strip().upper()
                ws, ls = parts[i_ws].strip().upper(), parts[i_ls].strip().upper()
                if not (wt and lt and ws and ls):
                    continue
                key = (wt, ws, lt, ls)
                slot = payoff.setdefault(key, {'for': 0, 'against': 0, 'games': 0})
                slot['for'] += 1
                slot['games'] += 1
                rev = (lt, ls, wt, ws)
                rslot = payoff.setdefault(rev, {'for': 0, 'against': 0, 'games': 0})
                rslot['against'] += 1
                rslot['games'] += 1
        except Exception as e:
            self._log_raw('coevo load failed: %s' % e)
        self._coevo_payoff = payoff
        return payoff

    def _coevo_score(self, type_name, sid, mix=None):
        """Expected payoff of this card vs current opposing mix."""
        payoff = self._coevo_payoff or {}
        if not payoff:
            return 0.0
        opp_types = [t for t in ('ROCK', 'PAPER', 'SCISSORS') if t != type_name]
        num = den = 0.0
        for (wt, ws, lt, ls), slot in payoff.items():
            if wt != type_name or ws != sid:
                continue
            if lt not in opp_types:
                continue
            w = 1.0
            if mix:
                w = float(mix.get((lt, ls), 0.0)) or 1.0
            g = max(1, int(slot.get('games') or 0))
            rate = float(slot.get('for') or 0) / g
            num += w * (2.0 * rate - 1.0) * g
            den += w * g
        if den <= 0:
            return 0.0
        return max(-1.0, min(1.0, num / den))

    def _coevo_mix(self, pb):
        """Usage mix per (type, sid) from overlay ticks."""
        mix = {}
        totals = {'ROCK': 0.0, 'PAPER': 0.0, 'SCISSORS': 0.0}
        for t in totals:
            for sid, ov in (pb.TEAM_OVERLAYS.get(t) or {}).items():
                ticks = float((ov.get('stats') or {}).get('ticks') or 0)
                mix[(t, sid)] = ticks
                totals[t] += ticks
        for (t, sid), v in list(mix.items()):
            den = totals.get(t) or 0.0
            mix[(t, sid)] = (v / den) if den > 0 else 0.0
        return mix

    # ------------------------------------------------------------------
    # Fitness
    # ------------------------------------------------------------------

    def _strategy_role_bonus(self, ov, st):
        states = [(ov.get('when') or {}).get('states') or []]
        if states and isinstance(states[0], list):
            states = states[0]
        states = [str(s).upper() for s in states]
        games = max(1, int(st.get('games') or 0))
        ticks = max(1, int(st.get('ticks') or 0))
        conv_for = int(st.get('conversions_for') or 0)
        blunder = int(st.get('last_prey_blunder') or 0)
        bonus = 0.0
        # Predators in a clean hunt: reward kill-rate (short endgame proxy)
        if any(s in states for s in ('CLEAR_HUNT', 'NO_FEAR')):
            bonus += 0.22 * min(2.0, conv_for / max(1.0, ticks / 90.0))
        # Last man / survive: reward time on card
        if any(s in states for s in (
                'LAST_MAN', 'NEAR_WIPE', 'NO_PREY_FEAR_ALIVE', 'OUTNUMBERED')):
            bonus += 0.18 * min(2.0, (ticks / games) / 400.0)
        # Last-prey care: punish wombling the last prey
        if any(s in states for s in ('LAST_PREY_RISK', 'LAST_PREY_CARE')):
            bonus -= 0.55 * (blunder / float(games))
        else:
            bonus -= 0.30 * (blunder / float(games))
        return bonus

    def _strategy_fitness(self, type_name, sid, ov, fitness_map, wipe_risk, mix):
        st = ov.get('stats') or {}
        games = max(1, int(st.get('games') or 0))
        ticks = int(st.get('ticks') or 0)
        if ticks <= 0 and games <= 1:
            # unseen card: slight prior so it can still mutate
            return 0.15 + 0.05 * float(fitness_map.get(type_name, 0.33))
        win_rate = float(st.get('wins') or 0) / games
        conv_for = float(st.get('conversions_for') or 0)
        conv_ag = float(st.get('conversions_against') or 0)
        conv_rate = conv_for / max(1.0, conv_for + conv_ag)
        type_fit = float(fitness_map.get(type_name, 0.33))
        wr = float(wipe_risk.get(type_name, 0) or 0)
        score = 0.34 * win_rate
        score += 0.20 * type_fit
        score += 0.14 * conv_rate
        score -= 0.10 * min(3.0, wr)
        score += self._strategy_role_bonus(ov, st)
        if getattr(self, 'COEVO_ENABLED', True):
            score += float(getattr(self, 'COEVO_WEIGHT', 0.22)) * self._coevo_score(
                type_name, sid, mix)
        return score

    def _ga_score_islands(self, pb, fitness_map, wipe_risk):
        mix = self._coevo_mix(pb)
        for (t, sid), island in list(self._ga_islands.items()):
            ov = (pb.TEAM_OVERLAYS.get(t) or {}).get(sid) or {}
            score = self._strategy_fitness(t, sid, ov, fitness_map, wipe_risk, mix)
            if island['fit']:
                island['fit'][0] = score
            # clones inherit a discounted score until they are deployed
            for i in range(1, len(island['fit'])):
                island['fit'][i] = 0.82 * island['fit'][i] + 0.08 * score
        return mix

    # ------------------------------------------------------------------
    # MAP-Elites
    # ------------------------------------------------------------------

    def _map_team_bucket(self, team_size):
        edges = getattr(self, 'MAP_TEAM_BUCKETS', (8, 12, 16, 24))
        try:
            ts = int(team_size)
        except Exception:
            ts = 12
        for e in edges:
            if ts <= e:
                return e
        return edges[-1]

    def _map_state_for(self, ov):
        states = (ov.get('when') or {}).get('states') or ['CONTESTED']
        if not states:
            return 'CONTESTED'
        return str(states[0]).upper()

    def _map_update(self, pb, team_size, state_for=None):
        if not getattr(self, 'MAP_ELITES_ENABLED', True):
            return
        if not self._ga_islands:
            self._map_seed_neighbors()
            return 0
        bucket = self._map_team_bucket(team_size)
        filled = 0
        state_for = state_for or {}
        for (t, sid), island in self._ga_islands.items():
            ov = (pb.TEAM_OVERLAYS.get(t) or {}).get(sid) or {}
            state = state_for.get((t, sid)) or self._map_state_for(ov)
            niche = (state, bucket, t)
            fit = island['fit'][0] if island['fit'] else 0.0
            genome = dict(island['pop'][0]) if island['pop'] else {}
            prev = self._map_elites.get(niche)
            if prev is None or fit > float(prev.get('fitness', -1e9)):
                self._map_elites[niche] = {
                    'fitness': float(fit),
                    'type': t,
                    'sid': sid,
                    'genome': genome,
                    'visits': int((prev or {}).get('visits', 0)) + 1,
                }
                filled += 1
            elif prev is not None:
                prev['visits'] = int(prev.get('visits', 0)) + 1
        self._map_seed_neighbors()
        return filled

    def _map_seed_neighbors(self):
        """Copy a filled (state, type) into the adjacent empty team bucket."""
        edges = list(getattr(self, 'MAP_TEAM_BUCKETS', (8, 12, 16, 24)))
        occupied = list((self._map_elites or {}).items())
        n_seed = 0
        for (state, bucket, t), slot in occupied:
            try:
                i = edges.index(int(bucket))
            except (ValueError, TypeError):
                continue
            neighbors = []
            if i > 0:
                neighbors.append(edges[i - 1])
            if i < len(edges) - 1:
                neighbors.append(edges[i + 1])
            for b in neighbors:
                niche = (state, b, t)
                if niche in (self._map_elites or {}):
                    continue
                self._map_elites[niche] = {
                    'fitness': 0.85 * float(slot.get('fitness', 0) or 0),
                    'type': t,
                    'sid': slot.get('sid'),
                    'genome': dict(slot.get('genome') or {}),
                    'visits': 0,
                }
                n_seed += 1
        return n_seed

    def _map_persist(self, pb):
        """Write archive + empty-niche suggestions for Grok."""
        try:
            from optimizer.paths import grok_path
            import json
            cells = []
            for (state, bucket, t), slot in sorted(self._map_elites.items()):
                cells.append({
                    'state': state,
                    'team_bucket': bucket,
                    'type': t,
                    'sid': slot.get('sid'),
                    'fitness': round(float(slot.get('fitness', 0)), 4),
                    'visits': int(slot.get('visits', 0)),
                })
            path = grok_path('map_elites.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'cells': cells, 'gen': self._ga_gen}, f, indent=2)
            try:
                pb.set_map_cells(cells)
            except Exception:
                pass
            # Known states × buckets × types
            states = set()
            for t in ('ROCK', 'PAPER', 'SCISSORS'):
                for sid, ov in (pb.TEAM_OVERLAYS.get(t) or {}).items():
                    states.add(self._map_state_for(ov))
            if not states:
                states = {'CONTESTED', 'CLEAR_HUNT', 'LAST_PREY_RISK',
                          'NEAR_WIPE', 'NO_PREY_FEAR_ALIVE'}
            buckets = getattr(self, 'MAP_TEAM_BUCKETS', (8, 12, 16, 24))
            empty = []
            for state in sorted(states):
                for b in buckets:
                    for t in ('ROCK', 'PAPER', 'SCISSORS'):
                        if (state, b, t) not in self._map_elites:
                            empty.append({'state': state, 'team_bucket': b, 'type': t})
            sug = grok_path('MAP_ELITES.md')
            lines = [
                '# MAP-Elites archive',
                '',
                'Filled cells: **%d**. Empty niches: **%d**.' % (len(cells), len(empty)),
                '',
                '## Occupied',
                '',
            ]
            for c in cells[:80]:
                lines.append('- `%s` team≤%s %s → **%s** fit=%.3f visits=%d' % (
                    c['state'], c['team_bucket'], c['type'], c['sid'],
                    c['fitness'], c['visits']))
            lines += ['', '## Empty niches (write a template for these)', '']
            for e in empty[:40]:
                lines.append('- `%s` team≤%s %s' % (
                    e['state'], e['team_bucket'], e['type']))
            with open(sug, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
            if empty:
                self._log_raw('MAP-Elites empty niches=%d (see optimizer/grok/MAP_ELITES.md)' % len(empty))
        except Exception as e:
            self._log_raw('MAP-Elites persist failed: %s' % e)

    # ------------------------------------------------------------------
    # Evolve + deploy
    # ------------------------------------------------------------------

    def _ga_evolve_islands(self):
        import random
        elite_n = max(1, int(getattr(self, 'GA_ELITE', 1)))
        self._ga_gen += 1
        summary = []
        # same-id partners for coevo crossover
        by_sid = {}
        for (t, sid) in self._ga_islands:
            by_sid.setdefault(sid, []).append(t)
        for (t, sid), island in self._ga_islands.items():
            pop, fit, tun = island['pop'], island['fit'], island['tun']
            n = len(pop)
            if n < 2 or not tun:
                continue
            order = sorted(range(n), key=lambda i: fit[i], reverse=True)
            new_pop, new_fit = [], []
            for i in order[:elite_n]:
                new_pop.append(dict(pop[i]))
                new_fit.append(fit[i])
            while len(new_pop) < n:
                # tournament inside island
                k = max(2, min(int(getattr(self, 'GA_TOURNAMENT_K', 3)), n))
                i1 = max(random.sample(range(n), k), key=lambda i: fit[i])
                # coevo: occasionally take parent 2 from another type's same card
                g2_src, f2 = pop, fit
                t2 = t
                if (getattr(self, 'GA_CROSS_TYPE', True)
                        and random.random() < float(getattr(self, 'GA_CROSS_TYPE_RATE', 0.22))):
                    others = [x for x in by_sid.get(sid, []) if x != t]
                    if others:
                        t2 = random.choice(others)
                        other = self._ga_islands.get((t2, sid))
                        if other and other.get('pop'):
                            g2_src, f2 = other['pop'], other['fit']
                i2 = max(random.sample(range(len(g2_src)), min(k, len(g2_src))),
                         key=lambda i: f2[i])
                child = self._ga_crossover_genomes(
                    pop[i1], g2_src[i2], tun, fit[i1], f2[i2])
                child = self._ga_mutate_genome(child, tun)
                new_pop.append(child)
                new_fit.append(0.5 * (fit[i1] + f2[i2]) * 0.9)
            island['pop'] = new_pop
            island['fit'] = new_fit
            summary.append('%s/%s:%.3f' % (t[0], sid[:8], new_fit[0]))
        self._log_raw(
            'GA gen=%d islands=%d elite=[%s]' % (
                self._ga_gen, len(self._ga_islands), ', '.join(summary[:12]))
        )
        return summary

    def _ga_deploy_islands(self, pb):
        if not getattr(self, 'GA_DEPLOY_ELITE', True):
            return 0
        n_chg = 0
        for (t, sid), island in self._ga_islands.items():
            pop, fit, tun = island['pop'], island['fit'], island['tun']
            if not pop:
                continue
            order = sorted(range(len(pop)), key=lambda i: fit[i], reverse=True)
            island['pop'] = [pop[i] for i in order]
            island['fit'] = [fit[i] for i in order]
            elite = island['pop'][0]
            ov = (pb.TEAM_OVERLAYS.get(t) or {}).get(sid)
            if ov is None:
                continue
            changed = False
            for path, val in elite.items():
                bounds = tun.get(path)
                if not bounds:
                    continue
                val = self._ga_clip_bounds(path, val, bounds)
                cur = pb._get_path(ov, path)
                try:
                    if cur is not None and abs(float(cur) - float(val)) < 1e-9:
                        continue
                except Exception:
                    if cur == val:
                        continue
                pb._set_path(ov, path, val)
                changed = True
                n_chg += 1
                if n_chg <= 16:
                    self.last_changes.append(
                        '%s.%s.%s: %s -> %s  (GA island gen=%d)' % (
                            t, sid, path, cur, val, self._ga_gen)
                    )
            if changed:
                pb.save_overlay(t, sid, ov)
        if n_chg:
            try:
                pb.invalidate_spec_cache()
            except Exception:
                pass
            self._log_raw('GA deploy: %d overlay knobs from island champions' % n_chg)
        return n_chg

    def _ga_strategy_step(self, fitness_map, wipe_risk, share=None):
        pb = self._ga_ensure_islands()
        self._coevo_load_payoff()
        self._ga_score_islands(pb, fitness_map, wipe_risk)
        # fictitious play among champions: log the 3-way card matchup
        try:
            champs = {}
            for t in ('ROCK', 'PAPER', 'SCISSORS'):
                best = None
                for (tt, sid), island in self._ga_islands.items():
                    if tt != t or not island['fit']:
                        continue
                    if best is None or island['fit'][0] > best[0]:
                        best = (island['fit'][0], sid)
                if best:
                    champs[t] = best[1]
                    co = self._coevo_score(t, best[1], self._coevo_mix(pb))
                    self._log_raw(
                        'coevo champion %s/%s fit=%.3f matchup=%.3f' % (
                            t, best[1], best[0], co)
                    )
        except Exception as e:
            self._log_raw('coevo champions failed: %s' % e)
        if getattr(self, 'GA_DEPLOY_ELITE', False):
            self._ga_evolve_islands()
            self._ga_deploy_islands(pb)
        else:
            self._log_raw('GA skip evolve/deploy (unevaluated island genomes)')
        avg_team = REF_TEAM_SIZE
        try:
            ww = getattr(self, 'w', None)
            if ww is not None and getattr(ww, 'teamSize', None):
                avg_team = int(ww.teamSize)
        except Exception:
            pass
        self._map_update(pb, avg_team)
        self._map_persist(pb)

    def _map_archive_step(self, fitness_map, wipe_risk, share=None):
        """Score live overlays into MAP-Elites. Never deploy island genomes."""
        if not getattr(self, 'MAP_ELITES_ENABLED', True):
            return
        prev = getattr(self, 'GA_DEPLOY_ELITE', False)
        self.GA_DEPLOY_ELITE = False
        try:
            self._ga_strategy_step(fitness_map, wipe_risk, share)
        finally:
            self.GA_DEPLOY_ELITE = prev

    def _map_fill_live(self, fitness_map, wipe_risk, team_size):
        """Occupy this match's team bucket from live overlays. No island evolve."""
        if not getattr(self, 'MAP_ELITES_ENABLED', True):
            return
        pb = self._ga_pb()
        self._coevo_load_payoff()
        mix = self._coevo_mix(pb)
        metrics = getattr(getattr(self, 'w', None), 'metrics', None)
        ticks_all = getattr(metrics, 'strategy_ticks', {}) if metrics is not None else {}
        if self._ga_islands is None:
            self._ga_islands = {}
        n_fill = 0
        state_for = {}
        for tname in ('ROCK', 'PAPER', 'SCISSORS'):
            used = ticks_all.get(tname) or {}
            bag = pb.TEAM_OVERLAYS.get(tname) or {}
            for sid, ov in bag.items():
                if not self._overlay_eligible(used.get(sid, 0), ov):
                    continue
                live, tun = self._ga_read_genome(pb, tname, sid)
                if not tun:
                    continue
                score = self._strategy_fitness(
                    tname, sid, ov, fitness_map, wipe_risk, mix)
                self._ga_islands[(tname, sid)] = {
                    'pop': [live], 'fit': [score], 'tun': tun,
                }
                state_for[(tname, sid)] = self._overlay_dom_state(tname, sid, ov)
                n_fill += 1
        ts = float(team_size or REF_TEAM_SIZE)
        self._map_update(pb, ts, state_for=state_for)
        self._map_persist(pb)
        if n_fill:
            self._log_raw('MAP-Elites live fill cards=%d team=%.0f' % (n_fill, ts))

    # ------------------------------------------------------------------
    # Particle Swarm Optimization — continuous refinement of STRATEGY_KEYS
    # Per-type swarm. Deferred fitness: score particle 0 (deployed) from
    # match metrics, then update velocities toward pbest / gbest.
    # Hybrid: runs after GA; gbest can overwrite TYPE_DEFAULTS.
    # ------------------------------------------------------------------

    def _pso_keys(self):
        return [k for k in STRATEGY_KEYS if k in STRATEGY_BOUNDS]

    def _pso_clip_pos(self, key, val):
        lo, hi, step = STRATEGY_BOUNDS[key]
        try:
            v = float(val)
        except Exception:
            v = float(lo)
        if key in (
            'target_lock_ttl', 'scatter_threshold', 'prey_reserve',
            'small_unit_threshold', 'late_count_threshold',
            'clear_split_threshold', 'voronoi_recompute_interval',
            'voronoi_overflow_threshold', 'clear_voronoi_cap_slack',
            'delaunay_k', 'pincer_min_friends', 'pincer_switch_cooldown',
            'overcrowd_threshold', 'near_wipe_threshold',
        ):
            v = int(round(v))
        return max(lo, min(hi, v))

    def _pso_vmax(self, key):
        lo, hi, step = STRATEGY_BOUNDS[key]
        span = max(abs(hi - lo), abs(step), 1e-9)
        return float(getattr(self, 'PSO_VMAX_FRAC', 0.2)) * span

    def _pso_pos_from_defaults(self, type_name, jitter=0.0):
        import random
        g = {}
        d = TYPE_DEFAULTS.get(type_name, {})
        for k in self._pso_keys():
            base = d.get(k, STRATEGY_BOUNDS[k][0])
            try:
                base = float(base)
            except Exception:
                base = float(STRATEGY_BOUNDS[k][0])
            if jitter > 0:
                lo, hi, step = STRATEGY_BOUNDS[k]
                base = base + random.gauss(0, jitter * abs(step))
            g[k] = self._pso_clip_pos(k, base)
        return g

    def _pso_zero_vel(self):
        return {k: 0.0 for k in self._pso_keys()}

    def _pso_ensure_swarm(self):
        import random
        if self._pso_pos is not None:
            return
        types = ('ROCK', 'PAPER', 'SCISSORS')
        n = int(getattr(self, 'PSO_SWARM_SIZE', 12))
        self._pso_pos = {}
        self._pso_vel = {}
        self._pso_pbest = {}
        self._pso_pbest_f = {}
        self._pso_gbest = {}
        self._pso_gbest_f = {}
        for t in types:
            positions = [self._pso_pos_from_defaults(t, jitter=0.0)]
            velocities = [self._pso_zero_vel()]
            for _ in range(n - 1):
                positions.append(self._pso_pos_from_defaults(t, jitter=1.2))
                # Small random initial velocity
                v = {}
                for k in self._pso_keys():
                    vmax = self._pso_vmax(k)
                    v[k] = random.uniform(-0.5 * vmax, 0.5 * vmax)
                velocities.append(v)
            self._pso_pos[t] = positions
            self._pso_vel[t] = velocities
            self._pso_pbest[t] = [dict(pos) for pos in positions]
            self._pso_pbest_f[t] = [float('-inf')] * n
            self._pso_gbest[t] = dict(positions[0])
            self._pso_gbest_f[t] = float('-inf')
        self._pso_gen = 0
        self._log_raw(
            f'PSO init: swarm={n} types={list(types)} dims={len(self._pso_keys())} '
            f'w=[{getattr(self,"PSO_W_MIN",0.4)},{getattr(self,"PSO_W_MAX",0.9)}] '
            f'c1={getattr(self,"PSO_C1_MAX",2.0)}->{getattr(self,"PSO_C1_MIN",1.2)} '
            f'c2={getattr(self,"PSO_C2_MIN",1.2)}->{getattr(self,"PSO_C2_MAX",2.0)} '
            f'c_sched={getattr(self,"PSO_C_SCHEDULE","adaptive")} '
            f'constrict={int(getattr(self,"PSO_USE_CONSTRICTION", False))}'
        )

    def _pso_schedule_t(self):
        """Normalized progress in [0, 1] over decay horizon."""
        decay = max(1, int(getattr(self, 'PSO_W_DECAY_GENS', 50)))
        g = max(0, int(getattr(self, '_pso_gen', 0)))
        return min(1.0, g / float(decay))

    def _pso_base_inertia(self, t=None):
        """
        Scheduled inertia from w_max → w_min.
        Modes:
          linear   — constant slope
          exp      — fast early drop, long tail near w_min
          sigmoid  — hold high, sharp mid transition, hold low
          cosine   — slow start, smooth mid, soft landing (default base)
          adaptive — cosine + stagnation/diversity boosts (applied in _pso_inertia)
        """
        import math
        wmax = float(getattr(self, 'PSO_W_MAX', 0.9))
        wmin = float(getattr(self, 'PSO_W_MIN', 0.35))
        if t is None:
            t = self._pso_schedule_t()
        mode = str(getattr(self, 'PSO_W_SCHEDULE', 'adaptive')).lower()
        # adaptive uses cosine as the base curve
        if mode in ('adaptive', 'cosine', 'cos'):
            # t=0 → wmax, t=1 → wmin via raised-cosine
            frac = 0.5 * (1.0 - math.cos(math.pi * t))
            return wmax - frac * (wmax - wmin)
        if mode in ('linear', 'lin'):
            return wmax - t * (wmax - wmin)
        if mode in ('exp', 'exponential'):
            k = float(getattr(self, 'PSO_W_EXP_K', 4.0))
            # exp decay of the (w - wmin) gap
            return wmin + (wmax - wmin) * math.exp(-k * t)
        if mode in ('sigmoid', 'sig'):
            k = float(getattr(self, 'PSO_W_SIGMOID_K', 10.0))
            # logistic centered at t=0.5
            s = 1.0 / (1.0 + math.exp(-k * (t - 0.5)))
            return wmax - s * (wmax - wmin)
        # fallback
        return wmax - t * (wmax - wmin)

    def _pso_swarm_diversity(self, type_name):
        """Mean normalized std-dev of positions across dims (0..~1)."""
        import math
        pos_list = (self._pso_pos or {}).get(type_name) or []
        if len(pos_list) < 2:
            return 1.0
        keys = self._pso_keys()
        if not keys:
            return 1.0
        acc = 0.0
        n_keys = 0
        n = len(pos_list)
        for k in keys:
            lo, hi, _ = STRATEGY_BOUNDS[k]
            span = max(abs(hi - lo), 1e-9)
            vals = []
            for pos in pos_list:
                try:
                    vals.append(float(pos.get(k, lo)))
                except Exception:
                    vals.append(float(lo))
            mean = sum(vals) / n
            var = sum((v - mean) ** 2 for v in vals) / n
            acc += math.sqrt(var) / span
            n_keys += 1
        return acc / max(1, n_keys)

    def _pso_update_stagnation(self):
        """Track gens since gbest fitness improved per type."""
        if not self._pso_gbest_f:
            return
        prev = getattr(self, '_pso_gbest_f_prev', None)
        if prev is None:
            self._pso_gbest_f_prev = {}
            self._pso_stag_count = {}
            prev = self._pso_gbest_f_prev
        stag = getattr(self, '_pso_stag_count', None)
        if stag is None:
            self._pso_stag_count = {}
            stag = self._pso_stag_count
        for t, f in self._pso_gbest_f.items():
            old = prev.get(t, float('-inf'))
            if f > old + 1e-6:
                stag[t] = 0
            else:
                stag[t] = stag.get(t, 0) + 1
            prev[t] = f

    def _pso_inertia(self):
        """
        Tuned inertia for high-D deferred-fitness search.
        Default schedule=adaptive: cosine annealing base, then bump w when
        gbest stagnates or swarm diversity collapses (re-explore).
        """
        wmax = float(getattr(self, 'PSO_W_MAX', 0.9))
        wmin = float(getattr(self, 'PSO_W_MIN', 0.35))
        mode = str(getattr(self, 'PSO_W_SCHEDULE', 'adaptive')).lower()
        w = self._pso_base_inertia()
        if mode == 'adaptive':
            self._pso_update_stagnation()
            stag_limit = int(getattr(self, 'PSO_W_STAGNATION_GENS', 5))
            boost = 0.0
            # Max stagnation across types drives re-exploration
            stag = getattr(self, '_pso_stag_count', {}) or {}
            max_stag = max(stag.values()) if stag else 0
            if max_stag >= stag_limit:
                boost += float(getattr(self, 'PSO_W_STAG_BOOST', 0.12))
            # Low diversity → boost
            try:
                divs = [self._pso_swarm_diversity(t) for t in ('ROCK', 'PAPER', 'SCISSORS')]
                mean_div = sum(divs) / max(1, len(divs))
                if mean_div < 0.08:
                    boost += float(getattr(self, 'PSO_W_DIVERSITY_BOOST', 0.08))
            except Exception:
                pass
            w = min(wmax, w + boost)
        return max(wmin, min(wmax, w))


    def _pso_score_deployed(self, fitness_map, wipe_risk, share=None):
        """Score particle 0 (synced to TYPE_DEFAULTS) and update pbest/gbest."""
        self._pso_ensure_swarm()
        types = ('ROCK', 'PAPER', 'SCISSORS')
        for t in types:
            base = float(fitness_map.get(t, 0.33))
            wr = float(wipe_risk.get(t, 0) or 0)
            score = base - 0.12 * min(3.0, wr)
            if share is not None:
                score -= 0.05 * abs(float(share.get(t, 0.33)) - 0.333)
            # Particle 0 is always the deployed strategy
            if score >= self._pso_pbest_f[t][0]:
                self._pso_pbest_f[t][0] = score
                self._pso_pbest[t][0] = dict(self._pso_pos[t][0])
            if score >= self._pso_gbest_f[t]:
                self._pso_gbest_f[t] = score
                self._pso_gbest[t] = dict(self._pso_pos[t][0])

    def _pso_coefficients(self):
        """
        Scheduled cognitive (c1) / social (c2) weights.
        linear/cosine: c1 decays, c2 grows over the inertia horizon.
        fixed: use PSO_C1 / PSO_C2.
        adaptive: cosine schedule + keep c1 high / c2 low while stagnating
                  or when swarm diversity collapses.
        Constriction: if PSO_USE_CONSTRICTION, return (chi, c1, c2) with
        chi≈0.729; caller applies v = chi*(v + c1 r1 (p-x) + c2 r2 (g-x)).
        """
        import math
        t = self._pso_schedule_t()
        mode = str(getattr(self, 'PSO_C_SCHEDULE', 'adaptive')).lower()
        c1_max = float(getattr(self, 'PSO_C1_MAX', 2.0))
        c1_min = float(getattr(self, 'PSO_C1_MIN', 1.2))
        c2_min = float(getattr(self, 'PSO_C2_MIN', 1.2))
        c2_max = float(getattr(self, 'PSO_C2_MAX', 2.0))
        if mode == 'fixed':
            c1 = float(getattr(self, 'PSO_C1', 1.8))
            c2 = float(getattr(self, 'PSO_C2', 1.3))
        else:
            if mode == 'linear':
                frac = t
            else:
                # cosine + adaptive share the same base frac
                frac = 0.5 * (1.0 - math.cos(math.pi * t))
            c1 = c1_max - frac * (c1_max - c1_min)
            c2 = c2_min + frac * (c2_max - c2_min)
            if mode == 'adaptive':
                stag_limit = int(getattr(self, 'PSO_W_STAGNATION_GENS', 5))
                stag = getattr(self, '_pso_stag_count', {}) or {}
                max_stag = max(stag.values()) if stag else 0
                if max_stag >= stag_limit:
                    c1 = min(c1_max, c1 + float(getattr(self, 'PSO_C_STAG_C1_BOOST', 0.25)))
                    c2 = max(c2_min, c2 - float(getattr(self, 'PSO_C_STAG_C2_CUT', 0.20)))
                try:
                    divs = [self._pso_swarm_diversity(tp) for tp in ('ROCK', 'PAPER', 'SCISSORS')]
                    mean_div = sum(divs) / max(1, len(divs))
                    if mean_div < 0.08:
                        c1 = min(c1_max, c1 + float(getattr(self, 'PSO_C_DIV_C1_BOOST', 0.15)))
                        c2 = max(c2_min, c2 * 0.85)
                except Exception:
                    pass
        use_chi = bool(getattr(self, 'PSO_USE_CONSTRICTION', False))
        chi = float(getattr(self, 'PSO_CHI', 0.729843788128)) if use_chi else 1.0
        return c1, c2, chi, use_chi

    def _pso_update_velocities_positions(self):
        import random
        self._pso_ensure_swarm()
        w = self._pso_inertia()
        c1, c2, chi, use_chi = self._pso_coefficients()
        types = ('ROCK', 'PAPER', 'SCISSORS')
        self._pso_gen += 1
        summary = []
        for t in types:
            n = len(self._pso_pos[t])
            gbest = self._pso_gbest[t]
            for i in range(n):
                pos = self._pso_pos[t][i]
                vel = self._pso_vel[t][i]
                pbest = self._pso_pbest[t][i]
                new_vel = {}
                new_pos = {}
                for k in self._pso_keys():
                    r1 = random.random()
                    r2 = random.random()
                    try:
                        xi = float(pos[k])
                        pi = float(pbest[k])
                        gi = float(gbest[k])
                        vi = float(vel.get(k, 0.0))
                    except Exception:
                        xi = float(STRATEGY_BOUNDS[k][0])
                        pi = xi
                        gi = xi
                        vi = 0.0
                    if use_chi:
                        # Clerc constriction: inertia absorbed into χ
                        vi = chi * (vi + c1 * r1 * (pi - xi) + c2 * r2 * (gi - xi))
                    else:
                        vi = w * vi + c1 * r1 * (pi - xi) + c2 * r2 * (gi - xi)
                    vmax = self._pso_vmax(k)
                    if vi > vmax:
                        vi = vmax
                    elif vi < -vmax:
                        vi = -vmax
                    xi = self._pso_clip_pos(k, xi + vi)
                    new_vel[k] = vi
                    new_pos[k] = xi
                self._pso_vel[t][i] = new_vel
                self._pso_pos[t][i] = new_pos
            # Occasional re-init of worst particle (diversity)
            reinit = float(getattr(self, 'PSO_REINIT_FRAC', 0.08))
            if n > 2 and random.random() < reinit:
                worst = min(range(n), key=lambda i: self._pso_pbest_f[t][i])
                if worst != 0:  # never reinit deployed slot blindly before score
                    self._pso_pos[t][worst] = self._pso_pos_from_defaults(t, jitter=1.5)
                    self._pso_vel[t][worst] = self._pso_zero_vel()
                    self._pso_pbest_f[t][worst] = float('-inf')
            summary.append(f'{t}:{self._pso_gbest_f[t]:.3f}')
        self._log_raw(
            f'PSO gen={self._pso_gen} w={w:.3f} c1={c1:.3f} c2={c2:.3f} '
            f'chi={chi:.3f} constrict={int(use_chi)} '
            f'w_sched={getattr(self,"PSO_W_SCHEDULE","adaptive")} '
            f'c_sched={getattr(self,"PSO_C_SCHEDULE","adaptive")} '
            f'gbest=[{", ".join(summary)}] swarm={getattr(self,"PSO_SWARM_SIZE",12)}'
        )
        return summary

    def _pso_deploy_gbest(self):
        """Write per-type gbest into TYPE_DEFAULTS."""
        if not getattr(self, 'PSO_DEPLOY_GBEST', True):
            return 0
        self._pso_ensure_swarm()
        n_chg = 0
        for t in ('ROCK', 'PAPER', 'SCISSORS'):
            gbest = self._pso_gbest.get(t)
            if not gbest:
                continue
            # Sync particle 0 to gbest for next score cycle
            self._pso_pos[t][0] = dict(gbest)
            for k, v in gbest.items():
                if k not in TYPE_DEFAULTS[t]:
                    continue
                old = TYPE_DEFAULTS[t][k]
                try:
                    if abs(float(old) - float(v)) < 1e-9:
                        continue
                except Exception:
                    if old == v:
                        continue
                TYPE_DEFAULTS[t][k] = v
                self.last_changes.append(
                    f'{t}.{k}: {old} -> {v}  (PSO gbest gen={self._pso_gen})'
                )
                n_chg += 1
        if n_chg:
            self._log_raw(f'PSO deploy: {n_chg} trait updates from gbest')
        return n_chg

    def _pso_step(self, fitness_map, wipe_risk, share=None):
        """Full PSO cycle: sync → score → velocity/position update → deploy gbest."""
        if not getattr(self, 'PSO_ENABLED', True):
            return
        try:
            self._pso_ensure_swarm()
            # Sync particle 0 with current TYPE_DEFAULTS (replicator/GA may have changed)
            for t in ('ROCK', 'PAPER', 'SCISSORS'):
                self._pso_pos[t][0] = self._pso_pos_from_defaults(t, jitter=0.0)
            self._pso_score_deployed(fitness_map, wipe_risk, share)
            self._pso_update_velocities_positions()
            self._pso_deploy_gbest()
        except Exception as e:
            try:
                self._log_raw(f'PSO step failed: {e}')
            except Exception:
                pass


    def optimise(self, recent_only=None, persist=True):
        import time as _time
        _t_opt = _time.perf_counter()
        try:
            from optimizer.perf import get_perf
            get_perf(getattr(self, 'w', None)).begin('optimise')
        except Exception:
            pass

        # HARD_ABS_CLAMP: every strategy key forced into STRATEGY_BOUNDS every pass
        for _tn, _d in TYPE_DEFAULTS.items():
            for _k, _bnd in STRATEGY_BOUNDS.items():
                if _k not in _d:
                    continue
                try:
                    _lo, _hi, _ = float(_bnd[0]), float(_bnd[1]), _bnd[2]
                    _v = float(_d[_k])
                    _v = max(_lo, min(_hi, _v))
                    if _k in ('target_lock_ttl', 'scatter_threshold', 'prey_reserve',
                              'small_unit_threshold', 'late_count_threshold',
                              'pincer_min_friends', 'pincer_switch_cooldown', 'overcrowd_threshold'):
                        _d[_k] = int(round(_v))
                    else:
                        _d[_k] = round(_v, 4)
                except Exception:
                    pass
        """Learn emergent strategies: large window, state inference, slow bound evolution."""
        import os, traceback, datetime
        if recent_only is None:
            recent_only = self.SAMPLE_WINDOW
        self.last_changes = []
        StrategyOptimizer.GENERATION += 1
        games = []
        try:
            games = self._load_games()
        except Exception as e:
            self._log_raw(f'optimise: _load_games failed: {e}')
            return self.last_changes
        try:
            from optimizer.logger import Metrics
            stored = Metrics.read_games_total()
        except Exception:
            stored = 0
        self.games_seen = max(int(stored or 0), len(games), int(getattr(self, 'games_seen', 0) or 0))
        try:
            from optimizer.logger import Metrics
            Metrics.write_games_total(self.games_seen)
        except Exception:
            pass
        if len(games) < self.MIN_GAMES:
            self._log_raw(
                f'optimise: only {len(games)} games (need {self.MIN_GAMES}) – '
                f'looking for {StrategyOptimizer.GAMES_CSV} in {os.getcwd()}'
            )
            return self.last_changes

        sample = games[-recent_only:] if len(games) > recent_only else games
        self._last_sample_games = sample
        n = len(sample)
        wins = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
        team_sizes = []
        for g in sample:
            w = g.get('winner', '')
            if w in wins:
                wins[w] += 1
            try:
                team_sizes.append(int(float(g.get('teamSize', REF_TEAM_SIZE))))
            except Exception:
                pass
        avg_dur = sum(g.get('_duration', 0) for g in sample) / max(1, n)
        avg_team = sum(team_sizes) / len(team_sizes) if team_sizes else REF_TEAM_SIZE

        ranked = sorted(wins.keys(), key=lambda t: wins[t])
        weak, strong = ranked[0], ranked[2]

        try:
            self._ensure_state_keys()
            self._sanitize_defaults()
            # ===== Replicator dynamics =====
            # ẋ_i = x_i (f_i - f̄)  →  trait updates ∝ (f_i - f̄)
            wipe_risk = self._count_prey_wipe_risk()
            fitness, share, f_bar = self._replicator_fitness(wins, n, wipe_risk, avg_dur)
            self._last_fitness = dict(fitness)
            self._last_fbar = f_bar
            fit_s = ', '.join(f'{k}:{v:.3f}' for k, v in fitness.items())
            sh_s = ', '.join(f'{k}:{v:.3f}' for k, v in share.items())
            self._log_raw(
                f'replicator gen={self.GENERATION} fitness=[{fit_s}] f_bar={f_bar:.3f} share=[{sh_s}]'
            )
            # Empirical RPS payoff: ALL + CONTESTED/CARE/CLEAR.
            # Simplex uses CONTESTED (the actual cycle). Trait ES keeps emp share.
            emp_share = dict(share)
            A = None
            try:
                bundle = self._state_payoff_bundle()
                all_bag = bundle.get('ALL') or {}
                A, counts, e_fit, pay_summary = (
                    all_bag.get('A'), all_bag.get('counts'),
                    all_bag.get('e_fit'), all_bag.get('summary'))
                self._log_payoff_matrix(A, counts, e_fit, pay_summary, share=share)
                self._last_payoff = A
                self._last_payoff_efit = e_fit
                cont = bundle.get('CONTESTED') or {}
                if int(cont.get('n') or 0) >= 12:
                    A = cont.get('A') or A
                    self._log_raw('simplex A source=CONTESTED n=%s cycle=%s/3' % (
                        cont.get('n'), cont.get('cycle_ok')))
                else:
                    self._log_raw('simplex A source=ALL n=%s' % all_bag.get('n'))
                try:
                    match_A, _mc = self._match_payoff_matrix(sample)
                    if match_A is not None:
                        A = match_A
                        self._log_raw('simplex A source=MATCH (not conversion tautology)')
                except Exception as _me:
                    self._log_raw('A_MATCH failed: %s' % _me)
            except Exception as _pe:
                A = None
                self._log_raw(f'payoff matrix failed: {_pe}')
            try:
                self._load_simplex()
                sx, sf, sfbar = self._replicator_step_simplex(
                    A, emp_share, scalar_fit=fitness)
                self._last_share = dict(sx)
                share = emp_share
            except Exception as _se:
                self._last_share = share
                self._log_raw('simplex step failed: %s' % _se)

            # Adaptive learning rates for this generation
            try:
                lr_map, lr_meta = self._adaptive_learning_rates(fitness, f_bar, share)
                self._log_raw(
                    f"adaptive_lr status={lr_meta.get('status')} "
                    f"global_m={lr_meta.get('global_m')} "
                    f"lr={lr_meta.get('lr')} sat={lr_meta.get('sat_frac')} "
                    f"Δmean16={lr_meta.get('delta_mean16')} efit_spread={lr_meta.get('efit_spread')}"
                )
            except Exception as _lr_e:
                self._last_lr = {'ROCK': 1.0, 'PAPER': 1.0, 'SCISSORS': 1.0}
                self._log_raw(f'adaptive_lr failed: {_lr_e}')

            # One knob writer per generation: GP-EI (heavy) XOR playbook
            # tunables of cards that actually played. Replicator fitness /
            # simplex still ran above for logs + adaptive LR. Type-wide
            # replicator spray, mutation, GA deploy, and PSO are off.
            every = max(1, int(getattr(self, 'LEARN_EVERY_HEAVY', 10)))
            try:
                from config import Config
                if getattr(Config, 'FAST_SIM', False):
                    every = 3
            except Exception:
                pass
            heavy = (n >= int(getattr(self, 'MIN_GAMES_GA', 8))
                     and (int(self.GENERATION) % every == 0))
            try:
                from config import Config
                if getattr(Config, 'FAST_SIM', False):
                    self._fast_heavy_n = int(getattr(self, '_fast_heavy_n', 0)) + 1
                    heavy = (self._fast_heavy_n % max(1, every) == 0
                             and n >= int(getattr(self, 'MIN_GAMES_GA', 8)))
            except Exception:
                pass

            try:
                import strategies.playbook as _pb
                _pb.EXPLORE_TYPES = {
                    t for t in ('ROCK', 'PAPER', 'SCISSORS')
                    if float(fitness.get(t, 0) or 0) < float(f_bar or 0)
                }
            except Exception:
                pass

            try:
                self._bo_record()
            except Exception as _bor:
                self._log_raw('BO record failed: %s' % _bor)

            ei_done = set()
            writer = None
            if heavy:
                try:
                    before = len(self.last_changes)
                    ei_done = self._bo_ei_step() or set()
                    ei_n = len(self.last_changes) - before
                    self._log_raw('GP-EI changes=%d cards=%d' % (ei_n, len(ei_done)))
                    if ei_done:
                        writer = 'gp-ei'
                except Exception as _boe:
                    ei_done = set()
                    self._log_raw('GP-EI failed: %s' % _boe)

            try:
                self._optimise_playbook(fitness, f_bar, wins, skip=ei_done)
                writer = ('gp-ei+playbook' if ei_done else 'playbook')
            except Exception as _pb:
                self._log_raw(f'playbook strategy pass failed: {_pb}')
                if writer is None:
                    writer = 'none'

            ts = REF_TEAM_SIZE
            try:
                ww = getattr(self, 'w', None)
                if ww is not None and getattr(ww, 'teamSize', None):
                    ts = int(ww.teamSize)
            except Exception:
                pass
            try:
                import strategies.playbook as _pb
                _pb.set_match_context(ts)
            except Exception:
                pass
            if heavy:
                try:
                    self._map_archive_step(fitness, wipe_risk, share)
                except Exception as _me:
                    self._log_raw('MAP-Elites archive failed: %s' % _me)
            else:
                try:
                    self._map_fill_live(fitness, wipe_risk, ts)
                except Exception as _me:
                    self._log_raw('MAP-Elites live fill failed: %s' % _me)

            self._log_raw(
                'knob writer=%s gen=%d heavy=%s n=%d' % (
                    writer or 'none', self.GENERATION, int(bool(heavy)), n))

            # State inference + bound evolution (structural learning)
            self._infer_state_strategies()
            self._evolve_bounds(wins, n, weak, strong)
        except Exception as e:
            self._log_raw(f'optimise nudges failed: {e}\n{traceback.format_exc()}')

        self._log_changes(sample, wins, avg_dur)
        # Dirty-only persist. force=True rewrites 90+ JSON files and is the
        # 0.7–1.3s persist spike. Full rewrite only every 40 games.
        try:
            from optimizer import motion as _motion
            _mc = _motion.apply(log=self._log_raw,
                                games_seen=int(getattr(self, 'games_seen', 0) or 0))
            if _mc:
                self.last_changes = list(self.last_changes or []) + list(_mc)
        except Exception as _me:
            try:
                self._log_raw('motion-balance failed: %s' % _me)
            except Exception:
                pass

        if persist:
            try:
                gs = int(getattr(self, 'games_seen', 0) or 0)
                self._persist_type_config(force=(gs > 0 and gs % 200 == 0))
            except Exception as e:
                self._log_raw(f'persist failed: {e}\n{traceback.format_exc()}')
        try:
            self._log_raw('timing optimise=%.0fms persist_incl gen=%d' % (
                (_time.perf_counter() - _t_opt) * 1000.0,
                int(getattr(self, 'GENERATION', 0) or 0)))
        except Exception:
            pass
        
        if not getattr(self, 'SINGLE_KNOB_WRITER', True):
            try:
                self._optimise_last_man_endgame()
            except Exception as _lm:
                self._log_raw('last-man endgame failed: %s' % _lm)
        else:
            self._log_raw('single writer: skip last-man overlay nudges')
        # CLEAR_HUNT endgame: shorter finishes via split assignment
        try:
            metrics = getattr(getattr(self, 'w', None), 'metrics', None)
            if metrics is not None:
                clear_kills = [c for c in metrics.conversions if c.get('game_state') == 'CLEAR_HUNT']
                splits = sum(int(c.get('clear_split_event', 0) or 0) for c in clear_kills)
                if clear_kills and splits >= 1:
                    for tname in ('ROCK', 'PAPER', 'SCISSORS'):
                        self._nudge_type(tname, 'clear_spread_weight', +1, 'endgame split active', strength=0.6)
                        self._nudge_type(tname, 'clear_finish_speed', +1, 'endgame faster finish', strength=0.6)
            ww = getattr(self, 'w', None)
            if ww is not None and getattr(ww, '_endgame_start_rc', None) is not None:
                eg = ww.runcount - ww._endgame_start_rc
                wt = getattr(ww, '_endgame_type', None)
                fps = max(1, int(getattr(_config(), 'FPS', 60)))
                # PREDATOR (winner type): push hard for parallel short clear
                if wt is not None and eg > fps * 8:  # predator: long endgame is a failure
                    tn = wt.name if hasattr(wt, 'name') else str(wt)
                    strength = min(2.2, 0.6 + eg / (fps * 32))
                    self._nudge_type(tn, 'clear_spread_weight', +1, 'predator short-endgame', strength=strength)
                    self._nudge_type(tn, 'clear_finish_speed', +1, 'predator short-endgame', strength=strength)
                    self._nudge_type(tn, 'clear_reassign_dist', +1, 'predator peel', strength=strength * 0.9)
                    self._nudge_type(tn, 'voronoi_balance', +1, 'predator balance', strength=strength * 0.9)
                    self._nudge_type(tn, 'voronoi_weight', +1, 'predator voronoi', strength=strength * 0.8)
                    self._nudge_type(tn, 'delaunay_overflow', +1, 'predator delaunay', strength=strength * 0.7)
                    self._nudge_type(tn, 'cohesion_weight', -1, 'predator less pack', strength=strength * 0.6)
                    self._nudge_type(tn, 'clear_voronoi_cap_slack', -1, 'predator tighter cap', strength=0.8)
                    imb = getattr(ww, '_endgame_voronoi_imbalance', 0) or 0
                    if imb > 1.2:
                        self._nudge_type(tn, 'voronoi_balance', +1, 'voronoi imbalance', strength=1.2)
                # PREY of this hunter only: maximise endgame length
                if wt is not None:
                    hunter_name = wt.name if hasattr(wt, 'name') else str(wt)
                    prey_t = TYPE_DEFAULTS.get(hunter_name, {}).get('prey')
                    if prey_t:
                        if eg > fps * 10:
                            # Already lasting — reinforce what worked
                            self._nudge_type(prey_t, 'escape_bonus', +1, 'prey long-endgame', strength=0.8)
                            self._nudge_type(prey_t, 'evade_turn_boost', +1, 'prey long-endgame', strength=0.7)
                            self._nudge_type(prey_t, 'fort_cover_weight', +1, 'prey long-endgame cover', strength=0.6)
                            self._nudge_type(prey_t, 'near_wipe_sep_mult', +1, 'prey long-endgame scatter', strength=0.6)
                        elif eg < fps * 6:
                            # Died fast — need more evade / cover
                            self._nudge_type(prey_t, 'escape_bonus', +1, 'prey short-endgame evade', strength=1.2)
                            self._nudge_type(prey_t, 'evade_threshold', -1, 'prey evade sooner', strength=1.0)
                            self._nudge_type(prey_t, 'fear_close_mult', +1, 'prey short-endgame fear', strength=0.9)
                            self._nudge_type(prey_t, 'fort_hide_bias', +1, 'prey short-endgame hide', strength=0.8)
                            self._nudge_type(prey_t, 'near_wipe_evade_mult', +1, 'prey short-endgame wipe', strength=0.8)
                            self._nudge_type(prey_t, 'small_escape_mult', +1, 'prey short-endgame small', strength=0.7)

        except Exception as _eg_err:
            try:
                self._log_raw(f'endgame optimise skip: {_eg_err}')
            except Exception:
                pass

        # Predator-strike spacing: multi-kills → victim type needs more sep_distance
        try:
            metrics = getattr(getattr(self, 'w', None), 'metrics', None)
            if metrics is not None:
                # Close open strike
                if getattr(metrics, '_strike_count', 0) >= 2:
                    metrics.strike_events.append({
                        'predator_id': metrics._strike_predator_id,
                        'victim_type': metrics._strike_victim_type,
                        'conversions': metrics._strike_count,
                        'rc': metrics._strike_last_rc,
                    })
                    metrics._strike_count = 0
                strikes = list(getattr(metrics, 'strike_events', []) or [])
                # Also from conversion rows
                multi = [c for c in metrics.conversions if int(c.get('strike_multi', 0) or 0) == 1]
                by_victim = {'ROCK': [], 'PAPER': [], 'SCISSORS': []}
                for c in multi:
                    # victim is loser
                    # conversion may not have loser type field - use total from strike_events
                    pass
                for s in strikes:
                    vt = s.get('victim_type')
                    if vt in by_victim:
                        by_victim[vt].append(int(s.get('conversions', 0) or 0))
                # From multi conversion rows: group by consecutive strike_size peaks
                for c in metrics.conversions:
                    if int(c.get('strike_size', 0) or 0) >= 2:
                        # Infer victim: winner's prey
                        wt = c.get('winner_type', '')
                        prey_map = {'ROCK': 'SCISSORS', 'PAPER': 'ROCK', 'SCISSORS': 'PAPER'}
                        vt = prey_map.get(wt)
                        if vt and vt in by_victim:
                            by_victim[vt].append(int(c.get('strike_size', 0)))
                for vt, sizes in by_victim.items():
                    if not sizes:
                        continue
                    avg_s = sum(sizes) / len(sizes)
                    max_s = max(sizes)
                    self._log_raw(
                        f"strike_spacing {vt}: multi_events={len(sizes)} avg_size={avg_s:.2f} max={max_s}"
                    )
                    if max_s >= 3 or avg_s >= 2.3:
                        # Tight packs getting multi-killed — spread out
                        strength = min(2.0, 0.5 + 0.25 * (avg_s - 1))
                        self._nudge_type(vt, 'sep_distance', +1, 'strike multi-kill sep', strength=strength)
                        self._nudge_type(vt, 'overcrowd_sep_boost', +1, 'strike multi-kill sep', strength=strength * 0.8)
                        self._nudge_type(vt, 'asymmetric_sep_front', +1, 'strike multi-kill sep', strength=strength * 0.6)
                        self._nudge_type(vt, 'small_sep_mult', +1, 'strike multi-kill sep', strength=strength * 0.5)
                        self._nudge_type(vt, 'near_wipe_sep_mult', +1, 'strike multi-kill sep', strength=0.5)
                    elif max_s <= 1 and len(sizes) == 0:
                        pass  # no multi strikes
                # Types with zero multi-strikes as victims but low win rate → can pack tighter
                for vt in ('ROCK', 'PAPER', 'SCISSORS'):
                    if not by_victim[vt]:
                        # mild: allow slightly tighter spacing for coordination
                        self._nudge_type(vt, 'sep_distance', -1, 'no multi-strike tighter', strength=0.25)
        except Exception as _st_err:
            try:
                self._log_raw(f'strike_spacing optimise skip: {_st_err}')
            except Exception:
                pass


        
        # Ally-protect: reduce knock-into-predator conversions for victim types
        try:
            metrics = getattr(getattr(self, 'w', None), 'metrics', None)
            if metrics is not None:
                knocks = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
                total_v = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
                prey_of = {'ROCK': 'SCISSORS', 'PAPER': 'ROCK', 'SCISSORS': 'PAPER'}
                for c in metrics.conversions:
                    wt = c.get('winner_type', '')
                    vt = prey_of.get(wt)
                    if vt:
                        total_v[vt] = total_v.get(vt, 0) + 1
                        if int(c.get('ally_knock_into_fear', 0) or 0) == 1:
                            knocks[vt] = knocks.get(vt, 0) + 1
                for vt in ('ROCK', 'PAPER', 'SCISSORS'):
                    n = total_v.get(vt, 0)
                    k = knocks.get(vt, 0)
                    if n >= 3 and k / max(1, n) >= 0.15:
                        rate = k / n
                        strength = min(1.8, 0.5 + rate * 2)
                        self._log_raw(f"ally_knock {vt}: {k}/{n} ({rate:.2f}) → boost protect")
                        self._nudge_type(vt, 'ally_protect_weight', +1, 'ally_knock protect', strength=strength)
                        self._nudge_type(vt, 'ally_protect_radius', +1, 'ally_knock protect', strength=strength * 0.7)
                        self._nudge_type(vt, 'sep_distance', +1, 'ally_knock spacing', strength=strength * 0.4)
                    elif n >= 5 and k == 0:
                        self._nudge_type(vt, 'ally_protect_weight', -1, 'ally_knock low', strength=0.2)
        except Exception as _ak_err:
            try:
                self._log_raw(f'ally_knock optimise skip: {_ak_err}')
            except Exception:
                pass

        
        # Dynamic threat weighting: victims with low threat response when killed → boost
        try:
            metrics = getattr(getattr(self, 'w', None), 'metrics', None)
            if metrics is not None:
                prey_of = {'ROCK': 'SCISSORS', 'PAPER': 'ROCK', 'SCISSORS': 'PAPER'}
                by_v = {'ROCK': [], 'PAPER': [], 'SCISSORS': []}
                for c in metrics.conversions:
                    wt = c.get('winner_type', '')
                    vt = prey_of.get(wt)
                    if not vt:
                        continue
                    tw = float(c.get('threat_weight_avg') or 0)
                    by_v[vt].append(tw)
                for vt, vals in by_v.items():
                    if len(vals) < 3:
                        continue
                    avg = sum(vals) / len(vals)
                    self._log_raw(f"threat_weight {vt}: avg={avg:.3f} n={len(vals)}")
                    if avg < 0.45:
                        # Not weighting threats enough before death
                        self._nudge_type(vt, 'threat_weight_base', +1, 'threat_weight low', strength=0.9)
                        self._nudge_type(vt, 'threat_dist_exp', +1, 'threat_weight low', strength=0.7)
                        self._nudge_type(vt, 'threat_count_scale', +1, 'threat_weight low', strength=0.6)
                        self._nudge_type(vt, 'escape_bonus', +1, 'threat_weight low', strength=0.5)
                    elif avg > 1.8:
                        # Over-reacting — slightly reduce
                        self._nudge_type(vt, 'threat_weight_base', -1, 'threat_weight high', strength=0.35)
                        self._nudge_type(vt, 'threat_front_scale', -1, 'threat_weight high', strength=0.25)
        except Exception as _tw_err:
            try:
                self._log_raw(f'threat_weight optimise skip: {_tw_err}')
            except Exception:
                pass

        
        # No-corner-herd: penalize finishing prey in corners while predators still exist
        try:
            metrics = getattr(getattr(self, 'w', None), 'metrics', None)
            if metrics is not None:
                by_w = {'ROCK': {'n': 0, 'corner': 0}, 'PAPER': {'n': 0, 'corner': 0}, 'SCISSORS': {'n': 0, 'corner': 0}}
                for c in metrics.conversions:
                    wt = c.get('winner_type', '')
                    if wt not in by_w:
                        continue
                    by_w[wt]['n'] += 1
                    if int(c.get('corner_herd_while_fear', 0) or 0) == 1:
                        by_w[wt]['corner'] += 1
                # Also last-prey corner finishes while fear (worst unherd failure)
                last_corner = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
                for c in metrics.conversions:
                    wt = c.get('winner_type', '')
                    if wt not in last_corner:
                        continue
                    if int(c.get('last_prey_with_fear', 0) or 0) == 1 and int(c.get('corner_herd_while_fear', 0) or 0) == 1:
                        last_corner[wt] += 1
                for wt, d in by_w.items():
                    if d['n'] < 3:
                        continue
                    rate = d['corner'] / d['n']
                    self._log_raw(f"unherd {wt}: corner_herd={d['corner']}/{d['n']} ({rate:.2f}) last_prey_corner={last_corner.get(wt, 0)}")
                    if rate >= 0.2 or last_corner.get(wt, 0) >= 1:
                        strength = min(2.0, 0.5 + rate * 2 + 0.3 * last_corner.get(wt, 0))
                        self._nudge_type(wt, 'no_corner_herd', +1, 'unherd avoid corner', strength=strength)
                        self._nudge_type(wt, 'open_field_bias', +1, 'unherd open field', strength=strength * 0.8)
                        self._nudge_type(wt, 'corner_zone_margin', +1, 'unherd corner margin', strength=strength * 0.5)
                        self._nudge_type(wt, 'finish_bonus', -1, 'unherd less finish', strength=strength * 0.4)
                        self._nudge_type(wt, 'state_last_prey_risk', -1, 'unherd last-prey restraint', strength=strength * 0.35)
                    elif rate == 0 and d['n'] >= 8:
                        self._nudge_type(wt, 'no_corner_herd', -1, 'unherd rare', strength=0.2)
        except Exception as _ch_err:
            try:
                self._log_raw(f'corner_herd optimise skip: {_ch_err}')
            except Exception:
                pass

        return self.last_changes

    SIMPLEX_ETA = 0.35
    SIMPLEX_MU = 0.045
    SIMPLEX_TRACK = 0.12

    def _simplex_path(self):
        try:
            from optimizer.paths import log_path
            return log_path('replicator_simplex.json')
        except Exception:
            return 'optimizer/metrics/replicator_simplex.json'

    def _load_simplex(self):
        import json, os
        types = ('ROCK', 'PAPER', 'SCISSORS')
        path = self._simplex_path()
        x = {t: 1.0 / 3.0 for t in types}
        try:
            if os.path.isfile(path):
                raw = json.loads(open(path, encoding='utf-8').read())
                bag = raw.get('x') if isinstance(raw, dict) else raw
                if isinstance(bag, dict):
                    for t in types:
                        x[t] = max(1e-4, float(bag.get(t, x[t])))
                xb = raw.get('xbar') if isinstance(raw, dict) else None
                if isinstance(xb, dict):
                    self._simplex_xbar = {
                        t: max(1e-4, float(xb.get(t, 1.0 / 3.0))) for t in types
                    }
        except Exception:
            pass
        s = sum(x.values()) or 1.0
        self._simplex = {t: x[t] / s for t in types}

    def _save_simplex(self, extra=None):
        import json, os
        path = self._simplex_path()
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            payload = {
                'x': dict(self._simplex),
                'pstar': {'ROCK': 1.0 / 3.0, 'PAPER': 1.0 / 3.0, 'SCISSORS': 1.0 / 3.0},
                'l1': float(getattr(self, '_simplex_l1', 0.0) or 0.0),
                'f': dict(getattr(self, '_simplex_f', {}) or {}),
                'fbar': float(getattr(self, '_simplex_fbar', 0.0) or 0.0),
            }
            if extra:
                payload.update(extra)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, indent=2)
        except Exception as e:
            try:
                self._log_raw('simplex save failed: %s' % e)
            except Exception:
                pass

    def _replicator_step_simplex(self, A, emp_share, scalar_fit=None):
        """
        Discrete replicator–mutator on the type simplex.
        f = A x  (payoff), blended with scalar fitness if A is sparse.
        x' ∝ x ⊙ exp(η (f − f̄)) then (1−μ)x' + μ/3.
        """
        import math
        types = ('ROCK', 'PAPER', 'SCISSORS')
        x = dict(self._simplex or {t: 1.0 / 3.0 for t in types})
        s = sum(x.values()) or 1.0
        x = {t: max(1e-4, x[t] / s) for t in types}

        pair_n = 0
        ax = {t: 0.0 for t in types}
        if A:
            for t in types:
                row = A.get(t) or {}
                ax[t] = sum(float(row.get(u, 0) or 0) * x[u] for u in types)
                for u in types:
                    if t != u and abs(float(row.get(u, 0) or 0)) > 1e-9:
                        pair_n += 1
        sc = scalar_fit or {}
        if pair_n < 4:
            f = {t: float(sc.get(t, 0) or 0) for t in types}
            src = 'scalar'
        else:
            f = {}
            for t in types:
                f[t] = 0.70 * ax[t] + 0.30 * float(sc.get(t, 0) or 0)
            src = 'Ax'

        fbar = sum(x[t] * f[t] for t in types)
        eta = float(getattr(self, 'SIMPLEX_ETA', 0.35))
        mu = float(getattr(self, 'SIMPLEX_MU', 0.045))
        track = float(getattr(self, 'SIMPLEX_TRACK', 0.12))
        y = {}
        for t in types:
            grow = x[t] * math.exp(eta * (f[t] - fbar))
            y[t] = (1.0 - mu) * grow + mu / 3.0
            emp = float((emp_share or {}).get(t, x[t]) or x[t])
            y[t] = (1.0 - track) * y[t] + track * max(1e-4, emp)
        z = sum(y.values()) or 1.0
        x2 = {t: y[t] / z for t in types}
        pstar = 1.0 / 3.0
        l1 = sum(abs(x2[t] - pstar) for t in types)
        xbar = dict(getattr(self, '_simplex_xbar', None) or x2)
        beta = 0.08
        xbar = {t: (1.0 - beta) * float(xbar.get(t, pstar)) + beta * x2[t] for t in types}
        zb = sum(xbar.values()) or 1.0
        xbar = {t: xbar[t] / zb for t in types}
        l1_bar = sum(abs(xbar[t] - pstar) for t in types)
        self._simplex = x2
        self._simplex_xbar = xbar
        self._simplex_f = f
        self._simplex_fbar = fbar
        self._simplex_l1 = l1
        self._simplex_src = src
        self._save_simplex({
            'src': src, 'emp': dict(emp_share or {}),
            'xbar': xbar, 'l1_bar': l1_bar,
        })
        self._log_raw(
            'simplex src=%s x=[R%.3f P%.3f S%.3f] xbar=[R%.3f P%.3f S%.3f] '
            'f=[R%.3f P%.3f S%.3f] fbar=%.3f ||x-p*||_1=%.3f ||xbar-p*||_1=%.3f mu=%.3f' % (
                src, x2['ROCK'], x2['PAPER'], x2['SCISSORS'],
                xbar['ROCK'], xbar['PAPER'], xbar['SCISSORS'],
                f['ROCK'], f['PAPER'], f['SCISSORS'],
                fbar, l1, l1_bar, mu))
        return x2, f, fbar

    def _replicator_fitness(self, wins, n, wipe_risk, avg_dur):
        """Fitness f_i and population share x_i for replicator update.

        Priorities (in order):
          1. Win rate
          2. Heavy penalty for killing last prey while predators still exist (auto-lose risk)
          3. Prefer shorter endgames / decisive games (not ultra-spam short)
        """
        types = ('ROCK', 'PAPER', 'SCISSORS')
        win_rate = {t: wins.get(t, 0) / max(1, n) for t in types}
        # Wipe: last-meal convert while fear lives. Duration is the proxy for
        # "nobody popped the last 2–3" — short windows mean someone did.
        wipe_pen = {}
        for t in types:
            wr = min(1.0, max(0.0, float(wipe_risk.get(t, 0) or 0)))
            wipe_pen[t] = min(0.45, 0.90 * wr)

        import math as _m
        # FAST_SIM games are 1–8s of tick time; live games 20–50s.
        ad = float(avg_dur or 0)
        center, span, short = (6.0, 4.0, 2.5) if ad < 12.0 else (25.0, 16.0, 8.0)
        dur_term = 0.32 * _m.tanh((ad - center) / span)
        if ad < short:
            dur_term -= 0.20

        # Dual endgame objective:
        #   Predator/winner: LEAST endgame time (penalty for long CLEAR_HUNT)
        #   Prey that was cleared: MOST survival time (bonus for long endgame when lost)
        eg_pen = {t: 0.0 for t in types}
        prey_survive_bonus = {t: 0.0 for t in types}
        try:
            games = getattr(self, '_last_sample_games', None) or []
            eg_sums = {t: [] for t in types}       # endgame duration when t won
            prey_eg = {t: [] for t in types}       # endgame duration when t did NOT win (was prey/cleared)
            prey_of = {n: d.get('prey') for n, d in TYPE_DEFAULTS.items()}
            for g in games:
                w = g.get('winner', '')
                try:
                    eg = float(g.get('endgame_seconds', 0) or 0)
                except Exception:
                    eg = 0.0
                if eg <= 0:
                    continue
                if w in eg_sums:
                    eg_sums[w].append(eg)
                # Only the winner's prey type was in that endgame
                pt = prey_of.get(w)
                if pt in prey_eg:
                    prey_eg[pt].append(eg)
            for t in types:
                if eg_sums[t]:
                    mean_eg = sum(eg_sums[t]) / len(eg_sums[t])
                    # Winners: short endgame is good
                    if mean_eg > 35:
                        eg_pen[t] = min(0.40, 0.012 * (mean_eg - 35))
                    elif mean_eg < 15:
                        eg_pen[t] = -0.06  # strong bonus for fast parallel clear
                    elif mean_eg < 25:
                        eg_pen[t] = -0.02
                if prey_eg[t]:
                    mean_ps = sum(prey_eg[t]) / len(prey_eg[t])
                    # Losers/prey: long survival under clear is good
                    if mean_ps > 40:
                        prey_survive_bonus[t] = min(0.20, 0.006 * (mean_ps - 40))
                    elif mean_ps < 12:
                        prey_survive_bonus[t] = -0.04  # died too fast — need more evade
        except Exception:
            pass

        fitness = {}
        for t in types:
            wr = min(1.0, max(0.0, float(wipe_risk.get(t, 0) or 0)))
            # Duration still counts; wipe only scales it down.
            dur_t = dur_term * (1.0 - 0.65 * wr)
            fitness[t] = (
                0.55 * win_rate[t]
                - wipe_pen[t]
                + dur_t
                - eg_pen[t]
                + prey_survive_bonus[t]
            )
        total_w = sum(wins.get(t, 0) for t in types) or 1
        # Floor high enough that a 1-win type still gets help (Paper overnight: 1/80).
        floor = 0.16 if min(wins.values()) <= max(2, int(0.08 * total_w)) else 0.05
        share = {t: max(floor, wins.get(t, 0) / total_w) for t in types}
        ssum = sum(share.values())
        share = {t: share[t] / ssum for t in types}
        f_bar = sum(share[t] * fitness[t] for t in types)
        return fitness, share, f_bar

    def _replicator_update(self, fitness, share, f_bar, wipe_risk, avg_team, avg_dur):
        """Apply ẋ_i = x_i (f_i - f̄) across ALL strategy keys with signed directions."""
        self._ensure_state_keys()
        types = ('ROCK', 'PAPER', 'SCISSORS')
        pressure = {t: fitness[t] - f_bar for t in types}

        # +1 direction = "more of this helps underperformers"; -1 = "less when dominant"
        # Every STRATEGY_KEY gets a role so nothing is left unoptimized
        HELP_DIR = {
            'near_target_aggro': +1,
            'finish_bonus': +1,
            'cluster_bonus': +1,
            'fear_close_mult': +1,
            'escape_bonus': +1,
            'cohesion_weight': +1,
            'pack_hunt_mult': +1,
            'focus_bonus': +1,
            'focus_fire_mult': +1,
            'support_join': +1,
            'target_lock_ttl': +1,
            'target_lock_bonus': +1,
            'target_switch_margin': -1,
            'scatter_threshold': +1,
            'hunt_advantage': +1,
            'prey_reserve': +1,
            'prey_reserve_penalty': -1,
            'clear_finish_mult': +1,
            'small_unit_threshold': +1,
            'small_raid_bonus': +1,
            'small_escape_mult': +1,
            'small_sep_mult': +1,
            'sep_distance': +1,
            'sep_softness': +1,
            'avoid_weight': +1,
            'avoid_lookahead': +1,
            'small_aggro_mult': +1,
            'solo_finish_mult': +1,
            'outnumbered_fear_mult': +1,
            'flank_bias': +1,
            'predict_lookahead': +1,
            'evade_threshold': -1,
            'evade_speed_mult': -1,
            'evade_brake': +1,
            'evade_reverse_risk': -1,
            'evade_turn_boost': +1,
            'evade_predict': +1,
            'evade_sep_boost': +1,
            'late_speed_mult': +1,
            'late_turn_mult': +1,
            'late_count_threshold': +1,
            'team_scale_aggro': +1,
            'team_scale_cohesion': +1,
            'team_scale_fear': +1,
            'team_scale_pack': +1,
            'state_clear_hunt': +1,
            'state_last_prey_risk': -1,
            'state_no_prey_fear': -1,
            'state_outnumbered': +1,
            'state_small_unit': +1,
            'state_contested': +1,
            'fort_cover_weight': +1,
            'fort_hide_bias': +1,
            'fort_ambush_bonus': +1,
            'pincer_weight': +1,
            'pincer_spread': +1,
            'pincer_min_friends': +1,
            'pincer_switch_hysteresis': +1,
            'pincer_switch_cooldown': +1,
            'pincer_switch_gain': +1,
            'overcrowd_sep_boost': +1,
            'overcrowd_cohesion_scale': -1,
            'overcrowd_threshold': +1,
            'asymmetric_sep_front': +1,
            'asymmetric_sep_rear': +1,
            'speed_match_weight': +1,
            'offset_pursue_dist': +1,
            'offset_pursue_gain': +1,
            'arrive_radius': +1,
            'arrive_slow': +1,
            'wander_strength': +1,
            'wander_rate': +1,
            'clear_spread_weight': +1,
            'clear_split_threshold': +1,
            'clear_finish_speed': +1,
            'clear_reassign_dist': +1,
            'voronoi_weight': +1,
            'voronoi_balance': +1,
            'voronoi_recompute_interval': -1,
            'voronoi_overflow_threshold': -1,
            'clear_voronoi_cap_slack': -1,
            'clear_voronoi_predict': +1,
            'delaunay_overflow': +1,
            'delaunay_k': +1,
            'near_wipe_threshold': +1,
            'near_wipe_sep_mult': +1,
            'near_wipe_evade_mult': +1,
            'near_wipe_fort_mult': +1,
            'near_wipe_cohesion': -1,
            'state_near_wipe': +1,
            'ally_protect_weight': +1,
            'ally_protect_radius': +1,
            'threat_weight_base': +1,
            'threat_dist_exp': +1,
            'threat_count_scale': +1,
            'threat_closing_scale': +1,
            'threat_front_scale': +1,
            'no_corner_herd': +1,
            'open_field_bias': +1,
            'corner_zone_margin': +1,
            'hide_among_prey_weight': +1,
            'hide_among_prey_radius': +1,
            'hide_among_prey_min': +1,
        }

        CURB_KEYS = {
            'near_target_aggro', 'finish_bonus', 'cluster_bonus', 'pack_hunt_mult',
            'focus_bonus', 'focus_fire_mult', 'clear_finish_mult', 'solo_finish_mult',
            'small_raid_bonus', 'small_aggro_mult', 'state_clear_hunt', 'flank_bias',
            'support_join', 'hunt_advantage',
        }
        WIPE_CURB = {
            'near_target_aggro', 'finish_bonus', 'focus_bonus', 'clear_finish_mult',
            'solo_finish_mult', 'state_clear_hunt', 'state_last_prey_risk',
            'state_no_prey_fear', 'small_raid_bonus',
        }
        WIPE_HELP = {
            'prey_reserve', 'escape_bonus', 'fear_close_mult', 'state_last_prey_risk',
            'state_no_prey_fear', 'evade_threshold', 'evade_brake', 'outnumbered_fear_mult',
            'hide_among_prey_weight', 'hide_among_prey_radius',
            'last_meal_rebound',
        }

        try:
            import strategies.playbook as _pb
            _pb.EXPLORE_TYPES = {t for t in types if pressure[t] < 0}
        except Exception:
            pass

        for t in types:
            pr = pressure[t]
            w = share[t] * pr
            if abs(w) < 0.008:
                continue
            strength = abs(w) * 8.0
            if pr < 0:
                # Evolve the loser. Do not touch the winner's knobs.
                skip_hunt = float(wipe_risk.get(t, 0) or 0) >= 0.35
                HELP_KEYS = (
                    'escape_bonus', 'fear_close_mult', 'prey_reserve',
                    'sep_distance', 'fort_cover_weight', 'hide_among_prey_weight',
                    'state_last_prey_risk', 'outnumbered_fear_mult',
                    'pack_hunt_mult', 'near_target_aggro', 'cohesion_weight',
                    'focus_fire_mult', 'hunt_advantage', 'clear_finish_mult',
                    'flank_bias', 'pincer_weight',
                )
                boost = 1.6 if share.get(t, 0) < 0.22 else 1.0
                for key in HELP_KEYS:
                    direction = HELP_DIR.get(key, +1)
                    if skip_hunt and key in CURB_KEYS:
                        continue
                    self._nudge_type(
                        t, key, direction,
                        f'replicator help {t} p={pr:.3f}',
                        strength=strength * boost)
            else:
                # Success is not nerfed. Log only.
                self._log_raw(
                    'replicator keep-winner %s p=%+.3f share=%.3f' % (
                        t, pr, share.get(t, 0)))

            wr = min(1.0, max(0.0, float(wipe_risk.get(t, 0) or 0)))
            if wr >= 0.25:
                ws = min(1.2, 0.35 + 0.85 * wr)
                help_only = WIPE_HELP
                # Hunt-curb only on losers. Winners keep their offense.
                if pr < 0:
                    curb_only = set(WIPE_CURB) - set(help_only)
                    for key in curb_only:
                        self._nudge_type(t, key, -1, f'replicator wipe-curb r={wr:.2f}', strength=ws)
                for key in help_only:
                    d = HELP_DIR.get(key, +1)
                    self._nudge_type(t, key, d, f'replicator wipe-help r={wr:.2f}', strength=ws)

        if avg_team >= 20:
            for t in types:
                self._nudge_type(t, 'team_scale_cohesion', +1, 'replicator large-team', strength=0.8)
                self._nudge_type(t, 'sep_distance', +1, 'replicator large-team sep', strength=0.6)
        elif avg_team <= 8:
            for t in types:
                self._nudge_type(t, 'clear_finish_mult', +1, 'replicator small-team', strength=0.8)
                self._nudge_type(t, 'state_small_unit', +1, 'replicator small-team', strength=0.8)
        if avg_dur > 200:
            for t in types:
                if pressure[t] < 0:
                    self._nudge_type(t, 'finish_bonus', +1, 'replicator slow-game', strength=1.0)
                    self._nudge_type(t, 'state_clear_hunt', +1, 'replicator slow-game', strength=0.8)
                    self._nudge_type(t, 'clear_finish_speed', +1, 'replicator slow-game clear', strength=0.9)
                    self._nudge_type(t, 'voronoi_weight', +1, 'replicator slow-game voronoi', strength=0.7)
                    self._nudge_type(t, 'delaunay_overflow', +1, 'replicator slow-game delaunay', strength=0.6)

        # Last-meal restraint for LOSERS only. Winners keep finish knobs.
        for t in types:
            wr = float(wipe_risk.get(t, 0) or 0)
            if wr >= 0.35 and pressure[t] < 0:
                self._nudge_type(t, 'prey_reserve', +1, 'wipe-avoid reserve', strength=min(1.4, 0.9 * wr))
                self._nudge_type(t, 'state_last_prey_risk', +1, 'wipe-avoid last-prey state', strength=min(1.2, 0.8 * wr))
                self._nudge_type(t, 'near_target_aggro', -1, 'wipe-avoid less aggro on last', strength=min(1.0, 0.35 * wr))

    def _sanitize_defaults(self):
        """Clamp all TYPE_DEFAULTS into STRATEGY_BOUNDS + absolute safety."""
        ABS = {
            'near_target_aggro': (1.0, 4.5), 'finish_bonus': (0.3, 2.5),
            'cluster_bonus': (0.2, 2.2), 'pack_hunt_mult': (0.5, 3.5),
            'clear_finish_mult': (1.2, 4.0), 'focus_bonus': (0.25, 1.8),
            'focus_fire_mult': (1.0, 2.6), 'small_raid_bonus': (1.0, 3.0),
            'solo_finish_mult': (1.0, 3.0), 'small_aggro_mult': (0.8, 1.8),
            'state_clear_hunt': (0.8, 2.8), 'predict_lookahead': (4.0, 28.0),
            'avoid_lookahead': (5.0, 40.0), 'sep_distance': (1.2, 10.0),
            'target_lock_ttl': (12, 120), 'fear_close_mult': (1.0, 3.8),
            'escape_bonus': (0.2, 1.5), 'cohesion_weight': (0.1, 1.1),
            'flank_bias': (0.2, 1.4), 'support_join': (0.15, 1.2),
            'hunt_advantage': (0.7, 1.8), 'outnumbered_fear_mult': (1.0, 2.8),
            'state_last_prey_risk': (0.2, 1.0), 'state_no_prey_fear': (0.08, 0.9),
            'state_outnumbered': (0.8, 2.0), 'state_small_unit': (0.8, 2.0),
            'state_contested': (0.6, 1.4), 'late_speed_mult': (1.0, 1.5),
            'late_turn_mult': (1.0, 1.4), 'team_scale_aggro': (-0.3, 0.5),
            'team_scale_cohesion': (-0.25, 0.45), 'team_scale_fear': (-0.3, 0.4),
            'team_scale_pack': (-0.25, 0.4),
        }
        for tname, d in TYPE_DEFAULTS.items():
            for key, val in list(d.items()):
                if key not in STRATEGY_BOUNDS and key not in ABS:
                    continue
                try:
                    v = float(val)
                except Exception:
                    continue
                lo, hi = ABS.get(key, (None, None))
                if key in STRATEGY_BOUNDS:
                    blo, bhi, _ = STRATEGY_BOUNDS[key]
                    # Reset STRATEGY_BOUNDS if they have diverged past ABS
                    if lo is not None:
                        STRATEGY_BOUNDS[key] = (max(float(blo), lo), min(float(bhi), hi) if hi else float(bhi), STRATEGY_BOUNDS[key][2])
                    blo, bhi, _ = STRATEGY_BOUNDS[key]
                    v = max(float(blo), min(float(bhi), v))
                if lo is not None:
                    v = max(lo, min(hi, v))
                if isinstance(d[key], int) or key in ('target_lock_ttl', 'scatter_threshold', 'prey_reserve', 'small_unit_threshold', 'late_count_threshold'):
                    d[key] = int(round(v))
                else:
                    d[key] = round(v, 4)

    def _ensure_state_keys(self):

        """Ensure emergent state-multiplier keys exist on every type."""
        defaults = {
            'state_clear_hunt': 1.5,
            'state_last_prey_risk': 0.7,
            'state_no_prey_fear': 0.4,
            'state_outnumbered': 1.15,
            'state_small_unit': 1.1,
            'state_contested': 1.0,
            'fort_cover_weight': 1.0,
            'fort_hide_bias': 1.0,
            'fort_ambush_bonus': 0.8,
            'pincer_weight': 1.0,
            'pincer_spread': 0.85,
            'pincer_min_friends': 2,
            'asymmetric_sep_front': 2.0,
            'asymmetric_sep_rear': 0.55,
            'speed_match_weight': 0.35,
            'offset_pursue_dist': 2.8,
            'offset_pursue_gain': 1.0,
            'arrive_radius': 3.5,
            'arrive_slow': 0.45,
            'wander_strength': 0.18,
            'wander_rate': 0.12,
            'clear_spread_weight': 1.0,
            'clear_split_threshold': 2,
            'clear_finish_speed': 1.15,
            'clear_reassign_dist': 4.0,
            'voronoi_weight': 1.0,
            'voronoi_balance': 0.7,
            'voronoi_recompute_interval': 8,
            'voronoi_overflow_threshold': 3,
            'clear_voronoi_cap_slack': 1,
            'clear_voronoi_predict': 0.35,
            'delaunay_overflow': 1.0,
            'delaunay_k': 3,
        }
        bounds_extra = {
            'state_clear_hunt': (0.6, 2.2, 0.05),
            'state_last_prey_risk': (0.2, 1.2, 0.05),
            'state_no_prey_fear': (0.1, 1.0, 0.05),
            'state_outnumbered': (0.8, 2.0, 0.05),
            'state_small_unit': (0.8, 2.0, 0.05),
            'state_contested': (0.7, 1.4, 0.04),
            'fort_cover_weight': (0.4, 1.8, 0.05),
            'fort_hide_bias': (0.4, 1.8, 0.05),
            'fort_ambush_bonus': (0.3, 1.5, 0.05),
            'pincer_weight': (0.2, 2.2, 0.06),
            'pincer_spread': (0.4, 1.4, 0.05),
            'pincer_min_friends': (2, 4, 1),
            'asymmetric_sep_front': (1.0, 3.0, 0.06),
            'asymmetric_sep_rear': (0.2, 1.0, 0.04),
            'speed_match_weight': (0.0, 0.8, 0.04),
            'offset_pursue_dist': (1.2, 5.0, 0.15),
            'offset_pursue_gain': (0.4, 1.8, 0.05),
            'arrive_radius': (1.5, 6.0, 0.15),
            'arrive_slow': (0.2, 0.75, 0.03),
            'wander_strength': (0.0, 0.45, 0.03),
            'wander_rate': (0.04, 0.3, 0.02),
            'clear_spread_weight': (0.5, 1.0, 0.05),
            'clear_split_threshold': (1, 4, 1),
            'clear_finish_speed': (1.0, 1.45, 0.03),
            'clear_reassign_dist': (2.0, 7.0, 0.2),
            'voronoi_weight': (0.0, 1.0, 0.05),
            'voronoi_balance': (0.0, 1.0, 0.05),
            'voronoi_recompute_interval': (2, 20, 1),
            'voronoi_overflow_threshold': (1, 6, 1),
            'clear_voronoi_cap_slack': (0, 3, 1),
            'clear_voronoi_predict': (0.0, 0.8, 0.05),
            'delaunay_overflow': (0.0, 1.0, 0.1),
            'delaunay_k': (2, 5, 1),
        }
        for t in TYPE_DEFAULTS:
            for k, v in defaults.items():
                if k not in TYPE_DEFAULTS[t]:
                    TYPE_DEFAULTS[t][k] = v
        for k, b in bounds_extra.items():
            if k not in STRATEGY_BOUNDS:
                STRATEGY_BOUNDS[k] = b
            if k not in STRATEGY_KEYS:
                STRATEGY_KEYS.append(k)

    def _infer_state_strategies(self):
        """Discover which game states correlate with wipe/loss and adapt multipliers."""
        import os
        self._ensure_state_keys()
        path = StrategyOptimizer.CONV_CSV
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding='utf-8') as f:
                lines = f.read().strip().split('\n')
        except Exception:
            return
        if len(lines) < 3:
            return
        headers = lines[0].split(',')
        rows = []
        for line in lines[-400:]:
            parts = line.split(',')
            if len(parts) < len(headers):
                continue
            rows.append(dict(zip(headers, parts)))
        for tname in ('ROCK', 'PAPER', 'SCISSORS'):
            t_rows = [r for r in rows if r.get('winner_type') == tname]
            if len(t_rows) < 5:
                continue
            wipe = [r for r in t_rows if r.get('last_prey_with_fear') in ('1', '1.0')]
            clear = [r for r in t_rows if r.get('game_state') == 'CLEAR_HUNT']
            risk = [r for r in t_rows if r.get('game_state') in ('LAST_PREY_RISK', 'NO_PREY_FEAR_ALIVE')]
            wipe_rate = len(wipe) / max(1, len(t_rows))
            if wipe_rate >= 0.08:
                self._nudge_type(tname, 'state_last_prey_risk', -1, f'{tname} infer wipe_rate={wipe_rate:.2f}')
                self._nudge_type(tname, 'state_no_prey_fear', -1, f'{tname} infer avoid no-prey finish')
                self._nudge_type(tname, 'prey_reserve', +1, f'{tname} infer keep buffer')
            elif wipe_rate <= 0.02 and len(t_rows) >= 20:
                self._nudge_type(tname, 'state_clear_hunt', +1, f'{tname} infer safe clear')
            if len(clear) >= 8:
                self._nudge_type(tname, 'state_clear_hunt', +1, f'{tname} infer clear-hunt kills={len(clear)}')
            if len(risk) >= 8 and wipe_rate >= 0.05:
                self._nudge_type(tname, 'state_outnumbered', +1, f'{tname} infer risk states')
            # Fort cover learning: deaths without cover while fear present → more hide
            exposed = 0
            covered = 0
            for r in t_rows:
                if r.get('loser_was') == tname:  # we lost a unit that was this type before? skip
                    pass
                # When we convert (winner_type==tname), track if we had cover vs victim
            # When conversions happen near fort for winners under fear-heavy samples
            near_fort_wins = sum(1 for r in t_rows if r.get('winner_near_fort') in ('1', '1.0'))
            cover_wins = sum(1 for r in t_rows if r.get('winner_cover') in ('1', '1.0'))
            if len(t_rows) >= 10:
                if cover_wins / max(1, len(t_rows)) >= 0.15:
                    cur_c = float(TYPE_DEFAULTS[tname].get('fort_cover_weight', 1.0))
                    if cur_c < 1.4:
                        self._nudge_type(tname, 'fort_cover_weight', +1, f'{tname} cover wins')
                        self._nudge_type(tname, 'fort_hide_bias', +1, f'{tname} cover wins')
                if near_fort_wins / max(1, len(t_rows)) >= 0.2:
                    self._nudge_type(tname, 'fort_ambush_bonus', +1, f'{tname} fort kills')

    def _evolve_bounds(self, wins, n, weak, strong):
        """DISABLED — bound expansion caused runaway (evade_predict 118, avoid 12).
        STRATEGY_BOUNDS are fixed absolute ceilings. Values clamp to bounds only.
        """
        return


    def _count_prey_wipe_risk(self):
        """Count last-prey kills while predators still exist (auto-lose path)."""
        import os
        counts = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
        try:
            from optimizer.paths import log_path
            path = log_path('metrics_games.csv')
        except Exception:
            path = getattr(StrategyOptimizer, 'GAMES_CSV', 'metrics_games.csv')
        if not os.path.exists(path):
            return counts
        try:
            headers, lines = self._tail_csv_lines(path, 80, byte_window=200000)
            window = []
            for line in lines:
                parts = line.split(',')
                if headers and len(parts) >= 6:
                    window.append(dict(zip(headers, parts)))
            n = max(1, len(window))
            for row in window:
                for t, col in (('ROCK', 'wipe_risk_rock'),
                               ('PAPER', 'wipe_risk_paper'),
                               ('SCISSORS', 'wipe_risk_scissors')):
                    try:
                        counts[t] += int(float(row.get(col) or 0))
                    except Exception:
                        pass
            counts = {t: min(1.0, counts[t] / n) for t in counts}
        except Exception:
            pass
        return counts

    def _type_config_paths(self):
        """Candidate paths for type_config.py (cwd first – where the game runs)."""
        import os
        paths = [os.path.abspath('type_config.py')]
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            paths.append(os.path.join(here, 'type_config.py'))
        except Exception:
            pass
        # de-dupe
        out = []
        for pth in paths:
            if pth not in out:
                out.append(pth)
        return out



    def _optimise_last_man_endgame(self):
        """Last man: maximise time-to-death. Their predator: minimise it."""
        import strategies.playbook as playbook
        from config import FEAR_OF, ParticleType
        ww = getattr(self, 'w', None)
        metrics = getattr(ww, 'metrics', None) if ww is not None else None
        frames = {}
        dead = {}
        hunters = {}
        if metrics is not None:
            frames = dict(getattr(metrics, 'last_man_frames', {}) or {})
            dead = dict(getattr(metrics, 'last_man_dead', {}) or {})
            hunters = dict(getattr(metrics, 'last_man_hunter', {}) or {})
        if ww is not None:
            for k, v in (getattr(ww, '_last_man_frames', {}) or {}).items():
                frames.setdefault(k, v)
            for k, v in (getattr(ww, '_last_man_dead', {}) or {}).items():
                dead.setdefault(k, v)
            for k, v in (getattr(ww, '_last_man_hunter', {}) or {}).items():
                hunters.setdefault(k, v)
        fps = max(1, int(getattr(_config(), 'TARGET_FPS', None) or getattr(_config(), 'FPS', 60) or 60))
        prey_sids = ('LAST_MAN_RUN', 'LAST_STAND', 'LAST_MEAL_STALL', 'SURVIVE_FEAR', 'OPEN_KITE', 'ORBIT_KITE', 'BOUNCE_JUKE')
        hunt_sids = ('PACK_HUNT', 'CLEAR_SPLIT', 'DENSITY_RAID', 'CHOKE_PINCH', 'GATE_CAMP', 'WALL_POUNCE')
        prey_paths = ('escape_bonus', 'fort_cover_weight', 'near_wipe_sep_mult',
                      'hide_among_prey_weight', 'switch.hold_frames')
        hunt_paths = ('near_target_aggro', 'clear_finish_mult', 'clear_spread_weight',
                      'voronoi_weight', 'pack_hunt_mult', 'switch.hold_frames')
        n = 0
        for tname, fr in frames.items():
            fr = int(fr or 0)
            if fr <= 0:
                continue
            seconds = fr / float(fps)
            died = tname in dead
            # Prey last-man: long clock is success
            if died and seconds < 8:
                pdir, pstr, preason = +1, 1.3, 'last-man died fast'
            elif seconds >= 12:
                pdir, pstr, preason = +1, 0.7, 'last-man lasted'
            else:
                pdir, pstr, preason = +1, 0.45, 'last-man mid'
            for sid in prey_sids:
                for path in prey_paths:
                    if playbook.nudge_tunable(tname, sid, path, pdir, strength=pstr):
                        n += 1
                        self.last_changes.append('%s.%s.%s last-man +time (%.1fs %s)' % (
                            tname, sid, path, seconds, preason))
            hunter = hunters.get(tname)
            if not hunter:
                try:
                    hunter = FEAR_OF[getattr(ParticleType, tname)].name
                except Exception:
                    hunter = None
            if not hunter:
                continue
            # Predator: long last-man clock is failure
            if seconds > 10:
                hdir, hstr, hreason = +1, min(2.0, 0.6 + seconds / 20.0), 'last-man lived too long'
            elif died and seconds < 6:
                hdir, hstr, hreason = +1, 0.5, 'last-man killed fast'
            else:
                hdir, hstr, hreason = +1, 0.4, 'last-man hunt mid'
            for sid in hunt_sids:
                for path in hunt_paths:
                    if playbook.nudge_tunable(hunter, sid, path, hdir, strength=hstr):
                        n += 1
                        self.last_changes.append('%s.%s.%s hunt -time vs %s (%.1fs %s)' % (
                            hunter, sid, path, tname, seconds, hreason))
        if n:
            playbook.save_all_overlays()
            self._log_raw('last-man endgame nudges=%d types=%s' % (n, list(frames)))

    _HUNT_KNOBS = (
        'near_target_aggro', 'pack_hunt_mult', 'finish_bonus', 'focus_fire_mult',
        'pincer_weight', 'clear_finish_mult', 'small_raid_bonus', 'focus_bonus',
        'hunt_advantage', 'cluster_bonus',
    )
    _EVADE_KNOBS = (
        'escape_bonus', 'fear_close_mult', 'fort_cover_weight',
        'hide_among_prey_weight', 'sep_distance', 'outnumbered_fear_mult',
    )
    _CARE_KNOBS = (
        'prey_repel_weight', 'prey_orbit_weight', 'no_corner_herd',
        'prey_reserve_penalty', 'open_field_bias', 'fort_cover_weight',
        'escape_bonus', 'fear_close_mult', 'sep_distance',
    )
    _CARE_SIDS = (
        'LAST_PREY_CARE', 'DELAY_FEAST', 'LAST_MEAL_STALL', 'LAST_MEAL_ORBIT',
    )

    def _playbook_dir(self, path, fi, blunderous, stall, care=False, card_score=0.0):
        """Signed step for one tunable. 0 = leave it."""
        if path == 'when.priority' or str(path).endswith('.priority'):
            return 0
        if path.startswith('movement['):
            return 0
        if path.startswith('switch.'):
            # hold_frames / margin are select policy (BO SKIP_SWITCH).
            return 0
        name = path.split('.')[-1] if '.' in path else path
        if care or stall:
            if name in self._HUNT_KNOBS:
                return -1 if blunderous else 0
            if name in self._CARE_KNOBS or name in self._EVADE_KNOBS:
                return +1 if (fi < 0 or blunderous) else 0
            return 0
        if blunderous and name in self._HUNT_KNOBS:
            return -1
        if name in self._HUNT_KNOBS:
            # Type can be winning while this hunt card is still bad.
            if fi < 0 or float(card_score) < -0.04:
                return +1
            return 0
        return 0

    def _optimise_playbook(self, fitness, f_bar, wins, skip=None):
        """Tune played cards' role knobs from a bounded decision residual."""
        import math
        import strategies.playbook as playbook
        skip = set(skip or ())
        metrics = getattr(getattr(self, 'w', None), 'metrics', None)
        ticks_all = getattr(metrics, 'strategy_ticks', {}) if metrics is not None else {}
        n_chg = 0
        n_elig = 0
        n_dir0 = 0
        care_sids = set(self._CARE_SIDS)
        stall_states = {
            'LAST_PREY_RISK', 'LAST_MAN', 'NO_PREY_FEAR_ALIVE', 'NEAR_WIPE',
            'OUTNUMBERED',
        }
        for tname in ('ROCK', 'PAPER', 'SCISSORS'):
            ticks = ticks_all.get(tname) or {}
            scores = {}
            for sid in playbook.list_ids():
                try:
                    scores[sid] = float(playbook.strategy_decision_score(tname, sid))
                except Exception:
                    scores[sid] = 0.0

            def _eligible(sid):
                if (tname, sid) in skip:
                    return False
                ov = (playbook.TEAM_OVERLAYS.get(tname) or {}).get(sid) or {}
                return self._overlay_eligible(ticks.get(sid, 0), ov)

            def _primary_stall(sid):
                if sid in care_sids:
                    return True
                ov = (playbook.TEAM_OVERLAYS.get(tname) or {}).get(sid) or {}
                try:
                    states = list((ov.get('when') or {}).get('states') or [])
                    primary = str(states[0]).upper() if states else ''
                    return primary in stall_states
                except Exception:
                    return False

            combat, stall_pool, care = [], [], []
            for s in playbook.list_ids():
                if not _eligible(s):
                    continue
                row = (int(ticks.get(s, 0) or 0), s)
                if s in care_sids:
                    care.append(row)
                elif _primary_stall(s):
                    stall_pool.append(row)
                else:
                    combat.append(row)
            combat.sort(reverse=True)
            stall_pool.sort(reverse=True)
            care.sort(reverse=True)

            def _nudge_pool(pool):
                nonlocal n_chg, n_elig, n_dir0
                if not pool:
                    return
                used_scores = [scores[s] for _, s in pool]
                mean_s = sum(used_scores) / max(1, len(used_scores))
                for used, sid in pool:
                    tunables = playbook.tunables_for(tname, sid)
                    ov = (playbook.TEAM_OVERLAYS.get(tname) or {}).get(sid) or {}
                    st = ov.get('stats') or {}
                    games = max(1.0, float(st.get('games') or 1))
                    blunderous = float(st.get('last_prey_blunder') or 0) / games > 0.08
                    is_care = sid in care_sids
                    stall = is_care
                    try:
                        states = list((ov.get('when') or {}).get('states') or [])
                        primary = str(states[0]).upper() if states else ''
                        stall = stall or primary in stall_states
                    except Exception:
                        pass
                    dec = scores.get(sid, 0.0) - mean_s
                    fi = math.tanh(dec)
                    ema = float(st.get('ema') or 0)
                    half = False
                    if abs(fi) < 0.04:
                        if (not is_care) and (not stall) and ema < 0 and used > 0:
                            fi = -0.08
                            half = True
                        else:
                            n_dir0 += 1
                            continue
                    n_elig += 1
                    strength = (0.18 if half else 0.30) + 0.55 * abs(fi)
                    n_this = 0
                    wrote_any = False
                    for path, bounds in tunables.items():
                        if n_this >= (2 if half else 4):
                            break
                        direction = self._playbook_dir(
                            path, fi, blunderous, stall, care=is_care,
                            card_score=scores.get(sid, 0.0))
                        if direction == 0:
                            continue
                        moved = playbook.nudge_tunable(
                            tname, sid, path, direction, strength=strength, bounds=bounds)
                        if moved is None:
                            continue
                        n_chg += 1
                        n_this += 1
                        wrote_any = True
                        cur = playbook._get_path(moved, path)
                        self.last_changes.append(
                            '%s.%s.%s -> %s  (f%+.2f dec%+.2f d%+d)' % (
                                tname, sid, path, cur, fi, dec, direction))
                    if not wrote_any:
                        n_dir0 += 1

            _nudge_pool(combat[:3])
            _nudge_pool(stall_pool[:2])
            _nudge_pool(care[:1])
        playbook.save_all_overlays()
        self._log_raw(
            'playbook strategy pass changes=%d wrote=%d eligible=%d dir0=%d strategies=%d skip=%d' % (
                n_chg, n_chg, n_elig, n_dir0, len(playbook.list_ids()), len(skip)))

    def _bo_record(self):
        """Snapshot current knob vector + payoff for every overlay that played."""
        import strategies.playbook as playbook
        from optimizer import bo
        metrics = getattr(getattr(self, 'w', None), 'metrics', None)
        ticks_all = getattr(metrics, 'strategy_ticks', {}) if metrics is not None else {}
        n_rec = 0
        for tname in ('ROCK', 'PAPER', 'SCISSORS'):
            bag = playbook.TEAM_OVERLAYS.get(tname) or {}
            used = ticks_all.get(tname) or {}
            for sid, ov in bag.items():
                if not self._overlay_eligible(used.get(sid, 0), ov):
                    continue
                tun = playbook.tunables_for(tname, sid)
                if sid in self._CARE_SIDS:
                    hunt = set(self._HUNT_KNOBS)
                    tun = {k: v for k, v in (tun or {}).items()
                           if (k.split('.')[-1] if '.' in k else k) not in hunt}
                y = bo.payoff(ov, tname, sid)
                c = 0.0
                try:
                    for row in getattr(metrics, 'conversions', []) or []:
                        if str(row.get('blamed_strategy') or '') == sid:
                            if str(row.get('winner_type') or '') == tname:
                                c = 1.0
                                break
                        if (str(row.get('winner_type') or '') == tname
                                and str(row.get('winner_strategy') or '') == sid
                                and int(row.get('last_prey_with_fear') or 0)):
                            c = 1.0
                            break
                except Exception:
                    c = 0.0
                playbook.TEAM_OVERLAYS[tname][sid] = bo.record(ov, tun, y, constraint=c)
                playbook._DIRTY_OVERLAYS.add((tname, sid))
                n_rec += 1
        if n_rec:
            self._log_raw('GP-EI recorded %d observations migrated=%d' % (
                n_rec, int(getattr(bo, 'LAST_MIGRATE', 0) or 0)))
            bo.LAST_MIGRATE = 0

    def _is_combat_card(self, sid, ov):
        if sid in self._CARE_SIDS:
            return False
        states = list(((ov or {}).get('when') or {}).get('states') or [])
        primary = str(states[0]).upper() if states else ''
        if primary in ('CONTESTED', 'CLEAR_HUNT', 'SMALL_UNIT'):
            return True
        return sid in (
            'PACK_HUNT', 'SCREEN_HUNT', 'OPEN_KITE', 'ESCORT_RING',
            'CLEAR_SPLIT', 'CLEAR_FAN', 'LANE_SWEEP', 'CROSS_LANE',
            'CHOKE_PINCH', 'DENSITY_RAID', 'ETA_STRIKE', 'BODY_CHECK',
        )

    def _bo_ei_step(self):
        """EI on a few played cards only. Returns set of (type, sid) written."""
        import strategies.playbook as playbook
        from optimizer import bo
        metrics = getattr(getattr(self, 'w', None), 'metrics', None)
        ticks_all = getattr(metrics, 'strategy_ticks', {}) if metrics is not None else {}
        explore = set(getattr(playbook, 'EXPLORE_TYPES', None) or ())
        done = set()
        skips = []
        max_per = int(getattr(self, 'BO_MAX_PER_TYPE', 2))
        for tname in ('ROCK', 'PAPER', 'SCISSORS'):
            bag = playbook.TEAM_OVERLAYS.get(tname) or {}
            used = ticks_all.get(tname) or {}
            played, rescue = [], []
            for sid, ov in bag.items():
                u = int(used.get(sid, 0) or 0)
                st = (ov or {}).get('stats') or {}
                life = int(st.get('ticks') or 0)
                games = int(st.get('games') or 0)
                y = bo.payoff(ov, tname, sid)
                if self._overlay_eligible(u, ov):
                    played.append((u, -float(y), sid, ov))
                    continue
                if tname in explore and self._is_combat_card(sid, ov) and (life >= 60 or games >= 4):
                    rescue.append((float(y), sid, ov))
            played.sort(reverse=True)
            rescue.sort()  # worst lifetime payoff first
            picked = []
            seen = set()
            if tname in explore and rescue:
                sid, ov = rescue[0][1], rescue[0][2]
                picked.append((sid, ov))
                seen.add(sid)
                self._log_raw('GP-EI rescue %s.%s y=%.3f' % (tname, sid, rescue[0][0]))
            if tname in explore:
                hunt_best = None
                hunt_wr = -1.0
                for sid in ('CLEAR_SPLIT', 'SCREEN_HUNT', 'OPEN_KITE', 'PACK_HUNT'):
                    ov = bag.get(sid)
                    if not ov:
                        continue
                    st = (ov.get('stats') or {})
                    g = float(st.get('games') or 0)
                    wr = (float(st.get('wins') or 0) / g) if g > 4 else -1.0
                    if wr > hunt_wr:
                        hunt_wr = wr
                        hunt_best = (sid, ov)
                if hunt_best and hunt_best[0] not in seen:
                    picked.append(hunt_best)
                    seen.add(hunt_best[0])
                    self._log_raw('GP-EI hunt %s.%s wr=%.3f' % (tname, hunt_best[0], hunt_wr))
            for _, _, sid, ov in played:
                if sid in seen:
                    continue
                picked.append((sid, ov))
                seen.add(sid)
                if len(picked) >= max_per:
                    break
            if tname in explore and len(picked) < max_per:
                for _, sid, ov in rescue:
                    if sid in seen:
                        continue
                    picked.append((sid, ov))
                    seen.add(sid)
                    if len(picked) >= max_per:
                        break
            for sid, ov in picked[:max_per]:
                tun = playbook.tunables_for(tname, sid)
                if sid in self._CARE_SIDS:
                    hunt = set(self._HUNT_KNOBS)
                    tun = {k: v for k, v in (tun or {}).items()
                           if (k.split('.')[-1] if '.' in k else k) not in hunt}
                vec = bo.propose(ov, tun)
                if not vec:
                    skips.append('%s.%s:%s' % (tname, sid, getattr(bo, 'LAST_SKIP', None) or 'none'))
                    continue
                before = dict(ov.get('weights') or {})
                ov = bo.apply_vector(ov, vec, tun)
                playbook.TEAM_OVERLAYS[tname][sid] = ov
                playbook._DIRTY_OVERLAYS.add((tname, sid))
                moved = []
                after = ov.get('weights') or {}
                for k, v in list(vec.items())[:4]:
                    if k.startswith('switch.'):
                        continue
                    if k in after and k in before and abs(float(after[k]) - float(before.get(k, 0))) > 1e-4:
                        moved.append('%s: %.3f->%.3f' % (k, float(before[k]), float(after[k])))
                if not moved:
                    # still a proposal — count the card so playbook skips it
                    moved.append('ei')
                done.add((tname, sid))
                self.last_changes.append('%s.%s GP-EI %s' % (tname, sid, ', '.join(moved[:3])))
        if done:
            playbook.save_all_overlays()
        elif skips:
            self._log_raw('GP-EI skip %s' % '; '.join(skips[:8]))
        else:
            self._log_raw('GP-EI skip no eligible cards')
        return done

    def _persist_type_config(self, force=False):
        """Learned knobs go to strategies/types JSON — never type_config.py."""
        import time as _time
        t0 = _time.perf_counter()
        try:
            import strategies.playbook as playbook
            try:
                from optimizer.perf import get_perf
                get_perf(getattr(self, 'w', None)).begin('persist')
            except Exception:
                pass
            written = playbook.persist_learned(
                games_seen=getattr(self, 'games_seen', 0),
                changes=list(self.last_changes or [])[:12])
            n = len(written or [])
            sample = [os.path.basename(p) for p in (written or [])[:6]]
            self._log_raw(
                'timing persist=%.0fms files=%d force=%s sample=%s' % (
                    (_time.perf_counter() - t0) * 1000.0,
                    n, int(bool(force)), sample))
            try:
                from optimizer.perf import get_perf
                get_perf(getattr(self, 'w', None)).end('persist')
            except Exception:
                pass
        except Exception as e:
            try:
                self._log_raw('persist learned failed: %s' % e)
            except Exception:
                pass


    def start_visible_pass(self):
        """Run one learn generation without persist. Events are replayed on TITLE."""
        self.last_changes = []
        try:
            self.optimise(persist=False)
        except Exception as e:
            self._log_raw('visible pass failed: %s' % e)
        events = []
        for line in list(self.last_changes or []):
            ev = self.parse_change_line(line)
            if ev:
                events.append(ev)
        sample = list(getattr(self, '_last_sample_games', []) or [])
        win_win = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
        for g in sample:
            w = g.get('winner', '')
            if w in win_win:
                win_win[w] += 1
        snap = {
            'gen': int(getattr(self, 'GENERATION', 0) or 0),
            'games': int(getattr(self, 'games_seen', 0) or 0),
            'window': len(sample),
            'wins': win_win,
            'simplex': dict(getattr(self, '_simplex', {}) or {}),
            'simplex_l1': float(getattr(self, '_simplex_l1', 0) or 0),
            'fitness': dict(getattr(self, '_last_fitness', {}) or {}),
            'fbar': float(getattr(self, '_last_fbar', 0) or 0),
            'share': dict(getattr(self, '_last_share', {}) or {}),
            'lr': dict(getattr(self, '_last_lr', {}) or {}),
            'events': events,
            'status': 'STABLE' if not events else 'TUNING',
        }
        return snap

    @staticmethod
    def parse_change_line(line):
        """Turn a last_changes string into a panel event."""
        raw = str(line or '').strip()
        if not raw:
            return None
        typ = 'ROCK'
        for t in ('ROCK', 'PAPER', 'SCISSORS'):
            if raw.startswith(t):
                typ = t
                break
        key = raw
        old = new = ''
        reason = ''
        sid = ''
        try:
            body, _, tail = raw.partition('  (')
            reason = tail.rstrip(')')
            if ':' in body and '->' in body:
                left, _, right = body.partition(':')
                parts = left.split('.')
                typ = parts[0] if parts else typ
                if len(parts) >= 3:
                    sid = parts[1]
                    key = '.'.join(parts[2:])
                else:
                    key = '.'.join(parts[1:]) if len(parts) > 1 else left
                if '->' in right:
                    a, _, b = right.partition('->')
                    old, new = a.strip(), b.strip()
            elif '->' in body:
                left, _, right = body.partition('->')
                parts = left.strip().split('.')
                typ = parts[0] if parts else typ
                if len(parts) >= 3:
                    sid = parts[1]
                    key = '.'.join(parts[2:])
                else:
                    key = '.'.join(parts[1:]) if len(parts) > 1 else left
                new = right.strip()
        except Exception:
            pass
        return {
            'type': typ,
            'strategy': sid,
            'key': key.strip(),
            'old': old,
            'new': new,
            'reason': reason,
            'raw': raw,
        }

    def _log_raw(self, msg):
        import datetime
        line = f'[{datetime.datetime.now().isoformat(timespec="seconds")}] {msg}\n'
        try:
            with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line)
        except Exception:
            pass

    def _log_changes(self, sample, wins, avg_dur):
        import datetime
        lines = [
            f'[{datetime.datetime.now().isoformat(timespec="seconds")}] '
            f'n={len(sample)} games_seen={self.games_seen} wins={wins} avg_dur={avg_dur:.1f}s',
        ]
        if self.last_changes:
            shown = self.last_changes[:12]
            lines += ['  ' + c for c in shown]
            extra = len(self.last_changes) - len(shown)
            if extra > 0:
                lines.append('  … +%d more (truncated)' % extra)
        else:
            lines.append('  (no param changes this pass – check bounds or balanced wins)')
        try:
            with open(self.LOG_FILE, 'a', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')
        except Exception as e:
            pass
