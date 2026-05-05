"""
Core compositor.  Assembles background, face, and particle layers into a
final (H, W, 3) uint8 frame ready to push to the output.
"""

import numpy as np
from PIL import Image


class Renderer:
    def __init__(self, width: int, height: int):
        self.w = width
        self.h = height

    # ── Layer builders ────────────────────────────────────────────────────────

    def solid_layer(self, color: tuple) -> np.ndarray:
        """Return an (H, W, 3) uint8 array filled with *color* (R, G, B)."""
        layer = np.empty((self.h, self.w, 3), dtype=np.uint8)
        layer[:] = color
        return layer

    # ── Material application ──────────────────────────────────────────────────

    def apply_material(self, face_rgba: np.ndarray,
                       material_rgb: np.ndarray) -> np.ndarray:
        """
        Combine a face sprite with a material colour layer.

        face_rgba   — (H, W, 4) uint8; RGB = detail/shading, A = shape mask
        material_rgb — (H, W, 3) uint8; the colour/pattern to paint the face

        Result: material colour multiplied by the face's normalised luminance,
        then composited over a transparent (zero) background using the face alpha.
        White face pixels show the material at full saturation; dark/grey pixels
        shade it.  Fully transparent pixels contribute nothing.

        Returns (H, W, 4) uint8 — still carries alpha so composite() can blend
        it over the background correctly.
        """
        face_rgb = face_rgba[:, :, :3].astype(np.float32)
        alpha    = face_rgba[:, :, 3:].astype(np.float32) / 255.0  # (H,W,1)
        mat      = material_rgb.astype(np.float32)

        # Luminance of the face art drives how much of the material shows through
        lum = face_rgb.mean(axis=2, keepdims=True) / 255.0         # (H,W,1)

        colored = np.clip(mat * lum, 0, 255).astype(np.uint8)

        result = np.zeros((self.h, self.w, 4), dtype=np.uint8)
        result[:, :, :3] = colored
        result[:, :,  3] = face_rgba[:, :, 3]
        return result

    # ── Compositing ───────────────────────────────────────────────────────────

    def composite(self, base: np.ndarray,
                  layers: list) -> np.ndarray:
        """
        Composite a list of RGBA layers over *base* (H, W, 3) using
        alpha blending.  Layers are applied bottom-to-top.

        Each element of *layers* is either:
          • (H, W, 4) ndarray  — blended normally (alpha blend over previous)
          • ((H,W,4) ndarray, 'add')  — additive blend (good for particles/glow)
          • None               — skipped
        """
        out = base.astype(np.float32)

        for item in layers:
            if item is None:
                continue

            if isinstance(item, tuple):
                layer, mode = item
            else:
                layer, mode = item, 'normal'

            if layer is None:
                continue

            rgb = layer[:, :, :3].astype(np.float32)
            a   = layer[:, :, 3:].astype(np.float32) / 255.0  # (H,W,1)

            if mode == 'add':
                out = np.clip(out + rgb * a, 0, 255)
            else:
                out = out * (1.0 - a) + rgb * a

        return np.clip(out, 0, 255).astype(np.uint8)

    def sub_renderer(self, width: int, height: int) -> 'Renderer':
        """Return a Renderer instance for a sub-canvas of the given size.

        Reuses cached instances to avoid repeated allocation on each frame.
        """
        if not hasattr(self, '_sub_cache'):
            self._sub_cache: dict[tuple[int,int], 'Renderer'] = {}
        key = (width, height)
        if key not in self._sub_cache:
            self._sub_cache[key] = Renderer(width, height)
        return self._sub_cache[key]

    # ── Utility ───────────────────────────────────────────────────────────────

    @staticmethod
    def pil_to_rgba(img: Image.Image, width: int, height: int) -> np.ndarray:
        """Resize a PIL image to (width, height) and return (H,W,4) uint8."""
        img = img.convert('RGBA').resize((width, height), Image.NEAREST)
        return np.array(img, dtype=np.uint8)

    @staticmethod
    def pil_to_rgb(img: Image.Image, width: int, height: int) -> np.ndarray:
        """Resize a PIL image to (width, height) and return (H,W,3) uint8."""
        img = img.convert('RGB').resize((width, height), Image.NEAREST)
        return np.array(img, dtype=np.uint8)
