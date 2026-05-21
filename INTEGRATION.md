# Protoface + ProtoHUD Integration Requirements

Analysis of running Protoface (LED face panels) alongside ProtoHUD (XR headset display) on the same CM5 compute module.

---

## Architecture Overview

```
CM5
├── ProtoHUD  (C++ / OpenGL ES)   — drives the HMD display, cameras, menus
│   └── ProtoFaceController       — Unix socket client → Protoface
│   └── ShmFrameReader            — reads /dev/shm/protoface_frame → panel preview
│
└── Protoface  (Python / numpy)   — drives HUB75 LED panels via Piomatter (RP1 PIO)
    └── IpcServer                 — Unix socket server on /run/protoface.sock
    └── ShmWriter                 — writes /dev/shm/protoface_frame
```

ProtoHUD and Protoface communicate through two one-way channels:

| Channel | Direction | Path | Purpose |
|---------|-----------|------|---------|
| Unix socket | ProtoHUD → Protoface | `/run/protoface.sock` | Commands (set_effect, set_color, etc.) |
| Shared memory | Protoface → ProtoHUD | `/dev/shm/protoface_frame` | Live panel preview in HMD |

---

## 1. CPU Requirements

### Protoface (Python)

Per-frame work on the 128×32 canvas at 30 fps (4 regions: 2 eyes + 2 mouths):

| Operation | Approx cost |
|-----------|-------------|
| 4× face sprite compositing (numpy) | ~0.5 ms |
| 4× material multiply | ~0.3 ms |
| 4× particle system update + render | ~1–3 ms (depends on layer count) |
| HUB75 transfer (Piomatter / RP1 PIO) | PIO-driven |
| Shm write (12288 bytes memcpy) | < 0.1 ms |
| **Total budget at 30 fps** | 33 ms |

The Python renderer is comfortably within budget at 30 fps on CM5.  Particle effects with 3+ layers may push towards 5–8 ms total; cap at `fps: 30` or reduce layer counts if needed.

### ProtoHUD (C++)

ProtoHUD is CPU-light per frame (main cost is OpenGL ES calls and camera DMA).  The `ProtoFaceController` reconnect thread sleeps 2 s between polls — negligible.  ShmFrameReader polls at the render frame rate but only does a 12289-byte memcpy when the sequence byte changes.

### CM5 Core Allocation

The CM5 has 4 ARM Cortex-A76 cores.  Suggested pinning (optional, via systemd `CPUAffinity`):

| Process | Suggested cores |
|---------|----------------|
| ProtoHUD render loop | 0, 1 |
| Protoface main loop | 2 |
| Piomatter PIO (RP1) | kernel/PIO-managed |

Without explicit pinning both processes will compete on all cores, which is fine at normal load but can cause frame drops if both spike simultaneously.

---

## 2. GPIO Conflicts ⚠️

This is the most critical hardware concern.

> **Bonnet note:** This analysis was originally written for a bonnet-less build
> that wired HUB75 directly with the raw `regular` mapping. This build now uses
> the **Adafruit Triple LED Matrix Bonnet** (active3 pinout) — you don't wire the
> HUB75 lines yourself, but the bonnet still consumes the same family of GPIO
> pins. The practical conclusions are unchanged: **use a USB mic** (I2S clashes
> with HUB75 lines), **put the gyro on the bonnet's I2C header**, and **a boop
> sensor needs a GPIO the active3 mapping leaves free**. Treat the specific pin
> tables below as a raw-mapping reference; verify any GPIO you intend to reuse
> against Piomatter's active3 pin usage.

### I2S Microphone vs. HUB75 Parallel Row-2

The I2S MEMS microphone (INMP441) and the second parallel row of HUB75 panels share **two GPIO pins**:

| Signal | BCM GPIO | Used by I2S mic | Used by HUB75 parallel row-2 |
|--------|----------|-----------------|------------------------------|
| LRCK (word select) | **GPIO 19** | ✓ WS pin | ✓ R2 (lower red, row 2) |
| DIN (data in) | **GPIO 20** | ✓ SD pin | ✓ B2 (lower blue, row 2) |

**You cannot use the I2S microphone and a multi-port (parallel) panel layout simultaneously** — the second HUB75 chain's data lines land on the I2S pins. (The default 2-panel single-port build only uses port 1, but still: use a USB mic to keep these pins free and avoid surprises if you expand.)

#### Options:

**Option A — Use USB microphone instead** *(recommended)*  
Set `inputs.microphone.type: usb` in `config.yaml`.  No GPIO conflict.  Plug any USB-A mic or USB sound card into the CM5.

**Option B — Remap the I2S overlay to different GPIO**  
The `i2s-mems-mic` overlay can be redirected using a custom device-tree overlay with different pin assignments.  This requires building a `.dts` file and is non-trivial.

**Option C — Use a USB audio interface for the mic**  
Same as Option A.  Even a £2 USB-C dongle works.

### Other GPIO in use

| Function | Pins | Conflict risk |
|----------|------|---------------|
| HUB75 data (row 1) | GPIO 11,27,7,8,9,25 | Dedicated — no conflict |
| HUB75 control | GPIO 22,23,24,10,17,4,18 | CLK=GPIO17 (same as I2C1-SDA on some mappings — verify) |
| HUB75 data (row 2) | GPIO 12,5,6,19,26,20 | GPIO 19+20 clash with I2S mic (above) |
| MPU-6050 (gyro) | GPIO 2 (SDA), 3 (SCL) | Safe — I2C bus shared between devices is fine |
| Boop sensor | GPIO 17 | **CLK conflict**: GPIO 17 is used for HUB75 CLK in `regular` mapping |

> **Boop sensor conflict:** The default GPIO 17 for the boop sensor collides with HUB75 CLK.  Reassign the boop sensor to an unused pin, e.g. GPIO 16 (Pin 36) or GPIO 21 (Pin 40).  Update `inputs.boop.gpio_pin` in `config.yaml`.

### ProtoHUD GPIO Usage

ProtoHUD runs on the same CM5 but drives its hardware differently:

| ProtoHUD function | Interface | GPIO pins |
|-------------------|-----------|-----------|
| IMU (Mpu9250) | SPI | GPIO 10,9,11,8 (SPI0) |
| Cameras (OV9281) | CSI / MIPI | dedicated CSI lanes — not GPIO |
| Display (DP/HDMI) | HDMI/DSI | dedicated — not GPIO |
| SmartKnob | UART | GPIO 14,15 (UART0) |

**SPI conflict:** ProtoHUD's IMU uses SPI0 (GPIO 8–11).  HUB75 `regular` mapping uses GPIO 11 (R1) and GPIO 9 (G2).  **GPIO 9 and 11 are shared.**

This means ProtoHUD's Mpu9250 over SPI0 and HUB75 panels **cannot run simultaneously** on the `regular` pin mapping.

#### Resolving the SPI/HUB75 conflict

Use an **alternative HUB75 pin mapping** that avoids SPI0 pins, or connect the IMU over **I2C** instead of SPI.  The MPU-9250 supports both; change the ProtoHUD config to use I2C (GPIO 2/3) and share the bus with the MPU-6050 at a different I2C address.

Moving the IMU to I2C is the clean fix — the bonnet's active3 pinout occupies the HUB75 data lines and isn't reconfigurable per-pin the way hzeller mappings were.

---

## 3. Memory

| Component | Resident memory |
|-----------|----------------|
| ProtoHUD process | ~120–300 MB (camera buffers, GL textures) |
| Protoface process (4 panels, 30 fps) | ~60–90 MB (numpy arrays, PIL images) |
| `/dev/shm/protoface_frame` | 12 KB |
| Piomatter / PIO buffers | ~1–2 MB |
| **Total** | ~200–400 MB |

CM5 ships with 2–8 GB.  Memory is not a concern on any variant.

---

## 4. Display / GPU

| Resource | ProtoHUD | Protoface |
|----------|---------|-----------|
| GPU (VideoCore VII) | OpenGL ES — HMD display render | Not used |
| Display output | HDMI/DSI → HMD | HUB75 via RP1 PIO (no GPU) |
| Camera ISP | 2× OV9281 cameras | Not used |

No GPU or display conflict.  Protoface renders entirely in CPU/numpy and pushes pixels via Piomatter through the RP1 PIO, which bypasses the GPU completely.

---

## 5. Startup Order and systemd Services

Protoface must start before ProtoHUD tries to use it, or ProtoHUD must gracefully handle the socket being absent (it already does — `ProtoFaceController::start()` is non-blocking and retries every 2 s).

### Recommended service files

**`/etc/systemd/system/protoface.service`:**
```ini
[Unit]
Description=Protoface LED Face Panels
After=network.target
# Start before protohud so the socket is ready
Before=protohud.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /home/pi/Protoface/run.py
WorkingDirectory=/home/pi/Protoface
# Piomatter needs /dev/pio0 (gpio group), not root.
User=pi
SupplementaryGroups=gpio i2c audio
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/protohud.service`:**
```ini
[Unit]
Description=ProtoHUD XR Display
After=protoface.service

[Service]
Type=simple
ExecStart=/home/pi/protohud/build/protohud
WorkingDirectory=/home/pi/protohud
User=root
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

> ProtoHUD needs **root** (or the `video` group) for OpenGL ES display access.
> Protoface does **not** need root — Piomatter uses `/dev/pio0` (gpio group).

Enable both:
```bash
sudo systemctl enable protoface protohud
sudo systemctl start protoface
sudo systemctl start protohud
```

---

## 6. Permissions

| Requirement | Both processes | Fix |
|-------------|---------------|-----|
| HUB75 (Piomatter) | Protoface needs `/dev/pio0` | user in `gpio` group (no root) |
| OpenGL ES display | ProtoHUD needs root or `video` group | `User=root` or `supplementary_groups=video` |
| `/run/protoface.sock` | Created by Protoface (mode 0660) | Run Protoface first so socket exists |
| `/dev/shm/protoface_frame` | Created by Protoface | Protoface must start first |
| GPIO access | Protoface (boop, gyro) | `/dev/gpiomem` — root or `gpio` group |
| I2C access | Protoface (gyro) | `/dev/i2c-1` — root or `i2c` group |

---

## 7. Conflict Summary and Action Items

| Issue | Severity | Action |
|-------|----------|--------|
| GPIO 19+20: I2S mic vs. HUB75 row-2 | **Blocking if using I2S mic** | Switch to USB microphone |
| GPIO 9+11: SPI0 IMU vs. HUB75 row-1 | **Blocking if ProtoHUD uses SPI IMU** | Move ProtoHUD IMU to I2C (active3 pins aren't remappable) |
| GPIO 17: boop sensor vs. HUB75 CLK | **Blocking if boop enabled** | Reassign boop to GPIO 16 or 21 in config.yaml |
| Startup ordering | Low — ProtoHUD retries connection | Use systemd `After=protoface.service` |
| CPU competition | Low on CM5 | Optional: `CPUAffinity` in service files |
| Memory | None — well within CM5 headroom | — |
| GPU / display | None — different subsystems | — |

---

## 8. Minimal Working Configuration

If you want both running immediately with no hardware changes:

1. **USB mic** — set `inputs.microphone.type: usb`
2. **Boop sensor** on GPIO 16 — set `inputs.boop.gpio_pin: 16`
3. **ProtoHUD IMU via I2C** — reconfigure ProtoHUD's Mpu9250 to use I2C bus 1 (GPIO 2/3) at address 0x69 (AD0 high)
4. **Confirm `/dev/pio0` exists** and `display.preview: false` in Protoface `config.yaml` (Piomatter handles the pinout; no `hardware_mapping`/`gpio_slowdown` needed)
5. Deploy both systemd services with Protoface `Before=protohud.service`
