"""Bump rps_pub/build.json and stamp rps.js / sw.js / index.html.

Run before a git push so Amplify deploys a new BUILD number.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PUB = os.path.join(ROOT, "rps_pub")
BUILD_JSON = os.path.join(PUB, "build.json")
RPS_JS = os.path.join(PUB, "rps.js")
SW_JS = os.path.join(PUB, "sw.js")
INDEX = os.path.join(PUB, "index.html")
EMBED = os.path.join(PUB, "embed.html")
GAMES_FILE = os.path.join(ROOT, "optimizer", "metrics", "games_total.txt")
OPT_LOG = os.path.join(ROOT, "optimizer", "metrics", "metrics_optimize.log")


def _read_games():
    try:
        return int(open(GAMES_FILE, encoding="utf-8").read().strip() or 0)
    except Exception:
        return 0


def _read_gen():
    gen = 0
    try:
        for ln in open(OPT_LOG, encoding="utf-8", errors="replace"):
            m = re.search(r"\bgen=(\d+)", ln)
            if m:
                gen = int(m.group(1))
    except Exception:
        pass
    return gen


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip() or "local"
    except Exception:
        return "local"


def _load_build():
    bag = {"build": 0, "gen": 0, "games": 0, "at": "", "sha": ""}
    try:
        bag.update(json.load(open(BUILD_JSON, encoding="utf-8")))
    except Exception:
        pass
    return bag


def stamp(js_path, build):
    src = open(js_path, encoding="utf-8").read()
    blob = (
        "  const BUILD = { n: %d, gen: %d, games: %d, at: %s, sha: %s };\n"
        % (
            int(build["build"]),
            int(build["gen"]),
            int(build["games"]),
            json.dumps(str(build.get("at") or "")),
            json.dumps(str(build.get("sha") or "")),
        )
    )
    if re.search(r"const BUILD = \{[^}]*\};", src):
        src = re.sub(r"  const BUILD = \{[^}]*\};\n", blob, src, count=1)
    else:
        src = src.replace(
            "  'use strict';\n",
            "  'use strict';\n" + blob,
            1,
        )
    open(js_path, "w", encoding="utf-8", newline="\n").write(src)


def stamp_sw(build_n):
    src = open(SW_JS, encoding="utf-8").read()
    src = re.sub(
        r'const CACHE = "rps-v[^"]*";',
        'const CACHE = "rps-v%d";' % int(build_n),
        src,
        count=1,
    )
    open(SW_JS, "w", encoding="utf-8", newline="\n").write(src)


def stamp_html(path, build_n):
    if not os.path.isfile(path):
        return
    src = open(path, encoding="utf-8").read()
    src = re.sub(
        r'src="\./rps\.js(?:\?v=\d+)?"',
        'src="./rps.js?v=%d"' % int(build_n),
        src,
    )
    open(path, "w", encoding="utf-8", newline="\n").write(src)


def main():
    bag = _load_build()
    bag["build"] = int(bag.get("build") or 0) + 1
    bag["gen"] = _read_gen()
    bag["games"] = _read_games()
    bag["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    bag["sha"] = _git_sha()
    os.makedirs(PUB, exist_ok=True)
    json.dump(bag, open(BUILD_JSON, "w", encoding="utf-8"), indent=2)
    open(BUILD_JSON, "a", encoding="utf-8").write("\n")
    stamp(RPS_JS, bag)
    stamp_sw(bag["build"])
    stamp_html(INDEX, bag["build"])
    stamp_html(EMBED, bag["build"])
    print("BUILD %(build)s  GEN %(gen)s  GAMES %(games)s  %(at)s  %(sha)s" % bag)


if __name__ == "__main__":
    main()
