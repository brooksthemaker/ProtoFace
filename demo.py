#!/usr/bin/env python3
"""
Protoface panel demo.

Shows the word "Demo" on each panel and lets you cycle through colours and
particle effects from the keyboard. Drives the panels through the same Piomatter
output as the main app (it always targets the HUB75 panels, ignoring
display.preview).

    python demo.py

Keys (terminal must be focused; works over SSH):
    c / v    next / previous colour
    x / z    next / previous effect
    q / Esc  quit
"""

import sys
import time

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

from protoface.output.hub75 import HUB75Output
from protoface.renderer import Renderer
from protoface.particles import ParticleSystem
from protoface.keyboard import KeyReader
from protoface.instance_lock import acquire_instance_lock

# ── Cyclable colours and effects ──────────────────────────────────────────────

COLORS = [
    ("red",     (255,   0,   0)),
    ("orange",  (255, 110,   0)),
    ("yellow",  (255, 230,   0)),
    ("green",   (  0, 255,   0)),
    ("teal",    (  0, 220, 180)),
    ("blue",    (  0,  90, 255)),
    ("purple",  (160,   0, 255)),
    ("magenta", (255,   0, 150)),
    ("white",   (255, 255, 255)),
]

EFFECTS = ["none", "sparkle", "embers", "confetti", "rain", "snow", "rings", "fireflies", "clouds"]

TEXT = "Demo"


def load_panel_geometry(path="config.yaml"):
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    p = cfg.get("panel", {})
    pw = p.get("panel_width",  p.get("width", 64))
    ph = p.get("panel_height", p.get("height", 32))
    chain = p.get("chain_length", 2)
    parallel = p.get("parallel", 1)
    return cfg, pw, ph, chain, parallel


def make_panel_text_mask(text, pw, ph):
    """Return a (ph, pw) uint8 luminance mask of *text* centred on one panel."""
    img = Image.new("L", (pw, ph), 0)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    d.text(((pw - tw) // 2 - l, (ph - th) // 2 - t), text, fill=255, font=font)
    return np.array(img, dtype=np.uint8)


def build_text_layer(mask, color, canvas_w, canvas_h, pw, ph, chain, parallel):
    """Tile the per-panel text mask across the canvas, tinted *color*. (H,W,4)."""
    rgba = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    for row in range(parallel):
        for col in range(chain):
            x, y = col * pw, row * ph
            rgba[y:y+ph, x:x+pw, 0] = color[0]
            rgba[y:y+ph, x:x+pw, 1] = color[1]
            rgba[y:y+ph, x:x+pw, 2] = color[2]
            rgba[y:y+ph, x:x+pw, 3] = mask
    return rgba


def apply_effect(ps, effect, color):
    if effect == "none":
        ps.set_effect("none")
    else:
        ps.set_effect({"effect": effect, "colors": [list(color)]})


def status(color_i, effect_i):
    cname = COLORS[color_i][0]
    ename = EFFECTS[effect_i]
    sys.stdout.write(
        f"\r  colour: {cname:<8} effect: {ename:<10}  "
        f"(c/v colour, x/z effect, q quit)   "
    )
    sys.stdout.flush()


def main():
    # Same /tmp/protoface.lock guard as run.py — the demo drives the same
    # /dev/pio0, so it must not run alongside a live Protoface instance.
    _instance_lock = acquire_instance_lock()

    cfg, pw, ph, chain, parallel = load_panel_geometry()
    canvas_w, canvas_h = pw * chain, ph * parallel

    out = HUB75Output(cfg)
    if not out.available:
        print("[demo] HUB75/Piomatter not available — is this the CM5 with /dev/pio0? "
              "Running anyway; nothing will display.")

    renderer = Renderer(canvas_w, canvas_h)
    ps = ParticleSystem(canvas_w, canvas_h, {"active": "none"})
    mask = make_panel_text_mask(TEXT, pw, ph)

    color_i = effect_i = 0
    apply_effect(ps, EFFECTS[effect_i], COLORS[color_i][1])

    print(f"Protoface demo — '{TEXT}' on each panel. c/v colour, x/z effect, q quit.")
    status(color_i, effect_i)

    target_dt = 1.0 / 30.0
    prev = time.monotonic()
    running = True
    try:
        with KeyReader() as keys:
            while running:
                now = time.monotonic()
                dt = min(now - prev, 0.1)
                prev = now

                k = keys.get()
                if k:
                    if k == "q":   # not ESC: arrow/function keys send ESC sequences
                        running = False
                    elif k in ("c", "v"):
                        color_i = (color_i + (1 if k == "c" else -1)) % len(COLORS)
                        apply_effect(ps, EFFECTS[effect_i], COLORS[color_i][1])
                        status(color_i, effect_i)
                    elif k in ("x", "z"):
                        effect_i = (effect_i + (1 if k == "x" else -1)) % len(EFFECTS)
                        apply_effect(ps, EFFECTS[effect_i], COLORS[color_i][1])
                        status(color_i, effect_i)

                ps.update(dt)
                base = renderer.solid_layer((0, 0, 0))
                text_layer = build_text_layer(mask, COLORS[color_i][1],
                                              canvas_w, canvas_h, pw, ph, chain, parallel)
                parts = ps.render()
                layers = [text_layer]
                if parts is not None:
                    layers.append(parts)
                frame = renderer.composite(base, layers)
                out.show(frame)

                sleep = target_dt - (time.monotonic() - now)
                if sleep > 0:
                    time.sleep(sleep)
    except KeyboardInterrupt:
        pass
    finally:
        out.close()
        print("\nDemo stopped.")


if __name__ == "__main__":
    main()
