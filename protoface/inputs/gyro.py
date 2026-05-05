"""
MPU-6050 gyro/accelerometer over I2C.

Returns a (dx, dy) pixel offset for the face based on head tilt.
Falls back to (0, 0) if smbus2 is not installed or the sensor is absent.

Install on Pi:
    sudo apt install python3-smbus
    pip install smbus2
"""

try:
    import smbus2
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_MPU6050_PWR  = 0x6B
_MPU6050_ACCEL = 0x3B


class Gyro:
    def __init__(self, cfg: dict):
        gyro_cfg  = cfg.get('inputs', {}).get('gyro', {})
        self._enabled = gyro_cfg.get('enabled', False) and _AVAILABLE
        self._addr    = gyro_cfg.get('i2c_address', 0x68)
        self._sens    = gyro_cfg.get('sensitivity', 0.4)
        self._max     = gyro_cfg.get('max_offset', 8)
        self._bus     = None
        self._offset  = (0.0, 0.0)

        if self._enabled:
            try:
                self._bus = smbus2.SMBus(1)
                self._bus.write_byte_data(self._addr, _MPU6050_PWR, 0)  # wake
            except Exception as e:
                print(f"[gyro] failed to open I2C: {e}")
                self._enabled = False
        elif gyro_cfg.get('enabled', False) and not _AVAILABLE:
            print("[gyro] smbus2 not installed — gyro disabled")

    def _read_word(self, reg: int) -> int:
        high = self._bus.read_byte_data(self._addr, reg)
        low  = self._bus.read_byte_data(self._addr, reg + 1)
        val  = (high << 8) | low
        return val - 65536 if val > 32767 else val

    def update(self, dt: float):
        if not self._enabled:
            return
        try:
            ax = self._read_word(_MPU6050_ACCEL)     / 16384.0  # g
            ay = self._read_word(_MPU6050_ACCEL + 2) / 16384.0
            # ax → horizontal tilt (roll), ay → vertical tilt (pitch)
            dx = max(-self._max, min(self._max, ax * self._sens * self._max))
            dy = max(-self._max, min(self._max, ay * self._sens * self._max))
            self._offset = (dx, dy)
        except Exception:
            self._offset = (0.0, 0.0)

    def get_offset(self) -> tuple[float, float]:
        return self._offset

    def close(self):
        if self._bus:
            self._bus.close()
