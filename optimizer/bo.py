"""Noisy GP-EI for per-(type, strategy) knob vectors.

Observations live on the overlay: stats.bo = {keys, X, y}.
No extra deps beyond numpy.
"""
from __future__ import annotations

import math
import random

import numpy as np

MAX_OBS = 40
N_CAND = 256
NOISE = 0.10
XI = 0.02
STEP = 0.40          # blend current → x_star
SKIP_PRIORITY = True


def _rbf(X, Z, length, signal):
    # X (n,d) Z (m,d) → (n,m)
    d2 = ((X[:, None, :] - Z[None, :, :]) / np.maximum(length, 1e-6)) ** 2
    return signal * np.exp(-0.5 * np.sum(d2, axis=-1))


def _ei(mu, sig, y_best, xi=XI):
    sig = np.maximum(sig, 1e-9)
    z = (mu - y_best - xi) / sig
    Phi = 0.5 * (1.0 + np.vectorize(math.erf)(z / math.sqrt(2.0)))
    phi = np.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    return (mu - y_best - xi) * Phi + sig * phi


def _nll(X, yc, length, signal, noise):
    n = X.shape[0]
    K = _rbf(X, X, length, signal) + (noise ** 2 + 1e-6) * np.eye(n)
    L = np.linalg.cholesky(K)
    alpha = np.linalg.solve(L.T, np.linalg.solve(L, yc))
    return 0.5 * float(yc.dot(alpha)) + float(np.sum(np.log(np.diag(L)))) + 0.5 * n * math.log(2 * math.pi)


def _fit_length(X, yc, signal, noise):
    d = X.shape[1]
    best_nll, best = 1e99, np.full(d, 0.30)
    for l0 in (0.12, 0.18, 0.28, 0.42, 0.65):
        length = np.full(d, l0)
        try:
            nll = _nll(X, yc, length, signal, noise)
        except np.linalg.LinAlgError:
            continue
        if nll < best_nll:
            best_nll, best = nll, length
    return best


def _fit_predict(X, y, Xs, noise=NOISE):
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    Xs = np.asarray(Xs, dtype=float)
    n, d = X.shape
    y_mean = float(np.mean(y))
    yc = y - y_mean
    var = float(np.var(yc))
    signal = var if var > 1e-8 else 0.25
    length = _fit_length(X, yc, signal, noise)
    K = _rbf(X, X, length, signal) + (noise ** 2 + 1e-6) * np.eye(n)
    try:
        L = np.linalg.cholesky(K)
    except np.linalg.LinAlgError:
        K = K + 1e-4 * np.eye(n)
        L = np.linalg.cholesky(K)
    alpha = np.linalg.solve(L.T, np.linalg.solve(L, yc))
    Ks = _rbf(X, Xs, length, signal)
    mu = y_mean + Ks.T.dot(alpha)
    v = np.linalg.solve(L, Ks)
    var_s = np.maximum(signal - np.sum(v * v, axis=0), 1e-9)
    return mu, np.sqrt(var_s)


def _unit(x, lo, hi):
    span = np.maximum(hi - lo, 1e-9)
    return (np.asarray(x, dtype=float) - lo) / span


def _from_unit(u, lo, hi):
    return np.asarray(lo, dtype=float) + np.asarray(u, dtype=float) * (hi - lo)


def current_vector(overlay, tunables):
    """Pack overlay weights/switch into a vector aligned with tunables keys."""
    keys = []
    lo, hi, x = [], [], []
    weights = dict((overlay or {}).get('weights') or {})
    sw = dict((overlay or {}).get('switch') or {})
    when = dict((overlay or {}).get('when') or {})
    for path, bounds in (tunables or {}).items():
        if SKIP_PRIORITY and (path == 'when.priority' or str(path).endswith('.priority')):
            continue
        if not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
            continue
        keys.append(path)
        lo.append(float(bounds[0]))
        hi.append(float(bounds[1]))
        cur = None
        if path.startswith('switch.'):
            cur = sw.get(path.split('.', 1)[1])
        elif path.startswith('when.'):
            cur = when.get(path.split('.', 1)[1])
        else:
            cur = weights.get(path)
        if cur is None:
            cur = 0.5 * (float(bounds[0]) + float(bounds[1]))
        try:
            cur = float(cur)
        except Exception:
            cur = 0.5 * (float(bounds[0]) + float(bounds[1]))
        x.append(cur)
    return keys, np.array(lo), np.array(hi), np.array(x, dtype=float)


def record(overlay, tunables, y, constraint=0.0):
    """Append one (x, y, c) observation. c=1 if last-prey blunder this match."""
    keys, lo, hi, x = current_vector(overlay, tunables)
    if not keys:
        return overlay
    st = dict((overlay or {}).get('stats') or {})
    bag = dict(st.get('bo') or {})
    if bag.get('keys') != keys:
        bag = {'keys': list(keys), 'X': [], 'y': [], 'c': []}
    Xu = _unit(x, lo, hi).tolist()
    bag.setdefault('X', []).append(Xu)
    bag.setdefault('y', []).append(float(y))
    bag.setdefault('c', []).append(float(constraint))
    if len(bag['y']) < 4:
        u = np.asarray(Xu, dtype=float)
        need = 4 - len(bag['y'])
        for _ in range(need):
            j = np.clip(u + np.random.normal(0, 0.04, size=u.shape), 0.0, 1.0)
            bag['X'].append(j.tolist())
            bag['y'].append(float(y) + float(np.random.normal(0, 0.03)))
            bag['c'].append(float(constraint))
    bag['X'] = bag['X'][-MAX_OBS:]
    bag['y'] = bag['y'][-MAX_OBS:]
    bag['c'] = (bag.get('c') or [])[-MAX_OBS:]
    st['bo'] = bag
    overlay['stats'] = st
    return overlay


def propose(overlay, tunables, y_fallback=0.0):
    """Return nudged x (dict path→value) maximising noisy EI, or None."""
    keys, lo, hi, x = current_vector(overlay, tunables)
    if not keys:
        return None
    st = dict((overlay or {}).get('stats') or {})
    bag = dict(st.get('bo') or {})
    X = list(bag.get('X') or [])
    y = list(bag.get('y') or [])
    if len(y) < 4:
        return None
    # drop rows if key set drifted
    if bag.get('keys') != keys:
        return None
    Xu = np.asarray(X, dtype=float)
    yv = np.asarray(y, dtype=float)
    # candidates in unit cube: current + jitter + uniform
    d = Xu.shape[1]
    u0 = _unit(x, lo, hi)
    cand = [u0]
    for _ in range(N_CAND // 3):
        cand.append(np.clip(u0 + np.random.normal(0, 0.08, size=d), 0.0, 1.0))
    for _ in range(N_CAND - len(cand)):
        cand.append(np.random.rand(d))
    Xs = np.asarray(cand, dtype=float)
    try:
        mu, sig = _fit_predict(Xu, yv, Xs)
    except Exception:
        return None
    y_best = float(np.max(yv))
    acq = _ei(mu, sig, y_best)
    # Expected constrained improvement: P(blunder is low) from a second GP.
    cv = np.asarray(bag.get('c') or [0.0] * len(y), dtype=float)
    if cv.shape[0] == yv.shape[0] and float(np.max(cv)) > 0:
        try:
            mu_c, sig_c = _fit_predict(Xu, cv, Xs, noise=0.12)
            zc = (0.30 - mu_c) / np.maximum(sig_c, 1e-6)
            feas = 0.5 * (1.0 + np.vectorize(math.erf)(zc / math.sqrt(2.0)))
            acq = acq * np.clip(feas, 0.05, 1.0)
        except Exception:
            pass
    star = Xs[int(np.argmax(acq))]
    x_star = _from_unit(star, lo, hi)
    x_next = x + STEP * (x_star - x)
    x_next = np.minimum(hi, np.maximum(lo, x_next))
    return {k: float(v) for k, v in zip(keys, x_next)}


def apply_vector(overlay, vec, tunables):
    """Write proposed knobs onto the overlay (weights / switch only)."""
    if not vec or not overlay:
        return overlay
    w = dict(overlay.get('weights') or {})
    sw = dict(overlay.get('switch') or {})
    for path, val in vec.items():
        if SKIP_PRIORITY and (path == 'when.priority' or str(path).endswith('.priority')):
            continue
        bounds = (tunables or {}).get(path)
        if bounds and len(bounds) >= 2:
            val = max(float(bounds[0]), min(float(bounds[1]), float(val)))
        if path.startswith('switch.'):
            key = path.split('.', 1)[1]
            if key == 'hold_frames':
                sw[key] = int(round(val))
            else:
                sw[key] = float(val)
        elif path.startswith('when.'):
            continue
        else:
            w[path] = float(val)
    overlay['weights'] = w
    overlay['switch'] = sw
    return overlay


def payoff(overlay):
    """Scalar y for the GP: Thompson mean + EMA − blunder rate."""
    st = (overlay or {}).get('stats') or {}
    a = float(st.get('alpha') or 1.0)
    b = float(st.get('beta') or 1.0)
    th = a / max(1e-6, a + b)
    ema = float(st.get('ema') or 0.0)
    games = max(1.0, float(st.get('games') or 1.0))
    bl = float(st.get('last_prey_blunder') or 0.0) / games
    # Last-prey blunders dominate: a doctrine that scrags the last meal
    # while fear lives must look bad to EI even if it "won" the match.
    return 0.50 * th + 0.30 * ema - 3.2 * bl
