"""
HUB75 output via hzeller's rpi-rgb-led-matrix (Pi Zero 2W / Pi 3 / Pi 4).

This is the BCM-GPIO bit-banging driver — the counterpart to hub75.py's
Piomatter backend. Piomatter needs the RP1's PIO (/dev/pio0), which only the
Pi 5 / CM5 family has; conversely this library bit-bangs the classic BCM GPIO
and therefore does NOT work on the Pi 5 / CM5. run.py picks between the two
via display.driver (auto-detects on /dev/pio0 by default).

Install (build from source — there is no reliable wheel):
    sudo apt install -y python3-dev cython3
    git clone https://github.com/hzeller/rpi-rgb-led-matrix ~/rpi-rgb-led-matrix
    cd ~/rpi-rgb-led-matrix && make build-python && sudo make install-python

Wiring assumed: panels daisy-chained on the classic Adafruit RGB Matrix Bonnet
(PID 3211, single HUB75 port) — hardware_mapping "adafruit-hat", or
"adafruit-hat-pwm" after the GPIO4→GPIO18 jumper mod for flicker-free output.

Notes for the Pi Zero 2W:
  - Run as root (the library needs /dev/mem; it drops privileges after init
    unless panel.drop_privileges is false).
  - Blacklist the onboard sound module (snd_bcm2835) — it conflicts with the
    PWM hardware the library uses.
  - gpio_slowdown 0-1 is typical for the Zero 2W's slower core.
Falls back silently if the library is missing (development on a non-Pi host).
"""

import numpy as np

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False


class HzellerOutput:
    def __init__(self, cfg: dict):
        panel = cfg.get('panel', {})

        self._panel_w  = panel.get('panel_width',  panel.get('width', 64))
        self._panel_h  = panel.get('panel_height', panel.get('height', 32))
        self._chain    = panel.get('chain_length', 2)
        self._parallel = panel.get('parallel', 1)

        # Logical canvas — matches what run.py builds and hands to show().
        self._w = self._panel_w * self._chain
        self._h = self._panel_h * self._parallel

        self._matrix = None
        self._canvas = None

        if not _AVAILABLE:
            print("[hub75-hzeller] rgbmatrix not available — output disabled")
            return
        if not _PIL:
            print("[hub75-hzeller] Pillow not available — output disabled")
            return

        opts = RGBMatrixOptions()
        opts.rows            = self._panel_h
        opts.cols            = self._panel_w
        opts.chain_length    = self._chain
        opts.parallel        = self._parallel
        # Classic bonnet default; "adafruit-hat-pwm" after the jumper mod.
        opts.hardware_mapping = panel.get('hardware_mapping', 'adafruit-hat')
        opts.gpio_slowdown    = int(panel.get('gpio_slowdown', 1))
        opts.pwm_bits         = int(panel.get('pwm_bits', 11))
        opts.pwm_lsb_nanoseconds = int(panel.get('pwm_lsb_nanoseconds', 130))
        # Panel-level brightness cap (render-pipeline brightness still applies
        # on top, over IPC / solo keys — this bounds worst-case current draw).
        opts.brightness       = int(panel.get('max_brightness_pct', 100))
        # Colour-order correction lives here (hzeller-native), NOT in the
        # (G,B,R) resend the Piomatter path does. Panels that display colours
        # rotated R→G→B want "GBR"; default "RGB" for standard panels.
        opts.led_rgb_sequence = panel.get('led_rgb_sequence', 'RGB')
        limit = int(panel.get('limit_refresh_rate_hz', 0))
        if limit:
            opts.limit_refresh_rate_hz = limit
        if panel.get('show_refresh_rate'):
            opts.show_refresh_rate = 1
        if panel.get('drop_privileges') is False:
            opts.drop_privileges = False

        try:
            self._matrix = RGBMatrix(options=opts)
            self._canvas = self._matrix.CreateFrameCanvas()
        except Exception as e:                          # noqa: BLE001
            print(f"[hub75-hzeller] init failed: {e} — output disabled")
            self._matrix = None
            self._canvas = None

    def show(self, frame: np.ndarray):
        """Push a (H, W, 3) uint8 RGB frame to the LED panels."""
        if self._matrix is None:
            return
        img = Image.fromarray(frame[:, :, :3], 'RGB')
        self._canvas.SetImage(img)
        self._canvas = self._matrix.SwapOnVSync(self._canvas)

    def close(self):
        if self._matrix is None:
            return
        self._matrix.Clear()

    @property
    def available(self) -> bool:
        return _AVAILABLE and self._matrix is not None

    @property
    def canvas_size(self) -> tuple[int, int]:
        return self._w, self._h
