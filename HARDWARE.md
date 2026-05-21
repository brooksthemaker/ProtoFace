# Protoface Hardware Reference

Component list, power requirements, and wiring for a CM5-driven HUB75 LED face
display using the **Adafruit Triple LED Matrix Bonnet** and the **Piomatter**
driver.

> **Why a bonnet + Piomatter:** The CM5 (Pi 5 / RP1 family) can't run hzeller's
> `rpi-rgb-led-matrix` (its GPIO isn't directly bit-bangable). The Triple Matrix
> Bonnet carries the level shifters and HUB75 wiring, and Adafruit's Piomatter
> driver generates the signal through the RP1's PIO. An earlier revision of this
> doc described a bonnet-less build with discrete 74AHCT125 level shifters driven
> by hzeller — that path does **not** work on the CM5 and has been removed.

---

## Table of Contents

1. [Core Components](#1-core-components)
2. [Power System](#2-power-system)
3. [Wiring](#3-wiring)
4. [Driver — Piomatter](#4-driver--piomatter)
5. [Optional Inputs](#5-optional-inputs)
6. [HUB75 Connector Reference](#6-hub75-connector-reference)
7. [Bill of Materials](#7-bill-of-materials)
8. [Troubleshooting](#8-troubleshooting)
9. [config.yaml Reference](#9-configyaml-reference)

---

## 1. Core Components

### Raspberry Pi Compute Module 5

The compute module that runs Protoface. Mounts on a carrier board that breaks
out the 40-pin GPIO header (the official CM5 IO board or any compatible carrier).
The CM5 is required for this build because the HUB75 output path uses the RP1
PIO via Piomatter.

| Variant | RAM | eMMC | Use case |
|---------|-----|------|----------|
| CM5 | 2–8 GB | 16–64 GB | Standard / parallel ProtoHUD |

**OS:** Raspberry Pi OS (trixie / Debian 13, 64-bit) with the Raspberry Pi
downstream kernel and current firmware, so that `/dev/pio0` exists.

### Adafruit Triple LED Matrix Bonnet (PID 6358)

```
  ┌───────────────────────────────────────────┐
  │  [Port 1]   [Port 2]   [Port 3]   HUB75    │
  │   ▦▦▦        ▦▦▦        ▦▦▦       outputs  │
  │                                            │
  │   ◉ 5V screw terminal      ⌷ I2C header    │
  │   ───── mounts on 40-pin GPIO header ───── │
  └───────────────────────────────────────────┘
```

- **3 HUB75 output ports** ("active3" pinout) — drive up to 3 chains in parallel.
- **On-board level shifters** (3.3 V → 5 V). No discrete buffers or breadboard
  wiring needed — fully assembled, no soldering.
- **5 V screw terminal** for external panel/logic power.
- **I2C header** — convenient for the gyro and other I2C peripherals.

### HUB75 RGB LED Matrix Panels — 64×32

```
  ┌──────────────────────────────────────────────┐
  │  · · · · · · · · · · · · · · · · · · · · ·  │  32
  │  · · · · · · · · · · · · · · · · · · · · ·  │  rows
  │ [HUB75 IN ▶]                  [HUB75 OUT ▶] │
  └──────────────────────────────────────────────┘
                    64 columns
```

The current build uses **2× 64×32** panels daisy-chained on **port 1**
(128×32 logical canvas). Each panel splits into a top half and bottom half
driven via separate R1/G1/B1 and R2/G2/B2 lines (handled by the bonnet).

| Parameter | Value | Notes |
|-----------|-------|-------|
| Interface | HUB75 | active3 / standard pinout |
| Scan rate | 1:16 | Standard for 32-row panels |
| Pitch | P2.5 / P3 / P4 | P2.5 draws the most current |
| Voltage | 5 V | Matches the PSU |
| Connector | 16-pin IDC | Standard HUB75 ribbon |

> Avoid panels labelled **HUB75E** (the extra E address line is for 64-row
> panels). A standard 64×32 panel uses 4 address lines.

---

## 2. Power System

### Current Draw Estimates

| Component | Voltage | Typical | Peak (worst case) |
|-----------|---------|---------|-------------------|
| CM5 (idle) | 5 V | 0.8 A | 1.5 A |
| CM5 (load) | 5 V | 1.5 A | 3.0 A |
| 64×32 P2.5 panel @ moderate brightness | 5 V | ~2 A | — |
| 64×32 P2.5 panel @ full white | 5 V | — | ~8 A |
| 2× 64×32 P2.5 panels | 5 V | ~4 A | up to ~16 A |

> P2.5 panels draw a lot at full white. Keep brightness moderate and provision
> PSU headroom. **The bonnet itself requires an external 5 V / 10 A+ supply.**

### Wiring the Power

```
  5V PSU (+) ──┬──► Bonnet 5V screw terminal
               └──► HUB75 panel power connectors (red/+5V) — one run per panel

  5V PSU (-) ──┬──► Bonnet GND
               └──► HUB75 panel power connectors (black/GND)
```

- **Power each panel directly from the PSU** in parallel. Do **not** chain panel
  power through the HUB75 OUT connector. Use heavy-gauge wire (18 AWG or better)
  for panel power runs.
- **Common ground:** the bonnet, panels, and CM5 must share GND. Floating
  grounds corrupt the display and can damage driver ICs.

---

## 3. Wiring

The bonnet does all the signal wiring — mount it and plug in ribbons.

```
1. Power off. Seat the bonnet on the CM5 carrier's 40-pin header.

2. Port 1 ──ribbon──► Panel A [IN]
   Panel A [OUT] ──ribbon──► Panel B [IN]      (daisy chain, 2 panels)

3. PSU 5V ──► bonnet screw terminal AND each panel's power connector.

4. Power on.
```

- Keep each HUB75 ribbon under ~20 cm; longer cables pick up noise and cause
  flicker/colour errors.
- To expand: add panels to the chain (raise `chain_length`) and/or use ports 2
  and 3 (raise `parallel`, up to 3).

---

## 4. Driver — Piomatter

Install:

```bash
pip install Adafruit-Blinka-Raspberry-Pi5-Piomatter
# trixie pip is externally managed (PEP 668): use a venv or --break-system-packages
```

Confirm the PIO device (created by the RP1 downstream kernel + recent firmware):

```bash
ls -l /dev/pio0          # crw-rw---- root gpio ...  → good, no sudo needed
lsmod | grep -i pio      # rp1_pio should be loaded
```

If `/dev/pio0` is missing: update firmware (`sudo apt update && sudo apt full-upgrade`),
reboot, and re-check. If it's owned by `root:root`, add a udev rule:
`SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"` in `/etc/udev/rules.d/99-com.rules`.

**Geometry (2× 64×32 on port 1):** Protoface builds this in
`protoface/output/hub75.py`:

| Parameter | Value | Meaning |
|-----------|-------|---------|
| `pinout` | `Pinout.Active3` | the triple bonnet pinout |
| `n_addr_lines` | 4 | 32-row panel (2^4 = 16 addressed rows) |
| `n_lanes` | 2 | port 1's two RGB triples (R1G1B1 + R2G2B2) |
| `width` | 128 | 64 × chain_length(2) |
| `height` | 32 | n_lanes << n_addr_lines |
| `colorspace` | `RGB888Packed` | framebuffer is (H, W, 3) uint8 |
| `map` | `simple_multilane_mapper(...)` | lane/address → pixel mapping |

**Colour order:** these panels display colours rotated R→G→B, so the driver
resends each pixel as `(G, B, R)`. If colours are wrong, adjust that line in
`hub75.py`.

---

## 5. Optional Inputs

All optional and individually enabled in `config.yaml`. The active3 pinout uses
most GPIO lines for HUB75, so prefer the bonnet's I2C header and USB for inputs.

### USB Microphone *(recommended)*

```
  CM5 USB port ──► USB microphone / USB sound card + 3.5 mm mic
```

Plug-and-play. Set `inputs.microphone.type: usb`. Drives mouth animation and
audio-reactive particles. (An I2S MEMS mic would collide with HUB75 GPIO lines —
use USB.)

### MPU-6050 Gyro / Accelerometer (I2C)

```
  Bonnet I2C header        MPU-6050
  ┌──────────┐            ┌──────────┐
  │ SDA      ├───────────►│ SDA      │
  │ SCL      ├───────────►│ SCL      │
  │ 3.3V     ├───────────►│ VCC      │
  │ GND      ├───────────►│ GND      │
  └──────────┘            └ AD0→GND (addr 0x68) ┘
```

Translates head tilt into an XY face offset. Enable with `inputs.gyro.enabled: true`.
I2C is far too slow to drive panels — it's only for sensors like this.

### Boop Sensor (GPIO)

A capacitive (e.g. TTP223) or IR proximity sensor on a single GPIO triggers a
configurable expression. **Pick a GPIO the active3 mapping leaves free** and set
`inputs.boop.gpio_pin` accordingly — most header pins are taken by HUB75, so
verify against the Piomatter active3 pin usage before wiring.

---

## 6. HUB75 Connector Reference

Standard 16-pin HUB75 IDC (for understanding the ribbon; the bonnet drives these):

```
   1  R1     2  G1
   3  B1     4  GND
   5  R2     6  G2
   7  B2     8  GND
   9  A     10  B
  11  C     12  D
  13  CLK   14  LAT/STB
  15  OE    16  GND
```

Pin 1 is marked with a triangle or red stripe on the ribbon. Panels have an
**IN** and an **OUT** connector — feed the bonnet into IN; OUT chains to the next
panel.

---

## 7. Bill of Materials

| # | Component | Value / Part | Qty | Notes |
|---|-----------|-------------|-----|-------|
| 1 | Compute module | CM5 | 1 | Required (RP1 PIO) |
| 2 | Carrier board | CM5/CM4 IO board or equivalent | 1 | Exposes 40-pin header |
| 3 | Matrix adapter | Adafruit Triple LED Matrix Bonnet (PID 6358) | 1 | On-board level shifters |
| 4 | HUB75 panel | 64×32, 1:16 scan | 2 | Daisy-chained on port 1 |
| 5 | 5 V PSU | 5 V / 10 A+ (more for full brightness) | 1 | Powers bonnet + panels |
| 6 | HUB75 ribbon | 16-pin IDC | 2 | One bonnet→panel, one panel→panel; <20 cm |
| 7 | Power wire | 18 AWG stranded | — | Panel power runs |
| 8 | USB microphone | USB-A mic / sound card | 1 | Optional |
| 9 | MPU-6050 | I2C breakout | 1 | Optional — via bonnet I2C header |
| 10 | Boop sensor | TTP223 / TCRT5000 | 1 | Optional — needs a free GPIO |

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `/dev/pio0` not found | Old firmware/kernel | `apt full-upgrade`, reboot; confirm RPi downstream kernel |
| Colours wrong (R/G/B swapped) | Panel colour order | The driver sends `(G,B,R)`; adjust in `hub75.py` if your panels differ |
| Permission denied on `/dev/pio0` | Not in `gpio` group / root-owned node | Add user to `gpio`, or add the udev rule (see §4) |
| Only one panel lights | Chain ribbon OUT→IN reversed/loose | Check the panel A OUT → panel B IN ribbon |
| Half a panel blank | R2/G2/B2 issue on that panel | Reseat the ribbon; check the panel |
| Random flicker | Long/noisy ribbon, weak PSU | Shorten ribbons (<20 cm); add PSU headroom |
| Right panel not mirrored / out of sync | `mirror_of` not set | set `mirror_of: face_left` on the right panel in config.yaml |
| Panel works in preview, not on hardware | `display.preview: true` | Set `display.preview: false` |
| Panels overheat (P2.5) | Brightness too high | Lower brightness; ensure airflow |

---

## 9. config.yaml Reference

### Current build — 2 panels on port 1 (128×32):

```yaml
panel:
  panel_width:  64
  panel_height: 32
  chain_length: 2          # 2 panels daisy-chained on port 1
  parallel:     1          # port 1 only (bonnet supports up to 3)
  # hardware_mapping / gpio_slowdown / brightness are legacy hzeller knobs,
  # ignored by Piomatter. Brightness is applied in the render pipeline.

display:
  fps:     30
  preview: false           # false = HUB75 output; true = pygame window (dev)

inputs:
  microphone:
    enabled: true
    type: usb              # use USB (I2S pins clash with HUB75)
  gyro:
    enabled: false
    i2c_address: 0x68      # via the bonnet's I2C header
  boop:
    enabled: false
    gpio_pin: 16           # must be a GPIO the active3 mapping leaves free
```

### Expanding (more panels / ports):

```yaml
panel:
  chain_length: 3          # 3 panels daisy-chained per port
  parallel:     2          # ports 1 and 2  → canvas 192×64
```

> Validate any new geometry against Adafruit's `triple_matrix_active3_simpletest.py`
> example before relying on it — lane/port ordering for multi-port layouts should
> be confirmed on hardware.
