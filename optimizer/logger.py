"""
Metrics logging for Rock-Paper-Scissors.

Writes metrics_games.csv, metrics_conversions.csv, metrics_population.csv,
metrics_summary.txt. particle.py imports Metrics — do not import particle
at module level.
"""

import os
from optimizer.paths import log_path
import math
import pygame

from config import Config, ParticleType, TeamMode, Role, PREY_OF, FEAR_OF
from strategies.playbook import STRATEGY_IDS
from config import (
    TYPE_DEFAULTS, TYPE_MOTION, STRATEGY_KEYS, effective_strategy,
)


def _FortLOS():
    from arena.fort import FortLOS
    return FortLOS


# ---------------------------------------------------------------------------
# Metrics – outcome-tied logging for tuning
# ---------------------------------------------------------------------------
class Metrics:
    """Logs game outcomes and decision context by particle type for optimisation."""

    GAMES_CSV = log_path('metrics_games.csv')
    CONV_CSV = log_path('metrics_conversions.csv')
    POP_CSV = log_path('metrics_population.csv')
    SUMMARY = log_path('metrics_summary.txt')
    TOTAL_FILE = log_path('games_total.txt')

    @classmethod
    def read_games_total(cls):
        import os
        path = getattr(cls, 'TOTAL_FILE', log_path('games_total.txt'))
        n = 0
        try:
            with open(path, encoding='utf-8') as f:
                n = int(float(f.read().strip() or 0))
        except Exception:
            n = 0
        # Floor from current csv length if the counter file is missing/stale.
        try:
            gp = cls.GAMES_CSV
            if os.path.isfile(gp):
                with open(gp, encoding='utf-8') as f:
                    rows = max(0, sum(1 for _ in f) - 1)
                n = max(n, rows)
        except Exception:
            pass
        return max(0, n)

    @classmethod
    def write_games_total(cls, n):
        n = max(0, int(n))
        try:
            with open(cls.TOTAL_FILE, 'w', encoding='utf-8') as f:
                f.write(str(n) + '\n')
        except Exception:
            pass
        return n

    @classmethod
    def bump_games_total(cls):
        n = cls.read_games_total() + 1
        return cls.write_games_total(n)

    @staticmethod
    def _safe_append(path, text_line):
        """Append a line; ignore permission / lock errors so the game never crashes."""
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(text_line)
        except (PermissionError, OSError):
            try:
                alt = path + '.tmp'
                with open(alt, 'a', encoding='utf-8') as f:
                    f.write(text_line)
            except Exception:
                pass

    @staticmethod
    def _safe_write(path, content):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
        except (PermissionError, OSError):
            try:
                with open(path + '.tmp', 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception:
                pass

    def __init__(self, world):
        self.w = world
        self.conversions = []       # this match
        self.mode_ticks = {t.name: {m.name: 0 for m in TeamMode} for t in ParticleType}
        self.role_ticks = {t.name: {r.name: 0 for r in Role} for t in ParticleType}
        self.strategy_ticks = {t.name: {s: 0 for s in STRATEGY_IDS} for t in ParticleType}
        self.strategy_mode_ticks = {
            t.name: {m.name: {s: 0 for s in STRATEGY_IDS} for m in TeamMode}
            for t in ParticleType
        }
        self.strategy_state_ticks = {t.name: {} for t in ParticleType}
        self._ensure_headers()

    def _ensure_headers(self):
        import os
        games_header = (
            'gameid,teamSize,forts,duration_s,runcount,winner,'
            'rock_final,paper_final,scissors_final,'
            'rock_conversions,paper_conversions,scissors_conversions,'
            'rock_mode_HUNT,rock_mode_DEFEND,rock_mode_REGROUP,rock_mode_SCATTER,'
            'paper_mode_HUNT,paper_mode_DEFEND,paper_mode_REGROUP,paper_mode_SCATTER,'
            'scissors_mode_HUNT,scissors_mode_DEFEND,scissors_mode_REGROUP,scissors_mode_SCATTER,'
            'total_conversions,'
            'wipe_risk_total,wipe_risk_rock,wipe_risk_paper,wipe_risk_scissors,'
            'winner_had_fear_at_end,winner_prey_left,'
            'fort_near_wins,fort_cover_wins,fort_near_losses,fort_cover_losses,overcrowd_events,avg_pack_density,avg_flank_imbalance,'
            'endgame_frames,endgame_seconds,endgame_prey_start,endgame_split_events,endgame_simultaneous,'
            'VISION_FAR,NEAR_TARGET_AGGRO,CLUSTER_BONUS,FEAR_CLOSE_MULT,'
            'SCATTER_COUNT_THRESHOLD,TARGET_LOCK_TTL,HUNT_ADVANTAGE,COHESION_WEIGHT,'
            'PACK_HUNT_MULT,FINISH_BONUS,ESCAPE_BONUS_WEIGHT,FEAR_POP_SCALE\n'
        )
        # Base event columns + full STRATEGY_KEYS vector for offline optimise
        _conv_base = [
            'gameid','time_s','runcount','teamSize','winner_type','loser_was','winner_role','winner_mode','winner_strategy','loser_strategy',
            'winner_speed','winner_maxspeed','winner_strength','winner_agility','winner_bravery',
            'winner_team_count','loser_team_count','fear_count','prey_count',
            'rock_count','paper_count','scissors_count',
            'self_before','fear_before','prey_before','self_after','fear_after','prey_after',
            'self_fear_ratio','self_prey_ratio','fear_prey_ratio',
            'winner_speed_base','winner_turn_base','dist_to_loser',
            'winner_near_fort','loser_near_fort','winner_cover','loser_cover','fort_count',
            'aggro','finish','cluster','fear_close','escape','cohesion','pack','focus','lock_ttl',
            'is_small_unit','small_raid','small_escape','solo_finish','outnumbered_fear','flank','predict','self_count',
            'was_evading','did_brake','did_reverse','evade_threshold','evade_speed','evade_brake',
            'evade_reverse_risk','evade_turn','evade_predict','residual_fear',
            'last_prey_kill','last_prey_with_fear','game_state',
            'effective_aggro','effective_finish','effective_escape',
            'ambush_kill','pincer_kill','pack_density','pack_density_at_prey','flank_imbalance','overcrowd_event',
            'arrive_active','wander_active','clear_split_event',
            'voronoi_imbalance','voronoi_reassign',
            'swarm_sep_mag','swarm_coh_mag','swarm_ali_mag','swarm_fear_mag','swarm_prey_mag','swarm_avoid_mag','swarm_total_mag',
            'delaunay_peels','cross_map_reassigns','delaunay_pure_edges','knn_fill_edges',
            'strike_size','strike_multi','local_friend_sep','local_friend_n','victim_sep_distance',
            'near_wipe_active','ally_knock_into_fear','ally_protect_hits',
            'threat_weight_avg','threat_weight_n',
            'prey_corner_score','corner_herd','corner_herd_while_fear','corner_herd_avoids','hide_among_prey_frames','hide_among_prey_weight','hide_among_prey_radius','hide_among_prey_min',
        ]
        _seen = set(_conv_base)
        for _sk in STRATEGY_KEYS:
            if _sk not in _seen:
                _conv_base.append(_sk)
                _seen.add(_sk)
        conv_header = ','.join(_conv_base) + chr(10)
        pop_header = (
            'gameid,time_s,runcount,teamSize,'
            'rock,paper,scissors,'
            'rock_fear,rock_prey,paper_fear,paper_prey,scissors_fear,scissors_prey,'
            'rock_mode,paper_mode,scissors_mode,'
            'any_last_prey_risk\n'
        )
        # Always ensure headers exist; if old schema missing fort cols, write .v2 companion
        if not os.path.exists(self.GAMES_CSV):
            self._safe_write(self.GAMES_CSV, games_header)
        else:
            try:
                with open(self.GAMES_CSV, encoding='utf-8') as f:
                    first = f.readline()
                if 'fort_near_wins' not in first:
                    self._safe_write(log_path('metrics_games_fort.csv'), games_header)
            except Exception:
                pass
        if not os.path.exists(self.CONV_CSV):
            self._safe_write(self.CONV_CSV, conv_header)
        else:
            try:
                with open(self.CONV_CSV, encoding='utf-8') as f:
                    first = f.readline()
                if 'winner_near_fort' not in first:
                    self._safe_write(log_path('metrics_conversions_fort.csv'), conv_header)
            except Exception:
                pass
        if not os.path.exists(getattr(self, 'POP_CSV', 'metrics_population.csv')):
            self._safe_write(getattr(self, 'POP_CSV', 'metrics_population.csv'), pop_header)

    def consume_used_metrics(self, conv_keep=2500, games_keep=None):
        """Cap conversions. Do not tail metrics_games.csv — the welcome
        counter and fitness window both need the growing history.
        games_keep is ignored (kept so old callers don't break)."""
        import os
        def _tail(path, keep):
            if not path or not os.path.isfile(path):
                return False
            with open(path, encoding='utf-8') as f:
                lines = f.read().splitlines()
            if not lines:
                return False
            header = lines[0]
            body = lines[1:]
            if len(body) <= keep:
                return False
            text = header + '\n' + '\n'.join(body[-keep:]) + '\n'
            self._safe_write(path, text)
            return True
        n_cleared = 0
        if _tail(self.CONV_CSV, conv_keep):
            n_cleared += 1
        for path in (
            log_path('metrics_games_fort.csv'),
            log_path('metrics_conversions_fort.csv'),
        ):
            if _tail(path, conv_keep):
                n_cleared += 1
        try:
            if hasattr(self.w, 'optimizer') and hasattr(self.w.optimizer, '_log_raw'):
                self.w.optimizer._log_raw('consumed metrics cleared (%s files)' % n_cleared)
        except Exception:
            pass

    def reset_match(self):
        self.conversions = []
        self.mode_ticks = {t.name: {m.name: 0 for m in TeamMode} for t in ParticleType}
        self.role_ticks = {t.name: {r.name: 0 for r in Role} for t in ParticleType}
        self.strategy_ticks = {t.name: {s: 0 for s in STRATEGY_IDS} for t in ParticleType}
        self.strategy_mode_ticks = {
            t.name: {m.name: {s: 0 for s in STRATEGY_IDS} for m in TeamMode}
            for t in ParticleType
        }
        self.strategy_state_ticks = {t.name: {} for t in ParticleType}

    def sample_modes(self):
        """Accumulate mode/role time and periodic relative population snapshots."""
        if not hasattr(self, 'state_ticks'):
            self.state_ticks = {t.name: {} for t in ParticleType}
            self.wipe_risk_events = []
            self._pop_sample_i = 0
        for t, team in self.w.teams.items():
            self.mode_ticks[t.name][team.mode.name] += 1
            sid = getattr(team, 'strategy_id', None) or 'PACK_HUNT'
            if sid not in self.strategy_ticks[t.name]:
                self.strategy_ticks[t.name][sid] = 0
            self.strategy_ticks[t.name][sid] += 1
            md = team.mode.name
            bucket = self.strategy_mode_ticks[t.name].setdefault(md, {})
            bucket[sid] = bucket.get(sid, 0) + 1
            for p in team.members:
                self.role_ticks[t.name][p.role.name] += 1
            fear = self.w.type_counts.get(FEAR_OF[t], 0)
            prey = self.w.type_counts.get(PREY_OF[t], 0)
            self_c = team.count
            if fear > 0 and prey <= 0:
                state = 'NO_PREY_FEAR_ALIVE'
            elif fear <= 0 and prey > 0:
                state = 'CLEAR_HUNT'
            elif fear > 0 and prey <= 3:
                state = 'LAST_PREY_RISK'
            elif fear > self_c:
                state = 'OUTNUMBERED'
            elif self_c <= 3:
                state = 'SMALL_UNIT'
            else:
                state = 'CONTESTED'
            bucket = self.state_ticks[t.name]
            bucket[state] = bucket.get(state, 0) + 1
            sst = self.strategy_state_ticks.setdefault(t.name, {})
            sbag = sst.setdefault(sid, {})
            sbag[state] = sbag.get(state, 0) + 1
        # Population time-series for relative size learning (~every 30 samples)
        self._pop_sample_i = getattr(self, '_pop_sample_i', 0) + 1
        if self._pop_sample_i % 30 == 0 and self.w.match_start_ticks:
            rc = self.w.type_counts
            rock = rc.get(ParticleType.ROCK, 0)
            paper = rc.get(ParticleType.PAPER, 0)
            scissors = rc.get(ParticleType.SCISSORS, 0)
            any_risk = int(
                (rock > 0 and paper > 0 and scissors == 0) or  # scissors out: paper fears scissors gone, rock prey gone
                (paper > 0 and scissors > 0 and rock == 0) or
                (scissors > 0 and rock > 0 and paper == 0)
            )
            # Per-type last-prey risk: prey gone but fear alive
            def risk(t):
                return int(rc.get(PREY_OF[t], 0) <= 0 and rc.get(FEAR_OF[t], 0) > 0 and rc.get(t, 0) > 0)
            any_risk = int(risk(ParticleType.ROCK) or risk(ParticleType.PAPER) or risk(ParticleType.SCISSORS))
            try:
                t_s = round((pygame.time.get_ticks() - self.w.match_start_ticks) / 1000.0, 2)
            except Exception:
                t_s = 0
            modes = {t.name: self.w.teams[t].mode.name for t in ParticleType}
            line = ','.join(str(x) for x in [
                str(self.w.gameid), t_s, self.w.runcount, self.w.teamSize,
                rock, paper, scissors,
                rc.get(FEAR_OF[ParticleType.ROCK], 0), rc.get(PREY_OF[ParticleType.ROCK], 0),
                rc.get(FEAR_OF[ParticleType.PAPER], 0), rc.get(PREY_OF[ParticleType.PAPER], 0),
                rc.get(FEAR_OF[ParticleType.SCISSORS], 0), rc.get(PREY_OF[ParticleType.SCISSORS], 0),
                modes['ROCK'], modes['PAPER'], modes['SCISSORS'],
                any_risk,
            ]) + chr(10)
            self._safe_append(self.POP_CSV, line)

    def _flank_imbalance(self, win):
        team = win.get_team() if hasattr(win, 'get_team') else None
        if team is None:
            return 0.0
        assigns = getattr(team, 'pincer_assignments', {}) or {}
        left = sum(1 for r in assigns.values() if r == 'left')
        right = sum(1 for r in assigns.values() if r == 'right')
        tot = left + right
        if tot <= 0:
            return 0.0
        return abs(left - right) / tot

    def _was_pincer_kill(self, win, lose):

        """True if ≥2 same-type allies were on different sides of the loser."""
        allies = [p for p in self.w.particles if p.type == win.type and p is not win]
        if len(allies) < 1:
            return False
        # Include winner as one side
        pts = [win] + allies
        near = []
        for p in pts:
            d = math.hypot(p.x - lose.x, p.y - lose.y)
            if d < 14 * win.size:
                ang = math.atan2(p.x - lose.x, -(p.y - lose.y))
                near.append(ang)
        if len(near) < 2:
            return False
        # Check if any pair has angular separation > 60°
        for i in range(len(near)):
            for j in range(i + 1, len(near)):
                ad = abs((near[i] - near[j] + math.pi) % (2 * math.pi) - math.pi)
                if ad > math.radians(60):
                    return True
        return False

    def _near_fort(self, p, mult=3.5):

        for f in getattr(self.w, 'fort_list', []) or []:
            if getattr(f, 'scale', 1.0) < 0.85:
                continue
            if math.hypot(p.x - f.x, p.y - f.y) < f.radius + p.size * mult:
                return True
        return False

    def _has_fort_cover(self, p):
        """True if any predator is LOS-blocked by a fort from p."""
        fear_type = FEAR_OF.get(p.type)
        if fear_type is None:
            return False
        for o in self.w.particles:
            if o.type != fear_type:
                continue
            if _FortLOS().occludes(self.w, p, o):
                return True
        return False


    def _ensure_conv_header(self):
        """Write conversions CSV header including all STRATEGY_KEYS if file is new."""
        path = self.CONV_CSV
        try:
            import os
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return
        except Exception:
            pass
        base = [
            'gameid','time_s','runcount','teamSize','winner_type','loser_was','winner_role','winner_mode','winner_strategy','loser_strategy',
            'winner_speed','winner_maxspeed','winner_strength','winner_agility','winner_bravery',
            'winner_team_count','loser_team_count','fear_count','prey_count',
            'rock_count','paper_count','scissors_count',
            'self_before','fear_before','prey_before','self_after','fear_after','prey_after',
            'self_fear_ratio','self_prey_ratio','fear_prey_ratio',
            'winner_speed_base','winner_turn_base','dist_to_loser',
            'winner_near_fort','loser_near_fort','winner_cover','loser_cover','fort_count',
            'aggro','finish','cluster','fear_close','escape','cohesion','pack','focus','lock_ttl',
            'is_small_unit','small_raid','small_escape','solo_finish','outnumbered_fear','flank','predict','self_count',
            'was_evading','did_brake','did_reverse','evade_threshold','evade_speed','evade_brake',
            'evade_reverse_risk','evade_turn','evade_predict','residual_fear',
            'last_prey_kill','last_prey_with_fear','game_state',
            'prey_reserve','prey_reserve_penalty','clear_finish_mult',
            'state_clear_hunt','state_last_prey_risk','state_no_prey_fear',
            'state_outnumbered','state_small_unit','state_contested',
            'effective_aggro','effective_finish','effective_escape',
            'fort_cover_weight','fort_hide_bias','fort_ambush_bonus','ambush_kill','pincer_kill','pack_density',
            'asymmetric_sep_front','asymmetric_sep_rear','speed_match_weight','offset_pursue_dist','offset_pursue_gain',
            'arrive_radius','arrive_slow','wander_strength','wander_rate','arrive_active','wander_active',
            'clear_spread_weight','clear_split_threshold','clear_finish_speed','clear_reassign_dist','clear_split_event',
            'voronoi_weight','voronoi_balance','voronoi_recompute_interval','voronoi_overflow_threshold',
            'clear_voronoi_cap_slack','clear_voronoi_predict','voronoi_imbalance','voronoi_reassign',
            'swarm_sep_mag','swarm_coh_mag','swarm_ali_mag','swarm_fear_mag','swarm_prey_mag','swarm_avoid_mag','swarm_total_mag',
            'delaunay_peels','cross_map_reassigns','delaunay_overflow','delaunay_k','delaunay_pure_edges','knn_fill_edges',
            'pack_density_at_prey','flank_imbalance','overcrowd_event',
            'strike_size','strike_multi','local_friend_sep','local_friend_n','victim_sep_distance',
            'near_wipe_threshold','near_wipe_sep_mult','near_wipe_evade_mult','near_wipe_fort_mult',
            'near_wipe_cohesion','state_near_wipe','near_wipe_active',
            'ally_knock_into_fear','ally_protect_hits','ally_protect_weight','ally_protect_radius',
            'threat_weight_avg','threat_weight_n','threat_weight_base','threat_dist_exp',
            'threat_count_scale','threat_closing_scale','threat_front_scale',
            'prey_corner_score','corner_herd','corner_herd_while_fear',
            'no_corner_herd','open_field_bias','corner_zone_margin','corner_herd_avoids','hide_among_prey_frames','hide_among_prey_weight','hide_among_prey_radius','hide_among_prey_min',
        ]
        for sk in STRATEGY_KEYS:
            if sk not in base:
                base.append(sk)
        try:
            self._safe_append(path, ','.join(base) + chr(10))
        except Exception:
            pass

    def log_conversion(self, win, lose, loser_type_before=None):
        self._ensure_conv_header()
        tname = win.type.name
        motion = TYPE_MOTION.get(tname, {})
        team = win.get_team()
        st = effective_strategy(tname, self.w.teamSize,
                            self_count=self.w.type_counts.get(win.type, team.count),
                            fear_count=self.w.type_counts.get(FEAR_OF[win.type], 0),
                            prey_count=self.w.type_counts.get(PREY_OF[win.type], 0))
        dist = math.hypot(win.x - lose.x, win.y - lose.y)
        loser_name = loser_type_before.name if loser_type_before is not None else (
            lose.starttype.name if hasattr(lose, 'starttype') else '?')
        row = {
            'gameid': str(self.w.gameid),
            'time_s': round((pygame.time.get_ticks() - self.w.match_start_ticks) / 1000.0, 2),
            'runcount': self.w.runcount,
            'teamSize': self.w.teamSize,
            'winner_type': tname,
            'loser_was': loser_name,
            'winner_role': win.role.name,
            'winner_mode': team.mode.name,
            'winner_strategy': getattr(team, 'strategy_id', '') or '',
            'loser_strategy': getattr(lose.get_team(), 'strategy_id', '') if hasattr(lose, 'get_team') else '',
            'winner_speed': round(win.speed, 3),
            'winner_maxspeed': round(win.maxspeed(), 3),
            'winner_strength': round(win.strength, 3),
            'winner_agility': round(win.agility, 3),
            'winner_bravery': round(win.bravery, 3),
            'winner_team_count': self.w.type_counts.get(win.type, team.count),
            'loser_team_count': self.w.type_counts.get(loser_type_before, 0) if loser_type_before else 0,
            'fear_count': self.w.type_counts.get(FEAR_OF[win.type], 0),
            'prey_count': self.w.type_counts.get(PREY_OF[win.type], 0),
            'rock_count': self.w.type_counts.get(ParticleType.ROCK, 0),
            'paper_count': self.w.type_counts.get(ParticleType.PAPER, 0),
            'scissors_count': self.w.type_counts.get(ParticleType.SCISSORS, 0),
            'winner_speed_base': motion.get('speed_base', 0),
            'winner_turn_base': motion.get('turn_base', 0),
            'dist_to_loser': round(dist, 1),
            'winner_near_fort': int(self._near_fort(win)),
            'loser_near_fort': int(self._near_fort(lose)),
            'winner_cover': int(self._has_fort_cover(win)),
            'loser_cover': int(self._has_fort_cover(lose)),
            'fort_count': len(getattr(self.w, 'fort_list', []) or []),
            'aggro': round(st['near_target_aggro'], 3),
            'finish': round(st['finish_bonus'], 3),
            'cluster': round(st['cluster_bonus'], 3),
            'fear_close': round(st['fear_close_mult'], 3),
            'escape': round(st['escape_bonus'], 3),
            'cohesion': round(st['cohesion_weight'], 3),
            'pack': round(st['pack_hunt_mult'], 3),
            'focus': round(st['focus_bonus'], 3),
            'lock_ttl': st['target_lock_ttl'],
            'is_small_unit': int(bool(st.get('_is_small_unit'))),
            'small_raid': round(st.get('small_raid_bonus', 0), 3),
            'small_escape': round(st.get('small_escape_mult', 0), 3),
            'solo_finish': round(st.get('solo_finish_mult', 0), 3),
            'outnumbered_fear': round(st.get('outnumbered_fear_mult', 0), 3),
            'flank': round(st.get('flank_bias', 0), 3),
            'predict': round(st.get('predict_lookahead', 0), 2),
            'self_count': self.w.type_counts.get(win.type, team.count),
            'was_evading': int(bool(getattr(win, '_evading', False))),
            'did_brake': int(bool(getattr(win, '_did_brake', False))),
            'did_reverse': int(bool(getattr(win, '_did_reverse', False))),
            'evade_threshold': round(st.get('evade_threshold', 0), 3),
            'evade_speed': round(st.get('evade_speed_mult', 0), 3),
            'evade_brake': round(st.get('evade_brake', 0), 3),
            'evade_reverse_risk': round(st.get('evade_reverse_risk', 0), 3),
            'evade_turn': round(st.get('evade_turn_boost', 0), 3),
            'evade_predict': round(st.get('evade_predict', 0), 2),
            'residual_fear': round(getattr(win, '_fear_intensity', 0), 3),
            'last_prey_kill': 0,
            'last_prey_with_fear': 0,
            'game_state': '',
        }
        # Relative sizes before/after this conversion (post-conversion type_counts)
        prey_type = PREY_OF.get(win.type)
        fear_type = FEAR_OF.get(win.type)
        self_after = self.w.type_counts.get(win.type, 0)
        prey_after = self.w.type_counts.get(prey_type, 0) if prey_type else 0
        fear_after = self.w.type_counts.get(fear_type, 0) if fear_type else 0
        # Approximate before: if we converted prey, prey_before = prey_after+1; self_before = self_after-1
        prey_before = prey_after
        self_before = self_after
        fear_before = fear_after
        if loser_type_before is not None:
            if prey_type is not None and loser_type_before == prey_type:
                prey_before = prey_after + 1
                self_before = max(0, self_after - 1)
            elif fear_type is not None and loser_type_before == fear_type:
                fear_before = fear_after + 1
                self_before = max(0, self_after - 1)
            elif loser_type_before == win.type:
                self_before = self_after  # same-type collision shouldn't convert
        row['self_before'] = self_before
        row['fear_before'] = fear_before
        row['prey_before'] = prey_before
        row['self_after'] = self_after
        row['fear_after'] = fear_after
        row['prey_after'] = prey_after
        row['self_fear_ratio'] = round(self_after / max(1, fear_after), 3)
        row['self_prey_ratio'] = round(self_after / max(1, prey_after), 3)
        row['fear_prey_ratio'] = round(fear_after / max(1, prey_after), 3)
        row['prey_reserve'] = st.get('prey_reserve', 0)
        row['prey_reserve_penalty'] = round(st.get('prey_reserve_penalty', 0), 3)
        row['clear_finish_mult'] = round(st.get('clear_finish_mult', 0), 3)
        # Detect killing last of our prey type while predators remain → lose path
        if loser_type_before is not None and prey_type is not None and loser_type_before == prey_type:
            last_meal = (prey_after <= 0 or prey_before <= 1
                         or int(row.get('loser_team_count') or 0) <= 1)
            if last_meal:
                row['last_prey_kill'] = 1
                if fear_after > 0 or fear_before > 0:
                    row['last_prey_with_fear'] = 1
                    if not hasattr(self, 'wipe_risk_events'):
                        self.wipe_risk_events = []
                    self.wipe_risk_events.append({
                        'winner_type': tname,
                        'fear_left': fear_after,
                        'self_after': self_after,
                        'mode': team.mode.name,
                        'runcount': self.w.runcount,
                        'self_fear_ratio': row['self_fear_ratio'],
                    })
                    try:
                        from optimizer import rl
                        rl.settle_convert(
                            tname, row.get('winner_strategy'), True,
                            prey_left=prey_after, fear_left=fear_after,
                            game_state=row.get('game_state') or 'LAST_PREY_RISK')
                    except Exception:
                        pass
        self_c = self_after
        if fear_after <= 0 and prey_after > 0:
            row['game_state'] = 'CLEAR_HUNT'
        elif fear_after > 0 and prey_after <= 0:
            row['game_state'] = 'NO_PREY_FEAR_ALIVE'
        elif fear_after > 0 and prey_after <= 1:
            row['game_state'] = 'LAST_PREY_RISK'
        elif self_c <= int(TYPE_DEFAULTS.get(win.type.name if hasattr(win.type,'name') else str(win.type), {}).get('near_wipe_threshold', 2)) and fear_after > 0:
            row['game_state'] = 'NEAR_WIPE'
        elif fear_after > self_c:
            row['game_state'] = 'OUTNUMBERED'
        elif self_c <= 3:
            row['game_state'] = 'SMALL_UNIT'
        else:
            row['game_state'] = 'CONTESTED'
        # Log all emergent state multipliers + effective (post-state) combat knobs
        d0 = TYPE_DEFAULTS.get(tname, {})
        for sk in ('state_clear_hunt', 'state_last_prey_risk', 'state_no_prey_fear',
                   'state_outnumbered', 'state_small_unit', 'state_contested'):
            row[sk] = round(float(d0.get(sk, st.get(sk, 1.0))), 4)
        row['effective_aggro'] = round(float(st.get('near_target_aggro', 0)), 4)
        row['effective_finish'] = round(float(st.get('finish_bonus', 0)), 4)
        row['effective_escape'] = round(float(st.get('escape_bonus', 0)), 4)
        row['fort_cover_weight'] = round(float(st.get('fort_cover_weight', 1.0)), 4)
        row['fort_hide_bias'] = round(float(st.get('fort_hide_bias', 1.0)), 4)
        row['fort_ambush_bonus'] = round(float(st.get('fort_ambush_bonus', 0.8)), 4)
        row['asymmetric_sep_front'] = round(float(st.get('asymmetric_sep_front', 2.0)), 4)
        row['asymmetric_sep_rear'] = round(float(st.get('asymmetric_sep_rear', 0.55)), 4)
        row['speed_match_weight'] = round(float(st.get('speed_match_weight', 0.35)), 4)
        row['offset_pursue_dist'] = round(float(st.get('offset_pursue_dist', 2.8)), 4)
        row['offset_pursue_gain'] = round(float(st.get('offset_pursue_gain', 1.0)), 4)
        row['arrive_radius'] = round(float(st.get('arrive_radius', 3.5)), 4)
        row['arrive_slow'] = round(float(st.get('arrive_slow', 0.45)), 4)
        row['wander_strength'] = round(float(st.get('wander_strength', 0.18)), 4)
        row['wander_rate'] = round(float(st.get('wander_rate', 0.12)), 4)
        row['clear_spread_weight'] = round(float(st.get('clear_spread_weight', 1.0)), 4)
        row['clear_split_threshold'] = int(st.get('clear_split_threshold', 2))
        row['clear_finish_speed'] = round(float(st.get('clear_finish_speed', 1.15)), 4)
        row['clear_reassign_dist'] = round(float(st.get('clear_reassign_dist', 4.0)), 4)
        row['clear_split_event'] = int(getattr(win, '_clear_split_event', 0) or 0)
        row['voronoi_weight'] = round(float(st.get('voronoi_weight', 1.0)), 4)
        row['voronoi_balance'] = round(float(st.get('voronoi_balance', 0.7)), 4)
        row['voronoi_recompute_interval'] = int(st.get('voronoi_recompute_interval', 8))
        row['voronoi_overflow_threshold'] = int(st.get('voronoi_overflow_threshold', 3))
        row['clear_voronoi_cap_slack'] = int(st.get('clear_voronoi_cap_slack', 1))
        row['clear_voronoi_predict'] = round(float(st.get('clear_voronoi_predict', 0.35)), 4)
        row['voronoi_imbalance'] = round(float(getattr(win, '_voronoi_imbalance', 0) or 0), 3)
        row['voronoi_reassign'] = int(getattr(win, '_voronoi_reassign', 0) or 0)
        # Swarm component magnitudes (averages for winner type this match so far)
        try:
            sm = self.w.swarm_mag_averages(win.type)
            row['swarm_sep_mag'] = sm.get('sep_mag', 0.0)
            row['swarm_coh_mag'] = sm.get('coh_mag', 0.0)
            row['swarm_ali_mag'] = sm.get('ali_mag', 0.0)
            row['swarm_fear_mag'] = sm.get('fear_mag', 0.0)
            row['swarm_prey_mag'] = sm.get('prey_mag', 0.0)
            row['swarm_avoid_mag'] = sm.get('avoid_mag', 0.0)
            row['swarm_total_mag'] = sm.get('mag', 0.0)
            row['near_wipe_threshold'] = int(st.get('near_wipe_threshold', 2))
            row['near_wipe_sep_mult'] = round(float(st.get('near_wipe_sep_mult', 2.2)), 4)
            row['near_wipe_evade_mult'] = round(float(st.get('near_wipe_evade_mult', 1.6)), 4)
            row['near_wipe_fort_mult'] = round(float(st.get('near_wipe_fort_mult', 1.5)), 4)
            row['near_wipe_cohesion'] = round(float(st.get('near_wipe_cohesion', 0.0)), 4)
            row['state_near_wipe'] = round(float(st.get('state_near_wipe', 1.35)), 4)
            row['near_wipe_active'] = 1 if st.get('_near_wipe') else 0
        except Exception:
            row['swarm_sep_mag'] = row['swarm_coh_mag'] = row['swarm_ali_mag'] = 0.0
            row['swarm_fear_mag'] = row['swarm_prey_mag'] = row['swarm_avoid_mag'] = 0.0
            row['swarm_total_mag'] = 0.0
        row['delaunay_peels'] = int(getattr(win, '_delaunay_peels', 0) or 0)
        row['delaunay_pure_edges'] = int(getattr(win, '_delaunay_pure_edges', 0) or 0)
        row['knn_fill_edges'] = int(getattr(win, '_knn_fill_edges', 0) or 0)
        row['cross_map_reassigns'] = int(getattr(win, '_cross_map_reassigns', 0) or 0)
        row['delaunay_overflow'] = round(float(st.get('delaunay_overflow', 1.0)), 4)
        row['delaunay_k'] = int(st.get('delaunay_k', 3))
        row['arrive_active'] = int(getattr(win, '_arrive_active', 0) or 0)
        row['wander_active'] = int(getattr(win, '_wander_active', 0) or 0)
        row['ambush_kill'] = int(
            getattr(win, '_ambush_mode', 'none') == 'spring'
            or (int(row.get('winner_cover', 0)) == 1 and int(row.get('loser_cover', 0)) == 0)
        )
        row['pincer_kill'] = int(self._was_pincer_kill(win, lose))
        pd = int(getattr(win, '_pack_density', 0) or 0)
        pdp = int(getattr(win, '_pack_density_at_prey', 0) or 0)
        row['pack_density'] = pd
        row['pack_density_at_prey'] = pdp
        row['flank_imbalance'] = round(self._flank_imbalance(win), 3)
        thr = int(win.strat().get('overcrowd_threshold', 4))
        row['overcrowd_event'] = int(pdp >= thr or pd >= thr)
        row['_game_state_applied'] = st.get('_game_state', row['game_state'])

        # --- Predator strike: multi-conversion burst by same predator ---
        STRIKE_WINDOW = 45  # frames to chain kills into one strike
        rc = int(getattr(self.w, 'runcount', 0) or 0)
        pid = getattr(win, 'id', id(win))
        if loser_type_before is not None:
            vtype = loser_type_before.name if hasattr(loser_type_before, 'name') else str(loser_type_before)
        else:
            vtype = lose.type.name if hasattr(lose.type, 'name') else str(getattr(lose, 'type', '?'))
        friend_sep_sum = 0.0
        friend_n = 0
        lose_size = max(1.0, float(getattr(lose, 'size', 20)))
        for o in self.w.particles:
            if o is lose:
                continue
            otype = o.type.name if hasattr(o.type, 'name') else str(o.type)
            if otype != vtype:
                continue
            d = math.hypot(o.x - lose.x, o.y - lose.y)
            if d < 20 * lose_size:
                friend_sep_sum += d
                friend_n += 1
        local_friend_sep = (friend_sep_sum / friend_n) if friend_n else 0.0
        try:
            victim_sep_cfg = float(TYPE_DEFAULTS.get(vtype, {}).get('sep_distance', 5.0))
        except Exception:
            victim_sep_cfg = 5.0
        if not hasattr(self, '_strike_predator_id'):
            self._strike_predator_id = None
            self._strike_count = 0
            self._strike_last_rc = -999
            self._strike_victim_type = None
            self.strike_events = []
        if (self._strike_predator_id == pid
                and rc - self._strike_last_rc <= STRIKE_WINDOW
                and self._strike_victim_type == vtype):
            self._strike_count += 1
        else:
            if getattr(self, '_strike_count', 0) >= 2 and self._strike_predator_id is not None:
                self.strike_events.append({
                    'predator_id': self._strike_predator_id,
                    'victim_type': self._strike_victim_type,
                    'conversions': self._strike_count,
                    'rc': self._strike_last_rc,
                    'avg_friend_sep': local_friend_sep,
                    'sep_distance': victim_sep_cfg,
                })
            self._strike_predator_id = pid
            self._strike_count = 1
            self._strike_victim_type = vtype
        self._strike_last_rc = rc
        row['strike_size'] = self._strike_count
        row['strike_multi'] = 1 if self._strike_count >= 2 else 0
        row['local_friend_sep'] = round(local_friend_sep, 2)
        row['local_friend_n'] = friend_n
        row['victim_sep_distance'] = round(victim_sep_cfg, 4)

        # Ally knock-into-predator: friend was close behind victim, aligned with predator
        ally_knock = 0
        ally_protect_hits = int(getattr(win, '_ally_protect_hits', 0) or 0)
        try:
            fear_of_victim = FEAR_OF.get(lose.type)
            if fear_of_victim is not None:
                # Was win a friend of the victim who converted them? No - win is predator
                # Check if victim had a same-type friend close, and a predator (win) beyond them
                for o in self.w.particles:
                    if o is lose or o.type != lose.type:
                        continue
                    d_friend = math.hypot(o.x - lose.x, o.y - lose.y)
                    if d_friend > 8 * lose_size:
                        continue
                    # Vector friend→victim and victim→predator(win)
                    fvx, fvy = lose.x - o.x, lose.y - o.y
                    vpx, vpy = win.x - lose.x, win.y - lose.y
                    fl = math.hypot(fvx, fvy) + 1e-6
                    vl = math.hypot(vpx, vpy) + 1e-6
                    # Friend was roughly behind victim relative to predator (push chain)
                    align = (fvx/fl) * (vpx/vl) + (fvy/fl) * (vpy/vl)
                    if align > 0.35:
                        ally_knock = 1
                        break
        except Exception:
            ally_knock = 0
        row['ally_knock_into_fear'] = ally_knock
        row['ally_protect_hits'] = ally_protect_hits
        row['ally_protect_weight'] = round(float(st.get('ally_protect_weight', 1.0)), 4)
        row['ally_protect_radius'] = round(float(st.get('ally_protect_radius', 12.0)), 4)

        # Dynamic threat weighting snapshot (from winner's recent evade context / loser's)
        try:
            tw_n = getattr(lose, '_threat_weight_n', 0) or 0
            tw_acc = getattr(lose, '_threat_weight_acc', 0.0) or 0.0
            row['threat_weight_avg'] = round(tw_acc / tw_n, 4) if tw_n else 0.0
            row['threat_weight_n'] = int(tw_n)
            row['threat_weight_base'] = round(float(st.get('threat_weight_base', 1.0)), 4)
            row['threat_dist_exp'] = round(float(st.get('threat_dist_exp', 1.4)), 4)
            row['threat_count_scale'] = round(float(st.get('threat_count_scale', 0.55)), 4)
            row['threat_closing_scale'] = round(float(st.get('threat_closing_scale', 0.45)), 4)
            row['threat_front_scale'] = round(float(st.get('threat_front_scale', 0.35)), 4)
        except Exception:
            row['threat_weight_avg'] = 0.0
            row['threat_weight_n'] = 0
            row['threat_weight_base'] = row['threat_dist_exp'] = 0.0
            row['threat_count_scale'] = row['threat_closing_scale'] = row['threat_front_scale'] = 0.0

        # Corner-herd: prey died near corner while hunter still had predators
        try:
            ww = float(getattr(self.w, 'width', 800))
            hh = float(getattr(self.w, 'height', 600))
            margin = float(st.get('corner_zone_margin', 120.0))
            cscore = SectorLogic.corner_score(lose.x, lose.y, ww, hh, margin)
            row['prey_corner_score'] = round(cscore, 3)
            row['corner_herd'] = 1 if (cscore >= 0.45 and int(row.get('fear_count', fc if 'fc' in dir() else 0) or 0) > 0) else 0
            # fear_count of winner at conversion
            win_fear = self.w.type_counts.get(FEAR_OF.get(win.type), 0)
            row['corner_herd_while_fear'] = 1 if (cscore >= 0.45 and win_fear > 0) else 0
            row['no_corner_herd'] = round(float(st.get('no_corner_herd', 1.0)), 4)
            row['open_field_bias'] = round(float(st.get('open_field_bias', 0.7)), 4)
            row['corner_zone_margin'] = round(float(st.get('corner_zone_margin', 120.0)), 2)
            row['corner_herd_avoids'] = int(getattr(win, '_corner_herd_avoid', 0) or 0)
            row['hide_among_prey_frames'] = int(getattr(win, '_hide_among_frames', 0) or 0)
            row['hide_among_prey_weight'] = round(float(st.get('hide_among_prey_weight', 0.0)), 4)
            row['hide_among_prey_radius'] = round(float(st.get('hide_among_prey_radius', 16.0)), 4)
            row['hide_among_prey_min'] = int(st.get('hide_among_prey_min', 3))
        except Exception:
            row['prey_corner_score'] = 0.0
            row['corner_herd'] = 0
            row['corner_herd_while_fear'] = 0
            row['no_corner_herd'] = row['open_field_bias'] = 0.0
            row['corner_zone_margin'] = 0.0
            row['corner_herd_avoids'] = 0
            row['hide_among_prey_frames'] = 0
            row['hide_among_prey_weight'] = 0.0
            row['hide_among_prey_radius'] = 0.0
            row['hide_among_prey_min'] = 0

        # Full STRATEGY_KEYS snapshot (winner effective strategy at conversion)
        try:
            for _sk in STRATEGY_KEYS:
                if _sk in row:
                    continue  # keep specialized metric already written
                val = st.get(_sk, TYPE_DEFAULTS.get(tname, {}).get(_sk, ''))
                if isinstance(val, bool):
                    row[_sk] = int(val)
                elif isinstance(val, (int, float)):
                    row[_sk] = round(float(val), 6) if isinstance(val, float) else int(val)
                else:
                    row[_sk] = val
        except Exception:
            for _sk in STRATEGY_KEYS:
                row.setdefault(_sk, '')

        self.conversions.append(row)
        # Header: event columns + every STRATEGY_KEY (union, stable order)
        keys = [
            'gameid','time_s','runcount','teamSize','winner_type','loser_was','winner_role','winner_mode','winner_strategy','loser_strategy',
            'winner_speed','winner_maxspeed','winner_strength','winner_agility','winner_bravery',
            'winner_team_count','loser_team_count','fear_count','prey_count',
            'rock_count','paper_count','scissors_count',
            'self_before','fear_before','prey_before','self_after','fear_after','prey_after',
            'self_fear_ratio','self_prey_ratio','fear_prey_ratio',
            'winner_speed_base','winner_turn_base','dist_to_loser',
            'winner_near_fort','loser_near_fort','winner_cover','loser_cover','fort_count',
            'aggro','finish','cluster','fear_close','escape','cohesion','pack','focus','lock_ttl',
            'is_small_unit','small_raid','small_escape','solo_finish','outnumbered_fear','flank','predict','self_count',
            'was_evading','did_brake','did_reverse','evade_threshold','evade_speed','evade_brake',
            'evade_reverse_risk','evade_turn','evade_predict','residual_fear',
            'last_prey_kill','last_prey_with_fear','game_state',
            'prey_reserve','prey_reserve_penalty','clear_finish_mult',
            'state_clear_hunt','state_last_prey_risk','state_no_prey_fear',
            'state_outnumbered','state_small_unit','state_contested',
            'effective_aggro','effective_finish','effective_escape',
            'fort_cover_weight','fort_hide_bias','fort_ambush_bonus','ambush_kill','pincer_kill','pack_density','asymmetric_sep_front','asymmetric_sep_rear','speed_match_weight','offset_pursue_dist','offset_pursue_gain','arrive_radius','arrive_slow','wander_strength','wander_rate','arrive_active','wander_active','clear_spread_weight','clear_split_threshold','clear_finish_speed','clear_reassign_dist','clear_split_event','voronoi_weight','voronoi_balance','voronoi_recompute_interval','voronoi_overflow_threshold','clear_voronoi_cap_slack','clear_voronoi_predict','voronoi_imbalance','voronoi_reassign','swarm_sep_mag','swarm_coh_mag','swarm_ali_mag','swarm_fear_mag','swarm_prey_mag','swarm_avoid_mag','swarm_total_mag','delaunay_peels','cross_map_reassigns','delaunay_overflow','delaunay_k','delaunay_pure_edges','knn_fill_edges','pack_density_at_prey','flank_imbalance','overcrowd_event','strike_size','strike_multi','local_friend_sep','local_friend_n','victim_sep_distance','near_wipe_threshold','near_wipe_sep_mult','near_wipe_evade_mult','near_wipe_fort_mult','near_wipe_cohesion','state_near_wipe','near_wipe_active','ally_knock_into_fear','ally_protect_hits','ally_protect_weight','ally_protect_radius','threat_weight_avg','threat_weight_n','threat_weight_base','threat_dist_exp','threat_count_scale','threat_closing_scale','threat_front_scale','prey_corner_score','corner_herd','corner_herd_while_fear','no_corner_herd','open_field_bias','corner_zone_margin','corner_herd_avoids','hide_among_prey_frames','hide_among_prey_weight','hide_among_prey_radius','hide_among_prey_min',
        ]
        # Append any STRATEGY_KEYS not already in the fixed header
        for _sk in STRATEGY_KEYS:
            if _sk not in keys:
                keys.append(_sk)
        try:
            line = ','.join(str(row.get(k, '')) for k in keys) + chr(10)
            buf = getattr(self, '_conv_buf', None)
            if buf is None:
                self._conv_buf = []
                buf = self._conv_buf
            buf.append(line)
            if len(buf) >= 8:
                self._safe_append(self.CONV_CSV, ''.join(buf))
                self._conv_buf = []
        except Exception:
            pass

    def flush_conv_buf(self):
        buf = getattr(self, '_conv_buf', None)
        if buf:
            try:
                self._safe_append(self.CONV_CSV, ''.join(buf))
            except Exception:
                pass
            self._conv_buf = []

    def log_gameover(self, winner_type):
        self.flush_conv_buf()

        if getattr(self.w, 'frozen_match_ms', 0):
            duration_s = round(self.w.frozen_match_ms / 1000.0, 2)
        elif self.w.match_start_ticks is not None:
            duration_s = round((pygame.time.get_ticks() - self.w.match_start_ticks) / 1000.0, 2)
        else:
            duration_s = 0.0
        # FAST_SIM / dummy driver: pygame clock is not wall time. Use ticks.
        if duration_s <= 0.0:
            rc = float(getattr(self.w, 'runcount', 0) or 0)
            fps = float(getattr(Config, 'FPS', 0) or getattr(Config, 'TARGET_FPS', 0) or 60) or 60.0
            duration_s = round(rc / fps, 2)
        counts = {t.name: self.w.type_counts.get(t, 0) for t in ParticleType}
        conv_by = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
        for c in self.conversions:
            conv_by[c['winner_type']] = conv_by.get(c['winner_type'], 0) + 1

        def mode_frac(tname, mname):
            total = sum(self.mode_ticks[tname].values()) or 1
            return round(self.mode_ticks[tname][mname] / total, 3)

        wname = winner_type.name if winner_type else '?'
        wipe = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
        for c in self.conversions:
            try:
                if int(c.get('last_prey_with_fear', 0) or 0) == 1:
                    wipe[c['winner_type']] = wipe.get(c['winner_type'], 0) + 1
            except Exception:
                pass
        wipe_total = sum(wipe.values())
        fort_near_wins = sum(1 for c in self.conversions if int(c.get('winner_near_fort', 0) or 0) == 1)
        fort_cover_wins = sum(1 for c in self.conversions if int(c.get('winner_cover', 0) or 0) == 1)
        fort_near_losses = sum(1 for c in self.conversions if int(c.get('loser_near_fort', 0) or 0) == 1)
        fort_cover_losses = sum(1 for c in self.conversions if int(c.get('loser_cover', 0) or 0) == 1)
        overcrowd_events = sum(1 for c in self.conversions if int(c.get('overcrowd_event', 0) or 0) == 1)
        multi_strike_events = sum(1 for c in self.conversions if int(c.get('strike_multi', 0) or 0) == 1)
        max_strike = max((int(c.get('strike_size', 0) or 0) for c in self.conversions), default=0)
        avg_friend_sep = 0.0
        seps = [float(c.get('local_friend_sep') or 0) for c in self.conversions if float(c.get('local_friend_sep') or 0) > 0]
        if seps:
            avg_friend_sep = sum(seps) / len(seps)
        dens_list = [float(c.get('pack_density_at_prey') or 0) for c in self.conversions]
        imb_list = [float(c.get('flank_imbalance') or 0) for c in self.conversions]
        avg_pack_density = sum(dens_list) / max(1, len(dens_list))
        avg_flank_imbalance = sum(imb_list) / max(1, len(imb_list))
        wtype = winner_type if winner_type else ParticleType.ROCK
        try:
            fear_left = counts.get(FEAR_OF[wtype].name, 0)
            prey_left = counts.get(PREY_OF[wtype].name, 0)
        except Exception:
            fear_left = 0
            prey_left = 0
        row = [
            str(self.w.gameid), self.w.teamSize, len(self.w.fort_list), duration_s, self.w.runcount, wname,
            counts['ROCK'], counts['PAPER'], counts['SCISSORS'],
            conv_by['ROCK'], conv_by['PAPER'], conv_by['SCISSORS'],
            mode_frac('ROCK','HUNT'), mode_frac('ROCK','DEFEND'), mode_frac('ROCK','REGROUP'), mode_frac('ROCK','SCATTER'),
            mode_frac('PAPER','HUNT'), mode_frac('PAPER','DEFEND'), mode_frac('PAPER','REGROUP'), mode_frac('PAPER','SCATTER'),
            mode_frac('SCISSORS','HUNT'), mode_frac('SCISSORS','DEFEND'), mode_frac('SCISSORS','REGROUP'), mode_frac('SCISSORS','SCATTER'),
            len(self.conversions),
            wipe_total, wipe['ROCK'], wipe['PAPER'], wipe['SCISSORS'],
            int(fear_left > 0), prey_left,
            fort_near_wins, fort_cover_wins, fort_near_losses, fort_cover_losses,
            overcrowd_events, round(avg_pack_density, 2), round(avg_flank_imbalance, 3),
            # Endgame (CLEAR_HUNT) duration metrics
            (self.w.runcount - self.w._endgame_start_rc) if getattr(self.w, '_endgame_start_rc', None) is not None else 0,
            round(((self.w.runcount - self.w._endgame_start_rc) / max(1, getattr(Config, 'FPS', 60))) if getattr(self.w, '_endgame_start_rc', None) is not None else 0, 2),
            getattr(self.w, '_endgame_prey_start', 0) or 0,
            getattr(self.w, '_endgame_split_events', 0) or 0,
            getattr(self.w, '_endgame_simultaneous', 0) or 0,
            Config.VISION_FAR, Config.NEAR_TARGET_AGGRO, Config.CLUSTER_BONUS, Config.FEAR_CLOSE_MULT,
            Config.SCATTER_COUNT_THRESHOLD, Config.TARGET_LOCK_TTL, Config.HUNT_ADVANTAGE, Config.COHESION_WEIGHT,
            Config.PACK_HUNT_MULT, Config.FINISH_BONUS, Config.ESCAPE_BONUS_WEIGHT, Config.FEAR_POP_SCALE,
        ]
        self._safe_append(self.GAMES_CSV, ','.join(str(x) for x in row) + chr(10))
        try:
            total = self.bump_games_total()
            if hasattr(self.w, 'optimizer') and self.w.optimizer is not None:
                self.w.optimizer.games_seen = total
        except Exception:
            pass
        # write_summary reads the whole CSV — never on the frame path.
        try:
            self.last_man_frames = dict(getattr(self.w, '_last_man_frames', {}) or {})
            self.last_man_dead = dict(getattr(self.w, '_last_man_dead', {}) or {})
            self.last_man_hunter = dict(getattr(self.w, '_last_man_hunter', {}) or {})
            # freeze clocks for types still alive as last man
            for t, team in (getattr(self.w, 'teams', {}) or {}).items():
                name = t.name if hasattr(t, 'name') else str(t)
                if int(getattr(team, 'count', 0) or 0) == 1:
                    self.last_man_frames[name] = int(self.last_man_frames.get(name, 0) or 0)
        except Exception:
            self.last_man_frames = {}
            self.last_man_dead = {}
            self.last_man_hunter = {}
        try:
            self.write_strategy_row(winner_type)
        except Exception:
            pass
        try:
            for tname, team in (getattr(self.w, 'teams', {}) or {}).items():
                nw = getattr(team, 'near_wipe_frames', 0)
                if nw and hasattr(self.w, 'optimizer') and hasattr(self.w.optimizer, '_log_raw'):
                    self.w.optimizer._log_raw(
                        f"near_wipe {tname}: frames={nw} events={getattr(team, 'near_wipe_events', 0)}"
                    )
        except Exception:
            pass
        try:
            if hasattr(self.w, 'optimizer') and hasattr(self.w.optimizer, '_log_raw'):
                self.w.optimizer._log_raw(
                    f"strike_match multi={multi_strike_events} max_strike={max_strike} "
                    f"avg_friend_sep={avg_friend_sep:.1f}"
                )
        except Exception:
            pass
        # Unherd / no-corner-herd match stats
        try:
            if hasattr(self.w, 'optimizer') and hasattr(self.w.optimizer, '_log_raw'):
                corner_n = sum(1 for c in self.conversions if int(c.get('corner_herd_while_fear', 0) or 0) == 1)
                avoids = sum(int(c.get('corner_herd_avoids', 0) or 0) for c in self.conversions)
                avg_cs = 0.0
                scores = [float(c.get('prey_corner_score') or 0) for c in self.conversions]
                if scores:
                    avg_cs = sum(scores) / len(scores)
                by_type = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
                for c in self.conversions:
                    if int(c.get('corner_herd_while_fear', 0) or 0) == 1:
                        wt = c.get('winner_type', '')
                        if wt in by_type:
                            by_type[wt] += 1
                self.w.optimizer._log_raw(
                    f"unherd match: corner_herd_while_fear={corner_n} "
                    f"avoids={avoids} avg_corner_score={avg_cs:.2f} "
                    f"by_winner={by_type}"
                )
        except Exception:
            pass
        try:
            sm_all = self.w.swarm_mag_averages()
            if hasattr(self.w, 'optimizer') and hasattr(self.w.optimizer, '_log_raw'):
                self.w.optimizer._log_raw(
                    f"swarm_mags avg sep={sm_all.get('sep_mag')} coh={sm_all.get('coh_mag')} "
                    f"ali={sm_all.get('ali_mag')} fear={sm_all.get('fear_mag')} "
                    f"prey={sm_all.get('prey_mag')} avoid={sm_all.get('avoid_mag')} "
                    f"total={sm_all.get('mag')}"
                )
        except Exception:
            pass
        # Heavy optimise/persist is queued by Arena and pumped off the
        # playing/gameover frames. Credit + CSV only happen here.

        try:
            import strategies.playbook as playbook
            mode_ticks = {}
            smt = getattr(self, 'strategy_mode_ticks', {}) or {}
            for tn, modes in smt.items():
                mode_ticks[tn] = {}
                # smt is {type: {mode: {sid: n}}}
                if modes and isinstance(next(iter(modes.values()), None), dict):
                    first = next(iter(modes.values()))
                    if first and next(iter(first.keys()), '').isupper() and '_' in next(iter(first.keys()), 'x'):
                        # actually {mode: {sid: n}}
                        for md, bag in modes.items():
                            for sid, n in (bag or {}).items():
                                mode_ticks[tn].setdefault(sid, {})[md] = mode_ticks[tn].setdefault(sid, {}).get(md, 0) + int(n or 0)
                    else:
                        mode_ticks[tn] = modes
            playbook.credit_decisions({
                'winner': winner_type.name if hasattr(winner_type, 'name') else str(winner_type),
                'ticks': getattr(self, 'strategy_ticks', {}),
                'mode_ticks': mode_ticks,
                'state_ticks': getattr(self, 'strategy_state_ticks', {}) or {},
                'conversions': list(self.conversions or []),
                'duration_s': duration_s,
                'endgame_seconds': round(
                    ((self.w.runcount - self.w._endgame_start_rc) /
                     max(1.0, float(getattr(Config, 'FPS', 60) or 60)))
                    if getattr(self.w, '_endgame_start_rc', None) is not None else 0.0, 2),
                'endgame_hunter': (
                    getattr(self.w, '_endgame_type', None).name
                    if getattr(self.w, '_endgame_type', None) is not None else ''),
            })
            try:
                playbook.write_grok_brief(self)
            except Exception:
                pass
            try:
                self.consume_used_metrics()
            except Exception:
                pass
        except Exception as e:
            try:
                if hasattr(self.w, 'optimizer'):
                    self.w.optimizer._log_raw('credit_decisions failed: %s' % e)
            except Exception:
                pass

    def write_summary(self):
        """Aggregate all games into actionable tuning notes."""
        import collections
        try:
            with open(self.GAMES_CSV, encoding='utf-8') as f:
                lines = f.read().strip().split('\n')
        except Exception:
            return
        if len(lines) < 2:
            return
        headers = lines[0].split(',')
        games = []
        for line in lines[1:]:
            parts = line.split(',')
            if len(parts) < len(headers):
                continue
            games.append(dict(zip(headers, parts)))

        n = len(games)
        wins = collections.Counter(g['winner'] for g in games)
        avg_dur = sum(float(g['duration_s']) for g in games) / n
        avg_conv = sum(int(g['total_conversions']) for g in games) / n

        # Per-type conversion share
        type_conv = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0}
        for g in games:
            for t in type_conv:
                type_conv[t] += int(g.get(f'{t.lower()}_conversions', 0))
        total_c = sum(type_conv.values()) or 1

        # Average mode share when that type wins
        def avg_mode_when_win(tname, mname):
            col = f'{tname.lower()}_mode_{mname}'
            vals = [float(g[col]) for g in games if g['winner'] == tname and col in g]
            return sum(vals) / len(vals) if vals else 0.0

        lines_out = []
        lines_out.append('=' * 60)
        lines_out.append('RPS METRICS SUMMARY – for Config fine-tuning')
        lines_out.append('=' * 60)
        lines_out.append(f'Games logged: {n}')
        lines_out.append(f'Avg duration: {avg_dur:.1f}s   Avg conversions/game: {avg_conv:.1f}')
        lines_out.append('')
        lines_out.append('--- Win rate by type (outcome) ---')
        for t in ('ROCK', 'PAPER', 'SCISSORS'):
            wr = 100.0 * wins.get(t, 0) / n
            motion = TYPE_MOTION[t]
            lines_out.append(
                f'  {t:8s}  wins={wins.get(t,0):3d} ({wr:5.1f}%)  '
                f'speed_base={motion["speed_base"]}  turn_base={motion["turn_base"]}  '
                f'conv_share={100*type_conv[t]/total_c:.1f}%'
            )
        lines_out.append('')
        lines_out.append('--- Mode mix when that type WINS (what success looks like) ---')
        for t in ('ROCK', 'PAPER', 'SCISSORS'):
            if wins.get(t, 0) == 0:
                lines_out.append(f'  {t}: (no wins yet)')
                continue
            parts = [f'{m}={avg_mode_when_win(t,m):.0%}' for m in ('HUNT', 'DEFEND', 'REGROUP', 'SCATTER')]
            lines_out.append(f'  {t}: ' + '  '.join(parts))

        lines_out.append('')
        lines_out.append('--- Type motion properties (from config.py) ---')
        lines_out.append('  ROCK:     slower, turns faster  -> prefers close fights / tighter turns')
        lines_out.append('  PAPER:    fastest, turns slowest -> needs earlier commitment / longer chase')
        lines_out.append('  SCISSORS: mid speed & turn      -> balanced')

        lines_out.append('')
        lines_out.append('--- Actionable tuning hints ---')
        # Simple heuristics
        if n >= 3:
            ranked = sorted(wins.keys(), key=lambda t: -wins[t])
            best, worst = ranked[0], ranked[-1]
            if wins[best] > wins[worst]:
                lines_out.append(f'  * {best} dominates ({wins[best]}/{n}). If undesired:')
                if best == 'PAPER':
                    lines_out.append('      - PAPER is fastest: lower NEAR_TARGET_AGGRO or raise FEAR_CLOSE_MULT for its prey (ROCK)')
                    lines_out.append('      - Or raise ROCK turn / chase (ROLE_HUNTER_PURSUIT, TARGET_LOCK_BONUS)')
                elif best == 'ROCK':
                    lines_out.append('      - ROCK turns well: reduce FINISH_BONUS / NEAR_TARGET_AGGRO slightly')
                    lines_out.append('      - Or boost PAPER escape (ESCAPE_BONUS_WEIGHT) / SCISSORS aggression')
                elif best == 'SCISSORS':
                    lines_out.append('      - SCISSORS balanced: tweak CLUSTER_BONUS or PACK_HUNT_MULT to shift group fights')
                lines_out.append(f'  * {worst} underperforms. Consider:')
                motion = TYPE_MOTION.get(worst, {})
                lines_out.append(f'      - Check mode mix when {worst} loses; if high SCATTER, raise SCATTER_COUNT_THRESHOLD')
                lines_out.append(f'      - Boost FOCUS_TARGET_BONUS / TARGET_LOCK_TTL so {worst} finishes chases')
            # Long games
            if avg_dur > 180:
                lines_out.append('  * Games are long (>3 min avg): raise NEAR_TARGET_AGGRO, FINISH_BONUS, or VISION_FAR')
            elif avg_dur < 45:
                lines_out.append('  * Games are very short: raise FEAR_CLOSE_MULT or lower NEAR_TARGET_AGGRO')
        else:
            lines_out.append('  * Need at least 3 finished games for automatic hints.')

        lines_out.append('')
        lines_out.append('--- Key Config knobs (current values) ---')
        for k in ('VISION_FAR', 'NEAR_TARGET_AGGRO', 'FINISH_BONUS', 'CLUSTER_BONUS',
                  'FEAR_CLOSE_MULT', 'ESCAPE_BONUS_WEIGHT', 'COHESION_WEIGHT', 'PACK_HUNT_MULT',
                  'TARGET_LOCK_TTL', 'TARGET_SWITCH_MARGIN', 'HUNT_ADVANTAGE', 'SCATTER_COUNT_THRESHOLD'):
            lines_out.append(f'  {k} = {getattr(Config, k)}')
        lines_out.append('')
        lines_out.append(f'Source CSVs: {self.GAMES_CSV}  |  {self.CONV_CSV}')
        lines_out.append('=' * 60)

        text = '\n'.join(lines_out) + '\n'
        # UTF-8 so Windows (cp1252) does not choke on any remaining non-ASCII
        with open(self.SUMMARY, 'w', encoding='utf-8') as f:
            f.write(text)
        return text


    def write_strategy_row(self, winner_type):
        """One row per match: ticks in each strategy per type + switch counts."""
        import csv as _csv
        path = log_path('metrics_strategy.csv')
        fields = ['gameid', 'winner', 'teamSize']
        for t in ('ROCK', 'PAPER', 'SCISSORS'):
            for s in STRATEGY_IDS:
                fields.append('%s_%s' % (t[:1], s))
            fields.append('%s_switches' % t[:1])
        need_header = True
        try:
            with open(path, 'r', encoding='utf-8') as f:
                need_header = not f.readline()
        except Exception:
            need_header = True
        row = {
            'gameid': getattr(self.w, 'gameid', ''),
            'winner': getattr(winner_type, 'name', str(winner_type)),
            'teamSize': getattr(self.w, 'teamSize', 0),
        }
        ticks = getattr(self, 'strategy_ticks', {})
        for t in ParticleType:
            team = self.w.teams.get(t)
            for s in STRATEGY_IDS:
                row['%s_%s' % (t.name[:1], s)] = ticks.get(t.name, {}).get(s, 0)
            row['%s_switches' % t.name[:1]] = getattr(team, 'strategy_switches', 0) if team else 0
        line = ','.join(str(row.get(k, 0)) for k in fields)
        if need_header:
            self._safe_write(path, ','.join(fields) + '\n' + line + '\n')
        else:
            self._safe_append(path, line + '\n')
