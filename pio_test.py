#!/usr/bin/env python3
"""
Minimal Piomatter test for 2x 64x32 panels daisy-chained on port 1 of the
Adafruit Triple Matrix Bonnet (active3). Shows a static, low-current test
pattern and holds it until you press Enter.

Uses:
  - confirm the panels light with the right geometry and colour order, and
  - isolate power problems: leave it up for ~60s. If this *static* pattern
    stays rock-solid but demo.py / run.py degrade (vertical lines / blackout),
    the extra lit LEDs are browning out your 5V rail rather than a code bug.

    python3 pio_test.py
"""

import numpy as np
import adafruit_blinka_raspberry_pi5_piomatter as piomatter
from adafruit_blinka_raspberry_pi5_piomatter.pixelmappers import simple_multilane_mapper

PANEL_W, CHAIN, N_ADDR, N_LANES = 64, 2, 4, 2       # 64x32 panels, 2 on port 1
width, height = PANEL_W * CHAIN, N_LANES << N_ADDR   # 128 x 32

pmap = simple_multilane_mapper(width, height, N_ADDR, N_LANES)
geo = piomatter.Geometry(width=width, height=height, n_addr_lines=N_ADDR,
                         n_planes=10, n_temporal_planes=4, map=pmap, n_lanes=N_LANES)
fb = np.zeros((height, width, 3), dtype=np.uint8)
matrix = piomatter.PioMatter(colorspace=piomatter.Colorspace.RGB888Packed,
                             pinout=piomatter.Pinout.Active3,
                             framebuffer=fb, geometry=geo)

# Build the pattern in true RGB, then apply the panels' G->B->R correction
# (the same one protoface/output/hub75.py applies on every frame).
img = np.zeros((height, width, 3), dtype=np.uint8)
img[0:8, 0:8]            = (255, 0, 0)    # RED  -> far-left  (panel 1 start)
img[0:8, width-8:width]  = (0, 0, 255)    # BLUE -> far-right (panel 2 end)
img[height // 2, :]      = (0, 255, 0)    # GREEN line across both panels

fb[:] = img[:, :, [1, 2, 0]]
matrix.show()

input("Pattern shown: red left, blue right, green line. Enter to clear/exit.")
fb[:] = 0
matrix.show()
