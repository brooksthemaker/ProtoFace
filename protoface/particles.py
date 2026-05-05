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
    return random.randint(
        cfg.get('size_min', default_min),
        cfg.get('size_max', default_max),
    )


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


# ── Registry ──────────────────────────────────────────────────────────────────

EFFECT_REGISTRY: dict[str, type] = {
    'sparkle':   SparkleEffect,
    'snow':      SnowEffect,
    'embers':    EmbersEffect,
    'confetti':  ConfettiEffect,
    'rings':     RingsEffect,
    'rain':      RainEffect,
    'fireflies': FirefliesEffect,
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
                out[:, :, 3:4] = np.clip(out_a * 65535, 0, 65535).astype(np.uint16)

        if not has_content:
            return None

        rgba = np.clip(out, 0, 255).astype(np.uint8)
        return (rgba, 'add' if all_additive else 'normal')
