"""
MPU-6050 gyro/accelerometer over I2C.

Returns a (dx, dy) pixel offset for the face based on head tilt.
Falls back to (0, 0) if smbus2 is not installed or the sensor is absent.

Polling runs on a daemon thread (like inputs/microphone.py) so the blocking
I2C transactions never stall the render loop; the main loop just reads the
cached offset via get_offset().

Install on Pi:
    sudo apt install python3-smbus
    pip install smbus2
"""

import threading
import time

try:
    import smbus2
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_MPU6050_PWR  = 0x6B
_MPU6050_ACCEL = 0x3B

_POLL_INTERVAL = 0.02   # 50 Hz — comfortably above the render rate


class Gyro:
    def __init__(self, cfg: dict):
        gyro_cfg  = cfg.get('inputs', {}).get('gyro', {})
        self._enabled = gyro_cfg.get('enabled', False) and _AVAILABLE
        self._addr    = gyro_cfg.get('i2c_address', 0x68)
        self._sens    = gyro_cfg.get('sensitivity', 0.4)
        self._max     = gyro_cfg.get('max_offset', 8)
        self._bus     = None
        self._offset  = (0.0, 0.0)
        self._lock    = threading.Lock()
        self._running = False
        self._thread  = None

        if self._enabled:
            try:
                self._bus = smbus2.SMBus(1)
                self._bus.write_byte_data(self._addr, _MPU6050_PWR, 0)  # wake
            except Exception as e:
                print(f"[gyro] failed to open I2C: {e}")
                self._enabled = False
        elif gyro_cfg.get('enabled', False) and not _AVAILABLE:
            print("[gyro] smbus2 not installed — gyro disabled")

        if self._enabled:
            self._running = True
            self._thread = threading.Thread(target=self._poll, daemon=True)
            self._thread.start()

    @staticmethod
    def _to_int16(high: int, low: int) -> int:
        val = (high << 8) | low
        return val - 65536 if val > 32767 else val

    def _read_accel_xy(self) -> tuple[float, float]:
        """Read ACCEL_XOUT/ACCEL_YOUT in one 4-byte block transaction
        (registers 0x3B-0x3E are contiguous) instead of four byte reads."""
        d = self._bus.read_i2c_block_data(self._addr, _MPU6050_ACCEL, 4)
        ax = self._to_int16(d[0], d[1]) / 16384.0   # g
        ay = self._to_int16(d[2], d[3]) / 16384.0
        return ax, ay

    # ── Poll thread ───────────────────────────────────────────────────────────

    def _poll(self):
        while self._running:
            try:
                ax, ay = self._read_accel_xy()
                # ax → horizontal tilt (roll), ay → vertical tilt (pitch)
                dx = max(-self._max, min(self._max, ax * self._sens * self._max))
                dy = max(-self._max, min(self._max, ay * self._sens * self._max))
                with self._lock:
                    self._offset = (dx, dy)
            except Exception:
                with self._lock:
                    self._offset = (0.0, 0.0)
            time.sleep(_POLL_INTERVAL)

    # ── Main-thread interface ─────────────────────────────────────────────────

    def update(self, dt: float):
        """Kept for API compatibility — polling happens on the daemon thread."""
        pass

    def get_offset(self) -> tuple[float, float]:
        with self._lock:
            return self._offset

    def close(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        if self._bus:
            self._bus.close()
