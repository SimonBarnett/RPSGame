"""Constrained motion balancer.

Nudge speed_base / turn_base toward 33% win share while KEEPING identity:

    speed:  ROCK < SCISSORS < PAPER
    turn:   PAPER < SCISSORS < ROCK

The live sim reads TYPE_DEFAULTS (overlay base last-writer), NOT TYPE_IDENTITY
alone. This module writes identity + TYPE_DEFAULTS + every overlay base.

Called from engine.optimise() each learn pass.
"""
from __future__ import annotations

import csv
import json
import os
import re

from optimizer.paths import METRICS

GAMES = os.path.join(METRICS, "metrics_games.csv")
STATE = os.path.join(METRICS, "motion_identity.json")

WINDOW = 40
MIN_N = 12
COOLDOWN_GAMES = 8
SPEED_STEP = 0.020
TURN_STEP = 0.12
SPEED_BOUNDS = {"ROCK": (1.08, 1.40), "SCISSORS": (1.22, 1.55), "PAPER": (1.48, 1.88)}
TURN_BOUNDS = {"PAPER": (11.2, 13.0), "SCISSORS": (12.2, 14.0), "ROCK": (13.4, 16.0)}
MIN_SPEED_GAP = 0.08
MIN_TURN_GAP = 0.35
TARGET = 1.0 / 3.0


def _shares(path=GAMES, window=WINDOW):
    if not os.path.isfile(path):
        return {}, 0
    try:
        rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    except Exception:
        return {}, 0
    rows = [r for r in rows[-window:] if (r.get("winner") or "") in ("ROCK", "PAPER", "SCISSORS")]
    n = len(rows)
    if n < MIN_N:
        return {}, n
    c = {"ROCK": 0, "PAPER": 0, "SCISSORS": 0}
    for r in rows:
        c[r["winner"]] += 1
    return {k: c[k] / n for k in c}, n


def _read_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def _read_identity():
    st = _read_state()
    ident = (st or {}).get("identity")
    if isinstance(ident, dict) and "ROCK" in ident:
        out = {}
        for name in ("ROCK", "PAPER", "SCISSORS"):
            d = ident.get(name) or {}
            out[name] = {
                "speed_base": float(d.get("speed_base", 1.18)),
                "turn_base": float(d.get("turn_base", 14.3)),
            }
        return out
    try:
        from config import TYPE_IDENTITY
        out = {}
        for name, d in TYPE_IDENTITY.items():
            out[name] = {
                "speed_base": float(d["speed_base"]),
                "turn_base": float(d["turn_base"]),
            }
        return out
    except Exception:
        return {
            "ROCK": {"speed_base": 1.18, "turn_base": 14.3},
            "PAPER": {"speed_base": 1.72, "turn_base": 12.3},
            "SCISSORS": {"speed_base": 1.34, "turn_base": 12.9},
        }


def _clamp_triangle(ident):
    for name in ident:
        lo, hi = SPEED_BOUNDS[name]
        ident[name]["speed_base"] = max(lo, min(hi, float(ident[name]["speed_base"])))
        lo, hi = TURN_BOUNDS[name]
        ident[name]["turn_base"] = max(lo, min(hi, float(ident[name]["turn_base"])))
    if ident["SCISSORS"]["speed_base"] < ident["ROCK"]["speed_base"] + MIN_SPEED_GAP:
        ident["SCISSORS"]["speed_base"] = ident["ROCK"]["speed_base"] + MIN_SPEED_GAP
    if ident["PAPER"]["speed_base"] < ident["SCISSORS"]["speed_base"] + MIN_SPEED_GAP:
        ident["PAPER"]["speed_base"] = ident["SCISSORS"]["speed_base"] + MIN_SPEED_GAP
    if ident["SCISSORS"]["turn_base"] < ident["PAPER"]["turn_base"] + MIN_TURN_GAP:
        ident["SCISSORS"]["turn_base"] = ident["PAPER"]["turn_base"] + MIN_TURN_GAP
    if ident["ROCK"]["turn_base"] < ident["SCISSORS"]["turn_base"] + MIN_TURN_GAP:
        ident["ROCK"]["turn_base"] = ident["SCISSORS"]["turn_base"] + MIN_TURN_GAP
    for name in ident:
        lo, hi = SPEED_BOUNDS[name]
        ident[name]["speed_base"] = round(max(lo, min(hi, ident[name]["speed_base"])), 4)
        lo, hi = TURN_BOUNDS[name]
        ident[name]["turn_base"] = round(max(lo, min(hi, ident[name]["turn_base"])), 4)
    return ident


def _nudge(ident, shares):
    """Trailing type gets a motion buff on BOTH axes that help its matchups.

    Paper behind: +speed (kite Rock) AND +turn (don't get chord-cut by Scissors).
    Rock behind: +turn (pin Scissors) AND +speed (less kited by Paper).
    Ahead: the reverse. Triangle clamp keeps identity order.
    """
    changes = []
    for name, sh in shares.items():
        err = sh - TARGET
        if abs(err) < 0.04:
            continue
        mag = min(2.0, abs(err) / 0.08)
        if err < 0:
            ds, dt = SPEED_STEP * mag, TURN_STEP * mag
        else:
            ds, dt = -SPEED_STEP * mag, -TURN_STEP * mag
        if name == "SCISSORS":
            ds *= 0.6
            dt *= 0.6
        before = (ident[name]["speed_base"], ident[name]["turn_base"])
        ident[name]["speed_base"] += ds
        ident[name]["turn_base"] += dt
        ident = _clamp_triangle(ident)
        after = (ident[name]["speed_base"], ident[name]["turn_base"])
        if after != before:
            changes.append(
                f"{name}.speed_base: {before[0]:.3f} -> {after[0]:.3f}  "
                f"(motion-balance share={sh:.3f})"
            )
            changes.append(
                f"{name}.turn_base: {before[1]:.2f} -> {after[1]:.2f}  "
                f"(motion-balance share={sh:.3f})"
            )
    return ident, changes


def _write_config(ident):
    here = os.path.abspath(os.path.dirname(__file__))
    cfg_path = None
    for _ in range(4):
        cand = os.path.join(here, "config.py")
        if os.path.isfile(cand):
            cfg_path = cand
            break
        here = os.path.dirname(here)
    if not cfg_path:
        return False
    try:
        text = open(cfg_path, encoding="utf-8").read()
    except Exception:
        return False
    for name, d in ident.items():
        block = rf'("{name}"\s*:\s*\{{[\s\S]*?"speed_base"\s*:\s*)([0-9.]+)'
        text2, n = re.subn(block, rf'\g<1>{d["speed_base"]:.4f}', text, count=1)
        if n:
            text = text2
        block = rf'("{name}"\s*:\s*\{{[\s\S]*?"turn_base"\s*:\s*)([0-9.]+)'
        text2, n = re.subn(block, rf'\g<1>{d["turn_base"]:.4f}', text, count=1)
        if n:
            text = text2
    try:
        tmp = cfg_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, cfg_path)
        return True
    except Exception:
        return False


def _sync_runtime(ident):
    """Push identity into every live structure the sim actually reads."""
    try:
        import config
        for name, d in ident.items():
            if name in getattr(config, "TYPE_IDENTITY", {}):
                config.TYPE_IDENTITY[name]["speed_base"] = d["speed_base"]
                config.TYPE_IDENTITY[name]["turn_base"] = d["turn_base"]
            if name in getattr(config, "TYPE_DEFAULTS", {}):
                config.TYPE_DEFAULTS[name]["speed_base"] = d["speed_base"]
                config.TYPE_DEFAULTS[name]["turn_base"] = d["turn_base"]
            if name in getattr(config, "TYPE_MOTION", {}):
                config.TYPE_MOTION[name]["speed_base"] = d["speed_base"]
                config.TYPE_MOTION[name]["turn_base"] = d["turn_base"]
    except Exception:
        pass
    try:
        import strategies.playbook as playbook
        bag = getattr(playbook, "TEAM_OVERLAYS", {}) or {}
        for name, d in ident.items():
            for sid, ov in (bag.get(name) or {}).items():
                if not isinstance(ov, dict):
                    continue
                base = dict(ov.get("base") or {})
                sp, tu = d["speed_base"], d["turn_base"]
                try:
                    same = (abs(float(base.get("speed_base") or 0) - float(sp)) < 1e-9
                            and abs(float(base.get("turn_base") or 0) - float(tu)) < 1e-9)
                except Exception:
                    same = False
                if same:
                    continue
                base["speed_base"] = sp
                base["turn_base"] = tu
                ov["base"] = base
                bag[name][sid] = ov
                try:
                    playbook._DIRTY_OVERLAYS.add((name, sid))
                except Exception:
                    pass
    except Exception:
        pass


def _seed_overlay_files(ident):
    """Rewrite types/{T}/*.json base.speed/turn so next import matches identity."""
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies", "types"))
    if not os.path.isdir(here):
        return 0
    n = 0
    for name, d in ident.items():
        tdir = os.path.join(here, name)
        if not os.path.isdir(tdir):
            continue
        for fn in os.listdir(tdir):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            path = os.path.join(tdir, fn)
            try:
                ov = json.load(open(path, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(ov, dict):
                continue
            base = dict(ov.get("base") or {})
            if base.get("speed_base") == d["speed_base"] and base.get("turn_base") == d["turn_base"]:
                continue
            base["speed_base"] = d["speed_base"]
            base["turn_base"] = d["turn_base"]
            ov["base"] = base
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(ov, f, separators=(",", ":"), ensure_ascii=False)
            os.replace(tmp, path)
            n += 1
    return n


def apply(log=None, games_seen=0):
    """One constrained motion step. Returns list of change strings."""
    shares, n = _shares()
    if n < MIN_N:
        return []
    prev = _read_state()
    prev_gs = int(prev.get("games_seen") or 0)
    if games_seen and prev_gs and (int(games_seen) - prev_gs) < COOLDOWN_GAMES:
        return []
    ident = _clamp_triangle(_read_identity())
    ident, changes = _nudge(ident, shares)
    if not changes:
        # still sync overlays so identity is what the sim runs
        _sync_runtime(ident)
        return []
    _write_config(ident)
    _sync_runtime(ident)
    seeded = _seed_overlay_files(ident)
    try:
        os.makedirs(METRICS, exist_ok=True)
        rec = {
            "shares": shares,
            "n": n,
            "games_seen": int(games_seen or prev_gs or n),
            "identity": ident,
            "changes": changes,
            "overlays_seeded": seeded,
        }
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2)
    except Exception:
        pass
    if log:
        try:
            log("motion-balance n=%d seeded=%d %s" % (n, seeded, "; ".join(changes[:4])))
        except Exception:
            pass
    return changes
