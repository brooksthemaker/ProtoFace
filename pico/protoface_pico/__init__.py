"""Protoface for Raspberry Pi Pico 2 / Pico 2 W (RP2350, CircuitPython).

A standalone LED-face engine that re-implements the CM5 Protoface pipeline on a
microcontroller:

    matrix.py     HUB75 panel via rgbmatrix/framebufferio (Protomatter, PIO+DMA)
    config.py     JSON config loader (no PyYAML on device)
    state.py      FaceState — expression/blink/mouth/wiggle/boop animation logic
    material.py   solid + palette-ramp colour tint (luminance x colour)
    face.py       displayio face engine: expressions, crossfade, blink, mouth
    particles.py  lightweight particle overlay (subset of the CM5 effects)

This package targets CircuitPython 9+ on the RP2350. It is intentionally free of
numpy/Pillow/pygame; heavy pixel work is delegated to displayio + bitmaptools.
"""

__version__ = "0.1.0-pico"
