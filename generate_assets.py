"""
Protoface — run once to generate the example face PNGs and sample material textures.

    pip install Pillow
    python generate_assets.py

Generates assets for:
  - faces/example_fox/   (original single-panel 64×32 fox face)
  - faces/left_eye/      (64×32 eye panel — left side)
  - faces/right_eye/     (64×32 eye panel — right side, mirrored)
  - faces/left_mouth/    (64×32 mouth panel — left side)
  - faces/right_mouth/   (64×32 mouth panel — right side, mirrored)
  - materials/           (teal, rainbow, warm, cool tiles)

Replace the generated PNGs with real artwork to customise the face.
White pixels = visible face shape (tinted by material); transparent = hidden.
"""

import colorsys
import os

from PIL import Image, ImageDraw

W, H = 64, 32


def blank() -> Image.Image:
    return Image.new('RGBA', (W, H), (0, 0, 0, 0))


WHITE = (255, 255, 255, 255)

# ── example_fox (original full-face panel) ────────────────────────────────────

def draw_fox(angry=False, sad=False, surprised=False,
             blink=False, mouth_open=False) -> Image.Image:
    img = blank()
    d   = ImageDraw.Draw(img)

    el_x, ey = 14, 10
    er_x     = 42
    ew       = 12
    eh = 1 if blink else (9 if surprised else (4 if sad else 6))

    if angry:
        d.polygon([(el_x, ey+3),(el_x+ew, ey),(el_x+ew, ey+eh),(el_x, ey+eh)], fill=WHITE)
        d.polygon([(er_x, ey),(er_x+ew, ey+3),(er_x+ew, ey+eh),(er_x, ey+eh)], fill=WHITE)
    else:
        d.rectangle([el_x, ey, el_x+ew-1, ey+eh-1], fill=WHITE)
        d.rectangle([er_x, ey, er_x+ew-1, ey+eh-1], fill=WHITE)

    mx, my, mw = 22, 22, 20
    if mouth_open:
        d.ellipse([mx, my, mx+mw, my+6], fill=WHITE)
    elif sad:
        d.arc([mx, my-3, mx+mw, my+5], start=0, end=180, fill=WHITE, width=2)
    else:
        d.arc([mx, my, mx+mw, my+8], start=180, end=360, fill=WHITE, width=2)

    return img


# ── Eye panel (64×32, two eyes per panel) ────────────────────────────────────

def draw_eye_panel(style='neutral', mirror=False) -> Image.Image:
    img = blank()
    d   = ImageDraw.Draw(img)

    # Eye positions on a 64×32 canvas
    lx, rx, ey = 14, 42, 9
    ew, eh = 18, 12

    def eye(cx, style):
        ex, eya = cx - ew//2, ey
        if style == 'neutral':
            d.rectangle([ex, eya, ex+ew-1, eya+eh-1], fill=WHITE)
            # Pupil cutout
            pw, ph = ew//3, eh//2
            d.rectangle([cx - pw//2, ey + eh//4, cx - pw//2 + pw - 1,
                         ey + eh//4 + ph - 1], fill=(0,0,0,0))
        elif style == 'happy':
            d.rectangle([ex, eya, ex+ew-1, eya + eh//2], fill=WHITE)
        elif style == 'angry':
            d.polygon([
                (ex, eya + eh//3), (ex+ew, eya),
                (ex+ew, eya+eh), (ex, eya+eh),
            ], fill=WHITE)
        elif style == 'surprised':
            d.ellipse([ex, eya, ex+ew-1, eya+eh-1], fill=WHITE)
        elif style == 'blink':
            d.rectangle([ex, eya + eh//2 - 1, ex+ew-1, eya + eh//2 + 1], fill=WHITE)

    if mirror:
        lx, rx = rx, lx   # swap so right eye mirrors left

    eye(lx, style)
    eye(rx, style)
    return img


# ── Mouth panel (64×32, mouth fills the panel) ───────────────────────────────

def draw_mouth_panel(style='neutral', mirror=False) -> Image.Image:
    img = blank()
    d   = ImageDraw.Draw(img)

    mx, my, mw, mh = 6, 8, 52, 16

    if style == 'neutral':
        d.rectangle([mx, my, mx+mw-1, my+mh-1], fill=WHITE)
        d.rectangle([mx+3, my+3, mx+mw-4, my+mh-4], fill=(0,0,0,0))
    elif style == 'talking':
        # Open mouth — taller hollow
        d.rectangle([mx, my-2, mx+mw-1, my+mh+1], fill=WHITE)
        d.rectangle([mx+3, my+2, mx+mw-4, my+mh-2], fill=(0,0,0,0))
    elif style == 'smile':
        d.arc([mx, my, mx+mw, my+mh*2], start=180, end=360, fill=WHITE, width=3)
    elif style == 'frown':
        d.arc([mx, my - mh, mx+mw, my+mh], start=0, end=180, fill=WHITE, width=3)

    return img


# ── Write helpers ─────────────────────────────────────────────────────────────

def save(img: Image.Image, path: str):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    img.save(path)
    print(f"  {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

print("Generating face assets …\n")

# example_fox (original)
fox = 'faces/example_fox'
os.makedirs(fox, exist_ok=True)
save(draw_fox(),                         f'{fox}/neutral.png')
save(draw_fox(blink=True),              f'{fox}/blink.png')
save(draw_fox(mouth_open=True),          f'{fox}/mouth_open.png')
save(draw_fox(angry=True),               f'{fox}/angry.png')
save(draw_fox(sad=True),                 f'{fox}/sad.png')
save(draw_fox(surprised=True),           f'{fox}/surprised.png')
save(draw_fox(surprised=True, mouth_open=True), f'{fox}/happy.png')

# Eye panels
for folder, mirror in [('faces/left_eye', False), ('faces/right_eye', True)]:
    os.makedirs(folder, exist_ok=True)
    for style in ('neutral', 'happy', 'angry', 'surprised', 'blink'):
        save(draw_eye_panel(style, mirror=mirror), f'{folder}/{style}.png')

# Mouth panels
for folder, mirror in [('faces/left_mouth', False), ('faces/right_mouth', True)]:
    os.makedirs(folder, exist_ok=True)
    for style in ('neutral', 'talking', 'smile', 'frown'):
        save(draw_mouth_panel(style, mirror=mirror), f'{folder}/{style}.png')

# Materials
os.makedirs('materials', exist_ok=True)

Image.new('RGB', (1, 1), (0, 220, 180)).save('materials/teal.png')

rainbow = Image.new('RGB', (W, 1))
for x in range(W):
    r, g, b = colorsys.hsv_to_rgb(x / W, 1.0, 1.0)
    rainbow.putpixel((x, 0), (int(r*255), int(g*255), int(b*255)))
rainbow.save('materials/rainbow.png')

warm = Image.new('RGB', (W, 1))
for x in range(W):
    t = x / W
    warm.putpixel((x, 0), (255, int(80 + 120*t), int(20*(1-t))))
warm.save('materials/warm.png')

cool = Image.new('RGB', (W, 1))
for x in range(W):
    t = x / W
    cool.putpixel((x, 0), (int(20*(1-t)), int(150 + 100*t), 255))
cool.save('materials/cool.png')

print("\nDone — replace PNGs with real artwork to customise the face.")
