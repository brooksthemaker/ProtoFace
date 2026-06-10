"""
POSIX shared memory frame writer.

Writes the latest rendered RGB canvas into /dev/shm/protoface_frame so that
ProtoHUD (C++ process) can map it and display a live panel preview widget.

Layout (24577 bytes for 128×64 canvas):
  byte 0          uint8  sequence counter — incremented each write so the
                         reader can detect a new frame without pixel comparison
  bytes 1-24576   uint8  W×H RGB pixel data, row-major (R G B R G B ...)

The width and height are configurable at construction time; the C++ reader
(shm_frame_reader.h) must be compiled with matching W / H constants.
"""

from __future__ import annotations

import mmap
import os


class ShmWriter:
    def __init__(self, path: str = '/dev/shm/protoface_frame',
                 width: int = 128, height: int = 64):
        self._path   = path
        self._seq    = 0
        self._pixels = width * height * 3
        self._size   = 1 + self._pixels

        try:
            self._fd = open(path, 'w+b')
            self._fd.write(b'\x00' * self._size)
            self._fd.flush()
            self._mm = mmap.mmap(self._fd.fileno(), self._size)
        except OSError as e:
            print(f'[shm] cannot create {path}: {e} — panel preview unavailable')
            self._fd = None
            self._mm = None

    def write(self, frame) -> None:
        """Write a (H, W, 3) uint8 RGB ndarray into shared memory."""
        if self._mm is None:
            return
        data = bytes(frame.data) if frame.data.c_contiguous else frame.tobytes()
        self._seq = (self._seq + 1) & 0xFF
        # Pixels first, sequence byte last — readers treat a seq change as
        # "frame ready", so bumping it before the copy hands them torn frames.
        self._mm[1:1 + self._pixels]   = data
        self._mm[0]                    = self._seq

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
        if self._fd is not None:
            self._fd.close()
        try:
            os.unlink(self._path)
        except OSError:
            pass
