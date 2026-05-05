"""
HUB75 output via rpi-rgb-led-matrix.

Falls back silently if the library is not installed (development on non-Pi).
On Raspberry Pi, install with:
    sudo pip install rgbmatrix
or build from source: https://github.com/hzeller/rpi-rgb-led-matrix

4-panel wiring (2×2 grid, 128×64 logical canvas):
  chain_length=2  — two panels chained horizontally per row
  parallel=2      — two rows of panels stacked vertically
  rows=32         — physical panel height (library multiplies by parallel)
  cols=64         — physical panel width  (library multiplies by chain_length)
"""

import numpy as np

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class HUB75Output:
    def __init__(self, cfg: dict):
        panel = cfg.get('panel', {})

        # Physical panel dimensions (one tile); library builds the logical canvas.
        self._panel_w = panel.get('panel_width', panel.get('width', 64))
        self._panel_h = panel.get('panel_height', panel.get('height', 32))
        self._chain   = panel.get('chain_length', 2)
        self._parallel = panel.get('parallel', 2)

        # Logical canvas dimensions
        self._w = self._panel_w * self._chain
        self._h = self._panel_h * self._parallel

        self._matrix = None
        self._canvas = None

        if not _AVAILABLE:
            print("[hub75] rpi-rgb-led-matrix not available — output disabled")
            return

        opts = RGBMatrixOptions()
        opts.rows                     = self._panel_h
        opts.cols                     = self._panel_w
        opts.chain_length             = self._chain
        opts.parallel                 = self._parallel
        opts.brightness               = panel.get('brightness', 80)
        opts.hardware_mapping         = panel.get('hardware_mapping', 'regular')
        opts.gpio_slowdown            = panel.get('gpio_slowdown', 4)
        opts.disable_hardware_pulsing = True
        opts.drop_privileges          = True

        self._matrix = RGBMatrix(options=opts)
        self._canvas = self._matrix.CreateFrameCanvas()

    def show(self, frame: np.ndarray):
        """Push a (H, W, 3) uint8 RGB frame to the LED panels."""
        if self._matrix is None or self._canvas is None:
            return
        from PIL import Image
        img = Image.fromarray(frame, 'RGB')
        self._canvas.SetImage(img)
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def close(self):
        if self._matrix:
            self._matrix.Clear()

    @property
    def available(self) -> bool:
        return _AVAILABLE and self._matrix is not None

    @property
    def canvas_size(self) -> tuple[int, int]:
        return self._w, self._h
