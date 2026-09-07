"""
Reynolds / boids steering for Rock-Paper-Scissors particles.

Separation, cohesion, alignment, fear/prey, collision avoidance.
particle.py imports SwarmIntelligence — do not import particle at module level.
"""

import math

from config import TeamMode


def _cfg():
    from config import Config
    return Config


def _los():
    from arena.fort import FortLOS
    return FortLOS


def _rel():
    from maths.ping import ParticleRelative
    return ParticleRelative


def _fear():
    from config import FEAR_OF
    return FEAR_OF


def _sec():
    from maths.ping import SectorLogic
    return SectorLogic


class SwarmIntelligence:
    """
    Classic swarm / boids forces computed in world space, then converted
    to a desired heading. Weights depend on team mode and fear state.
    """

    @staticmethod
    def _mode_weights(particle):
        team = particle.get_team()
        no_fear = particle.fearCount() <= 0
        st = particle.strat()
        sep = _cfg().SWARM_SEP_WEIGHT
        coh = _cfg().SWARM_COH_WEIGHT * st.get("cohesion_weight", 0.55)
        ali = _cfg().SWARM_ALI_WEIGHT
        fear_w = _cfg().SWARM_FEAR_WEIGHT * st.get("escape_bonus", 0.6)
        prey_w = _cfg().SWARM_PREY_WEIGHT * st.get("near_target_aggro", 2.0) * 0.35
        if no_fear:
            # CLEAR_HUNT: dissolve packs completely — only sep + assigned-prey pull
            coh *= 0.0
            ali *= 0.0
            sep *= 3.5  # strong spread between hunters
            fear_w = 0.0
            prey_w *= 6.0 * max(1.0, st.get("clear_finish_mult", 1.8) * 0.5)
            try:
                particle._speed_match_target = None
            except Exception:
                pass
        elif team.mode == TeamMode.SCATTER:
            coh *= _cfg().SCATTER_COHESION
            sep *= 1.6 * st.get("small_sep_mult", 1.0)
            ali *= 0.3
            fear_w *= 1.3
        if st.get("_near_wipe"):
            # About to wipe: max disperse + evade, no pack
            coh = float(st.get("near_wipe_cohesion", 0.0))
            ali *= 0.05
            sep *= float(st.get("near_wipe_sep_mult", 2.2))
            fear_w *= float(st.get("near_wipe_evade_mult", 1.6))
            prey_w *= 0.25
        # Being cleaned: only predators of another type remain as our fear, we have no prey
        if (not no_fear) and particle.preyCount() <= 0 and particle.fearCount() > 0:
            coh *= 0.15
            ali *= 0.2
            sep *= 1.8
            fear_w *= 1.8
            prey_w *= 0.1
        elif team.mode == TeamMode.DEFEND:
            coh *= _cfg().DEFEND_COHESION_BOOST
            ali *= 1.4
            sep *= 0.75
            fear_w *= 1.2
        elif team.mode == TeamMode.REGROUP:
            coh *= 1.35
            ali *= 1.25
            sep *= 0.85
        elif team.mode == TeamMode.HUNT:
            coh *= 0.7
            prey_w *= 1.35
            ali *= 0.9
        if st.get("_is_small_unit"):
            sep *= st.get("small_sep_mult", 1.3)
            coh *= 0.5
            fear_w *= st.get("small_escape_mult", 1.3)
        # Job 1: extra fear flee. Job 2: invert prey pull on last 2–3 meals.
        try:
            fc = particle.fearCount()
            pc = particle.preyCount()
        except Exception:
            fc, pc = 0, 99
        if fc > 0:
            fear_w *= 1.25
            if pc <= 3:
                caution = float(st.get("_last_meal_caution") or ((4.0 - max(1, min(3, pc))) / 3.0))
                # Last meals: keep prey_w as a scale for the tangent herd
                # (applied in the PREY branch). Do not invert to a radial flee.
                prey_w *= (0.55 + 0.65 * caution)
                fear_w *= (1.0 + 0.55 * caution)
                sep *= (1.0 + 0.35 * caution)
                coh *= max(0.05, 1.0 - 0.7 * caution)
        # Density-scaled cohesion: local pack overcrowding near prey → peel
        dens = float(st.get('_local_pack_density', 0) or 0)
        if dens >= 3:
            peel = float(st.get('overcrowd_cohesion_scale', 0.35))
            sep_boost = float(st.get('overcrowd_sep_boost', 1.4))
            coh *= max(0.08, peel / max(1.0, dens / 3.0))
            sep *= sep_boost * min(2.0, 1.0 + 0.15 * (dens - 2))
            ali *= 0.6
        return sep, coh, ali, fear_w, prey_w

    @staticmethod
    def compute(particle, include_ali_coh=True, include_fear_prey=True):
        """
        Return (force_x, force_y, components_dict).
        Axes match movement: +x right, +y down-ish via -cos heading.

        include_ali_coh: if False, skip alignment/cohesion loops (use caller cache).
        include_fear_prey: if False, skip fear/prey accumulation.
        Separation always computed when this is called.
        """
        sep_w, coh_w, ali_w, fear_w, prey_w = SwarmIntelligence._mode_weights(particle)
        if not include_ali_coh:
            coh_w = ali_w = 0.0
        if not include_fear_prey:
            fear_w = prey_w = 0.0
        size = particle.size
        st = particle.strat()
        # Tunable boid separation distance (per-type, learned)
        sep_dist = float(st.get("sep_distance", _cfg().SEPARATION_DIST)) * size
        sep_soft = float(st.get("sep_softness", 1.0))
        if st.get("_is_small_unit"):
            sep_dist *= st.get("small_sep_mult", 1.0)
        r_friend = max(sep_dist * 1.15, _cfg().SWARM_RADIUS_FRIEND * size)
        r_fear = _cfg().SWARM_RADIUS_FEAR * size
        r_prey = _cfg().SWARM_RADIUS_PREY * size

        sep_x = sep_y = 0.0
        coh_x = coh_y = 0.0
        ali_x = ali_y = 0.0
        fear_x = fear_y = 0.0
        prey_x = prey_y = 0.0
        n_friend = n_fear = n_prey = 0
        ali_vx = ali_vy = 0.0

        px, py = particle.x, particle.y
        radius = max(r_friend, r_fear, r_prey)
        others = particle.w.nearby(px, py, radius) if hasattr(particle.w, 'nearby') else particle.w.particles
        max_n = getattr(_cfg(), 'MAX_SWARM_NEIGHBORS', 12)
        if len(others) > max_n * 3:
            # Keep nearest-ish sample without full sort cost
            others = others[::max(1, len(others) // max_n)][:max_n]
        elif len(others) > max_n:
            others = others[:max_n]
        for other in others:
            if other is particle:
                continue
            dx, dy = other.x - px, other.y - py
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                continue
            # Swarm senses also blocked by forts (cannot react to occluded threats/prey)
            if _los().occludes(particle.w, particle, other):
                continue
            rel = particle.Identify(other)
            if rel == _rel().FRIEND:
                if dist < r_friend:
                    n_friend += 1
                    # Separation only inside personal sep_distance (boid rule)
                    if dist < sep_dist:
                        t = max(0.0, (sep_dist - dist) / sep_dist)
                        strength = t ** max(0.35, sep_soft)
                        # Asymmetric sep: strong in front, weak behind (type-tuned)
                        bearing = _sec().bearing(
                            particle.x, particle.y, particle.angle, other.x, other.y)
                        ab = abs(bearing)
                        front_m = float(st.get('asymmetric_sep_front', 2.0))
                        rear_m = float(st.get('asymmetric_sep_rear', 0.55))
                        if ab < math.radians(70):
                            # forward hemisphere
                            tcone = 1.0 - ab / math.radians(70)
                            strength *= (1.0 + (front_m - 1.0) * tcone)
                            lx, ly = -dy / dist, dx / dist
                            side = 1.0 if (hash(getattr(particle, 'id', id(particle))) & 1) else -1.0
                            sep_x += lx * side * strength * 0.7 * tcone
                            sep_y += ly * side * strength * 0.7 * tcone
                        else:
                            strength *= rear_m
                        # Base: push away from friend (from other toward self direction for me)
                        push_x = -(dx / dist) * strength
                        push_y = -(dy / dist) * strength
                        # Friend experiences opposite push (we shove them along +dx,+dy)
                        friend_push_x = (dx / dist) * strength
                        friend_push_y = (dy / dist) * strength
                        # --- Don't knock teammate into predators ---
                        protect = float(st.get('ally_protect_weight', 1.0))
                        protect_r = float(st.get('ally_protect_radius', 12.0)) * size
                        if protect > 0.05 and particle.fearCount() > 0:
                            fear_type = _fear().get(particle.type)
                            for pred in others:
                                if pred is particle or pred is other:
                                    continue
                                if pred.type != fear_type:
                                    continue
                                pdx = pred.x - other.x
                                pdy = pred.y - other.y
                                pd = math.hypot(pdx, pdy)
                                if pd < 1e-6 or pd > protect_r:
                                    continue
                                # Unit vector friend → predator
                                fx, fy = pdx / pd, pdy / pd
                                # How much our push on friend aligns with toward-predator
                                align = friend_push_x * fx + friend_push_y * fy
                                if align > 0.0:
                                    # Strip the component that shoves friend toward predator
                                    damp = min(1.0, protect * align / (strength + 1e-6))
                                    friend_push_x -= fx * align * damp
                                    friend_push_y -= fy * align * damp
                                    # Prefer lateral slide for us instead
                                    lx2, ly2 = -fy, fx
                                    push_x += lx2 * align * damp * 0.5
                                    push_y += ly2 * align * damp * 0.5
                                    # Our own push reduced along the dangerous axis
                                    push_x = -(friend_push_x)
                                    push_y = -(friend_push_y)
                                    particle._ally_protect_hits = getattr(particle, '_ally_protect_hits', 0) + 1
                        sep_x += push_x
                        sep_y += push_y
                    # Cohesion / alignment use wider neighborhood
                    coh_x += other.x
                    coh_y += other.y
                    ali_vx += math.sin(other.angle) * other.speed
                    ali_vy += -math.cos(other.angle) * other.speed
                    # for speed matching
                    if not hasattr(particle, '_spd_sum'):
                        particle._spd_sum = 0.0
                        particle._spd_n = 0
                    particle._spd_sum += other.speed
                    particle._spd_n += 1
            elif rel == _rel().FEAR:
                if dist < r_fear and particle.fearCount() > 0:
                    n_fear += 1
                    # Base distance falloff
                    strength = (r_fear - dist) / r_fear
                    # --- Dynamic threat weighting ---
                    tw = float(st.get('threat_weight_base', 1.0))
                    # Closer predators weigh more (power curve)
                    dist_exp = float(st.get('threat_dist_exp', 1.4))
                    strength *= (strength ** max(0.2, dist_exp - 1.0)) * tw
                    # Number pressure: more predators / fewer self → higher threat
                    fc = max(1, particle.fearCount())
                    sc = max(1, particle.selfcount())
                    ratio = fc / sc
                    strength *= 1.0 + float(st.get('threat_count_scale', 0.55)) * min(2.5, ratio - 0.5)
                    # Closing speed: predator approaching us
                    try:
                        ovx = math.sin(other.angle) * other.speed
                        ovy = -math.cos(other.angle) * other.speed
                        # relative velocity of predator toward us
                        closing = -((other.x - px) * ovx + (other.y - py) * ovy) / (dist + 1e-6)
                        if closing > 0:
                            strength *= 1.0 + float(st.get('threat_closing_scale', 0.45)) * min(1.5, closing / (other.maxspeed() + 1e-6))
                    except Exception:
                        pass
                    # Frontal threat (in our forward arc) weighs more
                    try:
                        bearing = _sec().bearing(particle.x, particle.y, particle.angle, other.x, other.y)
                        if abs(bearing) < math.radians(90):
                            strength *= 1.0 + float(st.get('threat_front_scale', 0.35)) * (1.0 - abs(bearing) / math.radians(90))
                    except Exception:
                        pass
                    # Near-wipe / outnumbered already scaled via st; clamp
                    strength = max(0.05, min(3.5, strength))
                    particle._threat_weight_acc = getattr(particle, '_threat_weight_acc', 0.0) + strength
                    particle._threat_weight_n = getattr(particle, '_threat_weight_n', 0) + 1
                    # Flee: opposite to predator (and slightly from predicted pos)
                    pred = particle._predicted_pos(other, particle.strat().get("evade_predict", 12.0))
                    pdx, pdy = pred[0] - px, pred[1] - py
                    pd = math.hypot(pdx, pdy) + 1e-6
                    fear_x -= (pdx / pd) * strength
                    fear_y -= (pdy / pd) * strength
            elif rel == _rel().PREY:
                if dist < r_prey:
                    # CLEAR_HUNT: only pull toward *assigned* prey (prevents dogpile on nearest)
                    if particle.fearCount() <= 0:
                        assigned = getattr(particle, '_locked_target', None)
                        if assigned is not None and other is not assigned:
                            continue  # ignore non-assigned prey forces
                    n_prey += 1
                    strength = (r_prey - dist) / r_prey * 0.5 + 0.5 * (1.0 - dist / r_prey)
                    pred = particle._predicted_pos(other, particle.strat().get("predict_lookahead", 12.0))
                    pdx, pdy = pred[0] - px, pred[1] - py
                    pd = math.hypot(pdx, pdy) + 1e-6
                    rx, ry = pdx / pd, pdy / pd
                    fc_now = 0
                    pc_now = 99
                    try:
                        fc_now = particle.fearCount()
                        pc_now = particle.preyCount()
                    except Exception:
                        pass
                    if fc_now > 0 and pc_now <= 3:
                        # Tangential herd: orbit the meal, soft radial *away*.
                        # Contact still converts if they overlap.
                        caution = float(st.get("_last_meal_caution") or ((4.0 - max(1, min(3, pc_now))) / 3.0))
                        tx, ty = -ry, rx
                        # Stable side from id; flip if that tangent runs toward fear.
                        if (hash(getattr(particle, 'id', id(particle))) & 1) == 0:
                            tx, ty = -tx, -ty
                        fear_type = _fear().get(getattr(particle, 'type', None))
                        if fear_type is not None:
                            nearest_f = None
                            nearest_d = 1e9
                            for pred_p in others:
                                if pred_p is particle or getattr(pred_p, 'type', None) != fear_type:
                                    continue
                                fdx = pred_p.x - px
                                fdy = pred_p.y - py
                                fd = fdx * fdx + fdy * fdy
                                if fd < nearest_d:
                                    nearest_d = fd
                                    nearest_f = pred_p
                            if nearest_f is not None:
                                # If tangent points toward fear, flip.
                                if tx * (nearest_f.x - px) + ty * (nearest_f.y - py) > 0:
                                    tx, ty = -tx, -ty
                        orbit_w = float(st.get('prey_orbit_weight', 1.15)) * (0.45 + 0.55 * caution)
                        repel_w = float(st.get('prey_repel_weight', 0.85)) * caution
                        prey_x += (tx * orbit_w - rx * repel_w) * strength
                        prey_y += (ty * orbit_w - ry * repel_w) * strength
                        particle._herd_orbit = getattr(particle, '_herd_orbit', 0) + 1
                    else:
                        prey_x += rx * strength
                        prey_y += ry * strength

        fx = fy = 0.0
        if n_friend > 0:
            fx += sep_x * sep_w
            fy += sep_y * sep_w
            # Cohesion toward mean neighbor position
            cx = (coh_x / n_friend) - px
            cy = (coh_y / n_friend) - py
            cl = math.hypot(cx, cy) + 1e-6
            fx += (cx / cl) * coh_w
            fy += (cy / cl) * coh_w
            # Alignment
            avx, avy = ali_vx / n_friend, ali_vy / n_friend
            al = math.hypot(avx, avy) + 1e-6
            fx += (avx / al) * ali_w
            fy += (avy / al) * ali_w
            # Speed matching (reduce accordion) — disabled in CLEAR_HUNT
            smw = float(st.get('speed_match_weight', 0.35))
            if particle.fearCount() <= 0:
                smw = 0.0
                particle._speed_match_target = None
            if smw > 0.01 and getattr(particle, '_spd_n', 0) > 0:
                avg_spd = particle._spd_sum / particle._spd_n
                particle._speed_match_target = (
                    particle.speed * (1.0 - smw) + float(avg_spd) * smw
                )
            else:
                particle._speed_match_target = None
            particle._spd_sum = 0.0
            particle._spd_n = 0
        if n_fear > 0:
            fx += fear_x * fear_w
            fy += fear_y * fear_w
        if n_prey > 0:
            fx += prey_x * prey_w
            fy += prey_y * prey_w

        # Predictive collision avoidance (friends + forts); never steer off PREY when hunting
        ax, ay, n_avoid = SwarmIntelligence.collision_avoidance(particle, st)
        avoid_w = float(st.get("avoid_weight", _cfg().SWARM_AVOID_WEIGHT))
        fx += ax * avoid_w
        fy += ay * avoid_w

        sep_fx, sep_fy = sep_x * sep_w, sep_y * sep_w
        # Reconstruct coh/ali force contributions for magnitude logging
        coh_fx = coh_fy = 0.0
        ali_fx = ali_fy = 0.0
        if n_friend > 0 and include_ali_coh:
            cx = (coh_x / n_friend) - px
            cy = (coh_y / n_friend) - py
            cl = math.hypot(cx, cy) + 1e-6
            coh_fx, coh_fy = (cx / cl) * coh_w, (cy / cl) * coh_w
            avx, avy = ali_vx / n_friend, ali_vy / n_friend
            al = math.hypot(avx, avy) + 1e-6
            ali_fx, ali_fy = (avx / al) * ali_w, (avy / al) * ali_w
        fear_fx, fear_fy = fear_x * fear_w, fear_y * fear_w
        prey_fx, prey_fy = prey_x * prey_w, prey_y * prey_w
        avoid_fx, avoid_fy = ax * avoid_w, ay * avoid_w
        comps = {
            'sep': (sep_fx, sep_fy),
            'coh': (coh_fx, coh_fy),
            'ali': (ali_fx, ali_fy),
            'fear': (fear_fx, fear_fy),
            'prey': (prey_fx, prey_fy),
            'avoid': (avoid_fx, avoid_fy),
            'sep_mag': math.hypot(sep_fx, sep_fy),
            'coh_mag': math.hypot(coh_fx, coh_fy),
            'ali_mag': math.hypot(ali_fx, ali_fy),
            'fear_mag': math.hypot(fear_fx, fear_fy),
            'prey_mag': math.hypot(prey_fx, prey_fy),
            'avoid_mag': math.hypot(avoid_fx, avoid_fy),
            'n_friend': n_friend, 'n_fear': n_fear, 'n_prey': n_prey,
            'n_avoid': n_avoid,
            'mag': math.hypot(fx, fy),
            'include_ali_coh': include_ali_coh,
            'include_fear_prey': include_fear_prey,
        }
        return fx, fy, comps

    @staticmethod
    def collision_avoidance(particle, st=None):
        """
        Time-to-collision style avoidance.
        Projects self and others forward; if paths come within combined radii,
        steer sideways (perpendicular to relative velocity) and slightly away.
        Avoids FRIENDs always; avoids FEAR as extra (with flee); does NOT avoid PREY
        (contact is required for RPS conversion).
        Also steers clear of fort surfaces.
        """
        st = st or particle.strat()
        size = particle.size
        look = float(st.get("avoid_lookahead", _cfg().SWARM_AVOID_LOOKAHEAD))
        clear = float(st.get("sep_distance", _cfg().SEPARATION_DIST)) * size * 0.55
        clear = max(clear, _cfg().SWARM_AVOID_RADIUS * size * 0.5)

        vx = math.sin(particle.angle) * particle.speed
        vy = -math.cos(particle.angle) * particle.speed
        px, py = particle.x, particle.y

        ax = ay = 0.0
        n_hit = 0

        others = particle.w.nearby(px, py, particle.speed * look + size * 8) if hasattr(particle.w, 'nearby') else particle.w.particles
        for other in others:
            if other is particle:
                continue
            rel = particle.Identify(other)
            # Must collide with PREY to convert – do not avoid them
            if rel == _rel().PREY:
                continue
            # Optional: still lightly avoid FEAR via this system (main flee is fear force)
            ovx = math.sin(other.angle) * other.speed
            ovy = -math.cos(other.angle) * other.speed
            # Relative position / velocity
            dx, dy = other.x - px, other.y - py
            dvx, dvy = ovx - vx, ovy - vy
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                continue
            # Combined collision radius
            rad = size + other.size + clear * 0.25
            # Time of closest approach along relative motion
            dv2 = dvx * dvx + dvy * dvy
            if dv2 < 1e-8:
                # Nearly parallel stationary relative – use separation if overlapping path
                if dist < rad * 1.5 and rel == _rel().FRIEND:
                    ax -= (dx / dist)
                    ay -= (dy / dist)
                    n_hit += 1
                continue
            t_ca = -(dx * dvx + dy * dvy) / dv2  # time to closest approach
            if t_ca < 0 or t_ca > look:
                continue
            # Closest approach separation
            cx = dx + dvx * t_ca
            cy = dy + dvy * t_ca
            ca_dist = math.hypot(cx, cy)
            if ca_dist >= rad:
                continue
            # Collision predicted – urgency rises as t_ca shrinks and ca_dist shrinks
            urgency = (1.0 - t_ca / look) * (1.0 - ca_dist / rad)
            urgency = max(0.0, min(1.0, urgency))
            if rel == _rel().FEAR:
                urgency *= 1.25
            # Steer perpendicular to relative velocity (side-step) + away from other
            rel_speed = math.sqrt(dv2)
            # Perpendicular to relative velocity
            rx, ry = -dvy / rel_speed, dvx / rel_speed
            # Choose the side that increases separation from other
            if rx * dx + ry * dy > 0:
                rx, ry = -rx, -ry
            away_x, away_y = -dx / dist, -dy / dist
            ax += (rx * 0.7 + away_x * 0.3) * urgency
            ay += (ry * 0.7 + away_y * 0.3) * urgency
            n_hit += 1

        # Fort future collision
        for f in particle.w.fort_list:
            # Ray from particle along velocity vs circle
            speed = particle.speed + 1e-6
            hx, hy = vx / speed, vy / speed
            fx_, fy_ = f.x - px, f.y - py
            proj = fx_ * hx + fy_ * hy
            if proj < 0 or proj > particle.speed * look:
                continue
            closest_x = px + hx * proj
            closest_y = py + hy * proj
            d = math.hypot(closest_x - f.x, closest_y - f.y)
            need = f.radius + size + _cfg().FORT_MARGIN * 0.5
            if d >= need:
                continue
            urgency = (1.0 - proj / (particle.speed * look + 1e-6)) * (1.0 - d / need)
            urgency = max(0.0, min(1.0, urgency))
            # Side-step around fort
            away_x, away_y = (px - f.x), (py - f.y)
            al = math.hypot(away_x, away_y) + 1e-6
            away_x, away_y = away_x / al, away_y / al
            # Perpendicular to heading
            sx_, sy_ = -hy, hx
            if sx_ * away_x + sy_ * away_y < 0:
                sx_, sy_ = -sx_, -sy_
            ax += (sx_ * 0.65 + away_x * 0.35) * urgency * 1.2
            ay += (sy_ * 0.65 + away_y * 0.35) * urgency * 1.2
            n_hit += 1

        # Wall future collision – same idea as forts (dynamic repulsion scale)
        margin = _cfg().WALL_MARGIN + size
        look_dist = particle.speed * look + margin
        try:
            wscale = particle.wall_repulsion_scale()
        except Exception:
            wscale = 1.0
        # Project along velocity
        speed = particle.speed + 1e-6
        hx, hy = vx / speed, vy / speed
        for frac in (0.3, 0.6, 1.0):
            axp = px + hx * look_dist * frac
            ayp = py + hy * look_dist * frac
            urgency = 0.0
            nx = ny = 0.0
            if axp < margin:
                urgency = max(urgency, (margin - axp) / margin * (1.1 - frac))
                nx = 1.0
            elif axp > particle.w.width - margin:
                urgency = max(urgency, (axp - (particle.w.width - margin)) / margin * (1.1 - frac))
                nx = -1.0
            if ayp < margin:
                urgency = max(urgency, (margin - ayp) / margin * (1.1 - frac))
                ny = 1.0
            elif ayp > particle.w.height - margin:
                urgency = max(urgency, (ayp - (particle.w.height - margin)) / margin * (1.1 - frac))
                ny = -1.0
            if urgency > 0:
                # Prefer slide parallel to wall + push inward
                if abs(nx) > abs(ny):
                    # vertical wall – side-step along y
                    sy = 1.0 if hy >= 0 else -1.0
                    ax += (nx * 0.55 + 0.0) * urgency
                    ay += sy * 0.45 * urgency
                else:
                    sx = 1.0 if hx >= 0 else -1.0
                    ax += sx * 0.45 * urgency
                    ay += (ny * 0.55) * urgency
                n_hit += 1
                break

        return ax, ay, n_hit

    @staticmethod
    def desired_heading(particle):
        """World heading from swarm force, or None if force is negligible.

        Separation (+ fear/prey) refresh every SWARM_SEP_EVERY / FEAR_PREY_EVERY frames.
        Alignment+cohesion only every SWARM_ALI_COH_EVERY frames; cached otherwise.
        """
        rc = getattr(particle.w, 'runcount', 0)
        pid = getattr(particle, 'id', id(particle))
        sep_every = max(1, int(getattr(_cfg(), 'SWARM_SEP_EVERY', 1)))
        ali_every = max(1, int(getattr(_cfg(), 'SWARM_ALI_COH_EVERY', 3)))
        fp_every = max(1, int(getattr(_cfg(), 'SWARM_FEAR_PREY_EVERY', 1)))
        do_sep = ((rc + (pid & 3)) % sep_every == 0)
        do_ali = ((rc + (pid & 7)) % ali_every == 0)
        do_fp = ((rc + (pid & 5)) % fp_every == 0)
        if not do_sep and not do_ali and not do_fp:
            # pure reuse of last heading
            cached = getattr(particle, '_swarm_heading_cache', None)
            comps = getattr(particle, '_swarm_comps', {}) or {}
            return cached, comps
        # Always include sep when we tick sep; ali/coh only on ali tick
        include_ali = do_ali
        include_fp = do_fp or do_sep  # keep fear with sep for safety
        fx, fy, comps = SwarmIntelligence.compute(
            particle, include_ali_coh=include_ali, include_fear_prey=include_fp)
        # Blend cached ali/coh contribution when skipped
        if not include_ali:
            cache = getattr(particle, '_swarm_ali_coh_force', None)
            if cache is not None:
                fx += cache[0]
                fy += cache[1]
                comps = dict(comps)
                comps['coh_mag'] = getattr(particle, '_swarm_coh_mag_cache', 0.0)
                comps['ali_mag'] = getattr(particle, '_swarm_ali_mag_cache', 0.0)
                comps['mag'] = math.hypot(fx, fy)
        else:
            # store ali+coh force for off frames
            particle._swarm_ali_coh_force = (
                comps.get('coh', (0, 0))[0] + comps.get('ali', (0, 0))[0],
                comps.get('coh', (0, 0))[1] + comps.get('ali', (0, 0))[1],
            )
            particle._swarm_coh_mag_cache = comps.get('coh_mag', 0.0)
            particle._swarm_ali_mag_cache = comps.get('ali_mag', 0.0)
        if comps['mag'] < 0.08:
            particle._swarm_heading_cache = None
            return None, comps
        heading = math.atan2(fx, -fy) % (2 * math.pi)
        particle._swarm_heading_cache = heading
        return heading, comps

    @staticmethod
    def blend_headings(primary, swarm, blend=None):
        """Slerp-like blend of two headings. blend=1 → full swarm."""
        if swarm is None:
            return primary
        if primary is None:
            return swarm
        b = _cfg().SWARM_BLEND if blend is None else blend
        # Convert to unit vectors, average, back to angle
        px, py = math.sin(primary), -math.cos(primary)
        sx, sy = math.sin(swarm), -math.cos(swarm)
        x = px * (1 - b) + sx * b
        y = py * (1 - b) + sy * b
        if abs(x) + abs(y) < 1e-9:
            return primary
        return math.atan2(x, -y) % (2 * math.pi)



# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
