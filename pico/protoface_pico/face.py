"""displayio face engine for the Pico port.

Renders one face (e.g. ``assets/main``) into a working bitmap and presents it on
the canvas, optionally mirrored to fill both panel halves (matching the CM5
``mirror_of`` layout where the right panel is the left flipped horizontally).

Faces are baked as 16-colour indexed BMPs where the index encodes luminance:

    index 0           = transparent (face shape mask)
    index 1..15       = dark -> bright

The material (colour) is the palette ramp written over those indices
(material.SolidMaterial.apply_to_palette), so recolouring the whole face is a
~16-entry palette rewrite rather than a per-pixel multiply.

Per frame the engine composes: current expression -> (crossfade from previous)
-> blink (eye regions or whole-face) -> mouth-open region, then positions the
tile(s) by the integer idle-wiggle + gyro offset.
"""

import json

import displayio
import bitmaptools
import adafruit_imageload

from . import material as material_mod


def _round(x):
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


class FaceEngine:
    def __init__(self, assets_dir, face_name, mat, canvas_w, canvas_h, mirror=True):
        self.dir = "%s/%s" % (assets_dir, face_name)
        self.material = mat
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h
        self.mirror = mirror

        self._expressions = {}   # name -> displayio.Bitmap (source, read-only use)
        self._blink = None
        self._mouth_open = None
        self._eye_left = None
        self._eye_right = None
        self._mouth = None

        self._load()

        # Face is authored at half the canvas width when mirroring (e.g. 64 of
        # 128). When not mirroring the face spans the whole canvas.
        self.face_w = self._fw
        self.face_h = self._fh

        # Shared palette (the material ramp) and the per-frame working bitmap.
        # value_count is taken from the loaded BMPs so bitmaptools.blit bit
        # depths always match, regardless of how Pillow padded the palette.
        self.palette = displayio.Palette(self._value_count)
        self.material.apply_to_palette(self.palette)
        self.working = displayio.Bitmap(self.face_w, self.face_h, self._value_count)

        # Build the displayio group (face tile + optional mirror tile).
        self.group = displayio.Group()
        self._tg_left = displayio.TileGrid(
            self.working, pixel_shader=self.palette, x=0, y=0
        )
        self.group.append(self._tg_left)
        self._tg_right = None
        if self.mirror:
            self._tg_right = displayio.TileGrid(
                self.working, pixel_shader=self.palette,
                x=self.face_w, y=0, flip_x=True,
            )
            self.group.append(self._tg_right)

    # -- Loading -------------------------------------------------------------

    def _load_bmp(self, filename):
        bitmap, _palette = adafruit_imageload.load(
            "%s/%s" % (self.dir, filename),
            bitmap=displayio.Bitmap, palette=displayio.Palette,
        )
        return bitmap

    def _load(self):
        try:
            with open("%s/config.json" % self.dir) as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}

        expr_map = cfg.get("expressions", {})
        if not expr_map:
            # Convention: bake neutral/happy/etc as <name>.bmp
            for name in ("neutral", "happy", "angry", "sad", "surprised"):
                expr_map[name] = "%s.bmp" % name

        for name, fname in expr_map.items():
            try:
                self._expressions[name] = self._load_bmp(fname)
            except OSError:
                pass

        if not self._expressions:
            raise RuntimeError("no expression BMPs found in %s" % self.dir)

        if "neutral" not in self._expressions:
            first = next(iter(self._expressions.values()))
            self._expressions["neutral"] = first

        # Determine authored size + index depth from the first expression bitmap.
        any_bmp = next(iter(self._expressions.values()))
        self._fw, self._fh = any_bmp.width, any_bmp.height
        # Must cover the 16 luminance levels the converter bakes (indices 0..15).
        self._value_count = max(material_mod.LEVELS, any_bmp.value_count)

        try:
            self._blink = self._load_bmp(cfg.get("blink", "blink.bmp"))
        except OSError:
            self._blink = None
        try:
            self._mouth_open = self._load_bmp("mouth_open.bmp")
        except OSError:
            self._mouth_open = None

        # Regions: scale from draw_size if provided.
        draw = cfg.get("draw_size")
        if draw and len(draw) == 2 and draw[0] and draw[1]:
            sx = self._fw / float(draw[0])
            sy = self._fh / float(draw[1])
        else:
            sx = sy = 1.0

        def region(d):
            return (
                int(d["x"] * sx), int(d["y"] * sy),
                max(1, int(d["w"] * sx)), max(1, int(d["h"] * sy)),
            )

        if "eye_left" in cfg:
            self._eye_left = region(cfg["eye_left"])
        if "eye_right" in cfg:
            self._eye_right = region(cfg["eye_right"])
        if "mouth" in cfg:
            self._mouth = region(cfg["mouth"])

    # -- Per-frame composition ----------------------------------------------

    def expression_names(self):
        return list(self._expressions.keys())

    def _blend_region(self, src_b, t, box):
        """In-place lerp working <- working*(1-t) + src_b*t over *box*.

        Index values are a linear luminance ramp, so blending indices matches
        the CM5 luminance crossfade. Pure-Python, but bounded to the box.
        """
        x0, y0, w, h = box
        x1 = min(x0 + w, self.face_w)
        y1 = min(y0 + h, self.face_h)
        wk = self.working
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                a = wk[xx, yy]
                b = src_b[xx, yy]
                wk[xx, yy] = a + _round((b - a) * t)

    def _copy(self, src_b):
        bitmaptools.blit(self.working, src_b, 0, 0)

    def set_material(self, mat, brightness=255):
        self.material = mat
        self.material.apply_to_palette(self.palette, brightness)

    def set_brightness(self, brightness):
        self.material.apply_to_palette(self.palette, brightness)

    def update(self, state):
        # 1. Base = current expression, crossfaded from previous if mid-transition.
        cur = self._expressions.get(state.expression, self._expressions["neutral"])
        prev = self._expressions.get(
            state.prev_expression, self._expressions["neutral"]
        )
        t = state.transition_t
        if t >= 1.0 or cur is prev:
            self._copy(cur)
        else:
            self._copy(prev)
            self._blend_region(cur, t, (0, 0, self.face_w, self.face_h))

        # 2. Blink (eye regions, else whole-face swap).
        bw = state.blink_weight
        if bw > 0.0 and self._blink is not None:
            if self._eye_left or self._eye_right:
                for box in (self._eye_left, self._eye_right):
                    if box:
                        self._blend_region(self._blink, bw, box)
            else:
                self._blend_region(self._blink, bw, (0, 0, self.face_w, self.face_h))

        # 3. Mouth open.
        mo = state.mouth_open
        if mo > 0.0 and self._mouth and self._mouth_open is not None:
            self._blend_region(self._mouth_open, mo, self._mouth)

        # 4. Wiggle + gyro -> integer tile offset (displayio positions are int).
        wx, wy = state.wiggle_offset()
        gx, gy = state.gyro_offset
        dx = _round(wx + gx)
        dy = _round(wy + gy)
        self._tg_left.x = dx
        self._tg_left.y = dy
        if self._tg_right is not None:
            # Mirror the horizontal motion so both halves stay symmetric.
            self._tg_right.x = self.face_w - dx
            self._tg_right.y = dy
