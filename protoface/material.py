"""
Material system.

A material describes the colour/pattern painted onto the face pixels.
Three built-in types:

  SolidMaterial(r, g, b)            — flat colour; no PNG needed
  TextureMaterial(path, w, h)       — PNG tiled to panel size, scrollable
  ZonedMaterial([mat_a, mat_b], boundary=0.5)
                                    — splits the panel horizontally; each
                                      half uses a different material

To add a new material type, subclass BaseMaterial and implement get_frame(t).

Loading from config
-------------------
  material.active: teal             → loads materials/teal.png
  material.active: solid:0,220,180  → SolidMaterial(0, 220, 180)
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


# ── Factory ───────────────────────────────────────────────────────────────────

def load_material(name: str, width: int, height: int,
                  scroll_x: float = 0.0, scroll_y: float = 0.0,
                  materials_dir: str = 'materials') -> BaseMaterial:
    """
    Resolve a material name to a BaseMaterial instance.

    Supported name formats:
      "teal"              → materials/teal.png  (TextureMaterial or SolidMaterial if 1×1)
      "solid:0,220,180"   → SolidMaterial(0, 220, 180)
      "zone:teal|rainbow" → ZonedMaterial with left=teal, right=rainbow
    """
    if name.startswith('solid:'):
        parts = name[6:].split(',')
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        return SolidMaterial(r, g, b, width, height)

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

    # Fallback: teal solid so the face always shows something
    print(f"[material] '{name}' not found — falling back to solid teal")
    return SolidMaterial(0, 220, 180, width, height)
