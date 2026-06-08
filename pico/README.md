# Protoface for Pico 2 / Pico 2 W (CircuitPython)

A standalone port of Protoface to the **Raspberry Pi Pico 2 / Pico 2 W**
(RP2350) running **CircuitPython**. It drives a HUB75 LED face directly from the
microcontroller — no Linux, no CM5, no ProtoHUD host required.

> This is a *separate platform target* living alongside the CM5 build. The CM5
> code (repo root) is unchanged. This folder is self-contained and gets copied
> to the board's CIRCUITPY drive.

## How this differs from the CM5 build

The CM5 Protoface is a CPython daemon built on `numpy` + `Pillow` + `pygame`,
talking to ProtoHUD over a Unix socket and shared memory, driving panels via
Piomatter (RP1-specific). None of that exists on a microcontroller, so each
layer is re-homed onto CircuitPython:

| Subsystem | CM5 | Pico 2 (this port) |
|---|---|---|
| Runtime | CPython 3 / Debian | CircuitPython 9+ on RP2350 |
| HUB75 driver | Piomatter (RP1 PIO) | `rgbmatrix` + `framebufferio` (Protomatter, PIO+DMA) |
| Compositing | numpy | `displayio` + `bitmaptools` |
| Face art | Pillow loads PNG | pre-baked 8-bit indexed **BMP** |
| Material tint | per-pixel luminance × colour | **palette ramp** (a ~16-entry rewrite) |
| Crossfade/blink | numpy lerp | index lerp over a bounded region |
| GIF | Pillow | `gifio.OnDiskGif` *(Phase 3)* |
| Mic / gyro | PyAudio / smbus | `audiobusio` + `ulab.fft` / `adafruit_mpu6050` *(Phase 4)* |
| Control | Unix socket IPC + terminal | USB-serial keys (+ buttons) — standalone |

## Hardware

**Recommended board: Pimoroni Interstate 75 W** — an RP2350 (Pico 2 W-class)
board purpose-built to drive HUB75 panels, with the pin mapping this port
defaults to. A bare **Pico 2** wired to a HUB75 panel through level shifters /
an Adafruit RGB-Matrix-style adapter also works; override the pins in
`config.json`.

Default pin mapping (Interstate 75 / `panel.pins` in `config.json` to change):

| Signal | Pins |
|---|---|
| RGB | R0 G0 B0 R1 G1 B1 (GP0–GP5) |
| Address | A B C D (GP6–GP9); add E (GP10) for 64-row panels |
| Clock / Latch / OE | CLK GP11 / LAT GP12 / OE GP13 |

Panel layout matches the CM5 build: **2× 64×32 chained = a 128×32 canvas**, with
the right half mirroring the left (`face.mirror: true`). Power the panels from a
proper external 5 V supply — see the repo-root `HARDWARE.md` for current/PSU
guidance (the panel side is identical).

> 520 KB SRAM is the real constraint, not the panel. Keep the canvas, particle
> counts, and number of loaded faces modest.

## Install

1. **Flash CircuitPython** (9.x+) for your board from
   <https://circuitpython.org/downloads>. Confirm the natives exist:
   ```python
   import rgbmatrix, gifio          # at the REPL
   from ulab import numpy as np
   ```
   If any are missing, flash a full build for your board.

2. **Copy libraries** into `CIRCUITPY/lib/` — see `lib-requirements.txt`. For
   Phase 1 you only need `adafruit_imageload`.

3. **Bake face assets** on your desktop (needs Pillow):
   ```bash
   pip install Pillow
   # generate the CM5 placeholder PNGs first if faces/main has none:
   python generate_assets.py
   python pico/tools/convert_assets.py --src faces/main --out pico/assets/main \
       --width 64 --height 32
   ```
   `--width/--height` is the *authored* face size (half the canvas with mirror
   on). The converter writes indexed BMPs + a device `config.json`.

4. **Copy this folder's contents to the CIRCUITPY root** so the drive has:
   ```
   CIRCUITPY/
     code.py
     config.json
     protoface_pico/        (the engine package)
     assets/main/           (baked BMPs + config.json)
     lib/                   (adafruit_imageload, …)
   ```
   CircuitPython runs `code.py` on boot.

## Controls (standalone)

Single keys over the USB serial console (e.g. `screen`, `tio`, the Mu/Thonny
REPL, or `ampy`'s console):

| Key | Action |
|---|---|
| `c` / `v` | next / previous face colour |
| `x` / `z` | next / previous particle effect |
| `e` / `w` | next / previous expression |
| `b` | manual blink |
| `+` / `-` | brightness up / down |

Physical buttons (Interstate 75 A/B) can be mapped via `keypad` later.

## Configuration

Edit `config.json` (schema mirrors the CM5 `config.yaml`, single-panel subset).
Defaults live in `protoface_pico/config.py`. Named colours: `teal red orange
yellow green blue purple magenta white`, or `[r,g,b]`, or `"solid:r,g,b"`.

## Feature parity status

| Feature | Status |
|---|---|
| HUB75 output (Protomatter) | ✅ Phase 1 |
| Expressions + crossfade | ✅ Phase 1 |
| Blink (eye regions / whole-face) | ✅ Phase 1 |
| Mouth-open region | ✅ Phase 1 (driven by mic in Phase 4) |
| Idle wiggle + gyro offset | ✅ Phase 1 (integer; gyro feeds in Phase 4) |
| Material colour tint + brightness | ✅ Phase 1 (solid) |
| Mirror layout | ✅ Phase 1 |
| Particles | ⚠️ Phase 2 — single-layer subset, opaque blend |
| Scrolling/tiled materials | ⬜ Phase 2 |
| GIF playback | ⬜ Phase 3 (`gifio`) |
| Mic-driven mouth + audio particles | ⬜ Phase 4 |
| Gyro input | ⬜ Phase 4 |
| Boop sensor + buttons | ⬜ Phase 4 |
| Additive particle blending / presets | ⬜ later |

## Performance note

The panel refresh is handled by PIO+DMA (free CPU). The limiter is per-frame
compositing in CircuitPython. Palette-tinted faces, blink, mouth, wiggle and
crossfades are cheap; heavy multi-layer particles are the risk. The engine
targets 30 fps and degrades gracefully (drop the FPS or particle counts in
`config.json` if needed). **Real frame numbers can only be confirmed on
hardware** — none of this has been run on a physical board yet.

## Layout

```
pico/
  code.py                  entry point (runs on CIRCUITPY boot)
  config.json              device config (copy/edit)
  lib-requirements.txt     CircuitPython libs to install
  tools/convert_assets.py  host-side PNG -> indexed BMP baker (needs Pillow)
  assets/                  baked face folders go here (gitignored output)
  protoface_pico/
    config.py     matrix.py     material.py
    state.py      face.py       particles.py     controls.py
```
