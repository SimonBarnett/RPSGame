"""Rock / Paper / Scissors.

  python game.py                 live window
  python game.py -learn 20       train 20 games
  python game.py /learn          train until Ctrl+C
  RPS_Game.exe /learn 50         same from the exe
"""
import argparse
import os
import sys


def _bootstrap():
    try:
        from app_paths import bootstrap
        created = bootstrap()
        if created:
            print('seeded', ', '.join(created), flush=True)
    except Exception as e:
        print('bootstrap', e, flush=True)


def _normalize(argv):
    out = []
    for a in list(argv or []):
        if a.lower() in ('/learn', '-learn', '--learn'):
            out.append('--learn')
        elif a.lower().startswith('/learn='):
            out.append('--learn')
            out.append(a.split('=', 1)[1])
        elif a.lower().startswith('/learn:'):
            out.append('--learn')
            out.append(a.split(':', 1)[1])
        else:
            out.append(a)
    return out


def _parse(argv=None):
    raw = _normalize(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser()
    p.add_argument('--learn', '-learn', nargs='?', const='forever', default=None,
                   metavar='N', help='headless train N games; omit N to run until Ctrl+C')
    p.add_argument('-n', nargs='?', const='forever', default=None, metavar='N',
                   help='alias for -learn')
    args = p.parse_args(raw)
    token = args.learn if args.learn is not None else args.n
    if token is None:
        return 0  # live
    if str(token).lower() in ('forever', 'inf', 'until', ''):
        return None  # until Ctrl+C
    try:
        n = int(token)
    except ValueError:
        return None
    return n if n > 0 else None


def live():
    import random
    from arena import Arena
    w = Arena()
    while w.running:
        w.teamSize = random.randint(5, 20)
        w.forts = random.randint(4, 10)
        w.reset()
        while w.running and not w.gameover():
            w.draw()
            w.events()


def learn(n=None):
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    from config import Config
    Config.FAST_SIM = True
    Config.VSYNC = False
    Config.TITLE_MS = 0
    Config.LEARN_REVEAL_MS = 0
    Config.LEARN_MAX_MS = 0
    Config.TARGET_FPS = 0
    Config.AI_BUDGET = 48
    Config.TEAM_UPDATE_EVERY = 5
    Config.FAST_SIM_PHYS_STEPS = 1
    Config.FAST_SIM_AI_EVERY = 1
    import random
    import time
    from arena import Arena
    w = Arena(800, 600)
    if getattr(w, 'perf', None) is not None:
        w.perf._enabled = False
    if getattr(w, 'optimizer', None) is not None:
        w.optimizer.LEARN_EVERY_HEAVY = 5
        w.optimizer.MIN_GAMES_GA = 8
    wins = {'ROCK': 0, 'PAPER': 0, 'SCISSORS': 0, 'NONE': 0}
    t0 = time.time()
    forever = n is None or int(n) <= 0
    print('learn until Ctrl+C' if forever else 'learn %d games' % int(n), flush=True)
    i = 0
    try:
      while forever or i < int(n):
        i += 1
        w.teamSize = random.randint(5, 9)
        w.forts = random.randint(3, 6)
        w.reset()
        try:
            w.metrics.reset_match()
        except Exception:
            pass
        frames = 0
        g0 = time.time()
        while w.running and not w.gameover() and frames < 2400:
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
            pass
        print('game %02d  frames=%d  %.2fs  team=%d  forts=%d  winner=%s  left=%s' % (
            i, frames, time.time() - g0, w.teamSize, w.forts, winner, counts), flush=True)
        if pending is not None and hasattr(w, 'metrics'):
            try:
                w.metrics.log_gameover(pending)
            except Exception as e:
                print('log_gameover', e, flush=True)
        w._pending_gameover_type = None
        try:
            w.optimizer.optimise(persist=True)
            print('  learn gen=%s changes=%d' % (
                getattr(w.optimizer, 'GENERATION', '?'),
                len(getattr(w.optimizer, 'last_changes', []) or [])), flush=True)
        except Exception as e:
            print('  optimise', e, flush=True)
    except KeyboardInterrupt:
        print('\nstopped after %d games' % i, flush=True)
    print('done in %.1fs  wins=%s' % (time.time() - t0, wins), flush=True)
    return wins


if __name__ == '__main__':
    _bootstrap()
    n = _parse()
    if n is None or n > 0:
        learn(n)
    else:
        live()
