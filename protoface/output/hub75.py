"""
HUB75 output via Adafruit Piomatter (Raspberry Pi 5 / CM5, RP1 PIO).

The legacy hzeller rpi-rgb-led-matrix library does NOT work on the CM5/Pi 5
(the RP1 GPIO can't be bit-banged the way that library expects), so this uses
Adafruit's PIO-based driver instead:
    pip install Adafruit-Blinka-Raspberry-Pi5-Piomatter
Requires /dev/pio0 (recent Raspberry Pi firmware + kernel). Falls back silently
if the library is missing (e.g. development on a non-Pi host).

Wiring assumed: panels daisy-chained on the Adafruit Triple Matrix Bonnet
(active3 pinout). `chain_length` panels per port; `parallel` = number of ports
used (1 = port 1 only). One port drives two lanes (its R1/G1/B1 + R2/G2/B2).
"""

import numpy as np

try:
    import adafruit_blinka_raspberry_pi5_piomatter as piomatter
    from adafruit_blinka_raspberry_pi5_piomatter.pixelmappers import simple_multilane_mapper
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


def _addr_lines(panel_h: int) -> int:
    # A panel addresses half its rows: 32 -> 4 (2^4=16), 64 -> 5, 16 -> 3.
    return (panel_h // 2).bit_length() - 1


class HUB75Output:
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
        self._fb = None

        if not _AVAILABLE:
            print("[hub75] piomatter not available — output disabled")
            return

        n_addr  = _addr_lines(self._panel_h)
        n_lanes = 2 * self._parallel          # 2 lanes per active port
        width   = self._w
        height  = n_lanes << n_addr           # == panel_h * parallel

        pixelmap = simple_multilane_mapper(width, height, n_addr, n_lanes)
        geometry = piomatter.Geometry(width=width, height=height,
                                      n_addr_lines=n_addr, n_planes=10,
                                      n_temporal_planes=4, map=pixelmap,
                                      n_lanes=n_lanes)

        self._fb = np.zeros((height, width, 3), dtype=np.uint8)
        self._matrix = piomatter.PioMatter(
            colorspace=piomatter.Colorspace.RGB888Packed,
            pinout=piomatter.Pinout.Active3,
            framebuffer=self._fb,
            geometry=geometry,
        )

    def show(self, frame: np.ndarray):
        """Push a (H, W, 3) uint8 RGB frame to the LED panels."""
        if self._matrix is None:
            return
        # These panels display colors rotated R->G->B; resend as (G,B,R) to correct.
        self._fb[:] = frame[:, :, [1, 2, 0]]
        self._matrix.show()

    def close(self):
        if self._matrix is not None:
            self._fb[:] = 0
            self._matrix.show()

    @property
    def available(self) -> bool:
        return _AVAILABLE and self._matrix is not None

    @property
    def canvas_size(self) -> tuple[int, int]:
        return self._w, self._h
