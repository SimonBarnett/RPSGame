"""Daily log/CSV tail. Keeps last-40/last-80 metrics; never touches counters."""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
METRICS = os.path.join(ROOT, "optimizer", "metrics")
STAMP = os.path.join(METRICS, ".log_cleanup_day")


def log_path(name):
    os.makedirs(METRICS, exist_ok=True)
    return os.path.join(METRICS, name)
KEEP_LOG = 20000
KEEP_CSV = 8000
KEEP_TXT = 4000
# Skip rewrite if already near the cap.
OVER = 1.25


def _utc_day():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _already_today():
    try:
        with open(STAMP, encoding="utf-8") as f:
            return f.read().strip() == _utc_day()
    except Exception:
        return False


def _mark_today():
    os.makedirs(METRICS, exist_ok=True)
    tmp = STAMP + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_utc_day() + "\n")
    os.replace(tmp, STAMP)


def _tail_lines(path, keep, header=False):
    if not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size < 64 * 1024:
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    if header:
        if len(lines) <= int(KEEP_CSV * OVER) + 1:
            return None
        head, data = lines[0], lines[1:]
        if len(data) <= keep:
            return None
        return [head] + data[-keep:]
    if len(lines) <= int(keep * OVER):
        return None
    return lines[-keep:]


def _replace(path, lines):
    tmp = path + ".trim"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)
        if lines and not lines[-1].endswith("\n"):
            f.write("\n")
    os.replace(tmp, path)
    return len(lines)


def run(force=False):
    if not force and _already_today():
        return []
    done = []
    # Never touch games_total.txt, generation.txt, or *highwater.txt.
    jobs = [
        (log_path("metrics_optimize.log"), KEEP_LOG, False),
        (log_path("metrics_perf.log"), KEEP_LOG, False),
        (log_path("metrics_games.csv"), KEEP_CSV, True),
        (log_path("metrics_conversions.csv"), KEEP_CSV, True),
        (log_path("metrics_population.csv"), KEEP_CSV, True),
        (log_path("metrics_strategy.csv"), KEEP_CSV, True),
        (log_path("metrics_payoff.csv"), KEEP_CSV, True),
        (os.path.join(ROOT, "gameover.txt"), KEEP_TXT, False),
        (os.path.join(ROOT, "speed_debug.log"), KEEP_TXT, False),
    ]
    for path, keep, header in jobs:
        try:
            lines = _tail_lines(path, keep, header=header)
            if not lines:
                continue
            n = _replace(path, lines)
            done.append("%s -> %d lines" % (os.path.basename(path), n))
        except Exception as e:
            done.append("%s skip (%s)" % (os.path.basename(path), e))
    try:
        _mark_today()
    except Exception:
        pass
    return done


def maybe_daily():
    """Idempotent; safe to call from log_gameover every game."""
    try:
        if _already_today():
            return []
        return run(force=False)
    except Exception:
        return []


def main():
    force = "--force" in sys.argv
    rows = run(force=force)
    if not rows:
        print("log cleanup: nothing to do")
        return 0
    for r in rows:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
