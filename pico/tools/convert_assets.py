#!/usr/bin/env python3
"""Bake CM5 face PNGs into Pico-ready 8-bit indexed BMPs.

The Pico has no Pillow, so face art is pre-converted on a desktop. Each source
PNG becomes an 8-bit indexed BMP whose pixel index encodes luminance:

    index 0       -> transparent pixel (source alpha < 128)
    index 1..15   -> dark..bright (source RGB luminance, matching the CM5 mean)

The on-device material palette (protoface_pico/material.py) then turns those
indices into a tinted, brightness-scaled colour ramp.

Usage:
    python pico/tools/convert_assets.py --src faces/main --out pico/assets/main \
        --width 64 --height 32

`--width/--height` are the *authored* face size. With the default mirror layout
the face is half the canvas (e.g. 64 of a 128-wide panel); the device mirrors it
to the right half. Run once per face folder you want on the device.

Requires Pillow (`pip install Pillow`) on the host. Not run on the Pico.
"""

import argparse
import json
import os

from PIL import Image

LEVELS = 16  # must match protoface_pico/material.py LEVELS


def _gray_palette():
    """256-entry palette: 0=black, 1..15 = gray ramp, rest black."""
    pal = []
    for i in range(256):
        if 1 <= i < LEVELS:
            v = round(i / (LEVELS - 1) * 255)
        else:
            v = 0
        pal += [v, v, v]
    return pal


def _to_indexed(img, w, h):
    """Resize *img* (nearest) and return a 'P' image of luminance indices."""
    img = img.convert("RGBA").resize((w, h), Image.NEAREST)
    px = img.load()
    out = Image.new("P", (w, h))
    out.putpalette(_gray_palette())
    op = out.load()
    span = LEVELS - 2  # indices 1..15 -> 15 levels
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 128:
                op[x, y] = 0
            else:
                lum = (r + g + b) // 3
                op[x, y] = 1 + round(lum / 255 * span)
    return out


def convert(src, out, w, h):
    os.makedirs(out, exist_ok=True)

    cfg_path = os.path.join(src, "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg = json.load(f)

    # Determine the expression list (config map, else scan PNGs).
    expr_map = dict(cfg.get("expressions", {}))
    pngs = sorted(f for f in os.listdir(src) if f.lower().endswith(".png"))
    if not expr_map:
        for p in pngs:
            stem = os.path.splitext(p)[0].lower()
            if stem not in ("blink", "mouth_open"):
                expr_map[stem] = p

    # Source authoring size, for scaling region boxes.
    draw = cfg.get("draw_size")
    if draw and len(draw) == 2 and draw[0] and draw[1]:
        src_w, src_h = draw
    elif pngs:
        with Image.open(os.path.join(src, pngs[0])) as im:
            src_w, src_h = im.size
    else:
        src_w, src_h = w, h

    out_expr = {}
    converted = 0

    def bake(filename):
        path = os.path.join(src, filename)
        if not os.path.exists(path):
            return None
        with Image.open(path) as im:
            idx = _to_indexed(im, w, h)
        bmp_name = os.path.splitext(filename)[0] + ".bmp"
        idx.save(os.path.join(out, bmp_name), "BMP")
        return bmp_name

    for name, fname in expr_map.items():
        bmp = bake(fname)
        if bmp:
            out_expr[name] = bmp
            converted += 1

    for special in (cfg.get("blink", "blink.png"), "mouth_open.png"):
        if bake(special):
            converted += 1

    # Rewrite config for the device: bmp filenames, baked draw_size, scaled boxes.
    sx = w / float(src_w)
    sy = h / float(src_h)

    def scale_box(d):
        return {
            "x": int(round(d["x"] * sx)), "y": int(round(d["y"] * sy)),
            "w": max(1, int(round(d["w"] * sx))),
            "h": max(1, int(round(d["h"] * sy))),
        }

    new_cfg = {"expressions": out_expr, "draw_size": [w, h]}
    if "blink" in cfg:
        new_cfg["blink"] = os.path.splitext(cfg["blink"])[0] + ".bmp"
    for k in ("eye_left", "eye_right", "mouth"):
        if k in cfg:
            new_cfg[k] = scale_box(cfg[k])

    with open(os.path.join(out, "config.json"), "w") as f:
        json.dump(new_cfg, f)

    print("Baked %d images -> %s (%dx%d)" % (converted, out, w, h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="source face folder (PNGs + config.json)")
    ap.add_argument("--out", required=True, help="output folder for baked BMPs")
    ap.add_argument("--width", type=int, default=64)
    ap.add_argument("--height", type=int, default=32)
    args = ap.parse_args()
    convert(args.src, args.out, args.width, args.height)


if __name__ == "__main__":
    main()
