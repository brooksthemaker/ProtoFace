# Protoface for Pico 2 / Pico 2 W (Arduino / C++)

A standalone port of Protoface to the **Raspberry Pi Pico 2 / Pico 2 W**
(RP2350), written in **C++** on the Arduino framework and driving HUB75 panels
through **Adafruit_Protomatter**. It runs a full LED face directly on the
microcontroller — no Linux, no CM5, no ProtoHUD host.

> Separate platform target, living alongside the CM5 build. The CM5 code (repo
> root) is unchanged. C++ was chosen for guaranteed full feature parity: the
> per-pixel compositing (crossfades, additive multi-layer particles) that would
> fight the frame rate in an interpreted runtime is cheap in compiled code.

## How this differs from the CM5 build

| Subsystem | CM5 | Pico 2 (this port) |
|---|---|---|
| Runtime | CPython 3 / Debian | Arduino C++ (arduino-pico core) on RP2350 |
| HUB75 driver | Piomatter (RP1 PIO) | Adafruit_Protomatter (RP2350 PIO+DMA) |
| Compositing | numpy | hand-written C over an RGB888 canvas |
| Face art | Pillow loads PNG | baked into a C header (luminance + alpha arrays) |
| Material tint | per-pixel luminance × colour | same, in the tint stage |
| Config | YAML | compile-time `config.h` |
| Control | Unix socket IPC + terminal | USB-serial keys — standalone |

## Hardware

**Recommended board: Pimoroni Interstate 75 W** — an RP2350 (Pico 2 W-class)
board purpose-built for HUB75, whose pinout this port defaults to. A bare
**Pico 2** wired to a panel through level shifters / a matrix bonnet also works;
change the pins in `config.h`.

Default pins (`config.h`):

| Signal | Pins |
|---|---|
| RGB | GP0–GP5 (R0 G0 B0 R1 G1 B1) |
| Address | GP6–GP9 (A B C D); add GP10 (E) for 64-row panels |
| Clock / Latch / OE | GP11 / GP12 / GP13 |

Panel layout matches the CM5 build: **2× 64×32 chained = 128×32**, right half
mirroring the left (`FACE_MIRROR`). Power the panels from a proper external 5 V
supply — see the repo-root `HARDWARE.md` (the panel side is identical).

> 520 KB SRAM is the real ceiling, not compute. Buffers here are modest
> (RGB888 canvas 12 KB + RGB565 8 KB + face work ~4 KB); face art lives in
> flash.

## Build & flash

1. **Install the toolchain**
   - Arduino IDE (or arduino-cli) with the **arduino-pico** core (Earle
     Philhower): add the board manager URL
     `https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json`,
     install "Raspberry Pi Pico/RP2040/RP2350".
   - Libraries (Library Manager): **Adafruit Protomatter** + **Adafruit GFX
     Library**.

2. **Bake a face header** on your desktop (needs Pillow):
   ```bash
   pip install Pillow
   # generate the CM5 placeholder PNGs first if faces/main has none:
   python generate_assets.py
   python pico/tools/convert_assets.py --src faces/main --name main \
       --out pico/protoface/assets/main.h --width 64 --height 32
   ```
   `--width/--height` is the authored face size (half the canvas with mirror
   on). This writes `protoface/assets/main.h`, which `config.h` includes. (The
   sketch won't compile without it — you'll get a clear `#error` telling you to
   bake it.)

3. **Open & flash** `pico/protoface/protoface.ino`. Select board "Raspberry Pi
   Pico 2" (or "Pico 2 W"), then Upload. Open Serial Monitor at 115200.

## Controls (standalone)

Single keys over the USB serial console:

| Key | Action |
|---|---|
| `c` / `v` | next / previous face colour |
| `x` / `z` | next / previous particle effect |
| `e` / `w` | next / previous expression |
| `b` | manual blink |
| `+` / `-` | brightness up / down |

## Configuration

Edit `protoface/config.h` (compile-time) for pins, panel geometry, bit depth,
target FPS, default colour/effect/brightness, and the active face. Named
colours live in `Material.h`.

## Face regions (blink / mouth)

The blink frame (`blink.png`) and mouth-open frame (`mouth_open.png`) are only
applied inside a designated region. Two ways to designate it, in order of
precedence:

1. **Shape mask PNG (recommended)** — drop an `eye_mask.png` and/or
   `mouth_mask.png` in the face folder. Draw the region white (on transparent
   or black); the baker turns it into a per-pixel 0–255 weight
   (`luminance × alpha`). This allows **any shape, with soft/feathered edges**,
   and is blended as `blink_weight × mask`. Grays = partial blink.
2. **Rectangle boxes** — `eye_left` / `eye_right` / `mouth` in the face's
   `config.json` (as on the CM5 build). Used when no mask is present.
3. **Whole-face** — if neither a mask nor eye boxes exist, blink swaps the whole
   face.

Masks are baked automatically by `convert_assets.py` when the PNGs are present;
no config changes needed.

## Feature parity status

| Feature | Status |
|---|---|
| HUB75 output (Protomatter) | ✅ Phase 1 |
| Expressions + crossfade | ✅ Phase 1 |
| Blink (eye regions / whole-face) | ✅ Phase 1 |
| Mouth-open region | ✅ Phase 1 (mic-driven in Phase 4) |
| Idle wiggle + gyro offset | ✅ Phase 1 (integer; gyro feeds in Phase 4) |
| Material colour tint + brightness | ✅ Phase 1 (solid) |
| Mirror layout | ✅ Phase 1 |
| Particles (additive, multi-effect) | ✅ Phase 1 (single-layer; multi-layer in Phase 2) |
| Scrolling/tiled materials | ⬜ Phase 2 |
| GIF playback | ⬜ Phase 3 |
| Mic-driven mouth + audio particles | ⬜ Phase 4 |
| Gyro input | ⬜ Phase 4 |
| Boop sensor + buttons | ⬜ Phase 4 |
| Multi-layer particle stacks / presets | ⬜ Phase 2 |
| Sub-pixel wiggle | ⬜ later (integer for now) |

## Status

⚠️ **Not yet run on physical hardware** — no Pico 2 / panel was available. The
engine, state machine and particle system are compiled and exercised off-device
(host g++ with an Arduino stub: composition, crossfade, blink, mouth, mirror,
and additive particles all run), but Protomatter init and on-panel output, plus
real frame timing, need verifying on a board.

## Layout

```
pico/
  README.md
  tools/convert_assets.py   host-side PNG -> C header baker (needs Pillow)
  protoface/                Arduino sketch (open protoface.ino)
    protoface.ino           setup/loop, Protomatter, canvas -> panel
    config.h                compile-time config (pins, geometry, defaults, face)
    face_asset.h            baked-face data format
    FaceState.h/.cpp        expression/blink/mouth/wiggle/boop logic (CM5 port)
    FaceEngine.h/.cpp       compose + tint + mirror -> RGB888 canvas
    Material.h              solid colour + named palette
    Particles.h/.cpp        additive particle effects
    Controls.h              USB-serial key input
    assets/                 generated face headers go here (gitignored)
```
