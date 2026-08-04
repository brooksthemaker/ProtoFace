"""
Button coprocessor input — ProtoHUD "proto-buttons v1" over USB CDC.

The classic Adafruit RGB Matrix Bonnet consumes nearly every usable GPIO on a
Pi Zero 2W, so physical controls move to a small MCU (RP2040/RP2350 Pico) that
debounces the switches and streams events over USB serial. The firmware is
ProtoHUD's `firmware/button_coproc/pico` — unchanged; the same protocol means
one flashed Pico works against either project.

Protocol (newline-delimited ASCII), MCU → Pi:
    HELLO proto-buttons v1 fw=<ver> n=<count>    # once on boot/connect
    BTN <id> SHORT                               # held < long_ms
    BTN <id> LONG                                # held >= long_ms (fires once)
    PING                                         # heartbeat ~1 Hz
Pi → MCU:
    PONG                                         # heartbeat ack
    CFG long_ms=<n>                              # retune long-press threshold
    LED <id> <0|1>                               # drive a switch backlight

The firmware stays "dumb about meaning": this module resolves <id> to an
action name via inputs.coprocessor.buttons and hands the names to run.py,
which dispatches them through the same path as the solo terminal keys.

Config (config.yaml):
    inputs:
      coprocessor:
        enabled: true
        device: /dev/serial/by-id/usb-ProtoHUD_Buttons-if00   # stable path;
                # globbed, so the board-serial suffix udev appends still matches
        baud: 115200
        long_ms: 600          # optional: pushed via CFG on connect
        buttons:              # id → action (string = short press only)
          0: {short: next_expression, long: save}
          1: {short: next_color,      long: prev_color}
          2: {short: next_effect,     long: prev_effect}
          3: {short: blink,           long: boop}
          4: {short: brightness_up,   long: brightness_down}

Valid actions (run.py's solo-control set):
    next_expression prev_expression next_color prev_color next_effect
    prev_effect blink boop brightness_up brightness_down save quit

Needs pyserial (pip install pyserial); no-ops gracefully without it, without a
device, or with enabled: false — like every other optional input.
"""

from __future__ import annotations

import glob
import threading
import time

try:
    import serial
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class ButtonCoprocessor:
    def __init__(self, cfg: dict):
        c = (cfg.get('inputs', {}) or {}).get('coprocessor', {}) or {}
        self.enabled = bool(c.get('enabled', False)) and _AVAILABLE
        if c.get('enabled') and not _AVAILABLE:
            print('[coproc] pyserial not installed — coprocessor disabled')

        self._device_pattern = c.get(
            'device', '/dev/serial/by-id/usb-ProtoHUD_Buttons-if00')
        self._baud    = int(c.get('baud', 115200))
        self._long_ms = c.get('long_ms')          # None = firmware default

        # Button map: id → {'short': action, 'long': action}. A bare string
        # value is shorthand for short-press only.
        self._map: dict[int, dict] = {}
        for key, val in (c.get('buttons') or {}).items():
            if isinstance(val, str):
                val = {'short': val}
            self._map[int(key)] = val or {}

        self._ser        = None
        self._running    = False
        self._thread     = None
        self._lock       = threading.Lock()
        self._actions: list[str] = []
        self._connected  = False
        self._last_seen  = 0.0
        self._fw_banner  = ''

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        if not self.enabled or self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def close(self):
        self._running = False
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    # ── run.py API ────────────────────────────────────────────────────────────

    def get_actions(self) -> list[str]:
        """Drain and return pending action names (thread-safe, never blocks)."""
        if not self.enabled:
            return []
        with self._lock:
            out, self._actions = self._actions, []
        return out

    def set_led(self, button_id: int, on: bool):
        """Drive a switch backlight on the coprocessor (best-effort)."""
        self._send(f'LED {int(button_id)} {1 if on else 0}')

    @property
    def connected(self) -> bool:
        # Heartbeat is ~1 Hz; treat >3 s of silence as offline.
        return self._connected and (time.monotonic() - self._last_seen) < 3.0

    # ── Reader thread ─────────────────────────────────────────────────────────

    def _resolve_device(self) -> str | None:
        """The by-id path udev creates usually carries the board's unique
        serial (…ProtoHUD_Buttons_<serial>-if00), so glob around the configured
        stem instead of requiring an exact match."""
        for pattern in (self._device_pattern,
                        self._device_pattern.replace('-if00', '*-if00'),
                        '/dev/serial/by-id/*ProtoHUD_Buttons*'):
            hits = sorted(glob.glob(pattern))
            if hits:
                return hits[0]
        return None

    def _loop(self):
        announced_wait = False
        while self._running:
            dev = self._resolve_device()
            if dev is None:
                if not announced_wait:
                    print(f'[coproc] waiting for {self._device_pattern} …')
                    announced_wait = True
                time.sleep(2.0)
                continue
            try:
                self._ser = serial.Serial(dev, self._baud, timeout=1.0)
            except (serial.SerialException, OSError) as e:
                print(f'[coproc] open {dev} failed: {e}')
                time.sleep(2.0)
                continue

            announced_wait = False
            print(f'[coproc] connected: {dev}')
            self._connected = True
            self._last_seen = time.monotonic()
            if self._long_ms is not None:
                self._send(f'CFG long_ms={int(self._long_ms)}')

            try:
                self._read_lines()
            except (serial.SerialException, OSError):
                pass
            finally:
                self._connected = False
                ser, self._ser = self._ser, None
                if ser is not None:
                    try:
                        ser.close()
                    except Exception:
                        pass
                if self._running:
                    print('[coproc] disconnected — retrying')
                    time.sleep(1.0)

    def _read_lines(self):
        buf = b''
        while self._running and self._ser is not None:
            chunk = self._ser.read(64)
            if chunk:
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    self._on_line(line.decode('ascii', 'replace').strip())
                if len(buf) > 512:      # garbage guard, no newline in sight
                    buf = b''

    def _on_line(self, line: str):
        if not line:
            return
        self._last_seen = time.monotonic()
        parts = line.split()

        if parts[0] == 'BTN' and len(parts) >= 3:
            try:
                btn_id = int(parts[1])
            except ValueError:
                return
            kind   = 'long' if parts[2] == 'LONG' else 'short'
            action = self._map.get(btn_id, {}).get(kind)
            if action:
                with self._lock:
                    self._actions.append(action)
            else:
                print(f'[coproc] unmapped: BTN {btn_id} {parts[2]}')

        elif parts[0] == 'PING':
            self._send('PONG')

        elif parts[0] == 'HELLO':
            self._fw_banner = line
            print(f'[coproc] {line}')

        # Anything else (CFG acks, debug prints) is ignored.

    def _send(self, line: str):
        ser = self._ser
        if ser is None:
            return
        try:
            ser.write((line + '\n').encode('ascii'))
        except (serial.SerialException, OSError):
            pass
