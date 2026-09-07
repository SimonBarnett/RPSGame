"""
Rock-Paper-Scissors Particle Simulation — decision layer.
Team + Particle AI. Geometry lives in maths/, presentation in arena/.
"""

import pygame
import random
import math
from pygame.sprite import Sprite

from config import (
    Config, TurnRelative, TeamMode, Role,
    PREY_OF, FEAR_OF, SECTOR_CENTRES, ALL_VISION_DIRS, FAST_VISION_DIRS,
)
from config import TYPE_DEFAULTS, effective_strategy
from arena.marble import display_particle
from arena.paths import image_path
from maths.phys import (
    maxspeed as phys_maxspeed, enforce_speed as phys_enforce_speed,
    bounce_walls, integrate as phys_integrate,
)
from maths.ping import ParticleRelative, Pinged, Direction, SectorLogic, Steer
from arena.fort import FortLOS, collide_particle as fort_collide_particle
from maths.voronoi import VoronoiEndgame
from maths.boids import SwarmIntelligence
from strategies import playbook

if not pygame.get_init():
    pygame.init()


class Team:
    __slots__ = ('type', 'world', 'members', 'center', 'avg_vel', 'mode',
                 'suggested_target', 'count', '_isolation_cache',
                 '_last_isolation_frame', 'alert_target', 'alert_ttl',
                 '_mode_candidate', '_mode_hold', 'recent_wins',
                 '_last_role_eval', 'pincer_assignments', 'pincer_switch_cd', 'pincer_side_pref',
                 'near_wipe_frames', 'near_wipe_events', 'clear_hunt_map',
                 'strategy_id', 'strategy_hold', 'strategy_switches',
                 '_endgame_switch')

    def __init__(self, ptype, world):
        self.type = ptype
        self.world = world
        self.members = []
        self.center = (world.width/2, world.height/2)
        self.avg_vel = (0.0, 0.0)
        self.mode = TeamMode.HUNT
        self.suggested_target = None
        self.count = 0
        self._isolation_cache = {}
        self._last_isolation_frame = -999
        self.alert_target = None
        self.alert_ttl = 0
        self._mode_candidate = TeamMode.HUNT
        self._mode_hold = 0
        self.recent_wins = 0.0
        self._last_role_eval = -999
        self.pincer_assignments = {}
        self.pincer_switch_cd = {}
        self.pincer_side_pref = {}
        self.near_wipe_frames = 0
        self.near_wipe_events = 0
        self.clear_hunt_map = {}
        self.strategy_id = 'PACK_HUNT'
        self.strategy_hold = 0
        self.strategy_switches = 0
        self._endgame_switch = None

    def update(self):
        self.members = [p for p in self.world.particles if p.type == self.type]
        self.count = len(self.members)
        if not self.members:
            self.center = (self.world.width/2, self.world.height/2)
            self.avg_vel = (0.0, 0.0)
            self.mode = TeamMode.REGROUP
            self.suggested_target = None
            self._isolation_cache.clear()
            self.alert_target = None
            self.alert_ttl = 0
            self.recent_wins = 0.0
            return
        self.center = (sum(p.x for p in self.members)/self.count,
                       sum(p.y for p in self.members)/self.count)
        self.avg_vel = (sum(math.sin(p.angle)*p.speed for p in self.members)/self.count,
                        sum(-math.cos(p.angle)*p.speed for p in self.members)/self.count)
        fear = self.world.type_counts.get(FEAR_OF[self.type], 0)
        prey = self.world.type_counts.get(PREY_OF[self.type], 0)
        self.recent_wins = max(0.0, self.recent_wins * 0.985)
        st = effective_strategy(self.type.name, self.world.teamSize, self_count=self.count,
            fear_count=fear, prey_count=prey)
        hunt_adv = st["hunt_advantage"]
        scatter_th = st["scatter_threshold"]
        game_state = st.get("_game_state", "CONTESTED")
        cut = playbook.endgame_switch(
            self.type.name, game_state,
            current=getattr(self, 'strategy_id', None),
            fear=fear, prey=prey, self_count=self.count,
            opponent=FEAR_OF[self.type].name)
        if cut is not None:
            sid, hold, switched = cut
            self._endgame_switch = sid
        else:
            sid, hold, switched = playbook.select(
                self.type.name, game_state,
                current=getattr(self, 'strategy_id', None),
                hold_frames=getattr(self, 'strategy_hold', 0),
                opponent=FEAR_OF[self.type].name)
            self._endgame_switch = None
        self.strategy_id = sid
        self.strategy_hold = hold
        try:
            ban = playbook._banned(self.type.name)
            if sid in ban:
                legal = playbook._legal_ids(self.type.name, game_state)
                sid = playbook._fallback(self.type.name, legal)
                self.strategy_id = sid
                self.strategy_hold = 0
                switched = True
        except Exception:
            pass
        try:
            from optimizer import rl
            rl.remember(self.type.name, game_state, sid, prey, fear)
        except Exception:
            pass
        if switched:
            self.strategy_switches = getattr(self, 'strategy_switches', 0) + 1
        st = playbook.annotate(st, sid, self.type.name)
        mode_name = playbook.team_mode_name(sid)
        small_th = st.get("small_unit_threshold", 3)
        if self.recent_wins > 2.0:
            hunt_adv *= (1.0 - Config.MOMENTUM_HUNT_BIAS)
        desired = getattr(TeamMode, mode_name, TeamMode.REGROUP)
        wipe_th = int(st.get("near_wipe_threshold", 2))
        near_wipe = (self.count <= wipe_th and fear > 0)
        if fear == 0 and prey > 0:
            desired = TeamMode.HUNT
        elif near_wipe:
            desired = TeamMode.SCATTER
        elif prey <= 0 and fear > 0:
            desired = TeamMode.SCATTER
        elif (self.count <= scatter_th or self.count <= small_th
                or (self.count < fear * 0.9 and self.count <= 5)
                or (self.count <= 2 and fear >= 1)):
            desired = TeamMode.SCATTER
        elif self.count >= max(1, fear) * hunt_adv and prey > 0:
            desired = TeamMode.HUNT
        elif self.count < fear * Config.DEFEND_RATIO or (fear > prey and self.count <= 3):
            desired = TeamMode.DEFEND
        else:
            desired = TeamMode.REGROUP

        if fear == 0 and prey > 0:
            self.mode = TeamMode.HUNT
            self._mode_candidate = TeamMode.HUNT
            self.alert_target = None
            self.alert_ttl = 0
            self.suggested_target = None
            try:
                prey_list = [q for q in self.world.particles if q.type == PREY_OF[self.type]]
                hunters = list(self.members)
                if prey_list and hunters and playbook.tactic_enabled(sid, 'voronoi_split', self.type.name):
                    mapping = VoronoiEndgame.assign(self.world, hunters, prey_list, st)
                    self.clear_hunt_map = mapping
                    for h in hunters:
                        hid = getattr(h, 'id', id(h))
                        assigned = mapping.get(hid)
                        if assigned is None and len(prey_list) >= 1:
                            prey_s = sorted(prey_list, key=lambda q: getattr(q, 'id', id(q)))
                            hunt_s = sorted(hunters, key=lambda q: getattr(q, 'id', id(q)))
                            try:
                                mi = next(i for i, x in enumerate(hunt_s) if x is h)
                            except StopIteration:
                                mi = abs(hash(hid)) % len(hunt_s)
                            assigned = prey_s[mi % len(prey_s)]
                        if assigned is not None:
                            h._locked_target = assigned
                            h._lock_ttl = 120
                            h._clear_assigned_id = getattr(assigned, 'id', id(assigned))
            except Exception:
                self.clear_hunt_map = {}
        elif near_wipe:
            self.mode = TeamMode.SCATTER
            self._mode_candidate = TeamMode.SCATTER
            self._mode_hold = 0
            self.alert_target = None
            self.alert_ttl = 0
            self.near_wipe_frames = getattr(self, 'near_wipe_frames', 0) + 1
            self.near_wipe_events = getattr(self, 'near_wipe_events', 0) + 1
        elif prey <= 0 and fear > 0:
            self.mode = TeamMode.SCATTER
            self._mode_candidate = TeamMode.SCATTER
            self._mode_hold = 0
        elif desired == self.mode:
            self._mode_candidate = desired
            self._mode_hold = 0
        elif desired == self._mode_candidate:
            self._mode_hold += 1
            need = 3 if desired == TeamMode.SCATTER else Config.MODE_HYSTERESIS
            if self._mode_hold >= need:
                self.mode = desired
                self._mode_hold = 0
        else:
            self._mode_candidate = desired
            self._mode_hold = 1

        if self.alert_ttl > 0:
            self.alert_ttl -= 1
            if self.alert_ttl <= 0:
                self.alert_target = None
        if (self.world.runcount - self._last_isolation_frame) >= Config.ISOLATION_UPDATE_EVERY:
            self._update_isolation_and_target()
            self._last_isolation_frame = self.world.runcount
        if (self.world.runcount - self._last_role_eval) >= Config.ROLE_REEVAL_EVERY:
            self._reeval_roles()
            self._last_role_eval = self.world.runcount
        if playbook.tactic_enabled(self.strategy_id, 'pincer_flank', self.type.name):
            self._assign_pincers()
        else:
            self.pincer_assignments = {}

    def _update_isolation_and_target(self):
        self._isolation_cache.clear()
        prey_type = PREY_OF[self.type]
        fear_type = FEAR_OF[self.type]
        fear_particles = [p for p in self.world.particles if p.type == fear_type]
        if fear_particles:
            fcx = sum(p.x for p in fear_particles) / len(fear_particles)
            fcy = sum(p.y for p in fear_particles) / len(fear_particles)
        else:
            fcx = fcy = 0.0
        best, best_score = None, -1e9
        for p in self.world.particles:
            if p.type != prey_type:
                continue
            same = sum(1 for o in self.world.particles
                       if o is not p and o.type == p.type
                       and math.hypot(o.x-p.x, o.y-p.y) < 8*p.size)
            isolation = 1.0 / (1 + same)
            self._isolation_cache[id(p)] = isolation
            near_us = sum(1 for m in self.members if math.hypot(m.x-p.x, m.y-p.y) < 12*p.size)
            speed_f = 1.0 - min(1.0, p.speed / (p.maxspeed()+1e-6)) * 0.35
            dist_c = math.hypot(p.x-self.center[0], p.y-self.center[1])
            fort_b = 0.0
            for f in self.world.fort_list:
                if math.hypot(p.x-f.x, p.y-f.y) < f.radius + 65:
                    fort_b += 0.45
            score = (isolation*2.3 + near_us*0.9 + fort_b) * speed_f - dist_c / max(self.world.width, 1)
            if self.mode != TeamMode.SCATTER and self.count > Config.SCATTER_COUNT_THRESHOLD:
                score += same * Config.CLUSTER_BONUS * 1.4 + fort_b * 0.3
            if self.mode == TeamMode.SCATTER or self.count <= Config.SCATTER_COUNT_THRESHOLD:
                dist_to_fear_cent = math.hypot(p.x - fcx, p.y - fcy) if fear_particles else 400
                nearest_fear_d = min((math.hypot(p.x-f.x, p.y-f.y) for f in fear_particles), default=400)
                safety = (dist_to_fear_cent / max(self.world.width, 1)) * 1.6 + (nearest_fear_d / max(self.world.width, 1)) * 0.9
                score = score * 0.7 + isolation * 1.8 + safety * 1.4 + fort_b * 0.6
            if not fear_particles:
                score += 3.5 + near_us * 0.5
            if score > best_score:
                best_score, best = score, p
        self.suggested_target = best
        if not fear_particles and best is not None:
            self.set_alert(best, Config.ALERT_TTL_KILL)

    def _assign_pincers(self):
        target = self.alert_target if (self.alert_target and self.alert_ttl > 0) else self.suggested_target
        if target is None or target not in self.world.particles:
            self.pincer_assignments = {}
            return
        if self.mode not in (TeamMode.HUNT, TeamMode.REGROUP):
            self.pincer_assignments = {}
            return
        st_ref = effective_strategy(self.type.name, self.world.teamSize, self_count=self.count)
        min_friends = int(st_ref.get('pincer_min_friends', 2))
        pw = float(st_ref.get('pincer_weight', 1.0))
        if pw < 0.05 or self.count < min_friends:
            self.pincer_assignments = {}
            return
        speed = getattr(target, 'speed', 0) or 0
        if speed > 0.15:
            ux = math.sin(target.angle)
            uy = -math.cos(target.angle)
        else:
            cx, cy = self.center
            dx, dy = target.x - cx, target.y - cy
            L = math.hypot(dx, dy) + 1e-6
            ux, uy = dx / L, dy / L
        lx, ly = -uy, ux
        hyst = float(st_ref.get('pincer_switch_hysteresis', 0.22))
        cd_max = int(st_ref.get('pincer_switch_cooldown', 28))
        switch_gain = float(st_ref.get('pincer_switch_gain', 1.0))
        for pid in list(self.pincer_switch_cd.keys()):
            self.pincer_switch_cd[pid] = max(0, self.pincer_switch_cd.get(pid, 0) - 1)

        def side_score(m, side_name):
            base = math.atan2(target.x - m.x, -(target.y - m.y))
            side = -1.0 if side_name == 'left' else 1.0
            off = 3.2 * m.size
            ox = target.x + math.sin(base + side * math.pi / 2) * off
            oy = target.y - math.cos(base + side * math.pi / 2) * off
            d = math.hypot(ox - m.x, oy - m.y)
            score = 1.0 / (1.0 + d / (10 * m.size))
            if FortLOS.clear(self.world, m.x, m.y, ox, oy, margin=1.5):
                score += 0.35
            if FortLOS.clear(self.world, m.x, m.y, target.x, target.y, margin=1.0):
                score += 0.2
            else:
                score -= 0.25
            mx, my = m.x - target.x, m.y - target.y
            signed = mx * lx + my * ly
            if side_name == 'left' and signed > 0:
                score += 0.3
            elif side_name == 'right' and signed < 0:
                score += 0.3
            elif (side_name == 'left' and signed < 0) or (side_name == 'right' and signed > 0):
                score -= 0.15
            for f in getattr(self.world, 'fort_list', []) or []:
                if getattr(f, 'scale', 1.0) < 0.85:
                    continue
                if math.hypot(ox - f.x, oy - f.y) < f.radius + 4 * m.size:
                    score += 0.15 * switch_gain
                    break
            return score

        counts = {'left': 0, 'right': 0, 'drive': 0}
        for role in self.pincer_assignments.values():
            counts[role] = counts.get(role, 0) + 1
        new_assign = {}
        members_by_dist = sorted(self.members, key=lambda m: math.hypot(m.x - target.x, m.y - target.y))
        drive_id = members_by_dist[0].id if len(members_by_dist) >= 3 else None
        for m in self.members:
            pid = m.id
            if pid == drive_id:
                new_assign[pid] = 'drive'
                self.pincer_side_pref[pid] = 'drive'
                continue
            sL = side_score(m, 'left')
            sR = side_score(m, 'right')
            sL -= 0.12 * counts.get('left', 0)
            sR -= 0.12 * counts.get('right', 0)
            prev = self.pincer_assignments.get(pid) or self.pincer_side_pref.get(pid)
            cd = self.pincer_switch_cd.get(pid, 0)
            chosen = prev if prev in ('left', 'right') else None
            if chosen is None:
                chosen = 'left' if sL >= sR else 'right'
            else:
                other = 'right' if chosen == 'left' else 'left'
                s_cur = sL if chosen == 'left' else sR
                s_oth = sR if chosen == 'left' else sL
                if cd <= 0 and s_oth > s_cur + hyst:
                    chosen = other
                    self.pincer_switch_cd[pid] = cd_max
                    counts[prev] = max(0, counts.get(prev, 1) - 1)
                    counts[chosen] = counts.get(chosen, 0) + 1
            new_assign[pid] = chosen
            self.pincer_side_pref[pid] = chosen
            if prev != chosen and prev in ('left', 'right'):
                counts[prev] = max(0, counts.get(prev, 1) - 1)
            counts[chosen] = counts.get(chosen, 0) + 1
        flankers = [pid for pid, r in new_assign.items() if r in ('left', 'right')]
        n_f = len(flankers)
        cap = max(1, (n_f + 1) // 2)
        for _pass in range(3):
            left_ids = [pid for pid, r in new_assign.items() if r == 'left']
            right_ids = [pid for pid, r in new_assign.items() if r == 'right']
            if len(left_ids) <= cap and len(right_ids) <= cap:
                break
            if len(left_ids) > cap:
                excess = len(left_ids) - cap
                left_ids.sort(key=lambda pid: self.pincer_switch_cd.get(pid, 0))
                for pid in left_ids[:excess]:
                    new_assign[pid] = 'right'
                    self.pincer_side_pref[pid] = 'right'
                    self.pincer_switch_cd[pid] = max(self.pincer_switch_cd.get(pid, 0), 8)
            left_ids = [pid for pid, r in new_assign.items() if r == 'left']
            right_ids = [pid for pid, r in new_assign.items() if r == 'right']
            if len(right_ids) > cap:
                excess = len(right_ids) - cap
                right_ids.sort(key=lambda pid: self.pincer_switch_cd.get(pid, 0))
                for pid in right_ids[:excess]:
                    new_assign[pid] = 'left'
                    self.pincer_side_pref[pid] = 'left'
                    self.pincer_switch_cd[pid] = max(self.pincer_switch_cd.get(pid, 0), 8)
        self.pincer_assignments = new_assign

    def pincer_heading(self, particle, target=None):
        return Steer.pincer_heading(self, particle, target)

    def set_alert(self, target, ttl=None):
        if target is not None:
            self.alert_target = target
            self.alert_ttl = ttl if ttl is not None else Config.ALERT_TTL_SPOT

    def register_conversion(self):
        self.recent_wins += 1.0
        if self.suggested_target is not None:
            self.set_alert(self.suggested_target, Config.ALERT_TTL_KILL)

    def _reeval_roles(self):
        if self.count == 0:
            return
        fear_type = FEAR_OF[self.type]
        prey_type = PREY_OF[self.type]
        for m in self.members:
            nearest_fear_d = min(
                (math.hypot(m.x - o.x, m.y - o.y)
                 for o in self.world.particles if o.type == fear_type),
                default=9999)
            nearest_prey_d = min(
                (math.hypot(m.x - o.x, m.y - o.y)
                 for o in self.world.particles if o.type == prey_type),
                default=9999)
            friend_threatened = False
            for o in self.members:
                if o is m:
                    continue
                if math.hypot(m.x - o.x, m.y - o.y) < 10 * m.size:
                    for f in self.world.particles:
                        if f.type == fear_type and math.hypot(o.x - f.x, o.y - f.y) < 8 * m.size:
                            friend_threatened = True
                            break
                if friend_threatened:
                    break
            dist_c = math.hypot(m.x - self.center[0], m.y - self.center[1])
            on_edge = dist_c > 6 * m.size
            if friend_threatened or (nearest_fear_d < 7 * m.size and nearest_fear_d < nearest_prey_d):
                m.role = Role.DEFENDER
            elif on_edge and self.mode == TeamMode.HUNT:
                m.role = Role.FLANKER
            elif nearest_prey_d < 12 * m.size or self.mode == TeamMode.SCATTER:
                m.role = Role.HUNTER
            else:
                m.assign_role()

    def get_isolation(self, particle):
        return self._isolation_cache.get(id(particle), 0.0)

    def dist_to_center(self, x, y):
        return math.hypot(x - self.center[0], y - self.center[1])



class Particle(Sprite):
    __slots__ = ('size','w','starttype','type','animation_images','image','rect',
                 'wins','losses','turn','polygons','turndir',
                 'strength','agility','bravery','role',
                 'x','y','angle','speed','_vision_dirty','_last_angle','_cached_nearby',
                 '_commit_dir', '_commit_frames', '_commit_risk',
                 '_fear_intensity', '_frames_since_fear',
                 '_locked_target', '_lock_ttl', '_lock_reward',
                 '_evading', '_evade_brake_done', '_did_reverse', '_did_brake',
                 '_ambush_mode', '_ambush_hold_frames', '_ambush_spring_frames',
                 '_ambush_fort', '_ambush_prey_id',
                 '_last_speed_log', 'id', '_sector_nearest', '_sector_totals', '_swarm_comps', '_trail',
                 '_prev_desired', '_prev_turn_cmd', '_speed_smooth', '_desired_heading', '_ai_mode',
                 '_vis_y_offset', '_vis_scale', '_roll_angle')

    def __init__(self, w, particle_type):
        Sprite.__init__(self)
        self.size = 20
        self.w = w
        self.starttype = self.type = particle_type
        try:
            self.animation_images = [pygame.transform.scale(pygame.image.load(f), (40,40))
                                     for f in (image_path('rock.png'), image_path('paper.png'), image_path('scissors.png'))]
        except Exception:
            self.animation_images = None
        self.image = None
        self.rect = pygame.Rect(0,0,40,40)
        self.wins = self.losses = self.turn = 0
        self.polygons = {i:[] for i in range(9)}
        self.turndir = 0
        self.strength = self.agility = self.bravery = 0.0
        self.role = Role.HUNTER
        self.x = self.y = self.angle = self.speed = 0.0
        self._vision_dirty = True
        self._last_angle = None
        self._cached_nearby = None
        self._commit_dir = None
        self._commit_frames = 0
        self._commit_risk = 0.0
        self._fear_intensity = 0.0
        self._frames_since_fear = 999
        self._locked_target = None
        self._lock_ttl = 0
        self._lock_reward = 0.0
        self._evading = False
        self._ambush_mode = 'none'
        self._ambush_hold_frames = 0
        self._ambush_spring_frames = 0
        self._ambush_fort = None
        self._ambush_prey_id = None
        self._evade_brake_done = False
        self._did_reverse = False
        self._did_brake = False
        self._last_speed_log = -999
        self.id = id(self) & 0xFFFF
        self._sector_nearest = {'FEAR': None, 'PREY': None, 'FRIEND': None}
        self._sector_totals = {'FEAR': 0, 'PREY': 0, 'FRIEND': 0}
        self._swarm_comps = {}
        self._trail = []
        self._roll_angle = 0.0
        self._prev_desired = None
        self._prev_turn_cmd = 0.0
        self._speed_smooth = 0.0
        self._desired_heading = None
        self._ai_mode = 'idle'
        self._vis_y_offset = 0.0
        self._vis_scale = 1.0
        self._hide_among_frames = 0

    def get_team(self):
        return self.w.teams[self.type]

    def assign_role(self):
        team = self.get_team()
        if team.mode == TeamMode.DEFEND or (self.bravery < -0.05 and self.strength < 0):
            self.role = Role.DEFENDER
        elif self.agility > 1.0 or abs(self.bravery) < 0.1:
            self.role = Role.FLANKER
        else:
            self.role = Role.HUNTER

    def reset(self):
        self.type = self.starttype
        for _ in range(50):
            self.x = random.randint(self.size, self.w.width-self.size)
            self.y = random.randint(self.size, self.w.height-self.size)
            if all(math.hypot(self.x-f.x, self.y-f.y) >= f.radius+self.size+10
                   for f in self.w.fort_list):
                break
        self.angle = random.uniform(0, math.pi*2)
        d = TYPE_DEFAULTS[self.type.name]
        self.size = d.get("size", 20)
        sr, ar, br = d["strength_range"], d["agility_range"], d["bravery_range"]
        self.strength = random.uniform(sr[0], sr[1])
        self.agility = random.uniform(ar[0], ar[1])
        self.bravery = random.uniform(br[0], br[1])
        self.speed = self.maxspeed()/10
        self.wins = self.losses = self.turn = 0
        self._vision_dirty = True
        self._last_angle = None
        self._fear_intensity = 0.0
        self._frames_since_fear = 999
        self._commit_dir = None
        self._commit_frames = 0
        self._locked_target = None
        self._lock_ttl = 0
        self._lock_reward = 0.0
        self._evading = False
        self._evade_brake_done = False
        self._did_reverse = False
        self._did_brake = False
        self._prev_desired = None
        self._prev_turn_cmd = 0.0
        self._speed_smooth = 0.0
        self._desired_heading = None
        self._ai_mode = 'idle'
        self._vis_y_offset = 0.0
        self._vis_scale = 1.0
        self._trail = []
        self._roll_angle = 0.0
        self.assign_role()
        return self.starttype.value, self.x, self.y, self.angle

    def display(self, screen):
        display_particle(self, screen)

    def Identify(self, p):
        if p.type == self.type: return ParticleRelative.FRIEND
        if p.type == PREY_OF[self.type]: return ParticleRelative.PREY
        return ParticleRelative.FEAR

    def fearCount(self): return self.w.type_counts.get(FEAR_OF[self.type], 0)
    def preyCount(self): return self.w.type_counts.get(PREY_OF[self.type], 0)
    def selfcount(self): return self.w.type_counts.get(self.type, 0)

    def fear_scale(self):
        fc = self.fearCount()
        if fc <= 0:
            self._fear_intensity = max(0.0, self._fear_intensity - Config.FEAR_DECAY_FAST)
            self._frames_since_fear += 1
            return self._fear_intensity
        sc = max(1, self.selfcount())
        pop = fc / (fc + sc)
        pop_factor = (1.0 - Config.FEAR_POP_SCALE) + Config.FEAR_POP_SCALE * (0.35 + 0.65 * pop)
        return max(0.0, min(1.0, self._fear_intensity * pop_factor))

    def note_fear_sighting(self, strength=1.0):
        self._frames_since_fear = 0
        self._fear_intensity = min(1.0, self._fear_intensity + Config.FEAR_BUILD_RATE * strength)

    def decay_fear(self):
        self._frames_since_fear += 1
        rate = Config.FEAR_DECAY_FAST if self.fearCount() <= 0 else Config.FEAR_DECAY_RATE
        extra = min(0.06, self._frames_since_fear * 0.002)
        self._fear_intensity = max(0.0, self._fear_intensity - rate - extra)

    def relative_bearing(self, other):
        return SectorLogic.bearing(self.x, self.y, self.angle, other.x, other.y)

    def find_nearby_particles(self, dirs=None):
        far = getattr(Config, 'VISION_AI_FAR', Config.VISION_FAR) * self.size
        candidates = self.w.nearby(self.x, self.y, far) if hasattr(self.w, 'nearby') else self.w.particles
        if len(candidates) > 24:
            candidates = candidates[:24]
        by_sector, self._sector_nearest, self._sector_totals = SectorLogic.scan(self, candidates)
        if dirs is None:
            return by_sector
        return {d.value: by_sector.get(d.value, []) for d in dirs}

    def ping(self):
        if (self._last_angle is None or
            abs((self.angle - self._last_angle + math.pi)%(2*math.pi)-math.pi) > Config.VISION_DIRTY_THRESHOLD):
            self._vision_dirty = True
        if not self._vision_dirty:
            return
        self._last_angle = self.angle
        self._vision_dirty = False

    def _compute_pack_density(self):
        st = self.strat()
        sep = float(st.get('sep_distance', Config.SEPARATION_DIST)) * self.size
        r = 3.0 * sep
        friends = 0
        for o in (self.w.nearby(self.x, self.y, r) if hasattr(self.w, 'nearby') else self.w.particles):
            if o is self or o.type != self.type:
                continue
            if math.hypot(o.x - self.x, o.y - self.y) < r:
                friends += 1
        self._pack_density = friends
        prey_d = 0
        nd, prey = 1e18, None
        for o in (self.w.nearby(self.x, self.y, Config.VISION_FAR * self.size) if hasattr(self.w, 'nearby') else self.w.particles):
            if self.Identify(o) == ParticleRelative.PREY:
                d = math.hypot(o.x - self.x, o.y - self.y)
                if d < nd:
                    nd, prey = d, o
        if prey is not None:
            for o in (self.w.nearby(prey.x, prey.y, r) if hasattr(self.w, 'nearby') else self.w.particles):
                if o.type == self.type and math.hypot(o.x - prey.x, o.y - prey.y) < r:
                    prey_d += 1
        self._pack_density_at_prey = prey_d
        return friends

    def update_ambush(self):
        st = self.strat()
        if not playbook.tactic_enabled(st.get('_strategy_id', 'PACK_HUNT'), 'fort_ambush', self.type.name):
            self._ambush_mode = 'none'
            return
        amb_w = float(st.get('fort_ambush_bonus', 0.8))
        cover_w = float(st.get('fort_cover_weight', 1.0))
        if not getattr(self.w, 'fort_list', None) or amb_w < 0.05 or cover_w < 0.05:
            self._ambush_mode = 'none'
            self._ambush_hold_frames = 0
            self._ambush_spring_frames = 0
            self._ambush_fort = None
            return
        if self.fearCount() > 0:
            for o in (self.w.nearby(self.x, self.y, 22 * self.size) if hasattr(self.w, 'nearby') else self.w.particles):
                if o is self:
                    continue
                if self.Identify(o) == ParticleRelative.FEAR and not FortLOS.occludes(self.w, self, o):
                    self._ambush_mode = 'none'
                    self._ambush_hold_frames = 0
                    self._ambush_spring_frames = 0
                    return
        if self.preyCount() <= 0:
            self._ambush_mode = 'none'
            return
        nearest_prey = None
        nd = 1e18
        for o in (self.w.nearby(self.x, self.y, Config.VISION_FAR * self.size) if hasattr(self.w, 'nearby') else self.w.particles):
            if o is self or self.Identify(o) != ParticleRelative.PREY:
                continue
            d = math.hypot(o.x - self.x, o.y - self.y)
            if d < nd:
                nd, nearest_prey = d, o
        if nearest_prey is None:
            self._ambush_mode = 'none'
            return
        occluded_from_prey = FortLOS.occludes(self.w, nearest_prey, self)
        we_see_prey = not FortLOS.occludes(self.w, self, nearest_prey)
        spring_range = 8.0 * self.size
        if self._ambush_mode == 'spring':
            self._ambush_spring_frames += 1
            if self._ambush_spring_frames > 45 or nd > spring_range * 2.5:
                self._ambush_mode = 'none'
                self._ambush_spring_frames = 0
            return
        if occluded_from_prey and nd > spring_range * 0.55:
            self._ambush_mode = 'hold'
            self._ambush_hold_frames += 1
            self._ambush_prey_id = id(nearest_prey)
            fort, cs = FortLOS.best_cover_fort(self, nearest_prey)
            self._ambush_fort = fort
            if self._ambush_hold_frames > 90:
                self._ambush_mode = 'spring'
                self._ambush_spring_frames = 1
                self._ambush_hold_frames = 0
            return
        if (we_see_prey and not occluded_from_prey and self._ambush_hold_frames > 3) or (nd <= spring_range and self._ambush_hold_frames > 0):
            self._ambush_mode = 'spring'
            self._ambush_spring_frames = 1
            self._ambush_hold_frames = 0
            self._locked_target = nearest_prey
            self._lock_ttl = max(self._lock_ttl, int(st.get('target_lock_ttl', 40)))
            return
        if occluded_from_prey and cover_w > 0.2 and nd < 20 * self.size:
            fort, cs = FortLOS.best_cover_fort(self, nearest_prey)
            if fort is not None and cs > 0.1:
                self._ambush_mode = 'hold'
                self._ambush_hold_frames = 1
                self._ambush_fort = fort
                self._ambush_prey_id = id(nearest_prey)
                return
        if self._ambush_mode == 'hold' and not occluded_from_prey:
            self._ambush_mode = 'none'
            self._ambush_hold_frames = 0

    def command_tiered(self, runcount):
        urgent = (
            self._evading or self._fear_intensity > 0.45
            or (self._sector_nearest.get('FEAR') is not None
                and self._sector_nearest['FEAR'][0] < 10 * self.size)
        )
        if urgent:
            every = getattr(Config, 'AI_URGENT_EVERY', 2)
        elif self._locked_target is not None or self._sector_nearest.get('PREY') is not None:
            every = getattr(Config, 'AI_NORMAL_EVERY', 3)
        else:
            every = getattr(Config, 'AI_IDLE_EVERY', 5)
        if (runcount + (self.id & 15)) % max(1, every) == 0:
            self.command(fast=not urgent)

    def command(self, fast=False):
        self._compute_pack_density()
        self.update_ambush()
        if self.speed < self.maxspeed() * Config.MIN_SPEED_FOR_AI:
            return
        self.ping()
        dirs = FAST_VISION_DIRS if fast else ALL_VISION_DIRS
        nb = self.find_nearby_particles(dirs)
        saw_fear = False
        max_fear_df = 0.0
        for pts in nb.values():
            for dist, rel, _p in pts:
                if rel == ParticleRelative.FEAR:
                    saw_fear = True
                    if dist < Config.VISION_NEAR * self.size:
                        max_fear_df = 1.0
                    else:
                        df = 1.0 - (dist - Config.VISION_NEAR * self.size) / (
                            (Config.VISION_FAR - Config.VISION_NEAR) * self.size)
                        max_fear_df = max(max_fear_df, max(0.0, df))
        if saw_fear and self.fearCount() > 0:
            self.note_fear_sighting(strength=max(0.3, max_fear_df))
        else:
            self.decay_fear()
        score = [self.RankDir(d, nb.get(d.value, [])) for d in dirs]
        do_full_bias = not fast
        for s in score:
            self.apply_team_bias(s)
            if do_full_bias:
                self.apply_fort_bias(s)
                self.apply_wall_bias(s)
            elif s.direction == TurnRelative.FRONT.value:
                self.apply_wall_bias(s)
        team = self.get_team()
        evade_th = Config.EVADE_THRESHOLD_BASE + self.bravery
        if self.role == Role.DEFENDER:
            evade_th *= 0.75
        elif self.role == Role.HUNTER:
            evade_th *= 1.15
        if self.fearCount() > 0 and (team.mode == TeamMode.SCATTER or self.fearCount() >= self.selfcount()):
            evade_th *= 0.85
        lock = self._locked_target
        if lock is not None:
            self._lock_ttl -= 1
            still_valid = (
                lock in self.w.particles
                and self.Identify(lock) == ParticleRelative.PREY
                and self._lock_ttl > 0
            )
            if not still_valid:
                self._locked_target = None
                self._lock_ttl = 0
                self._lock_reward = 0.0
                lock = None
        if lock is not None:
            pred = self._predicted_pos(lock)
            des = math.atan2(pred[0] - self.x, -(pred[1] - self.y))
            diff = (des - self.angle + math.pi) % (2 * math.pi) - math.pi
            cone_map = {k.value: SECTOR_CENTRES[k] for k in TurnRelative}
            for s in score:
                cone_c = cone_map.get(s.direction, 0)
                ad = abs((diff - cone_c + math.pi) % (2 * math.pi) - math.pi)
                if ad < math.radians(50):
                    st = self.strat()
                    s.reward = s.reward * st["target_lock_bonus"] + 0.35 * (1.0 - ad / math.radians(50))
                    if s.reward > 0.1:
                        self._lock_ttl = max(self._lock_ttl, st["target_lock_ttl"] // 2)
        nearest_fear = nearest_prey = None
        nearest_fear_d = nearest_prey_d = float('inf')
        front_score = next((s for s in score if s.direction == TurnRelative.FRONT.value), None)
        for pts in nb.values():
            for dist, rel, pobj in pts:
                if rel == ParticleRelative.FEAR and dist < nearest_fear_d:
                    nearest_fear_d, nearest_fear = dist, pobj
                elif rel == ParticleRelative.PREY and dist < nearest_prey_d:
                    nearest_prey_d, nearest_prey = dist, pobj
        front_risk = front_score.risk if front_score is not None else 0.0
        fear_ahead = False
        if nearest_fear is not None:
            fb = SectorLogic.bearing(self.x, self.y, self.angle, nearest_fear.x, nearest_fear.y)
            fear_ahead = abs(fb) < math.radians(90)
        fear_close = False
        if self.fearCount() > 0 and nearest_fear is not None:
            fear_close = (
                fear_ahead or nearest_fear_d < 20 * self.size
                or front_risk > evade_th * 0.55
                or (nearest_prey is None or nearest_fear_d <= nearest_prey_d * 1.2)
            )
        high_risk = [s for s in score if s.risk > evade_th * 0.75] if self.fearCount() > 0 else []
        chase_cands = [s for s in score if s.reward > 0.10 and s.risk <= evade_th * 0.70]
        mode = 'idle'
        best = front_score if front_score is not None else score[0]
        if fear_close or (high_risk and (front_risk > evade_th * 0.5 or fear_ahead)):
            mode = 'evade'
            safe = [s for s in score if s.risk <= evade_th * 0.9] or sorted(score, key=lambda x: x.risk)[:4]
            best = max(safe, key=lambda x: -x.risk * 2.0 + x.confidence * 0.25)
            self._locked_target = None
            self._lock_ttl = 0
            self._lock_reward = 0.0
            self._commit_dir = None
            self._commit_frames = 0
        elif (not fear_ahead) and (chase_cands or lock is not None or (nearest_prey is not None and front_risk <= evade_th * 0.7)):
            mode = 'chase'
            if chase_cands:
                best = max(chase_cands, key=lambda x: x.reward + x.flank_bonus + x.pack_bonus + x.cohesion * 0.3 - x.risk * 0.6)
            elif any(s.CostBenefit() > 0 for s in score):
                best = max(score, key=lambda x: x.CostBenefit())
        elif any(s.CostBenefit() > 0 for s in score):
            mode = 'bias'
            best = max(score, key=lambda x: x.CostBenefit())
        else:
            mode = 'idle'
            for s in score:
                if s.direction == TurnRelative.FRONT.value:
                    s.confidence = min(1.5, s.confidence + 0.25)
                    break
            best = max(score, key=lambda x: x.confidence + x.cohesion * 0.5)
        order = best.direction if best is not None else 0
        st = self.strat()
        pc, fc = self.preyCount(), self.fearCount()
        reserve = int(st.get("prey_reserve", 2))
        self._cmd_mode = mode
        allow_lock = mode != 'evade' and (fc <= 0 or pc > max(3, reserve))
        # Last 3/2/1 prey while predators live: steer off the meal.
        # Caution rises as the count drops. Convert stays legal if they touch.
        if fc > 0 and pc <= 5:
            caution = (4.0 - max(1, min(3, pc))) / 3.0
            allow_lock = False
            self._locked_target = None
            self._lock_ttl = 0
            if nearest_prey is not None:
                dx = self.x - nearest_prey.x
                dy = self.y - nearest_prey.y
                if dx * dx + dy * dy > 1.0:
                    away = math.atan2(dx, -dy)
                    self._desired_heading = away
                    if pc <= 2 or caution >= 0.6:
                        self._desired_heading = away
                        mode = 'evade'
                    elif mode == 'chase':
                        mode = 'bias'
        if getattr(self, '_kick_ttl', 0) > 0:
            self._kick_ttl -= 1
            allow_lock = False
            self._locked_target = None
            mode = 'evade'
        if getattr(self, '_ambush_mode', 'none') == 'hold' and not (fc > 0 and pc <= 1):
            mode = 'chase' if nearest_prey is not None else mode
            allow_lock = True
            if self._ambush_fort is not None and nearest_prey is not None:
                ch, cs = FortLOS.cover_heading(self, nearest_prey, st)
                if ch is not None:
                    self._desired_heading = ch
            if nearest_prey is not None:
                self._locked_target = nearest_prey
                self._lock_ttl = max(self._lock_ttl, st.get('target_lock_ttl', 40))
        elif getattr(self, '_ambush_mode', 'none') == 'spring':
            mode = 'chase'
            allow_lock = True
            if nearest_prey is not None:
                self._locked_target = nearest_prey
                self._lock_ttl = max(self._lock_ttl, int(st.get('target_lock_ttl', 40) * 1.2))
        dens = getattr(self, '_pack_density_at_prey', 0) or 0
        thr = int(st.get('overcrowd_threshold', 4))
        if dens >= thr and mode == 'chase' and nearest_prey is not None and self.fearCount() > 0:
            my_d = nearest_prey_d if nearest_prey_d < 1e17 else math.hypot(self.x - nearest_prey.x, self.y - nearest_prey.y)
            closer = sum(1 for o in self.w.particles
                         if o.type == self.type and o is not self
                         and math.hypot(o.x - nearest_prey.x, o.y - nearest_prey.y) < my_d - self.size)
            if closer >= max(2, thr - 1):
                self._locked_target = None
                self._lock_ttl = 0
                mode = 'bias'
        if allow_lock and nearest_prey is not None and best.risk <= evade_th * 1.1:
            if self._locked_target is None:
                self._locked_target = nearest_prey
                self._lock_ttl = st["target_lock_ttl"]
                self._lock_reward = max(0.2, best.reward)
            elif nearest_prey is self._locked_target:
                self._lock_ttl = st["target_lock_ttl"]
                self._lock_reward = max(self._lock_reward, best.reward)
            elif best.reward >= self._lock_reward * st["target_switch_margin"]:
                self._locked_target = nearest_prey
                self._lock_ttl = st["target_lock_ttl"]
                self._lock_reward = best.reward
        elif not allow_lock and self._locked_target is not None:
            if mode == 'evade' or (
                    self.Identify(self._locked_target) == ParticleRelative.PREY and pc <= reserve):
                self._locked_target = None
                self._lock_ttl = 0
                self._lock_reward = 0.0
        self.apply_evasion(best, high_risk, evade_th, nb)
        nearest_map = getattr(self, '_sector_nearest', None) or {
            'FEAR': (nearest_fear_d, nearest_fear) if nearest_fear else None,
            'PREY': (nearest_prey_d, nearest_prey) if nearest_prey else None,
            'FRIEND': None,
        }
        if self._locked_target is not None and self._locked_target in self.w.particles:
            ld = math.hypot(self._locked_target.x - self.x, self._locked_target.y - self.y)
            nearest_map = dict(nearest_map)
            nearest_map['PREY'] = (ld, self._locked_target)
        clear_hunt = self.fearCount() <= 0 and self.preyCount() > 0
        clear_assigned = None
        if clear_hunt:
            mode = 'chase'
            prey_list = [p for p in self.w.particles if self.Identify(p) == ParticleRelative.PREY]
            if prey_list:
                hunters = [q for q in self.w.particles if q.type == self.type]
                assigned = None
                if playbook.tactic_enabled(st.get('_strategy_id', 'CLEAR_SPLIT'), 'voronoi_split', self.type.name) and len(hunters) >= int(st.get('clear_split_threshold', 2)):
                    vk = (getattr(self.w, 'runcount', 0), self.type)
                    if getattr(self.w, '_voronoi_key', None) != vk:
                        self.w._voronoi_map = VoronoiEndgame.assign(self.w, hunters, prey_list, st)
                        self.w._voronoi_key = vk
                    mapping = getattr(self.w, '_voronoi_map', {}) or {}
                    assigned = mapping.get(getattr(self, 'id', id(self)))
                    if assigned is None:
                        assigned = min(prey_list, key=lambda pr: (self.x-pr.x)**2 + (self.y-pr.y)**2)
                    stats = VoronoiEndgame.stats()
                    self._voronoi_imbalance = stats['voronoi_imbalance']
                    self._voronoi_reassign = stats['voronoi_reassign']
                if assigned is None:
                    prey_list = sorted(prey_list, key=lambda q: getattr(q, 'id', id(q)))
                    hunters_s = sorted(hunters, key=lambda q: getattr(q, 'id', id(q)))
                    try:
                        my_i = next(i for i, h in enumerate(hunters_s) if h is self)
                    except StopIteration:
                        my_i = abs(hash(getattr(self, 'id', id(self)))) % max(1, len(hunters_s))
                    assigned = prey_list[my_i % len(prey_list)]
                clear_assigned = assigned
                self._locked_target = assigned
                self._lock_ttl = max(80, int(st.get('target_lock_ttl', 40)))
                nearest_prey = assigned
                nearest_prey_d = math.hypot(assigned.x - self.x, assigned.y - self.y)
                nearest_map = dict(nearest_map)
                nearest_map['PREY'] = (nearest_prey_d, assigned)
        desired, orient_mode = SectorLogic.orient(
            self, nearest_map, st, fear_close=(mode == 'evade' and not clear_hunt)
        )
        if clear_hunt and clear_assigned is not None:
            mode = 'chase'
            look = st.get('predict_lookahead', 12.0)
            desired = SectorLogic.chase_heading(self, clear_assigned, look)
            orient_mode = 'chase'
        if orient_mode == 'evade' and mode != 'evade' and not clear_hunt:
            mode = 'evade'
            self._locked_target = None
            self._lock_ttl = 0
            self._lock_reward = 0.0
            self.apply_evasion(best, high_risk, evade_th, nb)
        if mode in ('chase', 'bias') and getattr(self, '_ambush_mode', 'none') != 'hold':
            if playbook.tactic_enabled(st.get('_strategy_id', 'PACK_HUNT'), 'pincer_flank', self.type.name):
                ph = team.pincer_heading(self)
                if ph is not None:
                    blend = min(0.85, 0.35 + 0.35 * float(st.get('pincer_weight', 1.0)))
                    desired = ph if desired is None else SwarmIntelligence.blend_headings(desired, ph, blend=blend)
                    mode = 'chase'
        if desired is None and best is not None and order != 0:
            desired = SectorLogic.world_heading(self.angle, order)
        swarm_h, swarm_comps = SwarmIntelligence.desired_heading(self)
        json_moves = []
        try:
            json_moves = playbook.movement_for(st.get('_strategy_id'), self.type.name) or []
        except Exception:
            json_moves = []
        skip_swarm_blend = bool(json_moves) and getattr(Config, 'FAST_SIM', False)
        if clear_hunt:
            self._swarm_comps = swarm_comps
            target = self._locked_target
            if target is None or target not in self.w.particles:
                cmap = getattr(team, 'clear_hunt_map', {}) or {}
                target = cmap.get(getattr(self, 'id', id(self)))
            if target is not None and target in self.w.particles:
                desired = SectorLogic.chase_heading(self, target, float(st.get('predict_lookahead', 12.0)))
                mode = 'chase'
                self._locked_target = target
        elif mode == 'evade':
            if not skip_swarm_blend:
                desired = SwarmIntelligence.blend_headings(desired, swarm_h, blend=0.72)
            self._swarm_comps = swarm_comps
        elif mode == 'chase':
            if not skip_swarm_blend:
                desired = SwarmIntelligence.blend_headings(desired, swarm_h, blend=0.45)
            self._swarm_comps = swarm_comps
        else:
            if not skip_swarm_blend:
                desired = SwarmIntelligence.blend_headings(desired, swarm_h, blend=Config.SWARM_BLEND)
            self._swarm_comps = swarm_comps
        try:
            self.w.record_swarm_comps(self.type, swarm_comps)
        except Exception:
            pass
        if clear_hunt and self._locked_target is not None and self._locked_target in self.w.particles:
            desired = SectorLogic.chase_heading(self, self._locked_target, float(st.get('predict_lookahead', 12.0)))
            mode = 'chase'
        if desired is None:
            self._ai_mode = mode
            return
        try:
            from maths.dispatch import apply as apply_math_movement
            desired = apply_math_movement(self, desired, mode=mode)
        except Exception:
            pass
        desired = self._steer_past_friends(desired)
        desired = self._steer_around_forts(desired)
        if clear_hunt:
            wall_h = self._steer_around_walls(desired)
            if wall_h is not None and desired is not None:
                desired = SwarmIntelligence.blend_headings(desired, wall_h, blend=0.28)
        else:
            desired = self._steer_around_walls(desired)
        desired = self.adaptive_heading_damp(desired, mode=mode)
        self._desired_heading = desired
        self._ai_mode = mode
        self.turn = 0
        self.turndir = 0
        if mode == 'chase':
            self._commit_dir = order
            self._commit_frames = max(2, Config.COMMIT_FRAMES // 3)
            self._commit_risk = best.risk if best else 0
        self._vision_dirty = True

    def enforce_speed(self, source='move'):
        phys_enforce_speed(self, source=source)

    def adaptive_speed_damp(self, target):
        return Steer.adaptive_speed_damp(self, target)

    def adaptive_heading_damp(self, desired, mode='idle'):
        return Steer.adaptive_heading_damp(self, desired, mode=mode)

    def adaptive_turn_damp(self, turn_amt):
        return Steer.adaptive_turn_damp(self, turn_amt)

    def orient_in_place(self):
        desired = getattr(self, '_desired_heading', None)
        if desired is None:
            return
        err = (desired - self.angle + math.pi) % (2 * math.pi) - math.pi
        if abs(err) < math.radians(2):
            return
        rate = getattr(Config, 'SWIM_TURN_RATE', 0.12)
        max_step = getattr(Config, 'SWIM_TURN_MAX', 0.18)
        step = max(-max_step, min(max_step, err * rate))
        if abs(step) < abs(err) and abs(err) > max_step:
            step = math.copysign(max_step, err)
        self.angle = (self.angle + step) % (2 * math.pi)
        self.speed = self.maxspeed()

    def move(self):
        if int(getattr(self, '_meal_cooldown', 0) or 0) > 0:
            self._meal_cooldown = int(self._meal_cooldown) - 1
        if getattr(self, '_ambush_mode', 'none') == 'hold':
            fort = getattr(self, '_ambush_fort', None)
            if fort is not None and self.speed > self.maxspeed() * 0.45:
                self.speed = self.maxspeed() * 0.42
        elif getattr(self, '_ambush_mode', 'none') == 'spring':
            if self.speed < self.maxspeed() * 0.92:
                self.speed = min(self.maxspeed(), self.speed + self.maxspeed() * 0.04)
        ms = self.maxspeed()
        desired = getattr(self, '_desired_heading', None)
        if desired is None:
            desired = self.angle
            self._desired_heading = desired
        err = (desired - self.angle + math.pi) % (2 * math.pi) - math.pi
        evade = self._evading or getattr(self, '_ai_mode', '') == 'evade'
        if abs(err) > math.radians(1.5):
            rate = getattr(Config, 'SWIM_TURN_RATE_EVADE' if evade else 'SWIM_TURN_RATE', 0.12)
            max_step = getattr(Config, 'SWIM_TURN_MAX_EVADE' if evade else 'SWIM_TURN_MAX', 0.18)
            step = max(-max_step, min(max_step, err * rate))
            if abs(step) < abs(err) and abs(err) > max_step:
                step = math.copysign(max_step, err)
            self.angle = (self.angle + step) % (2 * math.pi)
            self.turndir = TurnRelative.LEFT.value if step < 0 else TurnRelative.RIGHT.value
        else:
            self.turndir = 0
        if self._evading:
            ev = 0.80
            cache = getattr(self, '_strat_cache', None)
            if cache:
                ev = float(cache.get("evade_speed_mult", ev) or ev)
            target = ms * ev
        else:
            target = ms
        if abs(err) > math.radians(50):
            target *= 0.92
        if self.speed < target:
            self.speed += (target - self.speed) * 0.18
        else:
            self.speed += (target - self.speed) * 0.28
        if self.speed > ms:
            self.speed = ms
        phys_integrate(self)

    def apply_evasion(self, best, high_risk, evade_th, nb):
        st = self.strat()
        risk = best.risk if best is not None else 0.0
        enter = (self.fearCount() > 0 and (
            risk >= st.get("evade_threshold", 0.9)
            or (high_risk and risk >= evade_th * 0.9)
            or self._fear_intensity > 0.75
        ))
        if enter:
            if not self._evading:
                if not self._evade_brake_done:
                    self.speed *= max(0.2, 1.0 - st.get("evade_brake", 0.4))
                    self._evade_brake_done = True
                    self._did_brake = True
                self._locked_target = None
                self._lock_ttl = 0
                self._lock_reward = 0.0
                self._commit_dir = None
                self._commit_frames = 0
            self._evading = True
            nearest_d = float('inf')
            for pts in nb.values():
                for dist, rel, other in pts:
                    if rel == ParticleRelative.FEAR and dist < nearest_d:
                        nearest_d = dist
            if (risk >= st.get("evade_reverse_risk", 1.8)
                    and nearest_d < 8 * self.size
                    and not self._did_reverse):
                self.angle = (self.angle + math.pi) % (2 * math.pi)
                self.turn = 0
                self.turndir = 0
                self._did_reverse = True
                self._vision_dirty = True
            return True
        self._evading = False
        self._evade_brake_done = False
        return False

    def type_defaults(self):
        return TYPE_DEFAULTS.get(self.type.name, TYPE_DEFAULTS["ROCK"])

    def strat(self):
        rc = getattr(self.w, 'runcount', 0)
        cached = getattr(self, '_strat_cache', None)
        if cached is not None and getattr(self, '_strat_rc', None) == rc:
            return cached
        team = self.get_team()
        sid = getattr(team, 'strategy_id', None)
        out = effective_strategy(
            self.type.name, self.w.teamSize, self_count=self.selfcount(),
            fear_count=self.w.type_counts.get(FEAR_OF[self.type], 0),
            prey_count=self.w.type_counts.get(PREY_OF[self.type], 0),
            strategy_id=sid)
        sid = sid or playbook.strategy_for_state(out.get('_game_state', 'CONTESTED'))
        out = playbook.annotate(out, sid, self.type.name)
        out['_local_pack_density'] = float(getattr(self, '_pack_density', 0) or 0)
        out['_pack_density_at_prey'] = float(getattr(self, '_pack_density_at_prey', 0) or 0)
        self._strat_cache = out
        self._strat_rc = rc
        return out

    def maxspeed(self):
        rc = getattr(self.w, 'runcount', 0)
        if getattr(self, '_ms_rc', None) == rc:
            return self._ms_cache
        v = phys_maxspeed(self)
        self._ms_cache = v
        self._ms_rc = rc
        return v

    def tturn(self):
        d = self.type_defaults()
        turn = math.radians(d["turn_base"] + self.agility)
        if self.selfcount() <= d.get("late_count_threshold", 2):
            turn *= d.get("late_turn_mult", 1.18)
        if self._evading:
            turn *= self.strat().get("evade_turn_boost", 1.4)
        return turn

    def bounce(self):
        bounce_walls(self)

    def _pincer_offset_point(self, prey, role):
        return Steer._pincer_offset_point(self, prey, role)

    def _steer_past_friends(self, desired):
        return Steer._steer_past_friends(self, desired)

    def _steer_around_forts(self, desired):
        return Steer._steer_around_forts(self, desired)

    def wall_repulsion_scale(self, heading=None):
        return Steer.wall_repulsion_scale(self, heading)

    def _steer_around_walls(self, desired):
        return Steer._steer_around_walls(self, desired)

    def apply_wall_bias(self, ds):
        Steer.apply_wall_bias(self, ds)

    def collide_forts(self):
        fort_collide_particle(self)

    def _predicted_pos(self, p, la=None):
        return Steer._predicted_pos(self, p, la)

    def apply_fort_bias(self, ds):
        Steer.apply_fort_bias(self, ds)

    def apply_team_bias(self, ds):
        team = self.get_team()
        if team.count == 0:
            return
        cone_c = {0:0,1:-math.radians(30),2:math.radians(30),3:-math.radians(60),4:math.radians(60),
                  5:-math.radians(90),6:math.radians(90),7:-math.radians(120),8:math.radians(120)}.get(ds.direction,0)
        no_fear = self.fearCount() <= 0
        if team.count == 1 and team.suggested_target:
            pred = self._predicted_pos(team.suggested_target)
            des = math.atan2(pred[0]-self.x, -(pred[1]-self.y))
            diff = (des - self.angle + math.pi)%(2*math.pi) - math.pi
            if abs((diff-cone_c+math.pi)%(2*math.pi)-math.pi) < math.radians(50):
                ds.reward += Config.FOCUS_TARGET_BONUS * Config.LAST_SURVIVOR_FINISH
            return
        dist_c = team.dist_to_center(self.x, self.y)
        isolation = min(1.0, dist_c / (max(self.w.width,self.w.height)*0.7))
        if no_fear:
            mode_f = 0.0
        elif team.mode == TeamMode.SCATTER:
            mode_f = Config.SCATTER_COHESION * (0.4 if self.role == Role.HUNTER else 1.0)
        elif team.mode == TeamMode.DEFEND:
            mode_f = Config.DEFEND_COHESION_BOOST
        elif team.mode == TeamMode.REGROUP:
            mode_f = 1.35
        else:
            mode_f = 1.0
        coh = self.strat()["cohesion_weight"] * (1.0 - isolation) * mode_f
        dx, dy = team.center[0]-self.x, team.center[1]-self.y
        desired = math.atan2(dx, -dy)
        diff = (desired - self.angle + math.pi)%(2*math.pi) - math.pi
        ang_diff = abs((diff - cone_c + math.pi)%(2*math.pi) - math.pi)
        if not no_fear and team.mode != TeamMode.SCATTER and ang_diff < math.radians(40):
            ds.cohesion += coh * (1.0 - ang_diff/math.radians(40))
        if no_fear:
            ds.pack_bonus = 0.0
            ds.cohesion = 0.0
        focus = team.alert_target if (team.alert_target and team.alert_ttl > 0) else team.suggested_target
        if focus is not None and team.mode != TeamMode.DEFEND:
            pred = self._predicted_pos(focus)
            td = math.atan2(pred[0]-self.x, -(pred[1]-self.y))
            tdiff = (td - self.angle + math.pi)%(2*math.pi) - math.pi
            tcd = abs((tdiff - cone_c + math.pi)%(2*math.pi) - math.pi)
            if tcd < math.radians(50):
                bonus = self.strat()["focus_bonus"] * (1.0 - tcd/math.radians(50))
                if self.role == Role.HUNTER:
                    bonus *= Config.ROLE_HUNTER_PURSUIT
                ds.reward += bonus
        sep_r = float(self.strat().get("sep_distance", Config.SEPARATION_DIST)) * self.size
        for item in ds.ping:
            if item.relative == ParticleRelative.FRIEND and item.distance < sep_r:
                t = 1.0 - item.distance / sep_r
                soft = float(self.strat().get("sep_softness", 1.0))
                ds.risk += Config.SEPARATION_RISK * (t ** max(0.35, soft)) * 0.65

    def RankDir(self, dir, ping):
        ret = Direction(dir.value if hasattr(dir,'value') else dir)
        team = self.get_team()
        st = self.strat()
        closest = float('inf')
        friends = preys = 0
        if ping:
            for dist, rel, particle in ping:
                if dist < Config.VISION_NEAR*self.size: df = 1.0
                elif dist > Config.VISION_FAR*self.size: df = 0.0
                else: df = 1.0 - (dist - Config.VISION_NEAR*self.size)/((Config.VISION_FAR-Config.VISION_NEAR)*self.size)
                p = Pinged(rel, dist, df)
                if rel == ParticleRelative.FEAR:
                    if self.fearCount() > 0:
                        scale = max(0.55, self.fear_scale())
                        fear_mult = scale
                        if dist < 10 * self.size:
                            fear_mult *= st["fear_close_mult"]
                        if self.fearCount() >= self.selfcount():
                            fear_mult *= st.get("outnumbered_fear_mult", Config.FEAR_OUTNUMBERED_MULT)
                        if st.get("_is_small_unit"):
                            fear_mult *= st.get("small_escape_mult", 1.0)
                        fear_mult *= 1.0 + 0.35 * df
                        ret.risk += max(0.35, df * fear_mult)
                        p.risk += max(0.35, df * fear_mult)
                        if dist < closest:
                            closest = dist
                            ret.confidence = dist / self.w.width
                elif rel == ParticleRelative.PREY:
                    preys += 1
                    iso = team.get_isolation(particle) * Config.ISOLATED_PREY_BONUS
                    if self.preyCount() >= self.fearCount():
                        iso += 0.35
                    if self.role == Role.HUNTER:
                        iso *= 1.15
                    if team.count == 1:
                        iso *= st.get("solo_finish_mult", Config.LAST_SURVIVOR_FINISH)
                    is_small = st.get("_is_small_unit") or team.mode == TeamMode.SCATTER
                    if is_small:
                        iso *= st.get("small_raid_bonus", Config.RAID_ISOLATED_BONUS)
                    amt = df * (1.0 + iso)
                    if df > 0.50:
                        amt *= st["near_target_aggro"]
                        ret.risk *= 0.75
                    if df > 0.80:
                        amt += st["finish_bonus"]
                        ret.risk *= 0.85
                    fc, pc = self.fearCount(), self.preyCount()
                    reserve = int(st.get("prey_reserve", 2))
                    if fc > 0 and pc <= 5:
                        # 3 left → keep 2/3 reward, 2 left → 1/3, 1 left → 0
                        amt *= max(0.0, (pc - 1) / 3.0)
                    elif fc > 0 and pc <= reserve:
                        amt *= st.get("prey_reserve_penalty", 0.15)
                    elif fc <= 0:
                        amt *= max(2.2, st.get("clear_finish_mult", 1.80)) * 1.35
                        ret.risk *= 0.25
                    if team.alert_target is particle and team.alert_ttl > 0:
                        amt *= st["focus_fire_mult"]
                    ret.reward += amt
                    p.reward += amt
                    if dist < closest:
                        closest = dist
                        ret.confidence = max(ret._confidence, dist / self.w.width)
                elif rel == ParticleRelative.FRIEND:
                    friends += 1
                    if dist < closest:
                        closest = dist
                        ret.confidence = max(ret._confidence, dist / self.w.width)
                    if self.selfcount() < self.fearCount():
                        ret.risk += df * 0.5
                        p.risk += df * 0.5
                    if (team.mode == TeamMode.SCATTER or self.fearCount() <= 0
                            or self.selfcount() <= st["scatter_threshold"] or st.get("_is_small_unit")):
                        sep_r = float(st.get("sep_distance", Config.SEPARATION_DIST)) * self.size * 1.8
                        if dist < sep_r:
                            sep = Config.SCATTER_SEPARATION * st.get("small_sep_mult", 1.0)
                            if self.fearCount() <= 0:
                                sep *= 1.35
                            soft = float(st.get("sep_softness", 1.0))
                            t = max(0.0, 1.0 - dist / sep_r)
                            ret.risk += df * sep * (t ** max(0.35, soft))
                            p.risk += df * sep * (t ** max(0.35, soft))
                if df > 0:
                    ret.ping.append(p)
            if friends > 0 and preys > 0 and team.mode != TeamMode.SCATTER and self.fearCount() > 0:
                ret.pack_bonus = st["pack_hunt_mult"] * min(friends, 2) * 0.45
            if self.fearCount() <= 0:
                ret.pack_bonus = 0.0
        else:
            oc = 0.85
            if team.mode in (TeamMode.DEFEND, TeamMode.REGROUP):
                oc *= 0.5
            elif team.mode == TeamMode.SCATTER:
                oc *= 1.50
            ret.confidence = oc
        sp = ((self.speed/self.maxspeed())*100)-50
        pen = Config.SPEED_PENALTY_STEP * int(sp/10) if sp > 0 else 0
        d = ret.direction
        if d == 0:
            ret.drag = Config.DRAG["FRONT"]
        elif d in (1, 2):
            ret.drag = Config.DRAG["SIDE"]
        elif d in (3, 4):
            ret.drag = Config.DRAG["30"] - pen
        elif d in (5, 6):
            ret.drag = Config.DRAG["60"] - pen
        elif d in (7, 8):
            ret.drag = Config.DRAG["90"] - pen
        elif d in (9, 10):
            ret.drag = 0.45 - pen
        else:
            ret.drag = 0.35 - pen
        if d >= 9 and ret.reward > 0:
            ret.reward *= 0.55
        return ret
