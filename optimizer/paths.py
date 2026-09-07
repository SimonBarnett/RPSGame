"""Optimizer paths.

  optimizer/           code
  optimizer/grok/      GROK_BRIEF.json + .md only
  optimizer/metrics/   every CSV / log the optimiser reads or writes
"""
import os

try:
    from app_paths import optimizer_root, metrics_root
    ROOT = optimizer_root()
    METRICS = metrics_root()
except Exception:
    ROOT = os.path.dirname(os.path.abspath(__file__))
    METRICS = os.path.join(ROOT, 'metrics')
GROK = os.path.join(ROOT, 'grok')


def log_path(name):
    os.makedirs(METRICS, exist_ok=True)
    return os.path.join(METRICS, name)


def grok_path(name):
    os.makedirs(GROK, exist_ok=True)
    return os.path.join(GROK, name)
