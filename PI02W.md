# Protoface on the Raspberry Pi Zero 2W

The standalone Pi Zero 2W build: same faces, particles, and IPC as the CM5
build, driven through **hzeller's `rpi-rgb-led-matrix`** instead of Piomatter,
with a **classic Adafruit RGB Matrix Bonnet** and a **button coprocessor**
(Pico over USB) for physical controls.

> **Why a different driver:** Piomatter needs the RP1 chip's PIO state
> machines (`/dev/pio0`) — Pi 5 / CM5 only. The Zero 2W (BCM2710) has no RP1,
> but its GPIO *can* be bit-banged, which is exactly what hzeller's library
> does (and why that library conversely can't run on the CM5). `run.py` picks
> the backend via `display.driver` (`auto` detects `/dev/pio0`).

---

## Hardware

| Part | Details |
|------|---------|
| Board | Raspberry Pi Zero 2W (quad A53 @ 1 GHz, 512 MB) |
| Adapter | Adafruit **RGB Matrix Bonnet** (PID 3211) — single HUB75 port, on-board level shifters |
| Panels | 2× 64×32 HUB75 (1:16 scan), daisy-chained → 128×32 canvas |
| Power | External 5 V / 10 A+ to the bonnet screw terminal; each panel powered directly from the PSU |
| Controls | Button coprocessor: Raspberry Pi Pico / Pico 2 on USB (see below) |
| Mic | USB microphone (no I2S pins free) |

Wiring is the same shape as the CM5 build (see `HARDWARE.md` §2–3): bonnet
port → panel A IN, panel A OUT → panel B IN, ribbons under ~20 cm, panel power
straight from the PSU, common ground.

**Optional PWM jumper mod:** solder a jumper between the bonnet's GPIO4 and
GPIO18 pads and use `hardware_mapping: adafruit-hat-pwm` for hardware-PWM
timing (much less flicker). Without the mod, keep `adafruit-hat`.

**Free GPIO** with the bonnet in place: I2C (2/3 — gyro works via the bonnet's
STEMMA/I2C pins), SPI (7–11), UART (14/15), and BCM 19/25 (boop sensor). GPIO 4
and 18 belong to the matrix (OE / PWM jumper).

## OS setup

Raspberry Pi OS **Lite 64-bit**. Then:

```bash
# 1. The matrix driver conflicts with onboard audio — blacklist it
echo "blacklist snd_bcm2835" | sudo tee /etc/modprobe.d/blacklist-rgb-matrix.conf
sudo sed -i 's/dtparam=audio=on/dtparam=audio=off/' /boot/firmware/config.txt

# 2. Reserve a core for the matrix refresh thread (recommended)
#    append to the single line in /boot/firmware/cmdline.txt:
#    isolcpus=3

sudo reboot
```

## Install

```bash
sudo apt install -y python3-dev python3-pip python3-venv cython3 git
git clone https://github.com/brooksthemaker/ProtoFace ~/Protoface
cd ~/Protoface
python3 -m venv --system-site-packages .venv && source .venv/bin/activate
pip install -r requirements.txt        # numpy Pillow PyYAML pygame pyaudio pyserial

# hzeller rgbmatrix python binding (no wheel — build once, ~10 min on the Zero 2W)
git clone https://github.com/hzeller/rpi-rgb-led-matrix ~/rpi-rgb-led-matrix
cd ~/rpi-rgb-led-matrix && make build-python PYTHON=$(which python3)
sudo make install-python PYTHON=$(which python3)
```

## Run

```bash
cd ~/Protoface
sudo $(which python3) run.py --config config.pi02w.yaml
```

Root is required (the driver maps `/dev/mem`). `drop_privileges` is off in the
profile so `state.yaml` and the IPC socket stay writable; the usual deployment
is a systemd unit running as root:

```ini
# /etc/systemd/system/protoface.service
[Unit]
Description=Protoface LED face
After=network.target

[Service]
ExecStart=/home/pi/Protoface/.venv/bin/python /home/pi/Protoface/run.py --config /home/pi/Protoface/config.pi02w.yaml
WorkingDirectory=/home/pi/Protoface
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Solo terminal controls (`c/v x/z e/w b +/- s q`) work over SSH exactly as on
the CM5 — see the README table.

### Performance notes

- The render pipeline is numpy at 30 fps over 128×32 — the Zero 2W keeps up
  at moderate particle counts. If frames drop: `display.fps: 25`, lower
  particle `count`s, or `pwm_bits: 10`.
- `gpio_slowdown: 1` is the usual Zero 2W value (`0` if your panels tolerate
  it, `2` if you see glitching).
- Colour order is handled by `led_rgb_sequence` (hzeller-native) — **not** the
  `(G,B,R)` resend the Piomatter path applies. Panels that show rotated
  colours want `led_rgb_sequence: GBR`.
- `max_brightness_pct` caps panel current in hardware; render-pipeline
  brightness (`+`/`-`, IPC `set_brightness`) still applies on top.

---

## Button coprocessor

The bonnet leaves almost no GPIO, so physical controls live on a Raspberry Pi
Pico (RP2040/RP2350) speaking **ProtoHUD's `proto-buttons v1`** protocol over
USB CDC — flash [`ProtoHUD/firmware/button_coproc/pico`](https://github.com/brooksthemaker/ProtoHUD/tree/main/firmware/button_coproc)
**unchanged**; the same board works against either project.

```
switches ── Pico GPIO (INPUT_PULLUP, other leg to GND)
Pico USB ── Pi Zero 2W USB port (data port, not PWR)
```

The firmware debounces, classifies short vs long press, and streams
`BTN <id> SHORT|LONG` lines; Protoface maps ids to actions in
`inputs.coprocessor.buttons` (`config.pi02w.yaml`), so remapping never needs a
reflash. Actions are the solo-control set: `next_expression`,
`prev_expression`, `next_color`, `prev_color`, `next_effect`, `prev_effect`,
`blink`, `boop`, `brightness_up`, `brightness_down`, `save`, `quit`.

After flashing, confirm the stable device path and point the config at it:

```bash
ls -l /dev/serial/by-id/     # …ProtoHUD_Buttons…-if00 (serial suffix is globbed)
```

---

## Face editor

`editor.py` is a desktop pixel editor for the face PNGs — a Python port of
ProtoHUD's in-HMD FaceEditor (tools, palette, mirror brush, undo, eye/mouth
hit-box authoring). ProtoHUD's camera features are **not** included in this
build.

```bash
python editor.py                 # edits faces/main (from config.yaml)
python editor.py --face example_fox --scale 18
```

Run it on a desktop machine against a checkout of the repo, or on the Pi over
VNC. With the daemon running on the panels, **V** pushes the canvas onto the
physical panels for 10 s (IPC `preview_face`), and **T** overlays the daemon's
live composited frame (material + particles) while you draw. Key reference is
in the module docstring (`python -c "import editor; print(editor.__doc__)"`).

---

## Differences vs the CM5 build

| | CM5 (`config.yaml`) | Pi Zero 2W (`config.pi02w.yaml`) |
|---|---|---|
| Driver | Piomatter (RP1 PIO, `/dev/pio0`) | hzeller `rpi-rgb-led-matrix` |
| Bonnet | Triple Matrix Bonnet (PID 6358, 3 ports) | RGB Matrix Bonnet (PID 3211, 1 port) |
| Max layout | 3 ports × chains | 1 port, chain only |
| Privileges | none (gpio group) | root (`/dev/mem`) |
| Colour fix | `(G,B,R)` resend in `hub75.py` | `led_rgb_sequence` option |
| Physical controls | free GPIO / ProtoHUD | button coprocessor (Pico, USB) |
| Audio module | n/a | `snd_bcm2835` must be blacklisted |
