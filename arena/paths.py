"""Asset locations under arena/."""
import os

try:
    from app_paths import arena_root
    ROOT = arena_root()
except Exception:
    ROOT = os.path.dirname(os.path.abspath(__file__))
SOUND_DIR = os.path.join(ROOT, 'sound')
IMAGE_DIR = os.path.join(ROOT, 'images')


def sound_path(name):
    path = os.path.join(SOUND_DIR, name)
    if os.path.exists(path):
        return path
    # case-insensitive fallback
    want = name.lower()
    try:
        for fn in os.listdir(SOUND_DIR):
            if fn.lower() == want:
                return os.path.join(SOUND_DIR, fn)
    except Exception:
        pass
    return path


def image_path(name):
    path = os.path.join(IMAGE_DIR, name)
    if os.path.exists(path):
        return path
    want = name.lower()
    try:
        for fn in os.listdir(IMAGE_DIR):
            if fn.lower() == want:
                return os.path.join(IMAGE_DIR, fn)
    except Exception:
        pass
    return path


def first_sound(*names):
    for name in names:
        path = sound_path(name)
        if os.path.exists(path):
            return path
    return None
