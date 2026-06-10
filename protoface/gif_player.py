"""
GIF playback.

Loads GIF files from a folder, decodes all frames and their durations with
Pillow, then advances playback on each update() call.

Usage in run.py:
    gif = GifPlayer(width, height)
    gif.load('gifs/celebration.gif')   # or pass None to stop
    ...
    frame_rgba = gif.get_frame(dt)     # None if not playing
    if frame_rgba is not None:
        # use as face layer replacement or overlay
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError


class GifPlayer:
    def __init__(self, width: int, height: int):
        self.w = width
        self.h = height
        self._frames: list[np.ndarray] = []
        self._durations: list[float]   = []   # seconds per frame
        self._frame_idx = 0
        self._elapsed   = 0.0
        self._playing   = False
        self._loop      = True

    # ── Loading ───────────────────────────────────────────────────────────────

    def load(self, path: str, loop: bool = True):
        """Decode all frames from *path*.  Call with None to stop playback."""
        if path is None:
            self.stop()
            return

        frames:    list[np.ndarray] = []
        durations: list[float]      = []

        # `with` closes the underlying file handle — Pillow keeps it open for
        # lazy frame seeks, which leaked an fd per load() with auto_cycle.
        try:
            with Image.open(path) as img:
                try:
                    while True:
                        frame = img.convert('RGBA').resize(
                            (self.w, self.h), Image.NEAREST)
                        frames.append(np.array(frame, dtype=np.uint8))
                        # GIF stores duration in centiseconds; convert to seconds
                        duration = img.info.get('duration', 100) / 1000.0
                        durations.append(max(0.016, duration))  # floor at ~60fps
                        img.seek(img.tell() + 1)
                except EOFError:
                    pass
        except (FileNotFoundError, UnidentifiedImageError) as e:
            print(f"[gif] cannot open '{path}': {e}")
            return

        if not frames:
            print(f"[gif] no frames decoded from '{path}'")
            return

        self._frames    = frames
        self._durations = durations

        self._loop      = loop
        self._frame_idx = 0
        self._elapsed   = 0.0
        self._playing   = True

    def stop(self):
        self._playing = False
        self._frames  = []

    # ── Playback ──────────────────────────────────────────────────────────────

    def update(self, dt: float):
        if not self._playing or not self._frames:
            return
        self._elapsed += dt
        while self._elapsed >= self._durations[self._frame_idx]:
            self._elapsed -= self._durations[self._frame_idx]
            self._frame_idx += 1
            if self._frame_idx >= len(self._frames):
                if self._loop:
                    self._frame_idx = 0
                else:
                    self._frame_idx = len(self._frames) - 1
                    self._playing   = False
                    return

    def get_frame(self) -> np.ndarray | None:
        """Return the current frame as (H, W, 4) RGBA uint8, or None if idle."""
        if not self._playing or not self._frames:
            return None
        return self._frames[self._frame_idx]

    @property
    def playing(self) -> bool:
        return self._playing

    # ── Folder scanning ───────────────────────────────────────────────────────

    @staticmethod
    def scan_folder(folder: str) -> list[str]:
        """Return sorted list of .gif file paths in *folder*."""
        p = Path(folder)
        if not p.exists():
            return []
        return sorted(str(f) for f in p.glob('*.gif'))
