"""Project root for source and frozen (PyInstaller) runs.

Evolving data (strategies/, optimizer/metrics/, arena assets) lives next to
the exe when frozen so the optimiser can keep writing JSON.
"""
from __future__ import annotations

import os
import sys


def project_root():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def arena_root():
    return os.path.join(project_root(), "arena")


def strategies_root():
    return os.path.join(project_root(), "strategies")


def optimizer_root():
    return os.path.join(project_root(), "optimizer")


def metrics_root():
    return os.path.join(optimizer_root(), "metrics")


def bundle_root():
    """Read-only files PyInstaller unpacked (sys._MEIPASS)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", project_root())
    return project_root()


def _copy_tree(src, dst):
    import shutil
    if not os.path.isdir(src):
        return 0
    n = 0
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for fn in files:
            if fn.endswith(".pyc") or fn == "Thumbs.db":
                continue
            s = os.path.join(root, fn)
            d = os.path.join(target, fn)
            if not os.path.exists(d):
                shutil.copy2(s, d)
                n += 1
    return n


def bootstrap():
    """If the exe was started in an empty folder, seed writable data from the bundle."""
    dest = project_root()
    src = bundle_root()
    created = []
    for sub in ("strategies", "arena", "maths"):
        need = os.path.join(dest, sub)
        have = os.path.join(src, sub)
        marker = os.path.join(need, "templates") if sub == "strategies" else need
        if sub == "arena":
            marker = os.path.join(need, "images")
        if not os.path.isdir(marker) and os.path.isdir(have):
            n = _copy_tree(have, need)
            created.append("%s (%d files)" % (sub, n))
        else:
            os.makedirs(need, exist_ok=True)
    os.makedirs(os.path.join(dest, "strategies", "templates"), exist_ok=True)
    os.makedirs(os.path.join(dest, "strategies", "types", "ROCK"), exist_ok=True)
    os.makedirs(os.path.join(dest, "strategies", "types", "PAPER"), exist_ok=True)
    os.makedirs(os.path.join(dest, "strategies", "types", "SCISSORS"), exist_ok=True)
    os.makedirs(os.path.join(dest, "optimizer", "metrics"), exist_ok=True)
    os.makedirs(os.path.join(dest, "optimizer", "grok"), exist_ok=True)
    os.makedirs(os.path.join(dest, "arena", "images"), exist_ok=True)
    os.makedirs(os.path.join(dest, "arena", "sound"), exist_ok=True)
    # copy optimizer json defaults that are not code
    opt_src = os.path.join(src, "optimizer")
    opt_dst = os.path.join(dest, "optimizer")
    if os.path.isdir(opt_src):
        for fn in os.listdir(opt_src):
            if fn.endswith(".json") or fn.endswith(".md"):
                s = os.path.join(opt_src, fn)
                d = os.path.join(opt_dst, fn)
                if os.path.isfile(s) and not os.path.exists(d):
                    import shutil
                    shutil.copy2(s, d)
                    created.append("optimizer/" + fn)
    # seed markdown docs next to the exe
    import shutil
    md_copied = 0
    for root, dirs, files in os.walk(src):
        for fn in files:
            if not fn.lower().endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(root, fn), src)
            if rel.startswith(".."):
                continue
            d = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if not os.path.exists(d):
                shutil.copy2(os.path.join(root, fn), d)
                md_copied += 1
    if md_copied:
        created.append("docs (%d md)" % md_copied)
    return created
