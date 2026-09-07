"""Depth-2 UCT over strategy cards. Rollout = overlay win rate, not a match.

Call pick() from playbook.sample_arm when CONTESTED and n>=20.
Banned cards must already be stripped from `legal`.
"""
from __future__ import annotations

import json
import math
import os
import random

from optimizer.paths import METRICS

VIS_PATH = os.path.join(METRICS, "mcts_visits.json")
C_UCT = 0.85
_VISITS = {}  # type -> sid -> n


def _load_vis():
    global _VISITS
    if _VISITS:
        return
    try:
        with open(VIS_PATH, "r", encoding="utf-8") as f:
            _VISITS = json.load(f) or {}
    except Exception:
        _VISITS = {}


def _save_vis():
    try:
        os.makedirs(METRICS, exist_ok=True)
        tmp = VIS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_VISITS, f)
        os.replace(tmp, VIS_PATH)
    except Exception:
        pass


def _mean(type_name, sid, state=None, opponent=None):
    """Empirical win rate from overlay stats."""
    try:
        from strategies.playbook import TEAM_OVERLAYS
        st = ((TEAM_OVERLAYS.get(type_name) or {}).get(sid) or {}).get("stats") or {}
    except Exception:
        st = {}
    slot = {}
    if opponent:
        slot = ((st.get("by_vs") or {}).get(opponent) or {})
    if not slot and state:
        slot = ((st.get("by_state") or {}).get(state) or {})
    g = float(slot.get("n", st.get("games", 0)) or 0)
    w = float(slot.get("wins", st.get("wins", 0)) or 0)
    if g <= 0:
        return 0.33, 0.0
    return max(0.02, min(0.98, w / g)), g


def _uct(mean, n, N, c=C_UCT):
    if n <= 0:
        return 1.0
    return mean + c * math.sqrt(math.log(max(N, 2)) / n)


def pick(type_name, legal, state=None, opponent=None, n_sims=24):
    """Return a legal sid via depth-2 UCT. Safe fallback: first legal."""
    legal = [s for s in (legal or []) if s]
    if not legal:
        return None
    if len(legal) == 1:
        return legal[0]
    _load_vis()
    bag = _VISITS.setdefault(str(type_name), {})
    # root stats
    stats = {}
    N = 0.0
    for sid in legal:
        mean, g = _mean(type_name, sid, state, opponent)
        n = float(bag.get(sid, 0)) + g
        stats[sid] = [mean, n]
        N += n
    # extra UCT sims (cheap — no pygame)
    for _ in range(max(8, int(n_sims))):
        # ply 1: this type's card
        scores = {s: _uct(stats[s][0], stats[s][1], max(N, 1.0)) for s in legal}
        a = max(scores, key=scores.get)
        # ply 2: opponent reply from same legal shape (best vs us)
        opp = opponent or None
        reply_mean = 0.33
        if opp:
            # opponent success ≈ 1 - our mean against them on this card
            reply_mean = 1.0 - stats[a][0]
        # backup: our mean minus a slice of opponent strength
        x = 0.72 * stats[a][0] + 0.28 * (1.0 - reply_mean)
        x += random.uniform(-0.03, 0.03)
        x = max(0.02, min(0.98, x))
        n = stats[a][1]
        stats[a][0] = (stats[a][0] * n + x) / (n + 1.0)
        stats[a][1] = n + 1.0
        N += 1.0
        bag[a] = bag.get(a, 0) + 1
    _save_vis()
    # exploit: most visits at root, tie-break on mean
    best = max(legal, key=lambda s: (stats[s][1], stats[s][0]))
    return best
