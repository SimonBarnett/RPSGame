# Batch 29 (FAST_SIM) — 2026-08-30

Games finished before session reset: **29** (game 30 did not log).
Wins: **ROCK 13 / SCISSORS 9 / PAPER 7**.

Frames: median ~450, long tails 768–1027 (endgame drag).
Snowball: winner finishes with the whole team converted (`left` is 3× teamSize).

## Conversion sample (last ~1800 rows)

- States: CONTESTED 1038, CLEAR_HUNT 465, OUTNUMBERED 186, NEAR_WIPE 55, LAST_PREY_RISK 36
- Almost every kill is **same-card vs same-card**:
  - SCISSORS/LANE_SWEEP vs PAPER/LANE_SWEEP (353)
  - ROCK/ORBIT_KITE vs SCISSORS/ORBIT_KITE (297)
  - PAPER/LANE_SWEEP vs ROCK/LANE_SWEEP (275)
  - CLEAR_SPLIT vs CLEAR_SPLIT (206 / 143 / 98)

Types pick the same state card and clone one trajectory.

## Added

Math
- `maths/intercept.py` — lead pursuit + chord-cut
- `maths/desync.py` — stable per-unit heading fan

Templates
- `CHORD_CUT` — cut the orbit (anti ORBIT_KITE)
- `MIRROR_BREAK` — desync when both sides lock the same card
- `CROSS_LANE` — cut across LANE_SWEEP
- `PAIR_LOCK` — two hunters per prey in CLEAR_HUNT
- `STALL_BREAK` — predator answer to LAST_MEAL_STALL

Empty niches still worth a later template: NEAR_WIPE × large team, LAST_PREY_RISK × Paper (weakest type).
