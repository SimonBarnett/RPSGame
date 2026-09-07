See [README.md](../README.md) for run flags (`-learn` / `/learn`).

# Separation of concerns

**Compiled (do not evolve):** `maths/*`, `phys`, collision convert, arena loop, marble render, UCB/MCTS/replicator *algorithms*.

**Data (optimizer reads and may rewrite):**
- `strategies/templates/{ID}.json` — drop a new doctrine here
- `strategies/types/{TYPE}/{ID}.json` — each team’s learned copy (weights, when, switch, stats)
- `strategies/meta.json` — banned / force pools / last-prey threshold / motion clamps
- `strategies/identity.json` — speed/turn triangle (shape locked, values nudged)
- `strategies/bounds.json` — knob floors/ceilings/steps
- `strategies/math.json`, `tactics.json`

A new strategy is a JSON file. Next `playbook.reload()` clones it to ROCK/PAPER/SCISSORS. The optimiser tunes those copies independently. Do not put tunables back in `config.py`.

# Strategy JSON — drop-in doctrine

A strategy is **data**. Python only runs math binaries (`maths/`, `arena/fort.py`).
Drop a new file in `strategies/templates/{ID}.json`. On the next match (or `playbook.reload()`)
each of ROCK / PAPER / SCISSORS gets its own copy under `strategies/types/{TYPE}/{ID}.json`.
The optimiser tunes **those copies independently** (when to swap, which tactics, switch hold).

## Template (`strategies/templates/ID.json`)

```json
{
  "id": "PACK_HUNT",
  "title": "Pack hunt",
  "mode": "HUNT",
  "desc": "One sentence. This is what Grok / the optimiser reads.",
  "when": {
    "states": ["CONTESTED"],
    "priority": 40
  },
  "tactics": ["flock_coh", "prey_pull", "pincer_flank"],
  "math": ["boids", "steer", "sectors"],
  "movement": [
    {"fn": "sectors.orient", "weight": 1.0},
    {"fn": "boids.desired_heading", "blend": 0.45, "when": "chase"}
  ],
  "switch": {"hold_frames": 8, "margin": 1.0},
  "bounds": {
    "near_target_aggro": [1.2, 3.2, 0.05],
    "speed_base": [0.9, 1.8, 0.02]
  },
  "base": {
    "speed_base": 1.3,
    "turn_base": 13.0,
    "size": 20
  }
}
```

Learned values live on `strategies/types/{TYPE}/{ID}.json` (`weights`, `base`, `bounds`, `stats`). There is no `_profile.json`.

### Fields

| field | meaning |
|---|---|
| `id` | Unique. Filename should match. |
| `mode` | `HUNT` `DEFEND` `REGROUP` `SCATTER` — TeamMode the sim already knows |
| `when.states` | Game states this strategy wants. First/highest priority wins. |
| `when.priority` | Higher beats lower when several match. Types can learn this. |
| `tactics` | Ids from `tactics.json`. Each binds to a math `fn` + a learned knob. |
| `math` | Modules from `math.json` this strategy is allowed to call. |
| `movement` | Ordered heading pipeline. `fn` is `module.api_tail`. `blend` mixes into current heading. Optional `when` (`chase`/`evade`/`CLEAR_HUNT`). |
| `switch.hold_frames` | Hysteresis before leaving the current strategy. |
| `switch.margin` | How much better the candidate must be before swapping. |
| `tunables` | Map of knob → `[lo, hi, step]`. **This is what the optimiser is allowed to change** for this strategy. Include `switch.hold_frames`, `switch.margin`, `when.priority`, tactic knobs, and `movement[i].blend`. If omitted, those are derived from `tactics` + `movement`. |



### Game states you can list in `when.states`

`CLEAR_HUNT` `NEAR_WIPE` `NO_PREY_FEAR_ALIVE` `LAST_PREY_RISK` `OUTNUMBERED` `SMALL_UNIT` `CONTESTED`

### Math binaries (`math.json`)

`boids` `voronoi` `steer` `sectors` `cover` `hash` `phys`

See each entry's `api` list. Do not invent a `fn` that is not in that list.


### Type profile (`strategies/types/ROCK/_profile.json`)

All learned knobs for that type (the old type_config strategy block).
The optimiser writes here, not into `type_config.py`.
`type_config.py` keeps only motion identity: speed, turn, size, ranges, prey, fear, icon, color.

On load, `_profile.json` is applied onto TYPE_DEFAULTS, then the active
`types/{TYPE}/{STRATEGY}.json` `weights` overlay that.

### Per-type copy (`strategies/types/ROCK/PACK_HUNT.json`)

Same schema plus:

```json
{
  "type": "ROCK",
  "enabled": true,
  "weights": { "near_target_aggro": 2.19, "pincer_weight": 1.4 },
  "stats": { "ticks": 0, "wins": 0, "games": 0 }
}
```

The optimiser writes `switch`, `when.priority`, `tactics`, and `weights` here.
`type_config.py` still holds the raw motion knobs; overlay `weights` override them while the strategy is active.

## How to invent a new strategy (paste this + GROK_BRIEF.md)

1. Read `strategies/GROK_BRIEF.md` (auto-written each persist).
2. Pick unused tactics from `tactics.json` and math from `math.json`.
3. Write `strategies/templates/YOUR_ID.json`.
4. Run the game. Copies appear under `strategies/types/{ROCK,PAPER,SCISSORS}/`.
5. Next optimiser pass treats YOUR_ID as a first-class strategy.

Do not put Python in the JSON. Movement is a list of `{fn, blend, when}`.
