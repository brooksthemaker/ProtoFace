"""
Procedural "animated eye" reactions.

A numpy port of ProtoHUD's eye_animations.cpp.  render_eye_animation() returns
an (H, W, 3) uint8 RGB frame that takes over the panels when a boop zone is
rapidly triggered (see reactions.ReactionController).  The six animations match
ProtoHUD's face::EyeAnim enum, in order.
"""

from __future__ import annotations

import numpy as np

# Order matches ProtoHUD's face::EyeAnim enum (Spiral=0 … Glitch=5).
EYE_ANIMS = ['spiral', 'rings', 'hearts', 'swirl', 'starburst', 'glitch']

_U32 = np.uint64(0xFFFFFFFF)


def _hash01(x: np.ndarray, y: np.ndarray, s: int) -> np.ndarray:
    """Vectorised deterministic hash → [0, 1).  Mirrors the C uint32 hash."""
    h = (x.astype(np.uint64) * np.uint64(374761393)) & _U32
    h = (h + ((y.astype(np.uint64) * np.uint64(668265263)) & _U32)) & _U32
    h = (h + ((np.uint64(s & 0xFFFFFFFF) * np.uint64(2246822519)) & _U32)) & _U32
    h = ((h ^ (h >> np.uint64(13))) * np.uint64(1274126177)) & _U32
    h = (h ^ (h >> np.uint64(16))) & _U32
    return (h & np.uint64(0xFFFFFF)).astype(np.float64) / float(0x1000000)


def _paint(inten: np.ndarray, rgb) -> np.ndarray:
    """Primary colour scaled by intensity, with a white core as intensity → 1."""
    inten = np.clip(inten, 0.0, 1.0)
    white = np.clip((inten - 0.82) / 0.18, 0.0, 1.0) * 150.0
    r = np.clip(rgb[0] * inten + white, 0, 255)
    g = np.clip(rgb[1] * inten + white, 0, 255)
    b = np.clip(rgb[2] * inten + white, 0, 255)
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def render_eye_animation(anim: str, t: float, w: int, h: int,
                         speed: float = 1.0, size: float = 1.0,
                         rgb=(0, 220, 180)) -> np.ndarray:
    """Render one animated-eye frame as (H, W, 3) uint8 RGB."""
    w = max(1, int(w))
    h = max(1, int(h))
    rgb = tuple(float(c) for c in rgb)[:3]
    sz = max(0.1, float(size))
    sp = float(speed)

    ys, xs = np.mgrid[0:h, 0:w]

    if anim == 'glitch':
        block = max(2, int(round(6.0 * sz)))
        step  = int(np.floor(t * max(0.1, sp) * 12.0))
        bx = xs // block
        by = ys // block
        r = _hash01(bx, by, step)
        inten = np.where(r > 0.55, 0.35 + (r - 0.55) * 1.6, 0.0)
        flash = _hash01(bx, by, step * 7 + 3) > 0.93
        inten = np.where(flash, 1.0, inten)
        return _paint(inten, rgb)

    cx = (w - 1) * 0.5
    cy = (h - 1) * 0.5
    scale = max(1.0, min(w, h) * 0.5)          # radius → ~1 at edge
    dx = (xs - cx) / scale
    dy = (ys - cy) / scale
    rr = np.sqrt(dx * dx + dy * dy)            # 0 at centre
    a  = np.arctan2(dy, dx)

    if anim == 'spiral':
        v = np.sin(2.0 * a + rr * (6.0 / sz) - t * 4.0 * sp)
        inten = np.clip(v * 1.3, 0.0, 1.0) * np.clip(1.15 - rr * 0.25, 0.0, 1.0)
    elif anim == 'rings':
        v = np.sin(rr * (10.0 / sz) - t * 5.0 * sp)
        inten = np.clip(v * 1.4, 0.0, 1.0)
    elif anim == 'hearts':
        pulse = 0.82 + 0.18 * np.sin(t * 4.0 * sp)
        k  = 1.0 / (1.25 * sz * pulse)
        hx = dx * k
        hy = -dy * k                            # y up
        q  = hx * hx + hy * hy - 1.0
        f  = q * q * q - hx * hx * hy * hy * hy
        inten = np.where(f <= 0.0, 0.65 + 0.35 * pulse, 0.0)
    elif anim == 'swirl':
        v = np.sin(3.0 * a + rr * (8.0 / sz) - t * 3.0 * sp)
        inten = (0.5 + 0.5 * v) * np.clip(1.2 - rr * 0.3, 0.0, 1.0)
    elif anim == 'starburst':
        v = np.cos(12.0 * a - t * 2.5 * sp)
        inten = (np.clip(v, 0.0, 1.0) * np.clip(1.1 - rr * 0.55, 0.0, 1.0)
                 * (0.6 + 0.4 * np.sin(rr * (6.0 / sz) - t * 3.0 * sp)))
    else:
        inten = np.zeros((h, w), dtype=np.float64)

    return _paint(inten, rgb)
