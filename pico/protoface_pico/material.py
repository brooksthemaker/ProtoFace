"""Material colour for the Pico face engine.

On the CM5 the material is multiplied by the face's luminance per pixel. The
Pico achieves the same result for a *solid* material almost for free using a
palette ramp: baked face bitmaps store luminance as an index 0..LEVELS-1, and
the material colour simply defines that palette's ramp. Recolouring the face is
then a palette rewrite (a few dozen entries), not a per-pixel multiply.

    index 0           -> transparent (face shape mask / background shows through)
    index 1..LEVELS-1 -> (i / (LEVELS-1)) * colour * (brightness / 255)

Scrolling/tiled PNG materials from the CM5 build are not yet ported (they need a
second masked bitmap layer); ``SolidMaterial`` covers the common case.
"""

# Number of luminance steps baked into a face bitmap (index 0 = transparent,
# 1..LEVELS-1 = dark->bright).
LEVELS = 16
# displayio.Palette / Bitmap value_count. Pillow writes 8-bit indexed BMPs
# (256-entry palette), and adafruit_imageload mirrors that, so the on-device
# bitmaps must also be 256-slot for bitmaptools.blit to match bit depth. Only
# indices 0..LEVELS-1 are used; the rest stay black.
PALETTE_LEN = 256


class SolidMaterial:
    def __init__(self, color):
        self.color = tuple(int(c) for c in color)

    def update(self, dt):
        pass  # solid material is static

    def apply_to_palette(self, palette, brightness=255):
        """Write the luminance->colour ramp into *palette* (a displayio.Palette
        of length LEVELS). Index 0 is made transparent."""
        r, g, b = self.color
        scale = brightness / 255.0
        palette[0] = 0x000000
        palette.make_transparent(0)
        denom = LEVELS - 1
        for i in range(1, LEVELS):
            lum = (i / denom) * scale
            pr = int(r * lum) & 0xFF
            pg = int(g * lum) & 0xFF
            pb = int(b * lum) & 0xFF
            palette[i] = (pr << 16) | (pg << 8) | pb


def make(name_or_rgb, resolve):
    """Build a material from config: a name, [r,g,b], or 'solid:r,g,b'.

    *resolve* is config.resolve_color, passed in to avoid a circular import.
    """
    return SolidMaterial(resolve(name_or_rgb))
