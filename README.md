# Protoface

A Python LED face display daemon for CM4/CM5. Drives 4× 64×32 P2.5 HUB75 panels arranged in a 2×2 grid (128×64 logical canvas) with per-panel sprite animations, scrolling materials, and multi-layer particle effects. Communicates with [ProtoHUD](https://github.com/brooksthemaker/ProtoHUD) over a Unix socket and POSIX shared memory.

---

## Panel Layout

```
┌──────────────┬──────────────┐
│  left_eye    │  right_eye   │
│   64×32      │   64×32      │
├──────────────┼──────────────┤
│  left_mouth  │  right_mouth │
│   64×32      │   64×32      │
└──────────────┴──────────────┘
        128×64 canvas
```

Each panel has its own face sprite, material colour, and particle layer stack — left and right eyes blink on independent timers, mouth panels drive audio-reactive expressions.

---

## Requirements

**Raspberry Pi OS Bullseye (64-bit)** on CM4 or CM5.

Python packages:

```bash
pip install -r requirements.txt
# numpy  Pillow  PyYAML  pygame  pyaudio
```

Pi-specific packages (HUB75 output + GPIO):

```bash
sudo pip install rgbmatrix        # rpi-rgb-led-matrix Python bindings
sudo apt install python3-smbus    # I2C for MPU-6050 gyro
sudo pip install RPi.GPIO         # boop sensor
```

For the preview window on a desktop machine, only `numpy`, `Pillow`, `PyYAML`, and `pygame` are needed.

---

## Quick Start

```bash
git clone https://github.com/brooksthemaker/ProtoFace ~/Protoface
cd ~/Protoface

# Desktop preview (no Pi hardware needed)
pip install -r requirements.txt
python run.py

# Pi with HUB75 panels
sudo python run.py
```

Preview window keyboard shortcuts:

| Key | Action |
|-----|--------|
| `0`–`9` | Switch particle effect/preset on all panels |
| `e` / `w` | Next / previous expression |
| `b` | Manual blink |
| `ESC` | Quit |

---

## Hardware

### Panels

| Part | Details |
|------|---------|
| Panels | 4× 64×32 P2.5 HUB75 LED matrix |
| Driver | `rpi-rgb-led-matrix` (`chain_length=2, parallel=2`) |
| Power | 5 V / 20 A minimum at ≤80% brightness; 5 V / 32 A for full white |
| Level shift | 74AHCT125 (3.3 V → 5 V) — one quad buffer per data row |

> Power the panels from a dedicated 5 V PSU connected directly to the panel power connectors. **Do not** power panels from the CM5.

### GPIO — HUB75 `regular` mapping

| Signal | BCM GPIO | Pin |
|--------|----------|-----|
| R1 | 11 | 23 |
| G1 | 27 | 13 |
| B1 | 7  | 26 |
| R2 | 8  | 24 |
| G2 | 9  | 21 |
| B2 | 25 | 22 |
| A  | 22 | 15 |
| B  | 23 | 16 |
| C  | 24 | 18 |
| D  | 10 | 19 |
| E  | 17 | 11 |
| CLK | 4 | 7 |
| LAT | 21 | 40 |
| OE  | 18 | 12 |
| R1 (row 2) | 12 | 32 |
| G1 (row 2) | 5  | 29 |
| B1 (row 2) | 6  | 31 |
| R2 (row 2) | 19 | 35 |
| G2 (row 2) | 26 | 37 |
| B2 (row 2) | 20 | 38 |

See [HARDWARE.md](HARDWARE.md) for full wiring diagrams, level-shifter connections, and power calculations.

### Optional Inputs

| Input | Interface | Config key |
|-------|-----------|------------|
| USB microphone | USB | `inputs.microphone.type: usb` |
| MPU-6050 gyro | I2C (GPIO 2/3) | `inputs.gyro.enabled: true` |
| Boop sensor | GPIO 16 | `inputs.boop.gpio_pin: 16` |

> **GPIO conflict note:** The default boop pin (GPIO 17) conflicts with the HUB75 CLK line. Use GPIO 16 (pin 36) or GPIO 21 (pin 40) instead. See [INTEGRATION.md](INTEGRATION.md) for all GPIO conflicts when running alongside ProtoHUD.

---

## Configuration

Edit `config.yaml` before running. Key sections:

```yaml
panel:
  panel_width:     64      # physical panel width
  panel_height:    32      # physical panel height
  brightness:      80      # 0–100; cap at 80 for thermal safety
  hardware_mapping: regular
  gpio_slowdown:   4       # P2.5 panels typically need 3–4
  chain_length:    2
  parallel:        2

display:
  fps:     30
  preview: true            # false on Pi for HUB75 output

panels:
  - name: left_eye
    region: [0, 0, 64, 32]
    face:     {active: left_eye, wiggle: {speed: 0.8, amplitude_x: 2.0, amplitude_y: 1.0}}
    material: {active: teal}
    particles: {active: none}

  - name: right_eye
    region: [64, 0, 64, 32]
    face:     {active: right_eye, wiggle: {speed: 0.85, amplitude_x: 2.0, amplitude_y: 1.0}}
    material: {active: teal}
    particles: {active: none}

  - name: left_mouth
    region: [0, 32, 64, 32]
    material: {active: teal, scroll_x: 12.0}
    particles: {preset: fire}

  - name: right_mouth
    region: [64, 32, 64, 32]
    material: {active: teal, scroll_x: -12.0}
    particles: {preset: fire}

ipc:
  socket:   /run/protoface.sock
  shm_path: /dev/shm/protoface_frame
```

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

Each face lives in its own folder under `faces/`. The folder name matches the `face.active` key in `config.yaml`.

```
faces/
  left_eye/
    neutral.png        64×32 RGBA
    happy.png
    blink.png
    config.json
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

Generate placeholder assets for all four face folders:

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
5. Output           HUB75 DMA (Pi) or pygame preview window (desktop)
   + Shared memory  128×64 RGB written to /dev/shm/protoface_frame
```

---

## ProtoHUD Integration

When running alongside [ProtoHUD](https://github.com/brooksthemaker/ProtoHUD) on the same CM5, Protoface communicates over two channels:

| Channel | Direction | Path | Purpose |
|---------|-----------|------|---------|
| Unix socket | ProtoHUD → Protoface | `/run/protoface.sock` | Commands (set_effect, set_color, etc.) |
| Shared memory | Protoface → ProtoHUD | `/dev/shm/protoface_frame` | Live 128×64 panel preview in HMD |

Enable the panel preview in the ProtoHUD menu: **Menu → Face → Panel Preview**.

### IPC Commands (JSON over Unix socket)

| Command | Fields | Description |
|---------|--------|-------------|
| `set_effect` | `effect_id` 0–15 | Switch particle effect (0=none, 1–7=built-ins, 8–15=presets) |
| `set_effect` | `layers: [...]` | Set arbitrary multi-layer stack |
| `set_color` | `r g b layer` | Set material colour |
| `set_brightness` | `value` 0–255 | Panel brightness |
| `play_gif` | `gif_id` | Play GIF by index |
| `set_palette` | `palette_id` | Switch colour palette |

### Startup order

Start Protoface before ProtoHUD. ProtoHUD's `ProtoFaceController` retries the socket every 2 s so order is not critical, but the socket must exist before ProtoHUD tries to use the preview.

```bash
# /etc/systemd/system/protoface.service
[Unit]
After=network.target
Before=protohud.service

[Service]
ExecStart=/usr/bin/python3 /home/pi/Protoface/run.py
WorkingDirectory=/home/pi/Protoface
User=root
Restart=on-failure
```

See [INTEGRATION.md](INTEGRATION.md) for the full GPIO conflict analysis, CPU budget, and minimal working configuration.

---

## Project Structure

```
run.py                      — entry point; argument parsing; main loop
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
  shm_writer.py             — writes 128×64 RGB to /dev/shm/protoface_frame
  ipc.py                    — Unix socket server; dispatches commands to all panels
  output/
    hub75.py                — rpi-rgb-led-matrix wrapper (graceful ImportError fallback)
    preview.py              — pygame scaled preview window for development
  inputs/
    microphone.py           — threaded PyAudio capture + FFT → volume/spectrum
    gyro.py                 — I2C MPU-6050 → pitch/roll face offset
    boop.py                 — GPIO debounced sensor → expression trigger

faces/
  left_eye/                 — 64×32 sprites + config.json
  right_eye/
  left_mouth/
  right_mouth/
  example_fox/              — single-panel reference design

materials/                  — PNG material files (tiled over face)
particles/
  presets.yaml              — named multi-layer presets (fire, aurora, blizzard, …)
gifs/                       — GIF files; auto-discovered at startup
```

---

## License

MIT — see [LICENSE](LICENSE) if present, otherwise assume all rights reserved until a licence file is added.
