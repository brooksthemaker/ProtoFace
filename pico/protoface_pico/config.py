"""Config loading for the Pico build.

The CM5 build uses YAML; CircuitPython has no PyYAML, so the device reads a
plain ``config.json`` from the CIRCUITPY filesystem. The schema is a trimmed,
single-panel subset of the CM5 ``config.yaml`` (the Pico drives one HUB75
chain as one wide canvas, so there is no multi-panel ``panels:`` list).

Missing keys fall back to the defaults in ``DEFAULTS`` so a minimal config
still boots.
"""

import json

DEFAULTS = {
    "panel": {
        # One HUB75 chain presented to displayio as a single wide canvas.
        # width = panel_width * chain_length ; height = panel_height.
        "panel_width": 64,
        "panel_height": 32,
        "chain_length": 2,      # 2x 64x32 daisy-chained -> 128x32
        "bit_depth": 4,         # Protomatter colour depth (1-6); 4 is a good start
    },
    "display": {
        "fps": 30,
        "background": [0, 0, 0],
        "brightness": 255,
    },
    "face": {
        "active": "main",
        "expression_fade": 0.3,
        "blink": {"duration": 0.15, "interval_min": 3.0, "interval_max": 7.0},
        "wiggle": {"speed": 0.3, "amplitude_x": 2.0, "amplitude_y": 1.0},
        "mirror": True,         # right half mirrors the left (matches CM5 layout)
    },
    "material": {
        "active": "teal",
    },
    "particles": {
        "active": "none",
    },
}

# Named material colours (matches the CM5 solo palette in run.py).
COLORS = {
    "teal": (0, 220, 180),
    "red": (255, 0, 0),
    "orange": (255, 110, 0),
    "yellow": (255, 230, 0),
    "green": (0, 255, 0),
    "blue": (0, 90, 255),
    "purple": (160, 0, 255),
    "magenta": (255, 0, 150),
    "white": (255, 255, 255),
}


def _merge(base, override):
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path="config.json"):
    """Load config.json merged over DEFAULTS. Returns the merged dict."""
    try:
        with open(path) as f:
            user = json.load(f)
    except (OSError, ValueError):
        user = {}
    return _merge(DEFAULTS, user)


def canvas_size(cfg):
    p = cfg["panel"]
    return p["panel_width"] * p["chain_length"], p["panel_height"]


def resolve_color(name_or_rgb):
    """Accept a named colour, an [r,g,b] list, or 'solid:r,g,b'."""
    if isinstance(name_or_rgb, (list, tuple)) and len(name_or_rgb) == 3:
        return tuple(int(c) for c in name_or_rgb)
    if isinstance(name_or_rgb, str):
        s = name_or_rgb.strip()
        if s.startswith("solid:"):
            parts = s[6:].split(",")
            if len(parts) == 3:
                return tuple(int(p) for p in parts)
        if s in COLORS:
            return COLORS[s]
    return COLORS["teal"]
