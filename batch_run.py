"""Headless strategy training. Usage: python batch_run.py [n_games]

Runs matches with no window, no clock cap, cheaper AI, then the same
learn persist a live TITLE screen would run after each game.
"""
import os
import sys
import time
import random

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

from config import Config
Config.FAST_SIM = True
Config.VSYNC = False
Config.TITLE_MS = 0
Config.LEARN_REVEAL_MS = 0
Config.LEARN_MAX_MS = 0
Config.TARGET_FPS = 0
# Live cap is 6. 64 made every particle think every frame (~70ms).
Config.AI_BUDGET = 8
Config.TEAM_UPDATE_EVERY = 4
Config.FAST_SIM_PHYS_STEPS = 3
Config.FAST_SIM_AI_EVERY = 1

from arena import Arena

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
# 3 physics steps × 700 frames ≈ 2100 live-equivalent ticks
MAX_FRAMES = 700

w = Arena(800, 600)
if hasattr(w, 'perf') and w.perf is not None:
    w.perf._enabled = False
if hasattr(w, 'optimizer') and w.optimizer is not None:
    # Replicator every game (same as live TITLE). GA/PSO every 5th game
    # so a 20-game batch does not stall a minute per persist.
    w.optimizer.LEARN_EVERY_HEAVY = 5
    w.optimizer.MIN_GAMES_GA = 8
wins = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0, 'NONE': 0}
t0 = time.time()
for i in range(N):
    w.teamSize = random.randint(5, 9)
    w.forts = random.randint(3, 6)
    w.reset()
    frames = 0
    g0 = time.time()
    while w.running and not w.gameover() and frames < MAX_FRAMES:
        w.draw()
        frames += 1
    winner = 'NONE'
    pending = getattr(w, '_pending_gameover_type', None)
    if pending is not None:
        winner = pending.name if hasattr(pending, 'name') else str(pending)
    elif w.particles:
        winner = w.particles[0].type.name
    wins[winner] = wins.get(winner, 0) + 1
    counts = {}
    try:
        counts = {t.name: int(w.type_counts.get(t, 0) or 0) for t in w.type_counts}
    except Exception:
        counts = {}
    sim_s = time.time() - g0
    print('game %02d  frames=%d  %.2fs  team=%d  forts=%d  winner=%s  left=%s' % (
        i + 1, frames, sim_s, w.teamSize, w.forts, winner, counts))
    pending = getattr(w, '_pending_gameover_type', None)
    if pending is not None and hasattr(w, 'metrics'):
        try:
            tlog = time.time()
            w.metrics.log_gameover(pending)
            print('  log_gameover %.2fs' % (time.time() - tlog))
        except Exception as e:
            print('log_gameover', e)
    w._pending_gameover_type = None
    l0 = time.time()
    try:
        print('  learn start')
        w.optimizer.optimise(persist=True)
        print('  learn gen=%s changes=%d  %.2fs' % (
            getattr(w.optimizer, 'GENERATION', '?'),
            len(getattr(w.optimizer, 'last_changes', []) or []),
            time.time() - l0))
    except Exception as e:
        print('  optimise', e)
dt = time.time() - t0
print('done in %.1fs  (%.2fs/game)  wins=%s' % (dt, dt / max(1, N), wins))
