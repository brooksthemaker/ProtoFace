"""
Runtime state persistence.

config.yaml is the hand-authored base (with comments) and is NEVER written by
the program. Runtime changes that ProtoHUD asks to keep (save_config) are stored
in a separate machine-managed `state.yaml`, which run.py loads *after* config.yaml
and applies on top. This keeps the commented config pristine while still letting
the look (brightness / material / particles) persist across restarts.
"""

from __future__ import annotations

import os
import tempfile
import threading

try:
    import yaml
    _YAML = True
except ImportError:
    _YAML = False


class LiveSettings:
    """Thread-safe holder for the persistable 'look': brightness, material, particles.

    Updated wherever the look changes (IPC handlers + solo keys) and dumped by
    save_config. It mirrors what is applied to the panels so it can be saved
    without reverse-engineering the live render objects.
    """

    def __init__(self, brightness: int = 255, material='teal', particles=None):
        self._lock = threading.Lock()
        self.brightness = int(brightness)
        self.material = material
        self.particles = particles if particles is not None else {'active': 'none'}

    def update(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'brightness': self.brightness,
                'material':   self.material,
                'particles':  self.particles,
            }


def load_state(path: str) -> dict:
    """Load the runtime state overlay; returns {} if missing/unavailable."""
    if not _YAML or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f'[state] could not load {path}: {e}')
        return {}


def save_state(path: str, data: dict) -> bool:
    """Atomically write the runtime state overlay. Returns True on success."""
    if not _YAML:
        print('[state] PyYAML not available — cannot save')
        return False
    try:
        directory = os.path.dirname(path) or '.'
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix='.tmp')
        with os.fdopen(fd, 'w') as f:
            f.write('# Auto-saved by ProtoHUD (save_config). Overlays config.yaml on load.\n')
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp, path)   # atomic on POSIX
        print(f'[state] saved {path}')
        return True
    except Exception as e:
        print(f'[state] could not save {path}: {e}')
        return False
