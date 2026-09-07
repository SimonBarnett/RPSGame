"""Cheap frame profiler. Writes optimizer/metrics_perf.log."""

import time
import os

from optimizer.paths import log_path


class PerfLog:
    def __init__(self, filename='metrics_perf.log'):
        self.path = log_path(filename)
        self._t0 = {}
        self._acc = {}
        self._n = {}
        self._peak = {}
        self.frames = 0
        self._frame_t0 = time.perf_counter()
        self._last_flush = time.perf_counter()
        self._flush_every = 2.0
        self._enabled = True
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write('\n# perf start %s\n' % time.strftime('%Y-%m-%dT%H:%M:%S'))
        except Exception:
            self._enabled = False

    def begin(self, name):
        if self._enabled:
            self._t0[name] = time.perf_counter()

    def end(self, name):
        if not self._enabled:
            return 0.0
        t0 = self._t0.pop(name, None)
        if t0 is None:
            return 0.0
        dt = time.perf_counter() - t0
        self._acc[name] = self._acc.get(name, 0.0) + dt
        self._n[name] = self._n.get(name, 0) + 1
        if dt > self._peak.get(name, 0.0):
            self._peak[name] = dt
        if dt >= 0.12:
            self._spike(name, dt)
        return dt

    def _spike(self, name, dt):
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write('SPIKE  %s  %.0f ms\n' % (name, dt * 1000.0))
        except Exception:
            pass

    def frame_done(self):
        if not self._enabled:
            return
        now = time.perf_counter()
        self._acc['frame'] = self._acc.get('frame', 0.0) + (now - self._frame_t0)
        self._n['frame'] = self._n.get('frame', 0) + 1
        self.frames += 1
        self._frame_t0 = now
        if now - self._last_flush >= self._flush_every:
            self.flush()

    def mark(self, name, dt):
        if not self._enabled:
            return
        self._acc[name] = self._acc.get(name, 0.0) + dt
        self._n[name] = self._n.get(name, 0) + 1
        if dt > self._peak.get(name, 0.0):
            self._peak[name] = dt

    def flush(self):
        if not self._enabled:
            return
        self._last_flush = time.perf_counter()
        names = sorted(self._acc.keys(), key=lambda k: -self._acc[k])
        frame_n = max(1, self._n.get('frame', 1))
        frame_s = self._acc.get('frame', 0.0)
        fps = frame_n / frame_s if frame_s > 1e-6 else 0.0
        lines = [
            '--- %s  frames=%d  fps=%.2f ---' % (
                time.strftime('%H:%M:%S'), frame_n, fps)
        ]
        for name in names:
            tot = self._acc[name]
            n = max(1, self._n[name])
            lines.append(
                '  %-18s  tot=%7.0fms  avg=%6.1fms  peak=%6.1fms  n=%d' % (
                    name, tot * 1000.0, (tot / n) * 1000.0,
                    self._peak.get(name, 0.0) * 1000.0, n)
            )
        text = '\n'.join(lines) + '\n'
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(text)
        except Exception:
            pass
        self._acc.clear()
        self._n.clear()
        self._peak.clear()


_PERF = None


def get_perf(world=None):
    global _PERF
    if world is not None and getattr(world, 'perf', None) is not None:
        return world.perf
    if _PERF is None:
        _PERF = PerfLog()
    return _PERF
