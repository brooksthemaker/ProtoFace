"""Lightweight particle overlay for the Pico port.

A single-layer, opaque-dot particle system covering a useful subset of the CM5
effects (sparkle, embers, snow, rain, confetti, fireflies). It renders into its
own indexed displayio.Bitmap layered over the face.

Differences from the CM5 ``particles.py`` (documented, for parity tracking):
  * single layer (no multi-layer stacks / presets.yaml yet)
  * opaque "normal" blend only (no additive glow — displayio can't cheaply
    additive-blend; additive is a phase-2 item)
  * small fixed colour palette per effect

Particle counts are deliberately modest; bump them once measured on hardware.
"""

import math
import random

import displayio

# effect -> parameters. emit: where particles spawn. grav: +y px/s^2.
_EFFECTS = {
    "none":      None,
    "sparkle":   {"count": 8,  "emit": "random", "grav": 0,   "vmin": 0,  "vmax": 0,
                  "life": (0.05, 0.2), "colors": [(255, 255, 220)], "size": 1},
    "embers":    {"count": 24, "emit": "bottom", "grav": -10, "vmin": 8,  "vmax": 22,
                  "life": (0.6, 1.4), "colors": [(255, 60, 0), (255, 110, 10)], "size": 1},
    "snow":      {"count": 28, "emit": "top",    "grav": 12,  "vmin": 4,  "vmax": 10,
                  "life": (2.0, 4.0), "colors": [(200, 220, 255)], "size": 1},
    "rain":      {"count": 30, "emit": "top",    "grav": 60,  "vmin": 40, "vmax": 80,
                  "life": (0.4, 0.9), "colors": [(120, 160, 255)], "size": 1},
    "confetti":  {"count": 24, "emit": "top",    "grav": 30,  "vmin": 10, "vmax": 30,
                  "life": (1.0, 2.0),
                  "colors": [(255, 80, 80), (80, 255, 120), (90, 140, 255),
                             (255, 230, 90)], "size": 1},
    "fireflies": {"count": 14, "emit": "random", "grav": 0,   "vmin": 2,  "vmax": 8,
                  "life": (1.0, 2.5), "colors": [(180, 255, 120)], "size": 1},
}


class ParticleSystem:
    def __init__(self, width, height):
        self.w = width
        self.h = height
        self._params = None
        self._particles = []
        self._spawn_acc = 0.0

        # Bitmap + palette (index 0 transparent). Palette sized for the largest
        # colour set so we can switch effects without reallocating.
        self.bitmap = displayio.Bitmap(width, height, 8)
        self.palette = displayio.Palette(8)
        self.palette[0] = 0x000000
        self.palette.make_transparent(0)
        self.tilegrid = displayio.TileGrid(self.bitmap, pixel_shader=self.palette)
        self.group = displayio.Group()
        self.group.append(self.tilegrid)

    def set_effect(self, name):
        params = _EFFECTS.get(name)
        self._params = params
        self._particles = []
        self.bitmap.fill(0)
        if params:
            cols = params["colors"]
            for i, c in enumerate(cols[:7]):
                self.palette[i + 1] = (c[0] << 16) | (c[1] << 8) | c[2]
            self._ncolors = len(cols[:7])

    def _spawn(self):
        p = self._params
        emit = p["emit"]
        if emit == "bottom":
            x, y = random.uniform(0, self.w), self.h - 1
        elif emit == "top":
            x, y = random.uniform(0, self.w), 0
        else:  # random
            x, y = random.uniform(0, self.w), random.uniform(0, self.h)
        speed = random.uniform(p["vmin"], p["vmax"])
        if emit == "bottom":
            vx, vy = random.uniform(-4, 4), -speed
        elif emit == "top":
            vx, vy = random.uniform(-4, 4), speed
        else:
            ang = random.uniform(0, 2 * math.pi)
            vx, vy = speed * math.cos(ang), speed * math.sin(ang)
        life = random.uniform(p["life"][0], p["life"][1])
        cidx = random.randint(1, max(1, self._ncolors))
        self._particles.append([x, y, vx, vy, life, life, cidx])

    def update(self, dt):
        p = self._params
        if not p:
            return
        # Maintain population.
        target = p["count"]
        alive = self._particles
        # Spawn toward target.
        while len(alive) < target:
            self._spawn()
        # Integrate.
        g = p["grav"]
        kept = []
        for q in alive:
            q[4] -= dt
            if q[4] <= 0:
                continue
            q[3] += g * dt
            q[0] += q[2] * dt
            q[1] += q[3] * dt
            if -2 <= q[1] <= self.h + 2:
                kept.append(q)
        self._particles = kept

    def render(self):
        """Redraw the overlay bitmap. Returns the group (always layered)."""
        if not self._params:
            return
        bmp = self.bitmap
        bmp.fill(0)
        w, h = self.w, self.h
        for q in self._particles:
            x = int(q[0])
            y = int(q[1])
            if 0 <= x < w and 0 <= y < h:
                bmp[x, y] = q[6]
