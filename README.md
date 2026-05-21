# Protoface

A Python LED face display daemon for the Raspberry Pi Compute Module 5. Drives HUB75 RGB matrix panels through the [Adafruit Triple LED Matrix Bonnet](https://www.adafruit.com/product/6358) using Adafruit's PIO-based [Piomatter](https://github.com/adafruit/Adafruit_Blinka_Raspberry_Pi5_Piomatter) driver, with per-panel sprite animations, scrolling materials, and multi-layer particle effects. Communicates with [ProtoHUD](https://github.com/brooksthemaker/ProtoHUD) over a Unix socket and POSIX shared memory.

> **Platform note:** The CM5 (Pi 5 / RP1 family) cannot run hzeller's `rpi-rgb-led-matrix` library — its GPIO can't be bit-banged the way that library expects. Protoface drives the panels via Piomatter, which uses the RP1's PIO state machines. A CM4 would need a different driver; this build targets the CM5.

---

## Panel Layout

The current build drives **2× 64×32 panels daisy-chained on port 1** of the bonnet (a 128×32 logical canvas). Both panels show the **same full face** from `faces/main`; the right panel is a horizontal **mirror** of the left, so the face is symmetric and the two halves stay perfectly in sync.

```
┌───────────────────────┬───────────────────────┐
│      face (main)      │  face (main, mirror)  │
│        64×32          │        64×32          │
└───────────────────────┴───────────────────────┘
   panel 1 (cols 0–63)     panel 2 (cols 64–127)
                  128×32 canvas
```

The face sprite is tinted by the panel's material colour and can carry a particle layer. The mirror is driven by `mirror_of` in `config.yaml` — the right panel renders the left panel flipped horizontally.

> The bonnet has **3 HUB75 ports** (active3 pinout), so the layout can be expanded — more panels daisy-chained per port (`chain_length`) and/or more ports (`parallel`, up to 3). The geometry below is for the validated 2-panel single-port setup.

---

## Requirements

**Raspberry Pi OS (trixie / Debian 13, 64-bit)** on a CM5, with the Raspberry Pi downstream kernel and current firmware so the PIO device `/dev/pio0` exists:

```bash
ls -l /dev/pio0     # must exist (crw-rw---- root gpio). If missing, update firmware + reboot.
```

Python packages:

```bash
pip install -r requirements.txt
# numpy  Pillow  PyYAML  pygame  pyaudio
```

Pi-specific packages (HUB75 output + optional inputs):

```bash
pip install Adafruit-Blinka-Raspberry-Pi5-Piomatter   # HUB75 via RP1 PIO
sudo apt install python3-smbus                          # I2C for MPU-6050 gyro
pip install RPi.GPIO                                    # boop sensor
```

> On trixie, system `pip` is "externally managed" (PEP 668). Install into a virtualenv, or pass `--break-system-packages` if you intend a system-wide install.

No `sudo` is needed to run — Piomatter talks to `/dev/pio0`, which is `gpio`-group writable, and the default CM5 user is in the `gpio` group (and `i2c`/`audio` for the optional inputs).

For the preview window on a desktop machine, only `numpy`, `Pillow`, `PyYAML`, and `pygame` are needed (Piomatter is skipped automatically with a graceful fallback).

---

## Quick Start

```bash
git clone https://github.com/brooksthemaker/ProtoFace ~/Protoface
cd ~/Protoface
pip install -r requirements.txt

# Desktop preview (no Pi hardware needed) — set display.preview: true in config.yaml
python run.py

# CM5 with HUB75 panels — set display.preview: false in config.yaml
pip install Adafruit-Blinka-Raspberry-Pi5-Piomatter
python run.py
```

Preview window keyboard shortcuts:

| Key | Action |
|-----|--------|
| `0`–`9` | Switch particle effect/preset on all panels |
| `e` / `w` | Next / previous expression |
| `b` | Manual blink |
| `ESC` | Quit |

**Solo controls on the panels** — when running `run.py` directly on the hardware (no ProtoHUD/IPC), control it from the terminal (works over SSH; no-ops automatically under systemd):

| Key | Action |
|-----|--------|
| `c` / `v` | Next / previous face colour |
| `x` / `z` | Next / previous particle effect |
| `e` / `w` | Next / previous expression |
| `b` | Manual blink |
| `+` / `-` | Brightness up / down |
| `q` / `Esc` | Quit |

---

## Demo

`demo.py` is a standalone hardware test — it shows **"Demo"** on each panel and lets you cycle colours and particle effects from the keyboard (works over SSH). It drives the panels through the same Piomatter output as the app, so it's a quick way to confirm wiring, colour order, and effects.

```bash
python demo.py
```

| Key | Action |
|-----|--------|
| `c` / `v` | Next / previous colour |
| `x` / `z` | Next / previous effect |
| `q` / `Esc` | Quit |

---

## Hardware

### Bonnet + Panels

| Part | Details |
|------|---------|
| Adapter | Adafruit Triple LED Matrix Bonnet (PID 6358) — 3 HUB75 ports, active3, **on-board level shifters** |
| Panels | 2× 64×32 HUB75 LED matrix (P2.5/P3/P4) |
| Driver | Adafruit Piomatter (`Pinout.Active3`, RP1 PIO) |
| Power | External 5 V / 10 A+ to the bonnet's screw terminal; power each panel directly from the PSU |

The bonnet mounts on the 40-pin header and handles all 3.3 V → 5 V level shifting and the HUB75 wiring — **no 74AHCT125 chips or breadboard wiring required**. You just plug a ribbon into a port and chain panels.

### Wiring (2 panels on port 1)

```
Bonnet Port 1 ──ribbon──► Panel A [IN]
                          Panel A [OUT] ──ribbon──► Panel B [IN]
```

- Keep each ribbon under ~20 cm.
- Power each panel directly from the 5 V PSU (don't pass a second panel's current through the HUB75 OUT). Common ground between PSU, panels, and the Pi.
- 2× 64×32 P2.5 panels can draw ~16 A peak (all-white) — provision the PSU and keep brightness moderate.

### Colour order

These panels report colours rotated R→G→B (the panel's red LED is driven by the blue data, etc.). The driver corrects this by resending each pixel as `(G, B, R)` — see `protoface/output/hub75.py`. If your panels show wrong colours, that mapping is the place to adjust.

### Optional Inputs

| Input | Interface | Config key |
|-------|-----------|------------|
| USB microphone | USB | `inputs.microphone.type: usb` |
| MPU-6050 gyro | I2C (use the bonnet's I2C header) | `inputs.gyro.enabled: true` |
| Boop sensor | a free GPIO | `inputs.boop.gpio_pin: <pin>` |

> The active3 pinout consumes most GPIO lines for HUB75. Use the bonnet's **I2C header** for the gyro. I2C can't drive the panels — it's only ~400 kHz–1 MHz, far below the HUB75 pixel clock. A boop sensor needs a GPIO that the active3 mapping leaves free; verify against the Piomatter active3 pin usage before wiring. See [HARDWARE.md](HARDWARE.md) and [INTEGRATION.md](INTEGRATION.md).

---

## Configuration

Edit `config.yaml` before running. Key sections:

```yaml
panel:
  panel_width:   64        # physical panel width
  panel_height:  32        # physical panel height
  chain_length:  2         # panels daisy-chained on port 1
  parallel:      1         # ports in use (1 = port 1 only; bonnet supports up to 3)
  # Logical canvas = panel_width*chain_length × panel_height*parallel = 128×32
  # NOTE: hardware_mapping / gpio_slowdown / brightness here are legacy hzeller
  #       knobs and are ignored by the Piomatter driver. Brightness is applied
  #       in the render pipeline (set_brightness over IPC / FaceState).

display:
  fps:     30
  preview: false           # false = HUB75 output (Pi); true = pygame window (dev)

panels:                    # both panels show faces/main; right mirrors left
  - name: face_left
    region: [0, 0, 64, 32]
    face:     {active: main, wiggle: {speed: 0.8, amplitude_x: 2.0, amplitude_y: 1.0}}
    material: {active: teal}
    particles: {active: none}

  - name: face_right
    region: [64, 0, 64, 32]
    mirror_of: face_left     # render = face_left flipped horizontally
    face:     {active: main}
    material: {active: teal}
    particles: {active: none}

ipc:
  socket:   /run/protoface.sock
  shm_path: /dev/shm/protoface_frame
```

> Faces are 64×32 and render at native size on each panel, so the blink/mouth-open hit-boxes in `faces/main/config.json` (defined in 64×32 space) line up correctly. `mirror_of` makes the right panel an exact flipped copy of the left, so blink and talk stay perfectly synchronised across both halves.

---

## Particle Effects

### Single effect (shorthand)

```yaml
particles: {active: embers}
```

### Named preset

```yaml
particles: {preset: fire}
```

Built-in presets: `fire`, `aurora`, `blizzard`, `sonar`, `plasma`, `celebration`, `galaxy`, `party`.

### Multi-layer (custom)

```yaml
particles:
  layers:
    - effect: embers
      count: 30
      colors: [[255, 60, 0], [255, 100, 10]]
      speed_min: 8.0
      speed_max: 22.0
      size_min: 1
      size_max: 2
      blend: add
    - effect: sparkle
      count: 6
      colors: [[255, 255, 220]]
      life_min: 0.05
      life_max: 0.15
      blend: add
```

#### Per-layer parameters

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `effect` | str | — | `sparkle` `embers` `snow` `rain` `confetti` `rings` `fireflies` |
| `count` | int | 30 | Simultaneous particles |
| `colors` | `[[r,g,b],...]` | effect default | Random pick at spawn |
| `blend` | str | `add` | `add` or `normal` |
| `speed_min/max` | float | effect default | px/s spawn velocity range |
| `size_min/max` | int | effect default | Radius in pixels |
| `life_min/max` | float | effect default | Lifetime seconds |
| `drift_x` | float | `0.0` | Horizontal velocity bias px/s |
| `shape` | str | `dot` | `dot` or `rect` |
| `emit_from` | str | effect default | `bottom` `top` `edges` `random` |
| `intensity` | float | `1.0` | Scales count and spawn rate |

---

## Face Assets

Each face lives in its own folder under `faces/`; the folder name matches the `face.active` key in `config.yaml`. The current layout uses one whole-face folder, **`faces/main`**, shown on both panels (right mirrored).

```
faces/
  main/
    neutral.png        white shape on transparent (tinted by the material)
    happy.png  angry.png  sad.png  surprised.png
    blink.png          eye-closed frame
    mouth_open.png     mouth-open frame (blended by mic volume)
    config.json        expressions map + eye/mouth hit-boxes
```

`config.json` defines blendable regions (optional — without it the whole sprite swaps):

```json
{
  "expressions": {"neutral": "neutral.png", "happy": "happy.png"},
  "blink": "blink.png",
  "eye_left":  {"x": 10, "y": 8,  "w": 20, "h": 12},
  "eye_right": {"x": 34, "y": 8,  "w": 20, "h": 12},
  "mouth":     {"x": 18, "y": 22, "w": 28, "h": 10}
}
```

Generate placeholder assets for all face folders:

```bash
python generate_assets.py
```

---

## Rendering Pipeline (per frame)

```
1. Background       solid colour
2. Material         PNG tiled to panel size, scrolled by (scroll_x × t, scroll_y × t)
3. Face             expression PNG lerped with blink PNG in eye region,
                    translated by gyro wiggle offset;
                    face luminance × material = final colour
4. Particles        RGBA multi-layer compositor; additive or normal blend
5. Output           HUB75 via Piomatter / RP1 PIO (Pi) or pygame preview (desktop);
                    G→B→R colour correction applied at the panel boundary
   + Shared memory  128×32 RGB written to /dev/shm/protoface_frame
```

---

## ProtoHUD Integration

When running alongside [ProtoHUD](https://github.com/brooksthemaker/ProtoHUD) on the same CM5, Protoface communicates over two channels:

| Channel | Direction | Path | Purpose |
|---------|-----------|------|---------|
| Unix socket | ProtoHUD → Protoface | `/run/protoface.sock` | Commands (set_effect, set_color, etc.) |
| Shared memory | Protoface → ProtoHUD | `/dev/shm/protoface_frame` | Live 128×32 panel preview in HMD |

Enable the panel preview in the ProtoHUD menu: **Menu → Face → Panel Preview**.

> The shared-memory frame is now 128×32 (was 128×64 in the 4-panel layout). If ProtoHUD's preview reader assumes a fixed size, update it to match the current canvas.

### IPC Commands (JSON over Unix socket)

| Command | Fields | Description |
|---------|--------|-------------|
| `set_effect` | `effect_id` 0–15 | Switch particle effect (0=none, 1–7=built-ins, 8–15=presets) |
| `set_effect` | `layers: [...]` | Set arbitrary multi-layer stack |
| `set_color` | `r g b layer` | Set material colour |
| `set_brightness` | `value` 0–255 | Panel brightness (applied in the render pipeline) |
| `play_gif` | `gif_id` | Play GIF by index |
| `set_palette` | `palette_id` | Switch colour palette |

### Startup order

Start Protoface before ProtoHUD. ProtoHUD's `ProtoFaceController` retries the socket every 2 s so order is not critical, but the socket must exist before ProtoHUD tries to use the preview.

```ini
# /etc/systemd/system/protoface.service
[Unit]
After=network.target
Before=protohud.service

[Service]
ExecStart=/usr/bin/python3 /home/pi/Protoface/run.py
WorkingDirectory=/home/pi/Protoface
# No root needed — the user must be in the gpio group (and i2c for the gyro).
User=pi
SupplementaryGroups=gpio i2c audio
Restart=on-failure
```

See [INTEGRATION.md](INTEGRATION.md) for GPIO usage, CPU budget, and the minimal working configuration.

---

## Project Structure

```
run.py                      — entry point; argument parsing; main loop
demo.py                     — standalone panel demo: "Demo" text + cycle colours/effects
config.yaml                 — panel layout, inputs, IPC paths
generate_assets.py          — creates placeholder PNGs for all face folders
requirements.txt

protoface/
  renderer.py               — layer compositor (apply_material, composite, sub_renderer)
  face.py                   — sprite loader; blink/expression/wiggle animator
  material.py               — solid, PNG, scrolling material
  particles.py              — multi-layer ParticleSystem + 7 built-in effects
  gif_player.py             — GIF decoder + per-frame timing
  state.py                  — FaceState dataclass (expression, blink, audio, gyro)
  shm_writer.py             — writes the canvas as RGB to /dev/shm/protoface_frame
  ipc.py                    — Unix socket server; dispatches commands to all panels
  output/
    hub75.py                — Adafruit Piomatter wrapper (graceful ImportError fallback)
    preview.py              — pygame scaled preview window for development
  inputs/
    microphone.py           — threaded PyAudio capture + FFT → volume/spectrum
    gyro.py                 — I2C MPU-6050 → pitch/roll face offset
    boop.py                 — GPIO debounced sensor → expression trigger

faces/
  main/                     — whole-face sprites shown on both panels (right mirrored)
  example_fox/              — single-panel reference design
  left_eye/ right_eye/ left_mouth/ right_mouth/   — legacy split-feature folders

materials/                  — PNG material files (tiled over face)
particles/
  presets.yaml              — named multi-layer presets (fire, aurora, blizzard, …)
gifs/                       — GIF files; auto-discovered at startup
```

---

## License

MIT — see [LICENSE](LICENSE) if present, otherwise assume all rights reserved until a licence file is added.
