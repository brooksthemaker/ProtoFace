"""
Particle effect system — multi-layer compositor.

Each effect class has:
  update(dt)           — advance simulation by dt seconds
  render() → ndarray   — return (H, W, 4) RGBA uint8 overlay

ParticleLayer wraps one effect with its own colour list, shape, blend mode and
per-spawn parameter overrides.  ParticleSystem holds a list of layers and
composites them into a single RGBA frame each tick.

Config forms
------------
Single shorthand (backward-compatible):
    particles: {active: embers, intensity: 1.0}

Named preset from particles/presets.yaml:
    particles: {preset: fire}

Multi-layer:
    particles:
      layers:
        - {effect: embers, colors: [[255,60,0],[255,100,10]], count: 30, blend: add}
        - {effect: sparkle, colors: [[255,255,200]], count: 6, blend: add}

Per-layer keys (all optional):
    effect       str       effect class name
    count        int       simultaneous particles
    colors       list      [[r,g,b], ...]  — random pick at spawn; falls back to 'color'
    color        [r,g,b]   single colour (legacy / default)
    blend        str       'add' | 'normal'
    speed_min    float     px/s min spawn speed
    speed_max    float     px/s max spawn speed
    size_min     int       min particle radius in pixels
    size_max     int       max particle radius in pixels
    life_min     float     min lifetime seconds
    life_max     float     max lifetime seconds
    drift_x      float     horizontal velocity bias px/s
    shape        str       'dot' | 'rect'
    emit_from    str       'bottom' | 'top' | 'edges' | 'random'
    intensity    float     scales count and spawn rate

Adding a new effect
-------------------
1. Subclass BaseEffect and implement update() / render().
2. Add it to EFFECT_REGISTRY at the bottom of this file.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass

import numpy as np

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False


# ── Particle dataclass ────────────────────────────────────────────────────────

@dataclass
class Particle:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    life: float = 1.0      # normalised remaining life; 1.0 = just spawned, 0.0 = dead
    max_life: float = 1.0  # total lifetime in seconds
    r: float = 255.0
    g: float = 255.0
    b: float = 255.0
    size: int = 1
    extra: float = 0.0     # effect-specific scratch value


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pick_color(cfg: dict) -> tuple[int, int, int]:
    """Pick one RGB colour from cfg['colors'] (list) or fall back to cfg['color']."""
    colors = cfg.get('colors')
    if colors:
        c = random.choice(colors)
        return int(c[0]), int(c[1]), int(c[2])
    c = cfg.get('color', [255, 255, 255])
    return int(c[0]), int(c[1]), int(c[2])


def _speed(cfg: dict, default_min: float, default_max: float) -> float:
    lo = cfg.get('speed_min', cfg.get('speed', default_min))
    hi = cfg.get('speed_max', cfg.get('speed', default_max))
    return random.uniform(lo, hi)


def _life(cfg: dict, default_min: float, default_max: float) -> float:
    return random.uniform(
        cfg.get('life_min', default_min),
        cfg.get('life_max', default_max),
    )


def _size(cfg: dict, default_min: int = 1, default_max: int = 1) -> int:
    # Tolerate float values and size_min > size_max (e.g. only size_min: 3 set
    # with the default max of 1) — randint would raise TypeError / ValueError.
    lo = int(cfg.get('size_min', default_min))
    hi = int(cfg.get('size_max', default_max))
    return random.randint(lo, max(lo, hi))


def _emit_pos(cfg: dict, w: int, h: int, default: str) -> tuple[float, float]:
    where = cfg.get('emit_from', default)
    if where == 'bottom':
        return random.uniform(0, w - 1), float(h)
    if where == 'top':
        return random.uniform(0, w - 1), -2.0
    if where == 'edges':
        side = random.randint(0, 3)
        if side == 0: return random.uniform(0, w - 1), -2.0
        if side == 1: return random.uniform(0, w - 1), float(h)
        if side == 2: return -2.0, random.uniform(0, h - 1)
        return float(w), random.uniform(0, h - 1)
    # random
    return random.uniform(0, w - 1), random.uniform(0, h - 1)


# ── Base class ────────────────────────────────────────────────────────────────

class BaseEffect:
    def __init__(self, width: int, height: int, cfg: dict):
        self.w = width
        self.h = height
        self.cfg = cfg
        self.particles: list[Particle] = []
        self._intensity = float(cfg.get('intensity', 1.0))

    def _count(self, default: int) -> int:
        return max(1, int(self.cfg.get('count', default) * self._intensity))

    def _draw_pixel(self, canvas: np.ndarray, x: int, y: int,
                    r: int, g: int, b: int, a: int):
        if 0 <= x < self.w and 0 <= y < self.h:
            canvas[y, x] = (r, g, b, a)

    def _draw_dot(self, canvas: np.ndarray, x: float, y: float,
                  r: int, g: int, b: int, alpha: float, size: int = 1):
        a = int(np.clip(alpha * 255, 0, 255))
        if size <= 1:
            self._draw_pixel(canvas, int(x), int(y), r, g, b, a)
            return
        ix, iy = int(x), int(y)
        for dy in range(-size + 1, size):
            for dx in range(-size + 1, size):
                self._draw_pixel(canvas, ix + dx, iy + dy, r, g, b, a)

    def _draw_rect(self, canvas: np.ndarray, x: float, y: float,
                   r: int, g: int, b: int, alpha: float, size: int = 1):
        a = int(np.clip(alpha * 255, 0, 255))
        ix, iy = int(x), int(y)
        self._draw_pixel(canvas, ix, iy, r, g, b, a)
        self._draw_pixel(canvas, ix, iy + 1, r, g, b, a)
        if size > 1:
            self._draw_pixel(canvas, ix + 1, iy, r, g, b, a)
            self._draw_pixel(canvas, ix + 1, iy + 1, r, g, b, a)

    def _draw_particle(self, canvas: np.ndarray, p: Particle, alpha: float):
        shape = self.cfg.get('shape', 'dot')
        r, g, b = int(p.r), int(p.g), int(p.b)
        if shape == 'rect':
            self._draw_rect(canvas, p.x, p.y, r, g, b, alpha, p.size)
        else:
            self._draw_dot(canvas, p.x, p.y, r, g, b, alpha, p.size)

    def update(self, dt: float):
        raise NotImplementedError

    def render(self) -> np.ndarray:
        raise NotImplementedError


# ── Sparkle ───────────────────────────────────────────────────────────────────

class SparkleEffect(BaseEffect):
    """Random pixels flash into existence and fade out."""

    def update(self, dt: float):
        alive = []
        for p in self.particles:
            p.life -= dt / p.max_life
            if p.life > 0:
                alive.append(p)
        self.particles = alive

        while len(self.particles) < self._count(40):
            ml = _life(self.cfg, 0.08, 0.35)
            r, g, b = _pick_color(self.cfg)
            x, y = _emit_pos(self.cfg, self.w, self.h, 'random')
            self.particles.append(Particle(
                x=x, y=y, life=1.0, max_life=ml,
                r=r, g=g, b=b, size=_size(self.cfg),
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            alpha = math.sin(p.life * math.pi)
            self._draw_particle(canvas, p, alpha)
        return canvas


# ── Snow ──────────────────────────────────────────────────────────────────────

class SnowEffect(BaseEffect):
    """Particles drift down from the top with slight horizontal wobble."""

    def update(self, dt: float):
        drift_x = self.cfg.get('drift_x', 1.5)
        for p in self.particles:
            spd = _speed(self.cfg, 6.0, 12.0) if p.extra == 0 else p.extra
            p.extra = spd
            p.vx = drift_x * math.sin(p.vx + p.y * 0.3)
            p.x += p.vx * dt
            p.y += spd * dt
            p.life -= dt / p.max_life

        self.particles = [p for p in self.particles if p.y < self.h and p.life > 0]

        while len(self.particles) < self._count(30):
            spd = _speed(self.cfg, 6.0, 12.0)
            ml = _life(self.cfg, 1.5, 4.0)
            r, g, b = _pick_color(self.cfg) if self.cfg.get('colors') or self.cfg.get('color') \
                      else (200, 220, 255)
            self.particles.append(Particle(
                x=random.uniform(0, self.w - 1),
                y=random.uniform(-2, 0),
                vx=random.uniform(0, math.tau),
                max_life=ml, life=1.0,
                r=r, g=g, b=b,
                size=_size(self.cfg),
                extra=spd,
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            self._draw_particle(canvas, p, 0.9)
        return canvas


# ── Embers ────────────────────────────────────────────────────────────────────

class EmbersEffect(BaseEffect):
    """Glowing particles rise from the bottom and fade as they cool."""

    def update(self, dt: float):
        spread = self.cfg.get('spread', 0.4)
        drift_x = self.cfg.get('drift_x', 0.0)
        for p in self.particles:
            p.extra += dt * 3.0
            p.vx = spread * math.sin(p.extra + p.y * 0.2) * p.vy + drift_x
            p.x += p.vx * dt
            p.y -= p.vy * dt
            p.life -= dt / p.max_life

        self.particles = [p for p in self.particles if p.y > -1 and p.life > 0]

        while len(self.particles) < self._count(25):
            spd = _speed(self.cfg, 8.0, 22.0)
            ml = _life(self.cfg, 0.8, 2.5)
            r, g, b = _pick_color(self.cfg) if self.cfg.get('colors') or self.cfg.get('color') \
                      else (255, 120, 20)
            self.particles.append(Particle(
                x=random.uniform(0, self.w - 1),
                y=float(self.h),
                vy=spd,
                max_life=ml, life=1.0,
                r=r, g=g, b=b,
                size=_size(self.cfg),
                extra=random.uniform(0, math.tau),
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            alpha = p.life
            gg = int(np.clip(p.g * p.life, 0, 255))
            gb = int(np.clip(p.b * (p.life ** 2), 0, 255))
            gr = int(np.clip(p.r, 0, 255))
            shape = self.cfg.get('shape', 'dot')
            a = int(np.clip(alpha * 255, 0, 255))
            if shape == 'rect':
                self._draw_rect(canvas, p.x, p.y, gr, gg, gb, alpha, p.size)
            else:
                self._draw_dot(canvas, p.x, p.y, gr, gg, gb, alpha, p.size)
        return canvas


# ── Confetti ──────────────────────────────────────────────────────────────────

class ConfettiEffect(BaseEffect):
    """Colourful particles tumble downward."""

    _DEFAULT_COLORS = [
        [255,  50,  50], [255, 180,  30], [ 50, 220,  50],
        [ 50, 150, 255], [220,  50, 220], [255, 255,  50],
    ]

    def update(self, dt: float):
        spd = _speed(self.cfg, 4.0, 10.0)
        drift_x = self.cfg.get('drift_x', 0.0)
        for p in self.particles:
            p.vx = math.sin(p.extra) * 2.0 + drift_x
            p.extra += dt * 4.0
            p.x += p.vx * dt
            p.y += spd * dt
            p.life -= dt / p.max_life

        self.particles = [p for p in self.particles if p.y < self.h and p.life > 0]

        while len(self.particles) < self._count(20):
            ml = _life(self.cfg, 2.0, 5.0)
            if self.cfg.get('colors') or self.cfg.get('color'):
                r, g, b = _pick_color(self.cfg)
            else:
                c = random.choice(self._DEFAULT_COLORS)
                r, g, b = c[0], c[1], c[2]
            self.particles.append(Particle(
                x=random.uniform(0, self.w - 1),
                y=random.uniform(-4, 0),
                max_life=ml, life=1.0,
                r=r, g=g, b=b, size=_size(self.cfg),
                extra=random.uniform(0, math.tau),
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            self._draw_particle(canvas, p, 1.0)
        return canvas


# ── Rings ─────────────────────────────────────────────────────────────────────

class RingsEffect(BaseEffect):
    """Expanding circles emanate from random points and fade as they grow."""

    def update(self, dt: float):
        max_r  = self.cfg.get('max_radius', 20)
        expand = _speed(self.cfg, 15.0, 25.0)

        for p in self.particles:
            p.extra += expand * dt
            p.life = max(0.0, 1.0 - p.extra / max_r)

        self.particles = [p for p in self.particles if p.life > 0]

        while len(self.particles) < self._count(3):
            r, g, b = _pick_color(self.cfg) if self.cfg.get('colors') or self.cfg.get('color') \
                      else (0, 200, 255)
            self.particles.append(Particle(
                x=random.uniform(0, self.w - 1),
                y=random.uniform(0, self.h - 1),
                max_life=max_r / expand, life=1.0,
                r=r, g=g, b=b, extra=0.0,
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            self._draw_circle(canvas, int(p.x), int(p.y), int(p.extra),
                              int(p.r), int(p.g), int(p.b), p.life)
        return canvas

    def _draw_circle(self, canvas, cx, cy, radius, r, g, b, alpha):
        if radius <= 0:
            return
        a = int(alpha * 200)
        x, y, err = radius, 0, 0
        while x >= y:
            for px, py in [
                (cx+x,cy+y),(cx-x,cy+y),(cx+x,cy-y),(cx-x,cy-y),
                (cx+y,cy+x),(cx-y,cy+x),(cx+y,cy-x),(cx-y,cy-x),
            ]:
                self._draw_pixel(canvas, px, py, r, g, b, a)
            y += 1
            if err <= 0:
                err += 2*y + 1
            else:
                x -= 1
                err += 2*(y - x) + 1


# ── Rain ──────────────────────────────────────────────────────────────────────

class RainEffect(BaseEffect):
    """Fast vertical streaks fall from the top."""

    def update(self, dt: float):
        length    = self.cfg.get('length', 4)
        drift_x   = self.cfg.get('drift_x', 0.0)

        for p in self.particles:
            p.y  += p.vy * dt
            p.x  += drift_x * dt
            p.life -= dt / p.max_life

        self.particles = [p for p in self.particles if p.y < self.h + length and p.life > 0]

        while len(self.particles) < self._count(15):
            spd = _speed(self.cfg, 30.0, 50.0)
            ml  = (self.h + length) / spd
            r, g, b = _pick_color(self.cfg) if self.cfg.get('colors') or self.cfg.get('color') \
                      else (100, 150, 255)
            self.particles.append(Particle(
                x=random.uniform(0, self.w - 1),
                y=random.uniform(-(length + 2), 0),
                vy=spd, max_life=ml, life=1.0,
                r=r, g=g, b=b,
                size=_size(self.cfg),
                extra=float(length),
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            length = int(p.extra)
            ix = int(p.x)
            for i in range(length):
                iy = int(p.y) - i
                alpha = (1.0 - i / length) * 0.9
                self._draw_dot(canvas, ix, iy, int(p.r), int(p.g), int(p.b), alpha, p.size)
        return canvas


# ── Fireflies ─────────────────────────────────────────────────────────────────

class FirefliesEffect(BaseEffect):
    """Slow drifting glowing dots with sinusoidal paths."""

    def update(self, dt: float):
        spd = _speed(self.cfg, 3.0, 6.0)
        for p in self.particles:
            p.extra += dt
            p.x += math.cos(p.extra * 1.3 + p.vx) * spd * dt
            p.y += math.sin(p.extra       + p.vy) * spd * dt
            p.x %= self.w
            p.y %= self.h
            p.life = 0.5 + 0.5 * math.sin(p.extra * 2.5)

        while len(self.particles) < self._count(8):
            r, g, b = _pick_color(self.cfg) if self.cfg.get('colors') or self.cfg.get('color') \
                      else (180, 255, 100)
            self.particles.append(Particle(
                x=random.uniform(0, self.w - 1),
                y=random.uniform(0, self.h - 1),
                vx=random.uniform(0, math.tau),
                vy=random.uniform(0, math.tau),
                life=1.0, max_life=9999,
                r=r, g=g, b=b,
                size=_size(self.cfg),
                extra=random.uniform(0, math.tau),
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            self._draw_particle(canvas, p, float(np.clip(p.life, 0, 1)))
        return canvas


# ── Clouds ────────────────────────────────────────────────────────────────────

class CloudsEffect(BaseEffect):
    """Drifting nebula clumps — irregular, wispy, semi-transparent.

    Each "cloud" is not a single disk but a clump of several offset *lobes*, so
    its silhouette is irregular rather than round. Every lobe picks a colour
    from the palette, so a clump blends multiple hues like a real nebula, and a
    per-clump turbulence field eats into the density to give a soft, streaky,
    wispy texture. ``size_min``/``size_max`` mix big and small clumps in one
    layer; ``alpha_min``/``alpha_max`` set per-clump opacity. Clumps drift
    sideways and wrap horizontally so the field never empties.

    Per-layer keys (all optional):
        count       int    number of clumps            (default 6)
        size_min    int    min clump radius in px       (default 5)
        size_max    int    max clump radius in px       (default 16)
        lobes_min   int    min sub-blobs per clump      (default 3)
        lobes_max   int    max sub-blobs per clump      (default 6)
        turbulence  float  wispiness 0..1; 0=smooth     (default 0.6)
        churn       float  internal swirl speed (rad/s) (default 0.4)
        alpha_min   float  min opacity 0..1             (default 0.15)
        alpha_max   float  max opacity 0..1             (default 0.5)
        speed_min   float  min drift px/s               (default 1.5)
        speed_max   float  max drift px/s               (default 5.0)
        softness    float  edge feather 0..1            (default 0.6)
        colors      list   [[r,g,b], ...] palette (default nebula magenta/blue)
        blend       str    'add' (default, glowy) | 'normal' (matte/translucent)
    """

    # Default nebula palette: magenta → violet → blue → teal → pink.
    _DEFAULT_COLORS = [
        (200, 70, 150), (120, 80, 210), (70, 120, 220),
        (40, 170, 190), (230, 120, 180),
    ]

    def _palette(self) -> list[tuple[int, int, int]]:
        pool = self.cfg.get('colors') or self._DEFAULT_COLORS
        return [(int(c[0]), int(c[1]), int(c[2])) for c in pool]

    def _make_lobes(self, R: float, pool: list) -> list:
        """Build a clump as a centre lobe plus offset satellite lobes."""
        lo = int(self.cfg.get('lobes_min', 3))
        hi = int(self.cfg.get('lobes_max', 6))
        n = max(1, random.randint(min(lo, hi), max(lo, hi)))
        lobes = []
        for i in range(n):
            if i == 0:
                ox = oy = 0.0
                lr = R * random.uniform(0.55, 0.9)
            else:
                ang  = random.uniform(0, math.tau)
                dist = random.uniform(0.2, 0.75) * R
                ox = math.cos(ang) * dist
                oy = math.sin(ang) * dist
                lr = R * random.uniform(0.3, 0.7)
            lobes.append((ox, oy, max(1.0, lr),
                          random.uniform(0.5, 1.0), random.choice(pool)))
        return lobes

    def _reseed(self, p: Particle):
        p.lobes = self._make_lobes(float(p.size), self._palette())

    def _spawn(self, x: float | None = None) -> Particle:
        R = float(_size(self.cfg, 5, 16))
        spd = _speed(self.cfg, 1.5, 5.0)
        if random.random() < 0.5:           # drift either direction
            spd = -spd
        alpha = random.uniform(
            self.cfg.get('alpha_min', 0.15),
            self.cfg.get('alpha_max', 0.5),
        )
        if x is None:
            x = random.uniform(0, self.w - 1)
        p = Particle(
            x=x, y=random.uniform(0, self.h - 1),
            vx=spd, life=1.0, max_life=9999,
            size=int(round(R)), extra=alpha,
        )
        p.lobes = self._make_lobes(R, self._palette())
        rf = lambda: random.uniform(0.2, 0.6)   # turbulence spatial freqs
        p.warp = (rf(), rf(), random.uniform(0, math.tau),
                  rf(), rf(), random.uniform(0, math.tau))
        p.phase = random.uniform(0, math.tau)
        return p

    def update(self, dt: float):
        churn = float(self.cfg.get('churn', 0.4))
        for p in self.particles:
            p.x += p.vx * dt
            p.phase += dt * churn           # slow internal swirl
            # Wrap horizontally; account for the clump reach so it glides fully
            # off one edge before reappearing on the other (then reseed shape).
            margin = p.size * 2 + 2
            if p.vx >= 0 and p.x - margin > self.w:
                p.x = -margin; p.y = random.uniform(0, self.h - 1); self._reseed(p)
            elif p.vx < 0 and p.x + margin < 0:
                p.x = self.w + margin; p.y = random.uniform(0, self.h - 1); self._reseed(p)

        while len(self.particles) < self._count(6):
            self.particles.append(self._spawn())

    def _draw_clump(self, acc: np.ndarray, p: Particle, power: float):
        """Render one nebula clump (offset lobes + turbulence) into *acc*."""
        lobes = getattr(p, 'lobes', None)
        if not lobes:
            return
        R = max(1.0, float(p.size))
        reach = R * 1.7
        x0 = int(math.floor(p.x - reach)); x1 = int(math.ceil(p.x + reach)) + 1
        y0 = int(math.floor(p.y - reach)); y1 = int(math.ceil(p.y + reach)) + 1
        x0c, x1c = max(0, x0), min(self.w, x1)
        y0c, y1c = max(0, y0), min(self.h, y1)
        if x0c >= x1c or y0c >= y1c:
            return
        ys, xs = np.ogrid[y0c:y1c, x0c:x1c]
        xs = xs.astype(np.float32); ys = ys.astype(np.float32)
        shp = (y1c - y0c, x1c - x0c)
        wsum = np.zeros(shp, dtype=np.float32)
        cr = np.zeros(shp, dtype=np.float32)
        cg = np.zeros(shp, dtype=np.float32)
        cb = np.zeros(shp, dtype=np.float32)
        for ox, oy, lr, wt, (lcr, lcg, lcb) in lobes:
            d = np.sqrt((xs - (p.x + ox)) ** 2 + (ys - (p.y + oy)) ** 2) / lr
            f = np.clip(1.0 - d, 0.0, 1.0) ** power
            f *= wt
            wsum += f
            cr += f * lcr; cg += f * lcg; cb += f * lcb

        # Wispy turbulence (cloud-local coords; churns slowly via p.phase).
        f1, g1, ph1, f2, g2, ph2 = p.warp
        lx = xs - p.x; ly = ys - p.y
        n1 = 0.5 + 0.5 * np.sin(lx * f1 + ly * g1 + ph1 + p.phase)
        n2 = 0.5 + 0.5 * np.sin(lx * f2 - ly * g2 + ph2 - p.phase * 0.7)
        turb = 0.6 * n1 + 0.4 * n2
        floor = 1.0 - float(np.clip(self.cfg.get('turbulence', 0.6), 0.0, 1.0))
        turb = floor + (1.0 - floor) * turb

        dens = np.clip(wsum * turb, 0.0, 1.0)
        a = dens * float(p.extra)                 # 0..base_alpha
        safe = np.where(wsum > 1e-6, wsum, 1.0)   # hue = falloff-weighted mean
        rr = cr / safe; gg = cg / safe; bb = cb / safe

        sub = acc[y0c:y1c, x0c:x1c]
        stronger = a > sub[:, :, 3]
        sub[:, :, 0] = np.where(stronger, rr, sub[:, :, 0])
        sub[:, :, 1] = np.where(stronger, gg, sub[:, :, 1])
        sub[:, :, 2] = np.where(stronger, bb, sub[:, :, 2])
        sub[:, :, 3] = np.maximum(sub[:, :, 3], a)

    def render(self) -> np.ndarray:
        acc = np.zeros((self.h, self.w, 4), dtype=np.float32)
        softness = float(np.clip(self.cfg.get('softness', 0.6), 0.0, 1.0))
        power = 1.0 + (1.0 - softness) * 2.0
        # Biggest first so smaller, denser clumps win the max-union on top.
        for p in sorted(self.particles, key=lambda q: -q.size):
            self._draw_clump(acc, p, power)
        out = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        out[:, :, :3] = np.clip(acc[:, :, :3], 0, 255).astype(np.uint8)
        out[:, :, 3] = np.clip(acc[:, :, 3] * 255.0, 0, 255).astype(np.uint8)
        return out


# ── Star field (3-D parallax) ─────────────────────────────────────────────────

class StarfieldEffect(BaseEffect):
    """3-D parallax star field: stars stream outward from the canvas centre.

    The centre of the 128x32 canvas is the vanishing point (the origin); the
    panel edges are the near plane. Each star has a fixed world direction
    (``vx``/``vy`` in [-1, 1]) and a depth ``z`` stored in ``extra``. Depth
    shrinks every frame, so the perspective projection ``screen = centre +
    dir * fov / z`` pushes the star from the centre out toward the edges,
    growing brighter and larger as it "approaches". Stars recycle to the far
    depth once they leave the screen, so the field never empties.

    Per-layer keys (all optional):
        count       int    number of stars                 (default 70)
        speed_min   float  min approach speed (depth/s)     (default 1.2)
        speed_max   float  max approach speed (depth/s)     (default 3.0)
        colors      list   [[r,g,b], ...] star palette      (default whites)
        size_max    int    max radius for near stars        (default 2)
        fov         float  projection scale (px)            (default w * 0.5)
    """

    _DEFAULT_COLORS = [
        (255, 255, 255), (200, 220, 255), (255, 240, 210), (210, 235, 255),
    ]
    _SPEED = (1.2, 3.0)
    _ZFAR = 8.0
    _ZNEAR = 0.55

    def _pick(self) -> tuple[int, int, int]:
        pool = self.cfg.get('colors') or self._DEFAULT_COLORS
        c = random.choice(pool)
        return int(c[0]), int(c[1]), int(c[2])

    def _fov(self) -> float:
        return float(self.cfg.get('fov', self.w * 0.5))

    def _respawn(self, p: Particle):
        """Send a star back to the far plane with a fresh direction/colour."""
        wx = random.uniform(-1, 1)
        wy = random.uniform(-1, 1)
        while abs(wx) < 0.05 and abs(wy) < 0.05:   # avoid a dead-centre star
            wx = random.uniform(-1, 1)
            wy = random.uniform(-1, 1)
        p.vx, p.vy = wx, wy
        p.extra = self._ZFAR
        p.max_life = _speed(self.cfg, *self._SPEED)
        p.r, p.g, p.b = self._pick()
        p.life = 0.0

    def _spawn(self) -> Particle:
        p = Particle(max_life=1.0)
        self._respawn(p)
        p.extra = random.uniform(self._ZNEAR + 0.5, self._ZFAR)   # spread depths
        return p

    def update(self, dt: float):
        cx, cy = self.w * 0.5, self.h * 0.5
        fov = self._fov()
        size_max = int(self.cfg.get('size_max', 2))
        span = self._ZFAR - self._ZNEAR
        for p in self.particles:
            p.extra -= p.max_life * dt          # approach: depth shrinks
            recycle = p.extra <= self._ZNEAR
            if not recycle:
                f = fov / p.extra
                p.x = cx + p.vx * f
                p.y = cy + p.vy * f
                if p.x < -2 or p.x > self.w + 1 or p.y < -2 or p.y > self.h + 1:
                    recycle = True
            if recycle:
                self._respawn(p)
                f = fov / p.extra
                p.x = cx + p.vx * f
                p.y = cy + p.vy * f
            near = (self._ZFAR - p.extra) / span
            p.life = float(np.clip(near, 0.0, 1.0))
            p.size = size_max if (size_max > 1 and p.life > 0.75) else 1

        while len(self.particles) < self._count(70):
            self.particles.append(self._spawn())

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            alpha = 0.2 + 0.8 * p.life
            self._draw_dot(canvas, p.x, p.y, int(p.r), int(p.g), int(p.b),
                           alpha, p.size)
        return canvas


# ── Warp (hyperspace) ─────────────────────────────────────────────────────────

class WarpEffect(StarfieldEffect):
    """Hyperspace warp — the star field cranked to "jump to lightspeed".

    Reuses the star field's centre-origin perspective projection but flies the
    stars outward faster and smears each into a radial streak pointing back to
    the centre. Streak length grows as a star nears the edge, so the field
    rushes past in bright tapering lines.

    Per-layer keys (all optional):
        count       int    number of stars                 (default 60)
        speed_min   float  min approach speed (depth/s)     (default 2.5)
        speed_max   float  max approach speed (depth/s)     (default 5.5)
        colors      list   [[r,g,b], ...] palette           (default whites)
        streak      float  streak length multiplier         (default 1.0)
        size_max    int    max radius for the leading dot    (default 1)
    """

    _SPEED = (2.5, 5.5)
    _ZNEAR = 0.4

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        cx, cy = self.w * 0.5, self.h * 0.5
        gain = float(self.cfg.get('streak', 1.0))
        for p in self.particles:
            alpha = 0.25 + 0.75 * p.life
            dx, dy = p.x - cx, p.y - cy
            dist = math.hypot(dx, dy) or 1.0
            ux, uy = dx / dist, dy / dist            # outward unit vector
            length = (1.0 + p.life * 6.0) * gain     # longer as it nears edge
            n = max(1, int(length))
            for i in range(n + 1):                   # streak back toward centre
                t = i / n
                a = alpha * (1.0 - t)
                if a <= 0:
                    break
                self._draw_dot(canvas, p.x - ux * length * t, p.y - uy * length * t,
                               int(p.r), int(p.g), int(p.b), a,
                               p.size if i == 0 else 1)
        return canvas


# ── Constellation (still twinkling sky) ───────────────────────────────────────

class ConstellationEffect(BaseEffect):
    """A still night sky: stars hold fixed positions and twinkle, each breathing
    brightness on its own phase and rate. A fraction are "bright" stars that sit
    a touch larger and grow a soft cross-shaped glint at their peak. Nothing
    moves off screen, so no centre/edge geometry applies.

    Per-layer keys (all optional):
        count        int    number of stars                (default 50)
        colors       list   [[r,g,b], ...] palette          (default whites)
        twinkle_min  float  slowest twinkle rate (rad/s)    (default 0.8)
        twinkle_max  float  fastest twinkle rate (rad/s)    (default 3.0)
        bright_frac  float  fraction that glint  0..1        (default 0.15)
    """

    _DEFAULT_COLORS = [
        (255, 255, 255), (200, 220, 255), (255, 240, 210), (255, 255, 235),
    ]

    def update(self, dt: float):
        # vx = twinkle rate, vy = base brightness, extra = phase, size 2 = bright.
        for p in self.particles:
            p.extra += p.vx * dt
            p.life = p.vy * (0.45 + 0.55 * (0.5 + 0.5 * math.sin(p.extra)))

        while len(self.particles) < self._count(50):
            pool = self.cfg.get('colors') or self._DEFAULT_COLORS
            c = random.choice(pool)
            bright = random.random() < float(self.cfg.get('bright_frac', 0.15))
            self.particles.append(Particle(
                x=random.uniform(0, self.w - 1),
                y=random.uniform(0, self.h - 1),
                vx=random.uniform(self.cfg.get('twinkle_min', 0.8),
                                  self.cfg.get('twinkle_max', 3.0)),
                vy=1.0 if bright else random.uniform(0.4, 0.85),
                r=int(c[0]), g=int(c[1]), b=int(c[2]),
                size=2 if bright else 1,
                max_life=9999, life=1.0,
                extra=random.uniform(0, math.tau),
            ))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        for p in self.particles:
            alpha = float(np.clip(p.life, 0.0, 1.0))
            r, g, b = int(p.r), int(p.g), int(p.b)
            self._draw_dot(canvas, p.x, p.y, r, g, b, alpha, 1)
            if p.size >= 2 and alpha > 0.55:        # soft cross glint at peak
                a2 = (alpha - 0.55) * 1.5
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    self._draw_dot(canvas, p.x + dx, p.y + dy, r, g, b, a2, 1)
        return canvas


# ── Shooting stars (meteors) ──────────────────────────────────────────────────

class ShootingStarsEffect(BaseEffect):
    """Occasional meteors that streak from the canvas centre out to a panel edge,
    leaving a fading tail. Sparse by design — they punctuate a calm sky rather
    than fill it. The spawn origin is the canvas centre (the origin); meteors
    fly radially out to the far edges and recycle once they leave the screen.

    Per-layer keys (all optional):
        count        int    max simultaneous meteors        (default 3)
        colors       list   [[r,g,b], ...] palette           (default white/blue)
        speed_min    float  min px/s                         (default 55)
        speed_max    float  max px/s                         (default 90)
        rate         float  spawns per second                (default 0.8)
        tail         int    tail length in px                (default 8)
    """

    _DEFAULT_COLORS = [(255, 255, 255), (200, 225, 255), (255, 240, 220)]

    def _spawn(self, cx: float, cy: float) -> Particle:
        ang = random.uniform(0, math.tau)
        spd = _speed(self.cfg, 55.0, 90.0)
        pool = self.cfg.get('colors') or self._DEFAULT_COLORS
        c = random.choice(pool)
        r0 = random.uniform(0, 6)                 # nudge off-centre so the tail reads
        return Particle(
            x=cx + math.cos(ang) * r0, y=cy + math.sin(ang) * r0,
            vx=math.cos(ang) * spd, vy=math.sin(ang) * spd,
            r=int(c[0]), g=int(c[1]), b=int(c[2]),
            size=_size(self.cfg, 1, 1),
            max_life=2.5, life=1.0, extra=ang,
        )

    def update(self, dt: float):
        cx, cy = self.w * 0.5, self.h * 0.5
        tail = int(self.cfg.get('tail', 8))
        for p in self.particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.life -= dt / p.max_life
        self.particles = [
            p for p in self.particles
            if p.life > 0 and -tail <= p.x <= self.w + tail
            and -tail <= p.y <= self.h + tail
        ]

        rate = float(self.cfg.get('rate', 0.8)) * self._intensity
        self._acc = getattr(self, '_acc', 0.0) + dt * rate
        cap = self._count(3)
        while self._acc >= 1.0:
            self._acc -= 1.0
            if len(self.particles) < cap:
                self.particles.append(self._spawn(cx, cy))

    def render(self) -> np.ndarray:
        canvas = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        tail = int(self.cfg.get('tail', 8))
        for p in self.particles:
            spd = math.hypot(p.vx, p.vy) or 1.0
            ux, uy = p.vx / spd, p.vy / spd
            head = float(np.clip(p.life * 1.5, 0.0, 1.0))
            for i in range(tail):
                a = (1.0 - i / tail) * head
                if a <= 0:
                    break
                self._draw_dot(canvas, p.x - ux * i, p.y - uy * i,
                               int(p.r), int(p.g), int(p.b), a, 1)
        return canvas


# ── Registry ──────────────────────────────────────────────────────────────────

EFFECT_REGISTRY: dict[str, type] = {
    'sparkle':       SparkleEffect,
    'snow':          SnowEffect,
    'embers':        EmbersEffect,
    'confetti':      ConfettiEffect,
    'rings':         RingsEffect,
    'rain':          RainEffect,
    'fireflies':     FirefliesEffect,
    'clouds':        CloudsEffect,
    'starfield':     StarfieldEffect,
    'warp':          WarpEffect,
    'constellation': ConstellationEffect,
    'shootingstars': ShootingStarsEffect,
}


# ── Preset loader ─────────────────────────────────────────────────────────────

_PRESETS: dict[str, dict] = {}

def _load_presets():
    path = os.path.join(os.path.dirname(__file__), '..', 'particles', 'presets.yaml')
    path = os.path.normpath(path)
    if not _YAML_OK or not os.path.exists(path):
        return
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        _PRESETS.update(data)
    except Exception as e:
        print(f"[particles] could not load presets: {e}")

_load_presets()


def _resolve_cfg(cfg) -> dict:
    """
    Normalise any config form into a canonical dict with a 'layers' key.

    Accepts:
      - None / 'none'                 → no layers
      - 'embers'                      → single-layer shorthand
      - {'active': 'embers', ...}     → legacy single-layer dict
      - {'preset': 'fire'}            → named preset from presets.yaml
      - {'layers': [...]}             → explicit multi-layer
    """
    if cfg is None or cfg == 'none' or cfg == {}:
        return {'layers': []}

    if isinstance(cfg, str):
        if cfg == 'none':
            return {'layers': []}
        return {'layers': [{'effect': cfg}]}

    if 'preset' in cfg:
        name = cfg['preset']
        preset = _PRESETS.get(name)
        if preset is None:
            print(f"[particles] unknown preset '{name}'")
            return {'layers': []}
        return _resolve_cfg(preset)

    if 'layers' in cfg:
        return cfg

    # Single-layer shorthand dict: {effect: 'embers', count: 30, colors: [...], ...}
    if 'effect' in cfg:
        return {'layers': [cfg]}

    # Legacy: {active: 'embers', intensity: 1.0, embers: {count: 30, ...}}
    name = cfg.get('active', 'none')
    if name == 'none' or not name:
        return {'layers': []}
    layer_cfg: dict = {'effect': name}
    layer_cfg.update(cfg.get(name, {}))
    layer_cfg['intensity'] = cfg.get('intensity', 1.0)
    return {'layers': [layer_cfg]}


# ── ParticleLayer ─────────────────────────────────────────────────────────────

class ParticleLayer:
    """One effect instance + blend mode."""

    def __init__(self, layer_cfg: dict, w: int, h: int):
        effect_name = layer_cfg.get('effect', 'none')
        self.blend  = layer_cfg.get('blend', 'add')
        if effect_name == 'none' or effect_name not in EFFECT_REGISTRY:
            if effect_name != 'none':
                print(f"[particles] unknown effect '{effect_name}'")
            self._effect: BaseEffect | None = None
            return
        cls = EFFECT_REGISTRY[effect_name]
        self._effect = cls(w, h, layer_cfg)

    def update(self, dt: float):
        if self._effect:
            self._effect.update(dt)

    def render(self) -> np.ndarray | None:
        if self._effect is None:
            return None
        return self._effect.render()


# ── ParticleSystem ────────────────────────────────────────────────────────────

class ParticleSystem:
    """
    Multi-layer particle compositor.

    render() returns a single composited (H, W, 4) RGBA array.
    Returns None if there are no active layers.
    """

    def __init__(self, width: int, height: int, cfg):
        self.w = width
        self.h = height
        self._layers: list[ParticleLayer] = []
        self._build_layers(_resolve_cfg(cfg))

    def _build_layers(self, resolved: dict):
        self._layers = [
            ParticleLayer(lc, self.w, self.h)
            for lc in resolved.get('layers', [])
        ]

    def set_effect(self, cfg):
        """Replace all layers at runtime (e.g. from IPC set_effect command)."""
        self._build_layers(_resolve_cfg(cfg))

    def update(self, dt: float):
        for layer in self._layers:
            layer.update(dt)

    def render(self) -> tuple[np.ndarray, str] | None:
        """
        Composite all layers and return (rgba, blend_mode) or None.

        blend_mode is 'add' when all layers use additive blend (typical for
        fire/sparkle/glow), otherwise 'normal'.  The Renderer.composite()
        method handles both forms.
        """
        if not self._layers:
            return None

        out = np.zeros((self.h, self.w, 4), dtype=np.uint16)
        has_content  = False
        all_additive = True

        for layer in self._layers:
            frame = layer.render()
            if frame is None:
                continue
            has_content = True
            if layer.blend != 'add':
                all_additive = False
            if layer.blend == 'add':
                out += frame.astype(np.uint16)
            else:
                src_a = frame[:, :, 3:4].astype(np.float32) / 255.0
                dst_a = out[:, :, 3:4].astype(np.float32) / 255.0
                out_a = src_a + dst_a * (1.0 - src_a)
                safe  = np.where(out_a > 0, out_a, 1.0)
                out[:, :, :3] = np.clip(
                    (frame[:, :, :3].astype(np.float32) * src_a
                     + out[:, :, :3].astype(np.float32) * dst_a * (1.0 - src_a)) / safe,
                    0, 65535
                ).astype(np.uint16)
                # Keep alpha on the same 0..255 scale the read above assumes
                # (and that the final clip preserves), so soft/semi-transparent
                # layers like clouds composite at their true opacity instead of
                # saturating to fully opaque.
                out[:, :, 3:4] = np.clip(out_a * 255.0, 0, 255).astype(np.uint16)

        if not has_content:
            return None

        rgba = np.clip(out, 0, 255).astype(np.uint8)
        return (rgba, 'add' if all_additive else 'normal')
