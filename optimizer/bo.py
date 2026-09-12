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
STEP = 0.18          # small blend; one heavy gen must not rewrite the card
MIN_OBS = 3
SKIP_PRIORITY = True
SKIP_SWITCH = True   # hold_frames / margin are select policy, not combat knobs
SKIP_MOVEMENT = True  # movement[] blends are structure, not EI knobs
LAST_MIGRATE = 0
LAST_SKIP = None


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
        if SKIP_SWITCH and path.startswith('switch.'):
            continue
        if SKIP_MOVEMENT and str(path).startswith('movement['):
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


def _project_bag(bag, keys):
    """Keep aligned columns when the tunable key set drifts (e.g. SKIP_SWITCH)."""
    global LAST_MIGRATE
    old = list((bag or {}).get('keys') or [])
    keys = list(keys)
    if old == keys:
        return bag or {'keys': keys, 'X': [], 'y': [], 'c': []}, False
    if not old:
        return {'keys': keys, 'X': [], 'y': [], 'c': []}, False
    idx = [old.index(k) if k in old else None for k in keys]
    Xn, yn, cn = [], [], []
    X = list((bag or {}).get('X') or [])
    y = list((bag or {}).get('y') or [])
    c = list((bag or {}).get('c') or [])
    for i, row in enumerate(X):
        if not isinstance(row, (list, tuple)) or len(row) != len(old):
            continue
        newrow = []
        kept = 0
        for j in idx:
            if j is None:
                newrow.append(0.5)
            else:
                try:
                    v = float(row[j])
                except Exception:
                    v = 0.5
                newrow.append(max(0.0, min(1.0, v)))
                kept += 1
        if kept <= 0:
            continue
        Xn.append(newrow)
        yn.append(float(y[i]) if i < len(y) else 0.0)
        cn.append(float(c[i]) if i < len(c) else 0.0)
    LAST_MIGRATE += 1
    return {
        'keys': keys,
        'X': Xn[-MAX_OBS:],
        'y': yn[-MAX_OBS:],
        'c': cn[-MAX_OBS:],
    }, True


def record(overlay, tunables, y, constraint=0.0):
    """Append one (x, y, c) observation. c=1 if last-prey blunder this match."""
    keys, lo, hi, x = current_vector(overlay, tunables)
    if not keys:
        return overlay
    st = dict((overlay or {}).get('stats') or {})
    bag = dict(st.get('bo') or {})
    bag, _migrated = _project_bag(bag, keys)
    Xu = _unit(x, lo, hi).tolist()
    bag.setdefault('X', []).append(Xu)
    bag.setdefault('y', []).append(float(y))
    bag.setdefault('c', []).append(float(constraint))
    bag['X'] = bag['X'][-MAX_OBS:]
    bag['y'] = bag['y'][-MAX_OBS:]
    bag['c'] = (bag.get('c') or [])[-MAX_OBS:]
    st['bo'] = bag
    overlay['stats'] = st
    return overlay


def propose(overlay, tunables, y_fallback=0.0):
    """Return nudged x (dict path→value) maximising noisy EI, or None."""
    global LAST_SKIP
    LAST_SKIP = None
    keys, lo, hi, x = current_vector(overlay, tunables)
    if not keys:
        LAST_SKIP = 'no_keys'
        return None
    st = dict((overlay or {}).get('stats') or {})
    bag = dict(st.get('bo') or {})
    bag, _ = _project_bag(bag, keys)
    X = list(bag.get('X') or [])
    y = list(bag.get('y') or [])
    if len(y) < MIN_OBS:
        LAST_SKIP = 'n=%d' % len(y)
        return None
    if bag.get('keys') != keys:
        LAST_SKIP = 'key_mismatch'
        return None
    Xu = np.asarray(X, dtype=float)
    yv = np.asarray(y, dtype=float)
    if Xu.ndim != 2 or Xu.shape[0] != yv.shape[0] or Xu.shape[1] != len(keys):
        return None

    def _toward(x_star):
        x_next = x + STEP * (np.asarray(x_star, dtype=float) - x)
        x_next = np.minimum(hi, np.maximum(lo, x_next))
        return {k: float(v) for k, v in zip(keys, x_next)}

    # Too few points for a stable GP: step toward the best observed x.
    if len(y) < 6:
        star = Xu[int(np.argmax(yv))]
        return _toward(_from_unit(star, lo, hi))

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
        star = Xu[int(np.argmax(yv))]
        return _toward(_from_unit(star, lo, hi))
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
        if SKIP_SWITCH and path.startswith('switch.'):
            continue
        if SKIP_MOVEMENT and str(path).startswith('movement['):
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


def payoff(overlay, type_name=None, sid=None):
    """Same hill as the playbook writer: bounded decision score − blunder rate."""
    st = (overlay or {}).get('stats') or {}
    games = max(1.0, float(st.get('games') or 1.0))
    bl = min(1.0, float(st.get('last_prey_blunder') or 0.0) / games)
    t = type_name or (overlay or {}).get('type')
    s = sid or (overlay or {}).get('id')
    if t and s:
        try:
            from strategies.playbook import strategy_decision_score
            return float(strategy_decision_score(t, s)) - 0.40 * bl
        except Exception:
            pass
    a = float(st.get('alpha') or 1.0)
    b = float(st.get('beta') or 1.0)
    th = a / max(1e-6, a + b)
    ema = float(st.get('ema') or 0.0)
    return 0.50 * th + 0.30 * ema - 3.2 * bl
