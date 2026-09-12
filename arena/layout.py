"""Seeded spawn + fort layout. Same algorithm as rps_pub/rps.js.

Given (W, H, teamSize, nForts, seed) both engines emit the same
x/y/r/angle. Fort radius scales with min(W,H)/720 so mobiles stay smaller.
"""
from __future__ import annotations

import math


def _u32(x):
    return x & 0xFFFFFFFF


def _i32(x):
    x = x & 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x


def _imul(a, b):
    return _i32((int(a) * int(b)) & 0xFFFFFFFF)


def mulberry32(seed):
    """JS-identical mulberry32 (`a|0` + Math.imul). Returns rand() in [0, 1)."""
    a = _i32(int(seed) if seed is not None else 1)

    def rnd():
        nonlocal a
        a = _i32(a + 0x6D2B79F5)
        t = _imul(a ^ (_u32(a) >> 15), a | 1)
        t = _i32(t + _imul(t ^ (_u32(t) >> 7), t | 61))
        return _u32(t ^ (_u32(t) >> 14)) / 4294967296.0

    return rnd


def make_rand(rng):
    def rand(lo, hi):
        return lo + rng() * (hi - lo)
    return rand


def clamp(v, a, b):
    return max(a, min(b, v))


def world_metrics(W, H):
    W, H = float(W), float(H)
    world_k = min(W, H) / 800.0
    pad = max(16.0, 28.0 * world_k)
    body = 18.0 * world_k
    return {'W': W, 'H': H, 'worldK': world_k, 'pad': pad, 'body': body}


def place_forts(W, H, n, pad, rand):
    """Symmetric fort ring. rMul = min(W,H)/720 → smaller forts on phones."""
    forts = []
    n = max(0, int(n or 0))
    if not n:
        return forts
    W, H, pad = float(W), float(H), float(pad)
    cx, cy = W / 2.0, H / 2.0
    span = min(W, H)
    r_mul = min(W, H) / 720.0
    gap = max(16.0, span * 0.07)
    seeds = []
    tries = 0
    need = int(math.ceil(n / 4.0))
    while len(seeds) < need and tries < 250:
        tries += 1
        r = rand(22, 36) * r_mul
        dist = rand(span * 0.16, span * 0.34)
        ang = rand(0.12, math.pi / 2 - 0.12)
        x = clamp(cx + dist * math.cos(ang), pad + r + 8, W - pad - r - 8)
        y = clamp(cy + dist * math.sin(ang), pad + r + 8, H - pad - r - 8)
        if all(math.hypot(x - s['x'], y - s['y']) >= r + s['r'] + gap for s in seeds):
            seeds.append({'x': x, 'y': y, 'r': r})
    for s in seeds:
        mirrors = (
            (s['x'], s['y']),
            (2 * cx - s['x'], s['y']),
            (s['x'], 2 * cy - s['y']),
            (2 * cx - s['x'], 2 * cy - s['y']),
        )
        for x, y in mirrors:
            if any(math.hypot(x - f['x'], y - f['y']) < s['r'] * 1.4 for f in forts):
                continue
            forts.append({'x': x, 'y': y, 'r': s['r']})
            if len(forts) >= n:
                return forts
    while len(forts) < n and tries < 400:
        tries += 1
        r = rand(22, 34) * r_mul
        dist = rand(span * 0.18, span * 0.38)
        ang = rand(0, math.pi * 2)
        x = clamp(cx + dist * math.cos(ang), pad + r + 8, W - pad - r - 8)
        y = clamp(cy + dist * math.sin(ang), pad + r + 8, H - pad - r - 8)
        if any(math.hypot(x - f['x'], y - f['y']) < r + f['r'] + gap for f in forts):
            continue
        forts.append({'x': x, 'y': y, 'r': r})
    return forts


def spawn_particles(W, H, team_size, forts, pad, body, rand):
    """Interleaved ROCK/PAPER/SCISSORS. Same loop as rps.js createSim."""
    out = []
    n = max(1, int(team_size or 1))
    W, H, pad, body = float(W), float(H), float(pad), float(body)
    pid = 1
    for _ in range(n):
        for typ in ('ROCK', 'PAPER', 'SCISSORS'):
            x = y = 0.0
            ok = False
            tries = 0
            while (not ok) and tries < 50:
                tries += 1
                x = rand(pad + body * 1.2, W - pad - body * 1.2)
                y = rand(pad + body * 1.2, H - pad - body * 1.2)
                ok = all(math.hypot(x - f['x'], y - f['y']) > f['r'] + body * 1.5 for f in forts)
                ok = ok and all(math.hypot(x - q['x'], y - q['y']) > body * 2.3 for q in out)
            out.append({
                'id': pid, 'type': typ, 'x': x, 'y': y,
                'angle': rand(0, math.pi * 2),
            })
            pid += 1
    return out
