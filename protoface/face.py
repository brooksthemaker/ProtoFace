"""
Face sprite loader and animator.

Loads a face folder containing PNG images and an optional config.json.
Each frame, get_frame(state) returns an (H, W, 4) RGBA ndarray with:
  - the current expression (crossfaded with the previous one)
  - blink animation applied to eye regions (or whole-face swap if no regions)
  - idle wiggle offset applied via pixel shift
  - mouth region swapped/lerped based on state.mouth_open
"""

import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image


def _shift_int(arr: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Shift *arr* by whole pixels (dy, dx).

    Vacated edges replicate the border pixel (edge clamp) instead of going
    blank, so a feature drawn to the image edge (mouth/nose) stays anchored to
    the panel edge as the face moves, rather than opening a gap. No wrap-around.
    """
    h, w = arr.shape[:2]
    ys = np.clip(np.arange(h) - dy, 0, h - 1)
    xs = np.clip(np.arange(w) - dx, 0, w - 1)
    return arr[ys[:, None], xs[None, :]]


def _shift_clip(arr: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """Sub-pixel shift by (dy, dx) with edge-clamped borders (no wrap).

    Fractional offsets are bilinearly interpolated so motion glides smoothly
    between pixels instead of jumping a whole pixel at a time.
    """
    iy, ix = int(math.floor(dy)), int(math.floor(dx))
    fy, fx = dy - iy, dx - ix
    if fy == 0.0 and fx == 0.0:
        return _shift_int(arr, iy, ix)
    base = arr.astype(np.float32)
    a = _shift_int(base, iy,     ix)
    b = _shift_int(base, iy,     ix + 1)
    c = _shift_int(base, iy + 1, ix)
    d = _shift_int(base, iy + 1, ix + 1)
    out = (a * ((1 - fy) * (1 - fx)) + b * ((1 - fy) * fx)
           + c * (fy * (1 - fx)) + d * (fy * fx))
    return np.clip(out, 0, 255).astype(arr.dtype)


class FaceLoader:
    def __init__(self, folder: str, width: int, height: int):
        self.w = width
        self.h = height
        self.folder = Path(folder)
        self._time = 0.0

        self._expressions: dict[str, np.ndarray] = {}
        self._blink: np.ndarray | None = None
        self._eye_left:  dict | None = None
        self._eye_right: dict | None = None
        self._mouth:     dict | None = None
        self._mouth_open_img: np.ndarray | None = None

        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load_png(self, path: Path) -> np.ndarray:
        """Load a PNG as (H, W, 4) RGBA ndarray scaled to panel size."""
        img = Image.open(path).convert('RGBA').resize(
            (self.w, self.h), Image.NEAREST)
        return np.array(img, dtype=np.uint8)

    def _load(self):
        cfg_path = self.folder / 'config.json'
        if cfg_path.exists():
            with open(cfg_path) as f:
                cfg = json.load(f)
        else:
            cfg = {}

        # Expression map: name → filename (default: scan folder for PNGs)
        expr_map: dict[str, str] = cfg.get('expressions', {})
        if not expr_map:
            for p in sorted(self.folder.glob('*.png')):
                name = p.stem.lower()
                if name not in ('blink', 'mouth_open'):
                    expr_map[name] = p.name

        for name, filename in expr_map.items():
            path = self.folder / filename
            if path.exists():
                self._expressions[name] = self._load_png(path)

        if not self._expressions:
            raise FileNotFoundError(
                f"No expression PNGs found in {self.folder}")

        # Fallback neutral
        if 'neutral' not in self._expressions:
            first = next(iter(self._expressions.values()))
            self._expressions['neutral'] = first

        # Blink image
        blink_file = cfg.get('blink', 'blink.png')
        blink_path = self.folder / blink_file
        if blink_path.exists():
            self._blink = self._load_png(blink_path)

        # Optional mouth-open image
        mouth_open_path = self.folder / 'mouth_open.png'
        if mouth_open_path.exists():
            self._mouth_open_img = self._load_png(mouth_open_path)

        # Region definitions. By default boxes are in panel pixels (self.w x
        # self.h). If config.json gives draw_size: [W, H], boxes are authored in
        # that resolution (e.g. your 128x64 art) and scaled down to the panel.
        draw = cfg.get('draw_size')
        if draw and len(draw) == 2 and draw[0] and draw[1]:
            sx = self.w / float(draw[0])
            sy = self.h / float(draw[1])
        else:
            sx = sy = 1.0

        def parse_region(d: dict) -> dict:
            return {
                'x': int(round(d['x'] * sx)),
                'y': int(round(d['y'] * sy)),
                'w': max(1, int(round(d['w'] * sx))),
                'h': max(1, int(round(d['h'] * sy))),
            }

        if 'eye_left' in cfg:
            self._eye_left = parse_region(cfg['eye_left'])
        if 'eye_right' in cfg:
            self._eye_right = parse_region(cfg['eye_right'])
        if 'mouth' in cfg:
            self._mouth = parse_region(cfg['mouth'])

    # ── Region blending ───────────────────────────────────────────────────────

    def _blend_region(self, base: np.ndarray, overlay: np.ndarray,
                      region: dict, t: float) -> np.ndarray:
        """
        Lerp the pixels inside *region* from *base* toward *overlay* by factor t.
        Returns a copy of base with the region updated.
        """
        out = base.copy()
        x, y, w, h = region['x'], region['y'], region['w'], region['h']
        x2, y2 = min(x + w, self.w), min(y + h, self.h)
        base_r  = base[y:y2, x:x2].astype(np.float32)
        over_r  = overlay[y:y2, x:x2].astype(np.float32)
        out[y:y2, x:x2] = np.clip(
            base_r * (1.0 - t) + over_r * t, 0, 255).astype(np.uint8)
        return out

    # ── Frame assembly ────────────────────────────────────────────────────────

    def get_frame(self, state) -> np.ndarray:
        """
        Return the composited face frame as (H, W, 4) RGBA.

        Reads from state:
          state.expression        — name of current expression
          state.prev_expression   — name of expression being faded from
          state.transition_t      — 0.0=prev, 1.0=current crossfade progress
          state.blink_weight      — 0.0=open, 1.0=fully closed
          state.mouth_open        — 0.0=closed, 1.0=wide open
          state.gyro_offset       — (dx, dy) pixel shift
          state.time              — elapsed seconds (for wiggle)
        """
        self._time = state.time

        # 1. Crossfade between previous and current expression
        cur  = self._expressions.get(state.expression,
                                     self._expressions['neutral'])
        prev = self._expressions.get(state.prev_expression,
                                     self._expressions['neutral'])
        t = float(np.clip(state.transition_t, 0.0, 1.0))
        if t >= 1.0 or cur is prev:
            frame = cur.copy()
        else:
            frame = np.clip(
                prev.astype(np.float32) * (1.0 - t) +
                cur.astype(np.float32) * t,
                0, 255).astype(np.uint8)

        # 2. Apply blink
        bw = float(np.clip(state.blink_weight, 0.0, 1.0))
        if bw > 0.0 and self._blink is not None:
            if self._eye_left or self._eye_right:
                for region in (self._eye_left, self._eye_right):
                    if region:
                        frame = self._blend_region(
                            frame, self._blink, region, bw)
            else:
                # Whole-face blink swap
                frame = np.clip(
                    frame.astype(np.float32) * (1.0 - bw) +
                    self._blink.astype(np.float32) * bw,
                    0, 255).astype(np.uint8)

        # 3. Apply mouth open
        mo = float(np.clip(state.mouth_open, 0.0, 1.0))
        if mo > 0.0 and self._mouth and self._mouth_open_img is not None:
            frame = self._blend_region(
                frame, self._mouth_open_img, self._mouth, mo)

        # 4. Wiggle + gyro offset
        # .get() with the same defaults state.py uses: a partial wiggle: dict in
        # config (e.g. only speed set) must not KeyError every frame.
        cfg_w = state.wiggle_cfg
        spd = cfg_w.get('speed', 0.3)
        dx = cfg_w.get('amplitude_x', 2.0) * math.sin(
            2 * math.pi * spd * state.time)
        dy = cfg_w.get('amplitude_y', 1.0) * math.sin(
            2 * math.pi * spd * state.time * 1.3)
        gx, gy = state.gyro_offset
        shift_x = dx + gx
        shift_y = dy + gy

        if abs(shift_x) > 0.01 or abs(shift_y) > 0.01:
            frame = _shift_clip(frame, shift_y, shift_x)

        return frame

    @property
    def expression_names(self) -> list[str]:
        return list(self._expressions.keys())
