# Protoface Hardware Reference

Complete component list, power requirements, and wiring guide for building a
CM4/CM5 driven HUB75 LED face display without a HAT or bonnet.

---

## Table of Contents

1. [Core Components](#1-core-components)
2. [Level Shifting](#2-level-shifting)
3. [Optional Inputs](#3-optional-inputs)
4. [Power System](#4-power-system)
5. [Connectors & Cables](#5-connectors--cables)
6. [Full Bill of Materials](#6-full-bill-of-materials)
7. [Wiring Diagrams](#7-wiring-diagrams)
8. [GPIO Pinout Table](#8-gpio-pinout-table)
9. [config.yaml Reference](#9-configyaml-reference)

---

## 1. Core Components

### Raspberry Pi CM4 or CM5

```
  ┌─────────────────────────────┐
  │  ○  Raspberry Pi CM5  ○    │
  │  ┌──────────┐               │
  │  │  BCM2712 │  RAM  EMMC   │
  │  └──────────┘               │
  │  ○                       ○  │
  └─────────────────────────────┘
        (mounts on carrier board)
```

The compute module that runs Protoface.  CM5 is preferred for its faster CPU
(useful if running ProtoHUD in parallel), but CM4 works fine for Protoface
alone.

| Variant | RAM | eMMC | Use case |
|---------|-----|------|----------|
| CM4 Lite | 1–8 GB | none (SD card) | Budget builds |
| CM4 | 1–8 GB | 8–32 GB | Standard |
| CM5 | 2–8 GB | 16–64 GB | Parallel ProtoHUD |

**Requires:** A carrier/IO board that breaks out the 40-pin GPIO header.
The official Raspberry Pi CM4 IO Board or any carrier with a standard 40-pin
header works.  The CM5 uses the same form factor.

---

### HUB75 RGB LED Matrix Panel — 64×32

```
  ┌──────────────────────────────────────────────┐
  │  · · · · · · · · · · · · · · · · · · · · ·  │
  │  · · · · · · · · · · · · · · · · · · · · ·  │
  │  · · · · · · · · · · · · · · · · · · · · ·  │  32
  │  · · · · · · · · · · · · · · · · · · · · ·  │  rows
  │  · · · · · · · · · · · · · · · · · · · · ·  │
  │  · · · · · · · · · · · · · · · · · · · · ·  │
  │ [HUB75 IN ▶]                  [HUB75 OUT ▶] │
  └──────────────────────────────────────────────┘
                    64 columns
```

The LED display.  Each dot is one RGB LED.  The panel is split into a top half
(rows 0–15) and a bottom half (rows 16–31) which are driven simultaneously via
separate R1/G1/B1 and R2/G2/B2 data lines.

**Key specs to check when buying:**

| Parameter | Required value | Why |
|-----------|---------------|-----|
| Interface | HUB75 | The library only supports HUB75 |
| Scan rate | 1:16 | Standard for 32-row panels |
| Pitch | 3 mm or 4 mm | P3 and P4 are the most common |
| Voltage | 5 V | Matches the PSU |
| Connector | 16-pin IDC | Required for standard wiring |

> **Avoid** panels labelled HUB75E — these add an E address line for 64-row
> panels and need extra config.  A standard 64×32 panel is HUB75, not HUB75E.

### 4-Panel 2×2 Face Layout

Protoface supports driving four 64×32 panels simultaneously, arranged in a
2×2 grid to form a full robot face with independent eye and mouth regions.

```
  ┌────────────────────┬────────────────────┐
  │    Left Eye        │    Right Eye       │  ← chain 1 (top row)
  │    64×32           │    64×32           │     parallel = 1
  ├────────────────────┼────────────────────┤
  │    Left Mouth      │    Right Mouth     │  ← chain 2 (bottom row)
  │    64×32           │    64×32           │     parallel = 2
  └────────────────────┴────────────────────┘
         128 columns total × 64 rows total
```

The `rpi-rgb-led-matrix` library treats this as a single 128×64 logical
canvas with `chain_length=2, parallel=2`.  Panels in the same row are
chained (daisy-chained via HUB75 OUT → IN); panels in different rows use a
second parallel data channel via additional GPIO pins.

**Chaining (horizontal):** Connect HUB75 OUT of panel A to HUB75 IN of panel B
within the same row.  The library shifts data for both panels using the same
R1/G1/B1/R2/G2/B2/CLK/LAT/OE/A-D signals.

**Parallel rows:** Each additional parallel row requires its own set of
R1/G1/B1 and R2/G2/B2 data lines.  CLK, LAT, OE, and address lines (A-D)
are shared across all parallel rows.

---

## 2. Level Shifting

The CM4/CM5 GPIO outputs 3.3 V logic.  HUB75 panels are designed for 5 V
logic on their control inputs.  Without level shifting, signal margins are
tight — panels usually work but become unreliable with longer cables or faster
clock speeds.

### Option A — 74AHCT125 Quad Buffer (recommended)

```
         74AHCT125
        ┌────────────┐
  5V ───┤ VCC    GND ├─── GND
        │            │
  GND ──┤ /1OE   1A  ├◄── GPIO (3.3 V)
        │        1Y  ├───► HUB75 signal (5 V)
        │            │
  GND ──┤ /2OE   2A  ├◄── GPIO (3.3 V)
        │        2Y  ├───► HUB75 signal (5 V)
        │            │
  GND ──┤ /3OE   3A  ├◄── GPIO (3.3 V)
        │        3Y  ├───► HUB75 signal (5 V)
        │            │
  GND ──┤ /4OE   4A  ├◄── GPIO (3.3 V)
        │        4Y  ├───► HUB75 signal (5 V)
        └────────────┘
```

- 4 channels per chip → need **4 chips** for 13 HUB75 signals (16 channels total)
- Tie all /OE pins to GND to permanently enable all channels
- Place one **100 nF ceramic capacitor** between VCC and GND on each chip,
  as close to the VCC pin as possible
- Accepts 3.3 V input with 5 V supply — "AHCT" is essential (plain HCT also
  works; plain CMOS 74HC125 does NOT)

### Option B — 74HCT245 Octal Bus Transceiver

```
         74HCT245
        ┌────────────────┐
  5V ───┤ VCC        GND ├─── GND
  5V ───┤ DIR (→ A→B)    │      DIR high = A inputs, B outputs
  GND ──┤ /OE (enable)   │      /OE low  = always enabled
        │                │
  GPIO ─┤ A1          B1 ├───► HUB75
  GPIO ─┤ A2          B2 ├───► HUB75
  GPIO ─┤ A3          B3 ├───► HUB75
  GPIO ─┤ A4          B4 ├───► HUB75
  GPIO ─┤ A5          B5 ├───► HUB75
  GPIO ─┤ A6          B6 ├───► HUB75
  GPIO ─┤ A7          B7 ├───► HUB75
  GPIO ─┤ A8          B8 ├───► HUB75
        └────────────────┘
```

- 8 channels per chip → need **2 chips** for 13 signals
- Simpler layout for breadboard builds
- Same AHCT/HCT rule applies

---

## 3. Optional Inputs

These are all optional and individually enabled/disabled in `config.yaml`.

### USB Microphone / Sound Card

```
  CM5 USB port ──► USB microphone dongle
                   (e.g. generic USB-A sound card + 3.5mm mic)
```

The simplest option.  Plug in and set `inputs.microphone.type: usb` in config.
Drives mouth animation and audio-reactive particle effects.

---

### I2S MEMS Microphone (e.g. INMP441, SPH0645, ICS43434)

```
  CM5 GPIO header              INMP441
  ┌──────────────┐            ┌──────────┐
  │ GPIO 18 (BCK)├───────────►│ SCK      │
  │ GPIO 19 (LRCK├───────────►│ WS       │
  │ GPIO 20 (DIN)│◄───────────┤ SD       │
  │ 3.3V         ├───────────►│ VDD      │
  │ GND          ├───────────►│ GND      │
  │              │            │ L/R ─GND │  (selects left channel)
  └──────────────┘            └──────────┘
```

Higher quality than USB dongles.  Requires adding to `/boot/config.txt`:
```
dtoverlay=i2s-mems-mic
```
Set `inputs.microphone.type: i2s` in `config.yaml`.

---

### MPU-6050 Gyroscope / Accelerometer

```
  CM5 GPIO header              MPU-6050 module
  ┌──────────────┐            ┌──────────────┐
  │ GPIO 2 (SDA) ├───────────►│ SDA          │
  │ GPIO 3 (SCL) ├───────────►│ SCL          │
  │ 3.3V         ├───────────►│ VCC          │
  │ GND          ├───────────►│ GND          │
  │              │            │ AD0 ── GND   │  (I2C address 0x68)
  └──────────────┘            └──────────────┘
```

Measures head tilt and translates pitch/roll into an XY face offset — the
face appears to "slide" in the direction you tilt your head.

Enable with `inputs.gyro.enabled: true` in `config.yaml`.

---

### Boop Sensor

A capacitive or IR proximity sensor wired to a single GPIO pin.  Triggers a
configurable expression (default: `surprised`) for a set duration when the
face is touched or something passes close.

**Capacitive touch (e.g. TTP223 module):**
```
  CM5 GPIO header              TTP223 module
  ┌──────────────┐            ┌──────────────┐
  │ GPIO 17      │◄───────────┤ OUT          │
  │ 3.3V         ├───────────►│ VCC          │
  │ GND          ├───────────►│ GND          │
  └──────────────┘            └──────────────┘
```

**IR proximity (e.g. TCRT5000 or Sharp GP2Y0A):**
Use a comparator or ADC between the sensor and GPIO.  Set the trigger
threshold with the module's onboard potentiometer so the GPIO sees a clean
high/low transition.

Enable with `inputs.boop.enabled: true`, `inputs.boop.gpio_pin: 17`.

---

## 4. Power System

### Current Draw Estimates

| Component | Voltage | Typical | Peak (worst case) |
|-----------|---------|---------|-------------------|
| CM5 module (idle) | 5 V | 0.8 A | 1.5 A |
| CM5 module (load) | 5 V | 1.5 A | 3.0 A |
| 64×32 P2.5 panel @ 50% brightness | 5 V | 2.0 A | — |
| 64×32 P2.5 panel @ 100% brightness (all white) | 5 V | — | ~8 A |
| 4× 64×32 P2.5 panels @ brightness 80 | 5 V | ~8 A | up to 32 A |
| MPU-6050 | 3.3 V | 3 mA | — |
| I2S microphone | 3.3 V | 1 mA | — |
| 74AHCT125 ×5 | 5 V | 25 mA | — |

> **P2.5 panels draw significantly more current than P3/P4** due to higher
> LED density.  A 64×32 P2.5 panel with all pixels white at full brightness
> can draw up to ~8 A.  Always cap brightness in config (`brightness: 80` or
> lower) and provision PSU headroom.

### Recommended PSU — Single Panel (P3/P4)

```
  ┌─────────────────────────────────────────────────────┐
  │                  5 V / 6 A PSU                      │
  │              (30 W minimum; 40 W recommended)        │
  └────────────────┬────────────────────────────────────┘
                   │ 5 V
          ┌────────┴────────┐
          │                 │
     ┌────▼────┐       ┌────▼────────────────────┐
     │  CM5 IO │       │  HUB75 panel power pins  │
     │  board  │       │  + 74AHCT125 VCC          │
     └────┬────┘       └─────────────────────────┘
          │ GND ──────────────────────── shared GND
```

### Recommended PSU — 4-Panel 2×2 Face (P2.5)

```
  ┌─────────────────────────────────────────────────────┐
  │          5 V / 20 A PSU (100 W) minimum             │
  │     5 V / 32 A PSU (160 W) if running full brightness│
  └──────────┬──────────────────────────────────────────┘
             │ 5 V
    ┌─────────┴──────────────────────────┐
    │                                    │
┌───▼───┐                     ┌──────────▼───────────────────┐
│  CM5  │                     │  4× HUB75 panel power connectors │
│  IO   │                     │  + 74AHCT125 ×5 VCC           │
│ board │                     └──────────────────────────────┘
└───┬───┘
    │ GND ────────────────────────────── shared GND (all panels)
```

> **Wire panel power in parallel** directly from the PSU — do NOT chain panel
> power through the HUB75 OUT connector.  Use 18 AWG wire or heavier for the
> power runs to each panel at 4-panel scale.

> **Critical:** The panel power and CM5 power must share a common GND.
> Floating grounds cause corrupted display output and can damage the panel
> driver ICs.

### Wiring the Power

```
  5V PSU (+) ──┬──► CM5 IO board 5V input
               └──► HUB75 power connector (red/+5V wires)
               └──► 74AHCT125 VCC pins

  5V PSU (-) ──┬──► CM5 IO board GND
               └──► HUB75 power connector (black/GND wires)
               └──► 74AHCT125 GND pins
```

Most 64×32 panels have a dedicated 2-pin or 4-pin power connector separate
from the HUB75 signal connector.  Both the signal GND (HUB75 pin 4/8/16) and
the power GND must connect to the same ground rail.

---

## 5. Connectors & Cables

### HUB75 16-Pin IDC Connector

```
  Panel side (female IDC, ribbon cable)
  
  ┌──┬──┐
  │1 │2 │   Pin 1 is usually marked with a triangle or red stripe on ribbon
  ├──┼──┤
  │3 │4 │
  ├──┼──┤
  │5 │6 │
  ├──┼──┤
  │7 │8 │
  ├──┼──┤
  │9 │10│
  ├──┼──┤
  │11│12│
  ├──┼──┤
  │13│14│
  ├──┼──┤
  │15│16│
  └──┴──┘

  Pin assignments:
   1  R1     2  G1
   3  B1     4  GND
   5  R2     6  G2
   7  B2     8  GND
   9  A     10  B
  11  C     12  D
  13  CLK   14  LAT/STB
  15  OE    16  GND
```

**Cable length:** Keep under 20 cm.  HUB75 signals are unshielded and fast;
longer cables pick up noise that causes pixel flickering or colour errors.

Panels typically have both an IN and OUT connector — use IN.  The OUT
connector is for chaining a second panel.

---

## 6. Full Bill of Materials

### Essential — Single Panel (P3 or P4)

| # | Component | Value / Part | Qty | Notes |
|---|-----------|-------------|-----|-------|
| 1 | Compute module | CM4 or CM5 | 1 | Min 1 GB RAM recommended |
| 2 | Carrier board | CM4 IO Board or equivalent | 1 | Must expose 40-pin GPIO |
| 3 | HUB75 LED panel | 64×32, P3 or P4, 1:16 scan | 1 | |
| 4 | Level shifter | 74AHCT125 | 4 | One chip per 4 signals (13 signals total) |
| 5 | OR level shifter | 74HCT245 | 2 | Alternative — 8 signals per chip |
| 6 | Decoupling cap | 100 nF ceramic | 4–8 | One per level shifter chip |
| 7 | 5 V PSU | 5 V / 6 A (30 W) | 1 | Powering CM5 + 1 panel |
| 8 | 16-pin IDC cable | HUB75 ribbon | 1 | Under 20 cm |
| 9 | Proto board | Half-size or full-size | 1 | For level shifter circuit |
| 10 | Jumper wires | M-M and M-F | 20+ | |
| 11 | MicroSD card | 8 GB+ (Class 10) | 1 | Only if using CM4 Lite |

### Essential — 4-Panel 2×2 Face (P2.5, 128×64 canvas)

| # | Component | Value / Part | Qty | Notes |
|---|-----------|-------------|-----|-------|
| 1 | Compute module | CM5 | 1 | CM5 recommended — extra CPU headroom |
| 2 | Carrier board | CM4 IO Board or equivalent | 1 | Must expose 40-pin GPIO |
| 3 | HUB75 LED panel | 64×32, P2.5, 1:16 scan | 4 | 2 for eyes, 2 for mouth |
| 4 | Level shifter | 74AHCT125 | 5 | 4 for row-1 signals + 1 extra for parallel row-2 RGB |
| 5 | Decoupling cap | 100 nF ceramic | 5–10 | One per chip |
| 6 | 5 V PSU | **5 V / 20 A (100 W) min** | 1 | At brightness 80; use 5V/32A for full brightness |
| 7 | 16-pin IDC cable | HUB75 ribbon | 4 | One per panel (under 20 cm) |
| 8 | IDC daisy-chain cable | HUB75 chain (OUT→IN) | 2 | One per row to chain the 2 panels in that row |
| 9 | Power wire | 18 AWG stranded | 2 m+ | Heavy-gauge for panel power runs |
| 10 | Proto board | Full-size | 1 | For all 5 level shifter chips |
| 11 | Jumper wires | M-M and M-F | 40+ | |
| 12 | MicroSD card | 8 GB+ (Class 10) | 1 | Only if using CM4 Lite |

### Optional — Microphone

| # | Component | Value / Part | Qty | Notes |
|---|-----------|-------------|-----|-------|
| 12a | USB microphone | Any USB-A mic or USB sound card + 3.5mm mic | 1 | Easiest option |
| 12b | I2S MEMS mic | INMP441, SPH0645, or ICS43434 module | 1 | Better quality |

### Optional — Gyroscope

| # | Component | Value / Part | Qty | Notes |
|---|-----------|-------------|-----|-------|
| 13 | IMU module | MPU-6050 breakout | 1 | I2C, 3.3 V |
| 14 | 4.7 kΩ resistor | Pull-up | 2 | SDA and SCL lines (if not on module) |

### Optional — Boop Sensor

| # | Component | Value / Part | Qty | Notes |
|---|-----------|-------------|-----|-------|
| 15a | Capacitive touch | TTP223 module | 1 | 3.3 V compatible |
| 15b | IR proximity | TCRT5000 or SHARP GP2Y0A21 | 1 | Needs comparator for clean GPIO signal |

---

## 7. Wiring Diagrams

### Full System Block Diagram

```
  ┌──────────────────────────────────────────────────────────────────┐
  │                         5 V / 6 A PSU                           │
  └──────┬───────────────────────────────────────────────┬──────────┘
         │ 5V                                            │ 5V
         ▼                                               ▼
  ┌─────────────┐    GPIO 3.3V    ┌──────────────┐  ┌──────────────┐
  │  CM5 + IO   │ ──────────────► │ 74AHCT125 ×4 │  │  HUB75 panel │
  │   board     │                 │  level shift  ├─►│  signal pins │
  │             │                 └──────────────┘  │              │
  │  I2C (SDA)  │ ──────────────────────────────────┼─ MPU-6050    │
  │  I2C (SCL)  │ ──────────────────────────────────┘              │
  │  GPIO 17    │ ◄─────── TTP223 boop sensor                      │
  │  I2S pins   │ ◄─────── INMP441 microphone                      │
  │             │                                                   │
  └──────┬──────┘                                    ┌─────────────┘
         │ GND ─────────────────────────────────────► GND (shared)
         └──────────────────────────────────────────►
```

### Level Shifter Detail (74AHCT125)

```
  CM5 GPIO header (3.3V signals)       74AHCT125          HUB75 (5V signals)
  
  GPIO 11 (R1)  ──────────────────► [1A → 1Y] ──────────► R1  (pin 1)
  GPIO 27 (G1)  ──────────────────► [2A → 2Y] ──────────► G1  (pin 2)
  GPIO  7 (B1)  ──────────────────► [3A → 3Y] ──────────► B1  (pin 3)
  GPIO  8 (R2)  ──────────────────► [4A → 4Y] ──────────► R2  (pin 5)
                                     Chip 1
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  GPIO  9 (G2)  ──────────────────► [1A → 1Y] ──────────► G2  (pin 6)
  GPIO 25 (B2)  ──────────────────► [2A → 2Y] ──────────► B2  (pin 7)
  GPIO 22 (A)   ──────────────────► [3A → 3Y] ──────────► A   (pin 9)
  GPIO 23 (B)   ──────────────────► [4A → 4Y] ──────────► B   (pin 10)
                                     Chip 2
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  GPIO 24 (C)   ──────────────────► [1A → 1Y] ──────────► C   (pin 11)
  GPIO 10 (D)   ──────────────────► [2A → 2Y] ──────────► D   (pin 12)
  GPIO 17 (CLK) ──────────────────► [3A → 3Y] ──────────► CLK (pin 13)
  GPIO  4 (LAT) ──────────────────► [4A → 4Y] ──────────► LAT (pin 14)
                                     Chip 3
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  GPIO 18 (OE)  ──────────────────► [1A → 1Y] ──────────► OE  (pin 15)
  (3 spare channels on chip 4)
                                     Chip 4

  All /OE pins (pins 1,4,10,13 per chip) ──► GND
  All VCC pins (pin 14 per chip) ──────────► 5V
  All GND pins (pin 7 per chip)  ──────────► GND
  100 nF cap between VCC and GND on each chip
```

### Additional Level Shifting for 4-Panel Parallel Row

The second parallel row requires 6 additional GPIO → HUB75 data signals
(R1/G1/B1/R2/G2/B2 for the second row's panels).  Add one more 74AHCT125
chip (chip 5) to handle these 6 lines (2 channels spare):

```
  CM5 GPIO header (3.3V)         Chip 5 (74AHCT125)     HUB75 row-2 IN (5V)
  
  GPIO 12 (R1 row-2) ─────────► [1A → 1Y] ──────────► R1  (pin 1)
  GPIO  5 (G1 row-2) ─────────► [2A → 2Y] ──────────► G1  (pin 2)
  GPIO  6 (B1 row-2) ─────────► [3A → 3Y] ──────────► B1  (pin 3)
  GPIO 19 (R2 row-2) ─────────► [4A → 4Y] ──────────► R2  (pin 5)
                                  Chip 5 (channels 1-4)
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  GPIO 26 (G2 row-2) ─────────► [1A → 1Y] ──────────► G2  (pin 6)
  GPIO 20 (B2 row-2) ─────────► [2A → 2Y] ──────────► B2  (pin 7)
  (2 spare channels on chip 5)
```

CLK, LAT, OE, and address lines (A/B/C/D) are shared — connect them to the
HUB75 IN connectors of both parallel rows (wire all CLK inputs together, etc.).

> **Important:** The GPIO pin assignments above match the `regular` hardware
> mapping in `rpi-rgb-led-matrix` for `parallel=2`.  Verify against
> https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/wiring.md
> if you use a different mapping.

---

## 8. GPIO Pinout Table

BCM GPIO numbering.  Verify against the
[rpi-rgb-led-matrix hardware mapping docs](https://github.com/hzeller/rpi-rgb-led-matrix)
before finalising your wiring.

| HUB75 Signal | BCM GPIO | 40-pin Header | Direction |
|---|---|---|---|
| R1 (upper red)   | 11 | Pin 23 | Out |
| G1 (upper green) | 27 | Pin 13 | Out |
| B1 (upper blue)  |  7 | Pin 26 | Out |
| R2 (lower red)   |  8 | Pin 24 | Out |
| G2 (lower green) |  9 | Pin 21 | Out |
| B2 (lower blue)  | 25 | Pin 22 | Out |
| A (row addr 0)   | 22 | Pin 15 | Out |
| B (row addr 1)   | 23 | Pin 16 | Out |
| C (row addr 2)   | 24 | Pin 18 | Out |
| D (row addr 3)   | 10 | Pin 19 | Out |
| CLK (clock)      | 17 | Pin 11 | Out |
| LAT (latch)      |  4 | Pin  7 | Out |
| OE  (output en.) | 18 | Pin 12 | Out |

**HUB75 GND pins (4, 8, 16)** connect to the shared power/Pi GND rail.
**HUB75 power pins** (separate 2-pin or 4-pin connector on the panel) connect
to the 5 V PSU directly — NOT through the level shifters.

### Additional GPIO Pins for 4-Panel Parallel Row 2

| HUB75 Signal | BCM GPIO | 40-pin Header | Direction |
|---|---|---|---|
| R1 (parallel row 2, upper red)   | 12 | Pin 32 | Out |
| G1 (parallel row 2, upper green) |  5 | Pin 29 | Out |
| B1 (parallel row 2, upper blue)  |  6 | Pin 31 | Out |
| R2 (parallel row 2, lower red)   | 19 | Pin 35 | Out |
| G2 (parallel row 2, lower green) | 26 | Pin 37 | Out |
| B2 (parallel row 2, lower blue)  | 20 | Pin 38 | Out |

CLK, LAT, OE, A, B, C, D are shared — connect them to all four panel HUB75 IN
connectors (parallel rows included).

---

## 9. config.yaml Reference

### Single panel (P3/P4):

```yaml
panel:
  panel_width: 64
  panel_height: 32
  brightness: 80            # 0-100; keep under 80 to reduce heat/current
  hardware_mapping: regular # use 'regular' for direct GPIO (not adafruit-hat)
  gpio_slowdown: 2          # increase to 3-4 if pixels look garbled
  chain_length: 1
  parallel: 1
```

### 4-panel 2×2 face (P2.5):

```yaml
panel:
  panel_width: 64
  panel_height: 32
  brightness: 80            # P2.5 panels get very bright/hot above 80
  hardware_mapping: regular
  gpio_slowdown: 4          # P2.5 panels need 3-4; increase if flickering
  chain_length: 2           # 2 panels per row
  parallel: 2               # 2 rows of panels

display:
  fps: 30
  preview: false            # false = HUB75 output; true = pygame window (dev only)

inputs:
  microphone:
    enabled: true
    type: usb               # usb | i2s
    # For I2S mic, also add dtoverlay=i2s-mems-mic to /boot/config.txt

  gyro:
    enabled: false
    i2c_address: 0x68       # MPU-6050 default
    sensitivity: 0.4        # pixels of face offset per degree of tilt

  boop:
    enabled: false
    gpio_pin: 17            # BCM number of the sensor output pin
    expression: surprised
    duration: 2.0
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Display works but colours wrong | R/G/B lines swapped | Check level shifter wiring order |
| Random pixel flickering | Signal noise or missing decoupling caps | Add 100 nF caps; shorten cables |
| Half the panel stays off | R2/G2/B2 not connected or OE stuck high | Check bottom-half data lines; verify OE wiring |
| All pixels on permanently | OE (Output Enable) not connected | OE must be driven; it is active-LOW |
| Corrupted image, shifting rows | Clock too fast for cable length | Increase `gpio_slowdown` in config |
| Panel works in pygame, not HUB75 | `preview: true` still set | Set `display.preview: false` |
| Must run as root | rpi-rgb-led-matrix DMA requirement | `sudo python run.py` — this is expected |
| Bottom two panels blank (4-panel) | Parallel row-2 GPIO not connected | Wire GPIO 12/5/6/19/26/20 via level shifter to bottom row HUB75 IN |
| Wrong panels lit in 4-panel layout | Chain order reversed | Swap HUB75 OUT→IN cable direction within a row |
| Panels overheat quickly (P2.5) | Brightness too high | Lower `brightness` to 60-70; ensure airflow behind panels |
| 4 panels but only 2 rows update | `parallel` not set to 2 | Set `panel.parallel: 2` in config.yaml |
