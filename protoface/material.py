"""
Material system.

A material describes the colour/pattern painted onto the face pixels.
Four built-in types:

  SolidMaterial(r, g, b)            — flat colour; no PNG needed
  TextureMaterial(path, w, h)       — PNG tiled to panel size, scrollable
  GradientMaterial([colours], ...)  — multi-colour gradient, optionally scrolling
  ZonedMaterial([mat_a, mat_b], boundary=0.5)
                                    — splits the panel horizontally; each
                                      half uses a different material

To add a new material type, subclass BaseMaterial and implement get_frame(t).

Loading from config
-------------------
  material.active: teal                          → loads materials/teal.png
  material.active: solid:0,220,180               → SolidMaterial(0, 220, 180)
  material.active: gradient:h:s:0:FF8C00-8A2BE2  → GradientMaterial (see below)

Gradient spec (mirrors ProtoHUD's GradientMaterial):
  gradient:<dir>:<mode>:<speed>:<RRGGBB>-<RRGGBB>-...
    dir   = h (left→right) | v (top→bottom)
    mode  = s (smooth blend) | b (banded / hard equal-width stripes)
    speed = scroll rate in px/s along the axis (integer; 0 = static)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image


class BaseMaterial:
    def update(self, dt: float):
        """Advance internal time.  Call once per frame."""

    def get_frame(self) -> np.ndarray:
        """Return (H, W, 3) uint8 RGB array ready for the compositor."""
        raise NotImplementedError


# ── Solid colour ──────────────────────────────────────────────────────────────

class SolidMaterial(BaseMaterial):
    def __init__(self, r: int, g: int, b: int, width: int, height: int):
        self._frame = np.empty((height, width, 3), dtype=np.uint8)
        self._frame[:] = (r, g, b)

    def get_frame(self) -> np.ndarray:
        return self._frame


# ── PNG texture with optional scrolling ───────────────────────────────────────

class TextureMaterial(BaseMaterial):
    def __init__(self, path: str, width: int, height: int,
                 scroll_x: float = 0.0, scroll_y: float = 0.0):
        self.w = width
        self.h = height
        self.scroll_x = scroll_x   # pixels per second
        self.scroll_y = scroll_y
        self._t = 0.0

        img = Image.open(path).convert('RGB')
        # Tile image to at least panel size so np.roll wraps cleanly
        tw = max(width,  img.width)
        th = max(height, img.height)
        tiled = Image.new('RGB', (tw, th))
        for y in range(0, th, img.height):
            for x in range(0, tw, img.width):
                tiled.paste(img, (x, y))
        tiled = tiled.crop((0, 0, width, height))
        self._base = np.array(tiled, dtype=np.uint8)

    def update(self, dt: float):
        self._t += dt

    def get_frame(self) -> np.ndarray:
        sx = int(self.scroll_x * self._t) % self.w
        sy = int(self.scroll_y * self._t) % self.h
        frame = self._base
        if sx:
            frame = np.roll(frame, sx, axis=1)
        if sy:
            frame = np.roll(frame, sy, axis=0)
        return frame


# ── Multi-colour gradient ─────────────────────────────────────────────────────

class GradientMaterial(BaseMaterial):
    """
    A multi-colour gradient painted along one axis and wrapped cyclically so a
    scroll wraps seamlessly.  Mirrors ProtoHUD's GradientMaterial:

      horizontal=True  → ramp runs left→right (axis length = width)
      horizontal=False → ramp runs top→bottom (axis length = height)
      smooth=True      → linear blend between stops
      smooth=False     → hard equal-width bands
      speed            → scroll rate in px/s along the axis (0 = static)

    N colour stops form N cyclic segments: segment i blends colours[i] →
    colours[(i+1) % N] so the position at the far edge wraps back to the start.
    """
    def __init__(self, colors, width: int, height: int,
                 horizontal: bool = True, smooth: bool = True,
                 speed: float = 0.0):
        self.w = width
        self.h = height
        self.horizontal = horizontal
        self.speed = float(speed)
        self._t = 0.0

        cols = [tuple(int(c) for c in col) for col in (colors or [])]
        if not cols:
            cols = [(0, 220, 180)]      # teal fallback
        n = len(cols)
        L = max(1, width if horizontal else height)
        arr = np.asarray(cols, dtype=np.float32)      # (N, 3)

        axis = np.empty((L, 3), dtype=np.float32)
        for p in range(L):
            f   = p / L * n
            seg = min(n - 1, int(f))
            if not smooth or n == 1:
                axis[p] = arr[seg]
            else:
                local = f - seg
                axis[p] = arr[seg] * (1.0 - local) + arr[(seg + 1) % n] * local
        axis = np.clip(axis + 0.5, 0, 255).astype(np.uint8)

        # Broadcast the 1-D ramp across the perpendicular axis.
        if horizontal:
            self._base = np.broadcast_to(
                axis[np.newaxis, :, :], (height, L, 3)).copy()
        else:
            self._base = np.broadcast_to(
                axis[:, np.newaxis, :], (L, width, 3)).copy()

    def update(self, dt: float):
        self._t += dt

    def get_frame(self) -> np.ndarray:
        if self.speed == 0.0:
            return self._base
        L = self.w if self.horizontal else self.h
        if L <= 0:
            return self._base
        off = int(self.speed * self._t)
        if off % L == 0:
            return self._base
        return np.roll(self._base, off, axis=1 if self.horizontal else 0)


# ── Horizontal zone split ─────────────────────────────────────────────────────

class ZonedMaterial(BaseMaterial):
    """
    Split the panel at *boundary* (0.0–1.0 fraction of width).
    Left of boundary uses mat_a, right uses mat_b.
    """
    def __init__(self, mat_a: BaseMaterial, mat_b: BaseMaterial,
                 width: int, height: int, boundary: float = 0.5):
        self.mat_a = mat_a
        self.mat_b = mat_b
        self.split = int(width * boundary)
        self.w = width
        self.h = height

    def update(self, dt: float):
        self.mat_a.update(dt)
        self.mat_b.update(dt)

    def get_frame(self) -> np.ndarray:
        a = self.mat_a.get_frame()
        b = self.mat_b.get_frame()
        frame = np.empty((self.h, self.w, 3), dtype=np.uint8)
        frame[:, :self.split]  = a[:, :self.split]
        frame[:, self.split:]  = b[:, self.split:]
        return frame


# ── Gradient spec parsing ─────────────────────────────────────────────────────

# Built-in gradient definitions for the named material presets, used as a
# fallback when the corresponding PNG tile isn't present (a fresh checkout that
# hasn't run generate_assets.py still shows the right colours).
_NAMED_GRADIENTS = {
    'rainbow': 'gradient:h:s:0:FF0000-FF8C00-FFED00-00B140-0057FF-8A2BE2',
    'cool':    'gradient:h:s:0:00E5FF-0077FF-8A2BE2',
    'warm':    'gradient:h:s:0:FFE000-FF7A00-E01E1E',
}


def _parse_gradient(spec: str, width: int, height: int) -> 'GradientMaterial':
    """Parse a ``gradient:<dir>:<mode>:<speed>:HEX-HEX-...`` spec."""
    body  = spec[len('gradient:'):]
    parts = body.split(':', 3)              # dir, mode, speed, hexlist
    dir_    = parts[0] if len(parts) > 0 else 'h'
    mode    = parts[1] if len(parts) > 1 else 's'
    try:
        speed = float(parts[2]) if len(parts) > 2 and parts[2] != '' else 0.0
    except ValueError:
        speed = 0.0
    hexlist = parts[3] if len(parts) > 3 else ''

    horizontal = dir_ != 'v'
    smooth     = mode != 'b'
    colors = []
    for tok in hexlist.split('-'):
        tok = tok.strip()
        if len(tok) >= 6:
            try:
                v = int(tok[:6], 16)
            except ValueError:
                continue
            colors.append(((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))
    return GradientMaterial(colors, width, height, horizontal, smooth, speed)


# ── Factory ───────────────────────────────────────────────────────────────────

def load_material(name: str, width: int, height: int,
                  scroll_x: float = 0.0, scroll_y: float = 0.0,
                  materials_dir: str = 'materials') -> BaseMaterial:
    """
    Resolve a material name to a BaseMaterial instance.

    Supported name formats:
      "teal"                          → materials/teal.png (or a built-in
                                        gradient fallback for rainbow/cool/warm)
      "solid:0,220,180"               → SolidMaterial(0, 220, 180)
      "gradient:h:s:0:FF8C00-8A2BE2"  → GradientMaterial (multi-colour gradient)
      "zone:teal|rainbow"             → ZonedMaterial, left=teal, right=rainbow
    """
    if name.startswith('solid:'):
        parts = name[6:].split(',')
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        return SolidMaterial(r, g, b, width, height)

    if name.startswith('gradient:'):
        return _parse_gradient(name, width, height)

    if name.startswith('zone:'):
        parts = name[5:].split('|')
        mat_a = load_material(parts[0].strip(), width, height,
                              scroll_x, scroll_y, materials_dir)
        mat_b = load_material(parts[1].strip(), width, height,
                              scroll_x, scroll_y, materials_dir)
        return ZonedMaterial(mat_a, mat_b, width, height)

    # PNG file
    candidates = [
        Path(materials_dir) / f'{name}.png',
        Path(materials_dir) / name,
    ]
    for path in candidates:
        if path.exists():
            return TextureMaterial(str(path), width, height, scroll_x, scroll_y)

    # Built-in gradient fallback for the named presets (rainbow/cool/warm)
    if name in _NAMED_GRADIENTS:
        return _parse_gradient(_NAMED_GRADIENTS[name], width, height)

    # Fallback: teal solid so the face always shows something
    print(f"[material] '{name}' not found — falling back to solid teal")
    return SolidMaterial(0, 220, 180, width, height)
