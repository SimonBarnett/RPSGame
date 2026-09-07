"""Load evolving meta (banned/force/motion) — compiled code has no card lists."""
from __future__ import annotations
import json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
_CACHE = None


def load(force=False):
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    path = os.path.join(ROOT, "meta.json")
    try:
        with open(path, encoding="utf-8") as f:
            _CACHE = json.load(f)
    except Exception:
        _CACHE = {}
    return _CACHE


def banned(type_name):
    return frozenset((load().get("banned") or {}).get(str(type_name or "").upper(), ()) or ())


def force(type_name, state):
    bag = ((load().get("force") or {}).get(str(type_name or "").upper()) or {})
    return tuple(bag.get(str(state or ""), ()) or ())


def motion():
    return load().get("motion") or {}


def last_prey_max():
    try:
        return int(load().get("last_prey_risk_max", 2))
    except Exception:
        return 2


def evolve():
    return load().get("evolve") or {}
