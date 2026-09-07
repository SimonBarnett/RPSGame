# GROK_BRIEF — live doctrine

Use this file plus `strategies/SCHEMA.md` to invent a new strategy JSON.
Do not edit Python. Drop `strategies/templates/NEW_ID.json` and restart.

## Math binaries you may name in `movement[].fn` and `math`

- `boids` (maths/boids.py) — separation, cohesion, alignment, fear/prey forces
  - `boids.compute`
  - `boids.desired_heading`
  - `boids.blend_headings`
- `voronoi` (maths/voronoi.py) — split hunters across remaining prey (endgame)
  - `voronoi.assign`
  - `voronoi.stats`
- `steer` (maths/ping.py) — wall/fort slide, heading damp, pincer offset, intercept
  - `steer.pincer_heading`
  - `steer.apply_wall_bias`
  - `steer.apply_fort_bias`
  - `steer.adaptive_heading_damp`
  - `steer._predicted_pos`
  - `steer._steer_around_forts`
  - `steer._steer_around_walls`
- `sectors` (maths/ping.py) — 360° fear/prey contacts → heading
  - `sectors.scan`
  - `sectors.orient`
  - `sectors.chase_heading`
  - `sectors.bearing`
- `cover` (arena/fort.py) — hide behind forts, ambush hold/spring
  - `cover.cover_heading`
  - `cover.best_cover_fort`
  - `cover.occludes`
  - `cover.clear`
- `hash` (maths/phys.py) — cheap local neighbourhood
  - `hash.query`
- `phys` (maths/phys.py) — immutable motion / collisions
  - `phys.integrate`
  - `phys.bounce_walls`
  - `phys.collide_pair`
  - `phys.maxspeed`
- `flow` (maths/flow.py) — potential field: attract prey, repel fear, ridge off walls/forts
  - `flow.heading`
  - `flow.force`
- `roles` (maths/roles.py) — SCREEN / BAIT / STRIKE / ESCORT from local fear vs prey
  - `roles.assign`
  - `roles.heading`
  - `roles.assign_team`
- `form` (maths/form.py) — wedge / line / ring slots about the pack centroid
  - `form.slot_heading`
  - `form.slot_point`
- `time` (maths/time.py) — ETA and convert-before-fear gate
  - `time.eta`
  - `time.closing_speed`
  - `time.can_convert_before_fear`
  - `time.heading`
- `orbit` (maths/orbit.py) — tangent stand-off around prey or a fort
  - `orbit.heading`
- `pressure` (maths/pressure.py) — local friend/fear/prey density; give ground, slide off blobs, hunt sparse prey
  - `pressure.heading`
  - `pressure.force`
  - `pressure.density_at`
  - `pressure.gradient`
- `lanes` (maths/lanes.py) — split hunters into parallel corridors so CLEAR_HUNT does not stack one gap
  - `lanes.heading`
  - `lanes.lane_index`
- `intercept` (maths/intercept.py) — lead pursuit and chord-cut of a circling target (anti-orbit)
  - `intercept.heading`
  - `intercept.lead_point`
  - `intercept.chord_point`
- `desync` (maths/desync.py) — stable per-unit heading fan so mirrored cards do not share one path
  - `desync.heading`
  - `desync.offset`

## Tactics you may list

- `flock_sep` → boids.compute  knob=`sep_distance`  [individual] don't pile on allies
- `flock_coh` → boids.compute  knob=`cohesion_weight`  [team] stay with the pack
- `flock_ali` → boids.compute  knob=`speed_match_weight`  [team] match pack heading
- `fear_flee` → boids.compute  knob=`escape_bonus`  [individual] steer off predators
- `prey_pull` → boids.compute  knob=`near_target_aggro`  [individual] steer onto prey
- `prey_repel` → boids.compute  knob=`prey_repel_weight`  [team] soft radial away from last 2-3 prey while predators live
- `orbit_herd` → boids.compute  knob=`prey_orbit_weight`  [team] tangential herd around last meals; contact still converts
- `voronoi_split` → voronoi.assign  knob=`voronoi_weight`  [team] one hunter per prey cell
- `pincer_flank` → steer.pincer_heading  knob=`pincer_weight`  [team] left/right offset pursue
- `wall_slide` → steer._steer_around_walls  knob=`avoid_weight`  [individual] don't eat the wall
- `fort_slide` → steer._steer_around_forts  knob=`avoid_weight`  [individual] don't eat a fort
- `fort_cover` → cover.cover_heading  knob=`fort_cover_weight`  [individual] put fort between self and fear
- `fort_ambush` → cover.best_cover_fort  knob=`fort_ambush_bonus`  [individual] hold then spring
- `hide_in_prey` → sectors.orient  knob=`hide_among_prey_weight`  [individual] blend into prey flock
- `focus_fire` → sectors.chase_heading  knob=`focus_fire_mult`  [team] shared alert target
- `raid_isolated` → sectors.orient  knob=`small_raid_bonus`  [individual] pick off stragglers
- `no_corner_herd` → steer._steer_around_walls  knob=`no_corner_herd`  [team] don't pin last prey in a corner
- `near_wipe_sep` → boids.compute  knob=`near_wipe_sep_mult`  [individual] explode when almost dead
- `intercept` → steer._predicted_pos  knob=`predict_lookahead`  [individual] aim ahead of moving prey
- `role_screen` → roles.heading  knob=`escape_bonus`  [team] SCREEN units face fear
- `form_wedge` → form.slot_heading  knob=`cohesion_weight`  [team] hold a wedge
- `orbit_ring` → orbit.heading  knob=`offset_pursue_dist`  [individual] tangent stand-off
- `eta_gate` → time.heading  knob=`predict_lookahead`  [individual] hunt only if convert-before-fear
- `flow_field` → flow.heading  knob=`near_target_aggro`  [individual] potential-field heading
- `give_ground` → pressure.heading  knob=`pressure_own`  [team] slide off own pack density
- `fear_blob` → pressure.heading  knob=`pressure_fear`  [individual] slide off predator blobs
- `sparse_prey` → pressure.heading  knob=`pressure_prey`  [individual] prefer low-density prey
- `close_melee` → hash.query  knob=`sep_distance`  [individual] act on hash-local neighbours only
- `bounce_reset` → phys.bounce_walls  knob=`avoid_weight`  [individual] use wall bounce as an evade heading reset
- `lane_sweep` → lanes.heading  knob=`lane_count`  [team] each hunter owns a parallel corridor
- `clock_eta` → time.heading  knob=`predict_lookahead`  [individual] steer by time-to-contact, not raw bearing
- `mark_role` → roles.heading  knob=`focus_fire_mult`  [team] 1-1 mark so two units do not chase the same prey
- `lead_intercept` → intercept.heading  knob=`predict_lookahead`  [individual] chase where prey will be, not where it is
- `chord_cut` → intercept.chord_point  knob=`predict_lookahead`  [individual] cut the chord of an orbiting prey
- `desync_fan` → desync.heading  knob=`desync_span`  [team] fan headings so mirrored cards do not clone one path

## Templates

### BAIT_TURN
- mode `HUNT` when ['CONTESTED', 'LAST_PREY_RISK'] priority 52
- tactics: role_screen, raid_isolated, fort_slide, pincer_flank, focus_fire, intercept
- movement: [{"fn": "roles.assign"}, {"fn": "roles.heading", "blend": 0.5}, {"fn": "steer._steer_around_forts", "blend": 0.35}, {"fn": "steer.pincer_heading", "blend": 0.3, "when": "chase"}]
- Assign one BAIT to peel around a fort; STRIKE hits the opened flank.

### BOUNCE_JUKE
- mode `SCATTER` when ['OUTNUMBERED', 'SMALL_UNIT', 'NEAR_WIPE'] priority 70
- tactics: wall_slide, fort_slide, orbit_ring, fear_flee, bounce_reset
- movement: [{"fn": "steer._steer_around_walls", "blend": 0.5}, {"fn": "steer._steer_around_forts", "blend": 0.35}, {"fn": "orbit.heading", "blend": 0.4}, {"fn": "flow.heading", "blend": 0.2}]
- Use wall/fort bounce (phys) as a heading reset the hunter cannot track. Cut tangent after impact.

### CHOKE_PINCH
- mode `HUNT` when ['CONTESTED'] priority 55
- tactics: pincer_flank, fort_ambush, focus_fire, prey_pull, no_corner_herd, intercept
- movement: [{"fn": "sectors.orient", "weight": 1.0}, {"fn": "steer.pincer_heading", "blend": 0.5, "when": "chase"}, {"fn": "cover.best_cover_fort", "blend": 0.2}]
- Contested with forts: pin prey against a fort/wall pair, pincer from both gaps.

### CHORD_CUT
- mode `HUNT` when ['CONTESTED', 'CLEAR_HUNT', 'SMALL_UNIT'] priority 72
- tactics: chord_cut, lead_intercept, flock_sep, prey_pull, wall_slide
- movement: [{"fn": "intercept.chord", "blend": 0.7}, {"fn": "intercept.lead", "blend": 0.35}, {"fn": "boids.desired_heading", "blend": 0.15}]
- Cut the chord of a circling prey. Counter to ORBIT_KITE mirrors that otherwise never close.

### CLEAR_FAN
- mode `HUNT` when ['CLEAR_HUNT'] priority 96
- tactics: voronoi_split, form_wedge, clock_eta, flock_sep, prey_pull, give_ground
- movement: [{"fn": "voronoi.assign", "when": "CLEAR_HUNT"}, {"fn": "form.slot_heading", "blend": 0.4, "shape": "wedge"}, {"fn": "time.heading", "blend": 0.45}, {"fn": "boids.desired_heading", "blend": 0.15}]
- No predators: fan into a wedge + time-to-intercept so leftover prey are taken in parallel, not one-by-one.

### CLEAR_SPLIT
- mode `HUNT` when ['CLEAR_HUNT'] priority 100
- tactics: voronoi_split, flock_sep, prey_pull, wall_slide, intercept, give_ground, sparse_prey
- movement: [{"fn": "voronoi.assign", "when": "CLEAR_HUNT"}, {"fn": "sectors.chase_heading", "weight": 1.0}, {"fn": "boids.desired_heading", "blend": 0.15}, {"fn": "pressure.heading", "blend": 0.35}]
- No predators left: Voronoi split + give ground so packs do not stack on one prey.

### CLOSE_QUARTERS
- mode `HUNT` when ['CONTESTED', 'CLEAR_HUNT', 'SMALL_UNIT'] priority 53
- tactics: flock_sep, intercept, prey_pull, give_ground, raid_isolated, close_melee
- movement: [{"fn": "boids.desired_heading", "blend": 0.35}, {"fn": "pressure.heading", "blend": 0.3}, {"fn": "sectors.chase_heading", "weight": 1.0}]
- Spatial-hash melee: local pack is tight. Separate, intercept, take the nearest prey only.

### CONTESTED_SPLIT
- mode `HUNT` when ['CONTESTED'] priority 54
- tactics: voronoi_split, give_ground, fear_flee, eta_gate, flock_sep
- movement: [{"fn": "voronoi.assign"}, {"fn": "pressure.heading", "blend": 0.35}, {"fn": "time.heading", "blend": 0.4}, {"fn": "boids.desired_heading", "blend": 0.2}]
- Fear still lives: Voronoi the current prey so the pack does not all crash the same contact while predators roam.

### CROSS_LANE
- mode `HUNT` when ['CONTESTED', 'CLEAR_HUNT'] priority 76
- tactics: desync_fan, lead_intercept, chord_cut, flock_sep, prey_pull
- movement: [{"fn": "desync.heading", "blend": 0.45}, {"fn": "intercept.chord", "blend": 0.5}, {"fn": "lanes.heading", "blend": 0.25}]
- Cut perpendicular to a lane-sweep. Counter when the other team owns LANE_SWEEP.

### DELAY_FEAST
- mode `DEFEND` when ['LAST_PREY_RISK'] priority 96
- tactics: prey_repel, orbit_herd, orbit_ring, fear_flee, fort_cover, no_corner_herd
- movement: [{"fn": "orbit.heading", "blend": 0.65}, {"fn": "cover.cover_heading", "blend": 0.4}, {"fn": "boids.desired_heading", "blend": 0.3}, {"fn": "steer._steer_around_walls", "blend": 0.25}]
- Last prey still lives and predators live: do not convert. Orbit and peel until fear is gone.

### DENSITY_RAID
- mode `SCATTER` when ['SMALL_UNIT', 'CONTESTED'] priority 57
- tactics: sparse_prey, raid_isolated, give_ground, intercept
- movement: [{"fn": "pressure.heading", "blend": 0.5}, {"fn": "sectors.orient", "blend": 0.35, "when": "chase"}]
- Small unit: hunt the sparsest prey, ignore the blob.

### ESCORT_RING
- mode `DEFEND` when ['NEAR_WIPE', 'SMALL_UNIT', 'OUTNUMBERED'] priority 78
- tactics: near_wipe_sep, fear_flee, fort_cover, flock_coh
- movement: [{"fn": "roles.assign"}, {"fn": "form.slot_heading", "shape": "ring", "blend": 0.45}, {"fn": "orbit.heading", "blend": 0.35}, {"fn": "roles.heading", "blend": 0.25}]
- Last few allies: ring formation, orbit the pack, body-block fear.

### ETA_SPLIT
- mode `HUNT` when ['CLEAR_HUNT'] priority 97
- tactics: voronoi_split, intercept, prey_pull, flock_sep, sparse_prey
- movement: [{"fn": "time.heading", "blend": 0.55}, {"fn": "intercept.lead", "blend": 0.45}, {"fn": "sectors.chase_heading", "weight": 1.3}]
- CLEAR_HUNT: assign hunters by time-to-intercept, not nearest, so wall prey get a closer hunter.

### ETA_STRIKE
- mode `HUNT` when ['CONTESTED'] priority 62
- tactics: prey_pull, fear_flee, no_corner_herd, intercept
- movement: [{"fn": "roles.assign"}, {"fn": "time.heading", "blend": 0.6}, {"fn": "flow.heading", "blend": 0.35, "when": "chase"}]
- Hunt only when convert-before-fear is true; otherwise peel. Two-wave feast.

### FEAR_RIDGE
- mode `SCATTER` when ['NO_PREY_FEAR_ALIVE'] priority 88
- tactics: fear_blob, give_ground, orbit_ring, fort_cover, wall_slide
- movement: [{"fn": "pressure.heading", "blend": 0.6}, {"fn": "orbit.heading", "blend": 0.3}, {"fn": "cover.cover_heading", "blend": 0.25}]
- No prey, fear alive: ride the low-density ridge between predator blobs and walls.

### FINISH_CLOCK
- mode `HUNT` when ['CLEAR_HUNT'] priority 97
- tactics: clock_eta, voronoi_split, prey_pull, flock_sep, intercept
- movement: [{"fn": "voronoi.assign", "when": "CLEAR_HUNT"}, {"fn": "time.heading", "blend": 0.7}, {"fn": "boids.desired_heading", "blend": 0.15}]
- Predators in a clean endgame: minimise time-to-contact on assigned prey. Opposite of LAST_MAN_CLOCK.

### FORT_KITE
- mode `DEFEND` when ['OUTNUMBERED', 'CONTESTED'] priority 75
- tactics: fort_cover, fort_slide, wall_slide, fear_flee, raid_isolated, intercept
- movement: [{"fn": "cover.cover_heading", "weight": 1.0}, {"fn": "steer._steer_around_forts", "blend": 0.45}, {"fn": "sectors.orient", "blend": 0.25, "when": "chase"}]
- Outnumbered but prey still lives: drag predators around forts, take shots only when cover is clean.

### GATE_CAMP
- mode `HUNT` when ['CONTESTED'] priority 56
- tactics: fort_ambush, pincer_flank, flow_field, no_corner_herd, focus_fire
- movement: [{"fn": "form.slot_heading", "blend": 0.35, "shape": "line"}, {"fn": "flow.heading", "blend": 0.4, "when": "chase"}, {"fn": "steer.pincer_heading", "blend": 0.35, "when": "chase"}, {"fn": "cover.best_cover_fort", "blend": 0.25}]
- Park in the alley between two forts. Flow funnels prey into the gap; pincer the exit.

### GIVE_GROUND
- mode `HUNT` when ['CONTESTED'] priority 58
- tactics: give_ground, sparse_prey, flock_sep, prey_pull
- movement: [{"fn": "pressure.heading", "blend": 0.55}, {"fn": "flow.heading", "blend": 0.3, "when": "chase"}]
- Contested overcrowding: slide off own density into prey gaps.

### HOLD_COVER
- mode `DEFEND` when ['OUTNUMBERED'] priority 80
- tactics: fort_cover, fort_ambush, flock_coh, fear_flee
- movement: [{"fn": "cover.cover_heading", "weight": 1.0}, {"fn": "boids.desired_heading", "blend": 0.4}]
- Outnumbered: hide, hold, spring

### LANE_SWEEP
- mode `HUNT` when ['CLEAR_HUNT', 'CONTESTED'] priority 88
- tactics: lane_sweep, flock_sep, prey_pull, wall_slide, fort_slide
- movement: [{"fn": "lanes.heading", "blend": 0.7}, {"fn": "boids.desired_heading", "blend": 0.2}]
- Split hunters across parallel corridors (new lanes math) so packs stop jamming one fort gap in CLEAR_HUNT.

### LAST_MAN_CLOCK
- mode `SCATTER` when ['LAST_MAN'] priority 108
- tactics: clock_eta, fear_flee, fort_cover, orbit_ring, wall_slide, near_wipe_sep
- movement: [{"fn": "time.heading", "blend": 0.55}, {"fn": "cover.cover_heading", "blend": 0.35}, {"fn": "orbit.heading", "blend": 0.3}]
- Last unit alive: steer by time-to-contact. Maximise hunter ETA; take cover only if it lengthens the clock.

### LAST_MAN_RUN
- mode `SCATTER` when ['LAST_MAN'] priority 110
- tactics: fear_flee, fort_cover, orbit_ring, wall_slide, fear_blob, near_wipe_sep
- movement: [{"fn": "cover.cover_heading", "blend": 0.55}, {"fn": "orbit.heading", "blend": 0.4}, {"fn": "steer._steer_around_walls", "blend": 0.35}, {"fn": "pressure.heading", "blend": 0.3}]
- Exactly one left and predators live: maximise time-to-death. Cover, kite, bounce, never cluster.

### LAST_MEAL_ORBIT
- mode `DEFEND` when ['LAST_PREY_RISK'] priority 94
- tactics: prey_repel, orbit_herd, orbit_ring, fear_flee, fort_cover, no_corner_herd, flock_sep
- movement: [{"fn": "orbit.heading", "blend": 0.7}, {"fn": "cover.cover_heading", "blend": 0.4}, {"fn": "boids.desired_heading", "blend": 0.25}, {"fn": "steer._steer_around_walls", "blend": 0.2}]
- Last 3/2/1 of our prey while our predator lives: tangent orbit, peel off contact. Convert is legal on touch — don't touch.

### LAST_MEAL_STALL
- mode `SCATTER` when ['NEAR_WIPE', 'OUTNUMBERED', 'NO_PREY_FEAR_ALIVE', 'LAST_PREY_RISK'] priority 88
- tactics: orbit_ring, wall_slide, fort_cover, fear_flee, near_wipe_sep
- movement: [{"fn": "orbit.heading", "blend": 0.55}, {"fn": "cover.cover_heading", "blend": 0.35}, {"fn": "flow.heading", "blend": 0.25}, {"fn": "steer._steer_around_walls", "blend": 0.3}]
- You are the food: maximize time-to-death. Orbit walls/forts, bounce-juke, never line up on the hunter.

### LAST_PREY_CARE
- mode `DEFEND` when ['LAST_PREY_RISK'] priority 92
- tactics: prey_repel, orbit_herd, fear_flee, fort_cover, no_corner_herd, flock_sep, give_ground
- movement: [{"fn": "boids.desired_heading", "blend": 0.85}, {"fn": "cover.cover_heading", "blend": 0.45}, {"fn": "steer.apply_wall_bias", "blend": 0.25}]
- 3/2/1 prey left and our predator lives: flee fear and peel off the meals. Convert is legal; touching them is a losing move.

### LAST_STAND
- mode `SCATTER` when ['NEAR_WIPE'] priority 95
- tactics: near_wipe_sep, fear_flee, fort_cover, hide_in_prey
- movement: [{"fn": "cover.cover_heading", "blend": 0.5}, {"fn": "boids.desired_heading", "blend": 0.7}]
- About to wipe: survive, don't cluster

### MARK_ONE
- mode `HUNT` when ['CONTESTED', 'SMALL_UNIT'] priority 58
- tactics: mark_role, prey_pull, flock_sep, pincer_flank, give_ground
- movement: [{"fn": "roles.assign"}, {"fn": "roles.heading", "blend": 0.65}, {"fn": "steer.pincer_heading", "blend": 0.25, "when": "chase"}]
- Contested: role-assign 1-1 marks so two allies do not collapse on the same prey while another walks free.

### MIRROR_BREAK
- mode `HUNT` when ['CONTESTED', 'CLEAR_HUNT'] priority 74
- tactics: desync_fan, flock_sep, prey_pull, pincer_flank, wall_slide
- movement: [{"fn": "desync.heading", "blend": 0.65}, {"fn": "intercept.lead", "blend": 0.4}, {"fn": "boids.desired_heading", "blend": 0.2}]
- Fan headings when both sides lock the same card (LANE_SWEEP vs LANE_SWEEP). Stops cloned trajectories.

### NASH_HOLD
- mode `REGROUP` when ['CONTESTED', 'LAST_PREY_RISK'] priority 62
- tactics: give_ground, form_wedge, eta_gate, no_corner_herd, flock_sep
- movement: [{"fn": "pressure.heading", "blend": 0.45}, {"fn": "form.slot_heading", "blend": 0.3, "shape": "wedge"}, {"fn": "time.heading", "blend": 0.4}]
- Winning too hard locks a hierarchy (pure Nash). Ease off: give ground, escort, stop the last conversion while fear lives.

### OPEN_KITE
- mode `DEFEND` when ['OUTNUMBERED', 'SMALL_UNIT'] priority 68
- tactics: wall_slide, fear_flee, flock_sep, raid_isolated, intercept
- movement: [{"fn": "sectors.orient", "weight": 1.0}, {"fn": "steer._steer_around_walls", "blend": 0.45}, {"fn": "boids.desired_heading", "blend": 0.35}]
- Outnumbered in open space: circle, slide walls, take only intercept shots. No fort required.

### ORBIT_KITE
- mode `DEFEND` when ['OUTNUMBERED', 'CONTESTED', 'SMALL_UNIT'] priority 66
- tactics: wall_slide, fear_flee, raid_isolated, intercept
- movement: [{"fn": "orbit.heading", "blend": 0.55}, {"fn": "time.heading", "blend": 0.35}, {"fn": "flow.heading", "blend": 0.25}]
- Circle prey or a fort on a tangent ring; take shots only when ETA is safe.

### PACK_HUNT
- mode `HUNT` when ['CONTESTED'] priority 40
- tactics: flock_coh, flock_ali, prey_pull, pincer_flank, focus_fire, intercept, give_ground
- movement: [{"fn": "sectors.orient", "weight": 1.0}, {"fn": "boids.desired_heading", "blend": 0.45, "when": "chase"}, {"fn": "steer.pincer_heading", "blend": 0.35, "when": "chase"}, {"fn": "pressure.heading", "blend": 0.25}]
- Outnumber prey: pack and collapse a chosen target

### PAIR_LOCK
- mode `HUNT` when ['CLEAR_HUNT'] priority 96
- tactics: voronoi_split, lead_intercept, flock_sep, mark_role, prey_pull
- movement: [{"fn": "intercept.lead", "blend": 0.55}, {"fn": "roles.heading", "blend": 0.35}, {"fn": "boids.desired_heading", "blend": 0.2}]
- CLEAR_HUNT: two hunters per prey via Voronoi + lead intercept. Cuts pile-on endgames.

### PRESSURE_BREAK
- mode `DEFEND` when ['LAST_PREY_RISK', 'OUTNUMBERED'] priority 72
- tactics: fear_blob, give_ground, no_corner_herd, fort_cover
- movement: [{"fn": "pressure.heading", "blend": 0.6}, {"fn": "cover.cover_heading", "blend": 0.3}]
- Last-prey / outnumbered: peel off fear blobs and refuse corner piles.

### REGROUP_MASS
- mode `REGROUP` when ['CONTESTED'] priority 20
- tactics: flock_coh, flock_ali, fort_cover
- movement: [{"fn": "boids.desired_heading", "weight": 1.0}]
- Rebuild cohesion before committing

### REGROUP_RIDGE
- mode `REGROUP` when ['OUTNUMBERED', 'NEAR_WIPE'] priority 62
- tactics: flow_field, give_ground, flock_coh, fort_cover, wall_slide
- movement: [{"fn": "flow.heading", "blend": 0.5}, {"fn": "pressure.heading", "blend": 0.3}, {"fn": "cover.cover_heading", "blend": 0.25}]
- Dispersed team: flow along the pressure ridge between forts/walls, then re-form. Fills the thin REGROUP book.

### ROLE_SWEEP
- mode `HUNT` when ['CONTESTED'] priority 56
- tactics: flock_coh, pincer_flank, prey_pull, fear_flee, intercept
- movement: [{"fn": "roles.assign"}, {"fn": "form.slot_heading", "shape": "wedge", "blend": 0.35}, {"fn": "flow.heading", "blend": 0.5}, {"fn": "roles.heading", "blend": 0.25}]
- Assign SCREEN/BAIT/STRIKE, hold a wedge, flow onto prey.

### SCATTER_RAID
- mode `SCATTER` when ['SMALL_UNIT'] priority 70
- tactics: flock_sep, raid_isolated, fear_flee, hide_in_prey, intercept
- movement: [{"fn": "sectors.orient", "weight": 1.0}, {"fn": "boids.desired_heading", "blend": 0.55}]
- Few of us: spread and eat isolated prey

### SCREEN_HUNT
- mode `HUNT` when ['CONTESTED', 'OUTNUMBERED'] priority 58
- tactics: role_screen, form_wedge, fort_cover, pincer_flank, fear_flee, focus_fire
- movement: [{"fn": "roles.assign"}, {"fn": "form.slot_heading", "shape": "wedge", "blend": 0.4}, {"fn": "roles.heading", "blend": 0.45}, {"fn": "cover.cover_heading", "blend": 0.25}]
- Assign SCREEN units to face fear; STRIKE takes isolated prey.

### SHADOW_PREY
- mode `SCATTER` when ['OUTNUMBERED', 'SMALL_UNIT', 'NEAR_WIPE', 'NO_PREY_FEAR_ALIVE'] priority 72
- tactics: hide_in_prey, fear_flee, flock_sep, fort_cover, intercept
- movement: [{"fn": "sectors.orient", "weight": 1.0}, {"fn": "boids.desired_heading", "blend": 0.5}, {"fn": "cover.cover_heading", "blend": 0.25}]
- Fear alive: hide inside the prey flock so predators must risk hitting their food.

### STALL_BREAK
- mode `HUNT` when ['CONTESTED', 'CLEAR_HUNT', 'OUTNUMBERED'] priority 70
- tactics: lead_intercept, clock_eta, prey_pull, flock_sep
- movement: [{"fn": "intercept.lead", "blend": 0.7}, {"fn": "time.heading", "blend": 0.3}]
- Predator answer to LAST_MEAL_STALL: lead intercept + ETA gate so a kiting last group cannot run the clock.

### SURVIVE_FEAR
- mode `SCATTER` when ['NO_PREY_FEAR_ALIVE'] priority 90
- tactics: fear_flee, fort_cover, flock_sep, hide_in_prey, fear_blob, orbit_ring, give_ground
- movement: [{"fn": "pressure.heading", "blend": 0.55}, {"fn": "orbit.heading", "blend": 0.3}, {"fn": "cover.cover_heading", "blend": 0.3}]
- Prey gone, predators live: slide off fear blobs, orbit cover, delay the loss.

### WALL_CUTOFF
- mode `HUNT` when ['CLEAR_HUNT'] priority 96
- tactics: voronoi_split, intercept, wall_slide, flock_sep, prey_pull, sparse_prey
- movement: [{"fn": "voronoi.assign", "when": "CLEAR_HUNT"}, {"fn": "intercept.heading", "blend": 0.7, "mode": "lead"}, {"fn": "sectors.chase_heading", "weight": 1.2}, {"fn": "boids.desired_heading", "blend": 0.1}]
- CLEAR_HUNT: intercept prey sliding a wall instead of chasing their current heading.

### WALL_POUNCE
- mode `HUNT` when ['CONTESTED', 'SMALL_UNIT'] priority 54
- tactics: wall_slide, fort_slide, intercept, prey_pull, raid_isolated
- movement: [{"fn": "orbit.heading", "blend": 0.4}, {"fn": "steer._steer_around_walls", "blend": 0.35}, {"fn": "flow.heading", "blend": 0.3, "when": "chase"}]
- Slide a wall or fort, then cut back onto prey on the rebound.

## Per-type tuned copies (from types/{TYPE}/*.json stats)

### ROCK
- **LAST_MEAL_STALL** ticks=206601 games=2799 wins=389 wr=14% blunder=0 pri=88 hold=24 margin=1.450064752014758
- **LAST_MAN_CLOCK** ticks=132896 games=2228 wins=120 wr=5% blunder=0 pri=108 hold=12 margin=0.9846651136905733
- **PACK_HUNT** ticks=111571 games=916 wins=171 wr=19% blunder=214 pri=40 hold=11 margin=1.2082337924929116
- **MIRROR_BREAK** ticks=81381 games=1293 wins=247 wr=19% blunder=7 pri=74 hold=15 margin=1.2700472882541856
- **LAST_PREY_CARE** ticks=78876 games=5812 wins=680 wr=12% blunder=117 pri=92 hold=14 margin=1.2589298566397638
- **SCREEN_HUNT** ticks=66953 games=473 wins=87 wr=18% blunder=45 pri=58 hold=18 margin=1.4502125652975422
- **LANE_SWEEP** ticks=66347 games=943 wins=210 wr=22% blunder=134 pri=88 hold=19 margin=0.6454989462524311
- **CHOKE_PINCH** ticks=60446 games=644 wins=166 wr=26% blunder=1274 pri=55 hold=23 margin=0.8236683152374971
- **CROSS_LANE** ticks=41989 games=1101 wins=195 wr=18% blunder=2 pri=76 hold=15 margin=1.269312382087242
- **ORBIT_KITE** ticks=34110 games=414 wins=67 wr=16% blunder=1 pri=66 hold=23 margin=1.4124569149286228
- **DELAY_FEAST** ticks=33044 games=1014 wins=29 wr=3% blunder=0 pri=96 hold=9 margin=0.500248647934014
- **LAST_MAN_RUN** ticks=26313 games=1562 wins=212 wr=14% blunder=2 pri=110 hold=20 margin=1.7704725976577735
- **STALL_BREAK** ticks=22482 games=672 wins=61 wr=9% blunder=2 pri=70 hold=3 margin=0.5005225864058357
- **BOUNCE_JUKE** ticks=20628 games=579 wins=157 wr=27% blunder=0 pri=70 hold=20 margin=1.0830970925131655
- **REGROUP_RIDGE** ticks=12822 games=482 wins=24 wr=5% blunder=2 pri=62 hold=23 margin=1.4097136420030791
- **ESCORT_RING** ticks=10980 games=513 wins=13 wr=3% blunder=1 pri=78 hold=23 margin=0.5001786049426842
- **CHORD_CUT** ticks=10837 games=298 wins=76 wr=26% blunder=5 pri=72 hold=19 margin=0.9767924683072907
- **FORT_KITE** ticks=9010 games=212 wins=41 wr=19% blunder=0 pri=75 hold=3 margin=1.9980358417420592
- **LAST_MEAL_ORBIT** ticks=8141 games=581 wins=5 wr=1% blunder=93 pri=94 hold=5 margin=1.9999991980003766
- **LAST_STAND** ticks=8014 games=480 wins=25 wr=5% blunder=0 pri=95 hold=12 margin=0.7274572627977426
- **CLEAR_SPLIT** ticks=7965 games=727 wins=189 wr=26% blunder=0 pri=100 hold=24.0 margin=1.9985275445418655
- **GATE_CAMP** ticks=6063 games=145 wins=31 wr=21% blunder=0 pri=56 hold=3 margin=0.5000834265865725
- **SHADOW_PREY** ticks=5566 games=567 wins=35 wr=6% blunder=2 pri=72 hold=3 margin=1.3304387446925592
- **SURVIVE_FEAR** ticks=5045 games=382 wins=11 wr=3% blunder=0 pri=90 hold=16 margin=0.6713414086358618
- **NASH_HOLD** ticks=4432 games=117 wins=18 wr=15% blunder=3 pri=62 hold=10 margin=1.173578431179131
- **WALL_POUNCE** ticks=4095 games=117 wins=22 wr=19% blunder=19 pri=54 hold=24 margin=1.9999999968308124
- **PAIR_LOCK** ticks=4093 games=257 wins=82 wr=32% blunder=61 pri=96 hold=23 margin=1.2096251257343515
- **FEAR_RIDGE** ticks=4023 games=341 wins=0 wr=0% blunder=0 pri=88 hold=23 margin=1.9987325731638086
- **BAIT_TURN** ticks=2862 games=85 wins=5 wr=6% blunder=1 pri=52 hold=22 margin=1.9906504833963954
- **DENSITY_RAID** ticks=2687 games=107 wins=23 wr=21% blunder=20 pri=57 hold=24 margin=1.9999995126502383
- **ETA_STRIKE** ticks=2327 games=82 wins=10 wr=12% blunder=31 pri=62 hold=3 margin=0.5003642278268544
- **HOLD_COVER** ticks=1581 games=113 wins=13 wr=12% blunder=0 pri=80 hold=23 margin=1.9784486646224393
- **REGROUP_MASS** ticks=1481 games=50 wins=3 wr=6% blunder=0 pri=20 hold=23 margin=1.9999579558396339
- **PRESSURE_BREAK** ticks=1475 games=92 wins=1 wr=1% blunder=0 pri=72 hold=5 margin=1.05
- **OPEN_KITE** ticks=1313 games=129 wins=17 wr=13% blunder=0 pri=68 hold=11 margin=1.1041826648575246
- **MARK_ONE** ticks=898 games=53 wins=3 wr=6% blunder=0 pri=58 hold=7 margin=1.0
- **CONTESTED_SPLIT** ticks=823 games=46 wins=1 wr=2% blunder=0 pri=54 hold=7 margin=1.0
- **ROLE_SWEEP** ticks=820 games=38 wins=4 wr=11% blunder=10 pri=56 hold=23 margin=1.9928351525754155
- **ETA_SPLIT** ticks=660 games=347 wins=2 wr=1% blunder=0 pri=97 hold=8 margin=1.1
- **CLEAR_FAN** ticks=658 games=340 wins=3 wr=1% blunder=0 pri=96 hold=7 margin=1.0
- **FINISH_CLOCK** ticks=650 games=342 wins=3 wr=1% blunder=0 pri=97 hold=7 margin=1.0
- **WALL_CUTOFF** ticks=619 games=349 wins=2 wr=1% blunder=0 pri=96 hold=8 margin=1.1
- **GIVE_GROUND** ticks=442 games=32 wins=0 wr=0% blunder=0 pri=58 hold=6 margin=1.06
- **CLOSE_QUARTERS** ticks=405 games=34 wins=0 wr=0% blunder=10 pri=53 hold=5 margin=1.05
- unused: SCATTER_RAID

### PAPER
- **ORBIT_KITE** ticks=211445 games=2070 wins=165 wr=8% blunder=6 pri=66 hold=24 margin=1.540194655043446
- **LANE_SWEEP** ticks=157146 games=1532 wins=191 wr=12% blunder=658 pri=88 hold=5 margin=0.878548277938082
- **LAST_MAN_CLOCK** ticks=105433 games=2049 wins=126 wr=6% blunder=7 pri=108 hold=23 margin=1.989647581747157
- **DELAY_FEAST** ticks=103378 games=1166 wins=40 wr=3% blunder=0 pri=96 hold=23 margin=1.97223658085881
- **LAST_MAN_RUN** ticks=85029 games=2135 wins=179 wr=8% blunder=4 pri=110 hold=24 margin=0.5567437764415598
- **PACK_HUNT** ticks=68984 games=1186 wins=53 wr=4% blunder=111 pri=40 hold=24 margin=1.7008418113232286
- **BOUNCE_JUKE** ticks=44373 games=1319 wins=142 wr=11% blunder=2 pri=70 hold=24.0 margin=0.7913965185833665
- **SCREEN_HUNT** ticks=43149 games=787 wins=56 wr=7% blunder=124 pri=58 hold=3 margin=0.5076413370176884
- **LAST_PREY_CARE** ticks=38402 games=6570 wins=552 wr=8% blunder=139 pri=92 hold=3 margin=1.9982002223032178
- **LAST_MEAL_ORBIT** ticks=36151 games=995 wins=18 wr=2% blunder=307 pri=94 hold=7 margin=1.0
- **OPEN_KITE** ticks=35517 games=705 wins=44 wr=6% blunder=2 pri=68 hold=23 margin=0.5043964912291793
- **LAST_MEAL_STALL** ticks=34708 games=1628 wins=120 wr=7% blunder=0 pri=88 hold=15 margin=0.6336346617488784
- **HOLD_COVER** ticks=19353 games=142 wins=12 wr=8% blunder=0 pri=80 hold=23 margin=1.9944273699752126
- **CHOKE_PINCH** ticks=17158 games=318 wins=70 wr=22% blunder=1814 pri=55 hold=24.0 margin=0.6667685325987786
- **SHADOW_PREY** ticks=13280 games=1033 wins=47 wr=5% blunder=4 pri=72 hold=6 margin=1.2110344952209422
- **SURVIVE_FEAR** ticks=12695 games=889 wins=6 wr=1% blunder=0 pri=90 hold=24 margin=1.072354368396257
- **LAST_STAND** ticks=12332 games=499 wins=23 wr=5% blunder=1 pri=95 hold=11 margin=1.5751216596024715
- **FEAR_RIDGE** ticks=11379 games=848 wins=2 wr=0% blunder=0 pri=88 hold=23 margin=1.9930972435118823
- **STALL_BREAK** ticks=9991 games=861 wins=163 wr=19% blunder=14 pri=70 hold=18 margin=1.7476378698566428
- **ESCORT_RING** ticks=9933 games=432 wins=6 wr=1% blunder=2 pri=78 hold=4 margin=0.9580663425266757
- **FORT_KITE** ticks=9691 games=385 wins=76 wr=20% blunder=4 pri=75 hold=10 margin=1.4994114660446969
- **CROSS_LANE** ticks=8613 games=427 wins=40 wr=9% blunder=2 pri=76 hold=23 margin=1.9999927581906016
- **REGROUP_RIDGE** ticks=8224 games=516 wins=50 wr=10% blunder=0 pri=62 hold=23 margin=1.9220062349557292
- **DENSITY_RAID** ticks=2350 games=73 wins=9 wr=12% blunder=22 pri=57 hold=24 margin=0.5000116712963618
- **CLEAR_SPLIT** ticks=2301 games=259 wins=85 wr=33% blunder=0 pri=100 hold=24.0 margin=1.9985275445418655
- **GATE_CAMP** ticks=657 games=73 wins=13 wr=18% blunder=2 pri=56 hold=10 margin=0.76750664934006
- **FINISH_CLOCK** ticks=396 games=139 wins=7 wr=5% blunder=0 pri=97 hold=7 margin=1.0
- **BAIT_TURN** ticks=383 games=64 wins=22 wr=34% blunder=1 pri=52 hold=23 margin=1.4748911395281958
- **WALL_POUNCE** ticks=280 games=46 wins=12 wr=26% blunder=22 pri=54 hold=24 margin=0.5000000040164869
- **CLEAR_FAN** ticks=233 games=131 wins=1 wr=1% blunder=0 pri=96 hold=7 margin=1.0
- **ETA_SPLIT** ticks=182 games=107 wins=1 wr=1% blunder=0 pri=97 hold=8 margin=1.2177324605374
- **WALL_CUTOFF** ticks=172 games=114 wins=1 wr=1% blunder=0 pri=96 hold=8 margin=1.1
- **CHORD_CUT** ticks=165 games=11 wins=3 wr=27% blunder=0 pri=72 hold=7 margin=1.0
- **PRESSURE_BREAK** ticks=131 games=11 wins=1 wr=9% blunder=1 pri=72 hold=5 margin=1.05
- **ETA_STRIKE** ticks=130 games=11 wins=3 wr=27% blunder=27 pri=62 hold=6 margin=1.08
- **MARK_ONE** ticks=127 games=20 wins=6 wr=30% blunder=0 pri=58 hold=7 margin=1.0
- **CLOSE_QUARTERS** ticks=113 games=16 wins=3 wr=19% blunder=7 pri=53 hold=5 margin=1.05
- **MIRROR_BREAK** ticks=111 games=6 wins=0 wr=0% blunder=1 pri=74 hold=7 margin=1.0
- **ROLE_SWEEP** ticks=90 games=12 wins=4 wr=33% blunder=14 pri=56 hold=3 margin=1.9999999987127923
- **PAIR_LOCK** ticks=78 games=3 wins=0 wr=0% blunder=4 pri=96 hold=7 margin=1.0
- **NASH_HOLD** ticks=77 games=9 wins=2 wr=22% blunder=1 pri=62 hold=7 margin=1.12
- **REGROUP_MASS** ticks=41 games=6 wins=0 wr=0% blunder=0 pri=20 hold=7 margin=1.0
- **GIVE_GROUND** ticks=34 games=1 wins=0 wr=0% blunder=0 pri=58 hold=6 margin=1.06
- **CONTESTED_SPLIT** ticks=33 games=4 wins=0 wr=0% blunder=0 pri=54 hold=6 margin=1.08
- unused: SCATTER_RAID

### SCISSORS
- **LANE_SWEEP** ticks=211896 games=1308 wins=404 wr=31% blunder=463 pri=88 hold=17 margin=1.1676269796282135
- **BOUNCE_JUKE** ticks=122893 games=1538 wins=347 wr=23% blunder=9 pri=70 hold=8 margin=1.7296729312447992
- **REGROUP_RIDGE** ticks=109356 games=1364 wins=118 wr=9% blunder=3 pri=62 hold=23 margin=1.9999999999999998
- **LAST_PREY_CARE** ticks=105757 games=6556 wins=795 wr=12% blunder=179 pri=92 hold=11 margin=0.5000519820618176
- **ORBIT_KITE** ticks=98476 games=1184 wins=247 wr=21% blunder=4 pri=66 hold=24 margin=1.256730870511914
- **LAST_MAN_RUN** ticks=83777 games=2195 wins=297 wr=14% blunder=1 pri=110 hold=21 margin=0.825711194350265
- **FORT_KITE** ticks=40285 games=583 wins=59 wr=10% blunder=1 pri=75 hold=5 margin=0.9302799387357987
- **CROSS_LANE** ticks=37987 games=1343 wins=236 wr=18% blunder=8 pri=76 hold=5 margin=1.0491716973404543
- **LAST_MEAL_ORBIT** ticks=36366 games=962 wins=42 wr=4% blunder=365 pri=94 hold=19 margin=1.9999789888609871
- **LAST_MEAL_STALL** ticks=35595 games=1547 wins=141 wr=9% blunder=0 pri=88 hold=18 margin=1.7441508169820297
- **DELAY_FEAST** ticks=34906 games=986 wins=31 wr=3% blunder=0 pri=96 hold=13 margin=1.3970003289404804
- **LAST_MAN_CLOCK** ticks=32547 games=1352 wins=105 wr=8% blunder=4 pri=108 hold=9 margin=1.326095955211053
- **STALL_BREAK** ticks=27567 games=939 wins=222 wr=24% blunder=6 pri=70 hold=11 margin=1.1136235175463107
- **SHADOW_PREY** ticks=25257 games=957 wins=48 wr=5% blunder=2 pri=72 hold=18 margin=1.0839529162473047
- **CHOKE_PINCH** ticks=23194 games=409 wins=108 wr=26% blunder=2173 pri=55 hold=24 margin=0.5000822583222986
- **WALL_POUNCE** ticks=14159 games=149 wins=20 wr=13% blunder=18 pri=54 hold=24 margin=1.9999999922410001
- **SURVIVE_FEAR** ticks=11641 games=779 wins=11 wr=1% blunder=1 pri=90 hold=16 margin=0.9260731567791358
- **FEAR_RIDGE** ticks=10698 games=710 wins=0 wr=0% blunder=0 pri=88 hold=17 margin=1.0282242707464073
- **PRESSURE_BREAK** ticks=5713 games=105 wins=4 wr=4% blunder=0 pri=72 hold=5 margin=1.05
- **ESCORT_RING** ticks=3949 games=269 wins=5 wr=2% blunder=1 pri=78 hold=3 margin=0.5003526033692178
- **CLEAR_SPLIT** ticks=3414 games=624 wins=138 wr=22% blunder=0 pri=100 hold=24.0 margin=1.9852346839105626
- **DENSITY_RAID** ticks=3198 games=111 wins=17 wr=15% blunder=18 pri=57 hold=24 margin=1.9999999999989904
- **LAST_STAND** ticks=3112 games=269 wins=17 wr=6% blunder=2 pri=95 hold=20 margin=0.8451338474637623
- **BAIT_TURN** ticks=2093 games=91 wins=8 wr=9% blunder=0 pri=52 hold=6 margin=1.08
- **CLEAR_FAN** ticks=2084 games=505 wins=24 wr=5% blunder=0 pri=96 hold=14 margin=1.380499786135671
- **PACK_HUNT** ticks=2007 games=67 wins=5 wr=7% blunder=9 pri=40 hold=24.0 margin=1.6297754924274341
- **GATE_CAMP** ticks=1689 games=108 wins=18 wr=17% blunder=0 pri=56 hold=23 margin=0.5000000092512638
- **NASH_HOLD** ticks=1620 games=60 wins=6 wr=10% blunder=0 pri=62 hold=23 margin=1.9995487346223249
- **MARK_ONE** ticks=1587 games=52 wins=2 wr=4% blunder=0 pri=58 hold=23 margin=1.9999999999999998
- **REGROUP_MASS** ticks=1498 games=61 wins=4 wr=7% blunder=0 pri=20 hold=7 margin=1.0
- **CONTESTED_SPLIT** ticks=1376 games=53 wins=4 wr=8% blunder=0 pri=54 hold=23 margin=0.542702375847598
- **OPEN_KITE** ticks=1177 games=117 wins=18 wr=15% blunder=0 pri=68 hold=24.0 margin=1.6380772586241577
- **SCREEN_HUNT** ticks=1096 games=103 wins=1 wr=1% blunder=7 pri=58 hold=7 margin=1.05
- **HOLD_COVER** ticks=903 games=76 wins=3 wr=4% blunder=0 pri=80 hold=7 margin=1.0
- **MIRROR_BREAK** ticks=817 games=50 wins=2 wr=4% blunder=2 pri=74 hold=7 margin=1.0
- **FINISH_CLOCK** ticks=783 games=436 wins=3 wr=1% blunder=0 pri=97 hold=7 margin=1.0
- **ROLE_SWEEP** ticks=731 games=57 wins=4 wr=7% blunder=15 pri=56 hold=7 margin=1.05
- **CHORD_CUT** ticks=636 games=46 wins=2 wr=4% blunder=0 pri=72 hold=7 margin=1.0
- **ETA_SPLIT** ticks=594 games=410 wins=2 wr=0% blunder=0 pri=97 hold=8 margin=1.1
- **WALL_CUTOFF** ticks=593 games=411 wins=3 wr=1% blunder=0 pri=96 hold=6 margin=0.9399705243963979
- **CLOSE_QUARTERS** ticks=589 games=38 wins=0 wr=0% blunder=8 pri=53 hold=5 margin=1.05
- **ETA_STRIKE** ticks=369 games=45 wins=0 wr=0% blunder=12 pri=62 hold=6 margin=1.08
- **GIVE_GROUND** ticks=343 games=32 wins=0 wr=0% blunder=0 pri=58 hold=6 margin=1.06
- **PAIR_LOCK** ticks=80 games=5 wins=1 wr=20% blunder=5 pri=96 hold=7 margin=1.0
- unused: SCATTER_RAID

## Invent next

1. Find a gap (state + math combo no template covers well).
2. Write templates/NEW_ID.json using only tactics and fns listed above.
3. Keep `id` unique and UPPER_SNAKE.
4. Types will clone it; optimiser will tune switch + weights per type.

