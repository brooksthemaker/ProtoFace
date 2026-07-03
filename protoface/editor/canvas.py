"""
Pixel drawing tools + undo, as pure numpy operations on (H, W, 4) uint8 RGBA
arrays.  No pygame dependency, so every tool is unit-testable headless.

Colours are (r, g, b, a) tuples.  The eraser is just painting (0, 0, 0, 0).
"""

from __future__ import annotations

import numpy as np

TOOLS = ('pencil', 'eraser', 'bucket', 'eyedrop', 'line', 'rect')
TRANSPARENT = (0, 0, 0, 0)


def stamp(arr: np.ndarray, x: int, y: int, rgba, brush: int = 1):
    """Paint a brush×brush square roughly centred on (x, y)."""
    h, w = arr.shape[:2]
    r = brush // 2
    x0, y0 = max(0, x - r), max(0, y - r)
    x1, y1 = min(w, x - r + brush), min(h, y - r + brush)
    if x1 > x0 and y1 > y0:
        arr[y0:y1, x0:x1] = rgba


def erase(arr: np.ndarray, x: int, y: int, brush: int = 1):
    stamp(arr, x, y, TRANSPARENT, brush)


def line_points(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham integer line from (x0,y0) to (x1,y1), inclusive."""
    pts: list[tuple[int, int]] = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return pts


def draw_line(arr, x0, y0, x1, y1, rgba, brush=1):
    for (px, py) in line_points(x0, y0, x1, y1):
        stamp(arr, px, py, rgba, brush)


def draw_rect(arr, x0, y0, x1, y1, rgba, brush=1, filled=False):
    lo_x, hi_x = sorted((x0, x1))
    lo_y, hi_y = sorted((y0, y1))
    if filled:
        h, w = arr.shape[:2]
        cx0, cy0 = max(0, lo_x), max(0, lo_y)
        cx1, cy1 = min(w, hi_x + 1), min(h, hi_y + 1)
        if cx1 > cx0 and cy1 > cy0:
            arr[cy0:cy1, cx0:cx1] = rgba
    else:
        draw_line(arr, lo_x, lo_y, hi_x, lo_y, rgba, brush)
        draw_line(arr, lo_x, hi_y, hi_x, hi_y, rgba, brush)
        draw_line(arr, lo_x, lo_y, lo_x, hi_y, rgba, brush)
        draw_line(arr, hi_x, lo_y, hi_x, hi_y, rgba, brush)


def bucket_fill(arr, x, y, rgba):
    """Flood-fill the 4-connected region of pixels matching arr[y, x]."""
    h, w = arr.shape[:2]
    if not (0 <= x < w and 0 <= y < h):
        return
    target = arr[y, x].copy()
    new = np.array(rgba, dtype=np.uint8)
    if np.array_equal(target, new):
        return
    stack = [(x, y)]
    while stack:
        cx, cy = stack.pop()
        if not (0 <= cx < w and 0 <= cy < h):
            continue
        if not np.array_equal(arr[cy, cx], target):
            continue
        arr[cy, cx] = new
        stack.append((cx + 1, cy))
        stack.append((cx - 1, cy))
        stack.append((cx, cy + 1))
        stack.append((cx, cy - 1))


def pick(arr, x, y):
    """Eyedropper — return the (r, g, b, a) tuple at (x, y), or None."""
    h, w = arr.shape[:2]
    if 0 <= x < w and 0 <= y < h:
        return tuple(int(v) for v in arr[y, x])
    return None


# ── Undo / redo ───────────────────────────────────────────────────────────────

class UndoStack:
    """Undo/redo of full-array snapshots, tagged with the expression name so an
    undo restores the change to the right sprite even after switching tabs."""

    def __init__(self, limit: int = 32):
        self.limit = limit
        self._undo: list[tuple[str, np.ndarray]] = []
        self._redo: list[tuple[str, np.ndarray]] = []

    def record(self, name: str, arr: np.ndarray):
        """Snapshot *arr* as the pre-edit state before a stroke is applied."""
        self._undo.append((name, arr.copy()))
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, cur_name: str, cur_arr: np.ndarray):
        if not self._undo:
            return None
        self._redo.append((cur_name, cur_arr.copy()))
        return self._undo.pop()

    def redo(self, cur_name: str, cur_arr: np.ndarray):
        if not self._redo:
            return None
        self._undo.append((cur_name, cur_arr.copy()))
        return self._redo.pop()
