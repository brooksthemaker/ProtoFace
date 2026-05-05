"""
GPIO boop / touch sensor.

Monitors a GPIO pin (active-LOW by default) and exposes is_booped() with
software debounce.  Falls back to keyboard-triggered boop in preview mode.

Install on Pi:
    pip install RPi.GPIO
"""

import time

try:
    import RPi.GPIO as GPIO
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class BoopSensor:
    def __init__(self, cfg: dict):
        boop_cfg  = cfg.get('inputs', {}).get('boop', {})
        self._enabled  = boop_cfg.get('enabled', False) and _AVAILABLE
        self._pin      = boop_cfg.get('gpio_pin', 17)
        self._debounce = boop_cfg.get('debounce', 0.05)
        self._expr     = boop_cfg.get('expression', 'surprised')
        self._duration = boop_cfg.get('duration', 2.0)

        self._last_state   = False
        self._last_trigger = 0.0
        self._pending      = False   # set externally by preview keyboard shortcut

        if self._enabled:
            try:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            except Exception as e:
                print(f"[boop] GPIO setup failed: {e}")
                self._enabled = False
        elif boop_cfg.get('enabled', False) and not _AVAILABLE:
            print("[boop] RPi.GPIO not installed — boop sensor disabled (use 'b' key in preview)")

    def trigger_from_preview(self):
        """Called by preview.py when the user presses 'b'."""
        self._pending = True

    def is_booped(self) -> bool:
        """
        Returns True once per physical boop event (edge detect + debounce).
        Call once per frame.
        """
        # Software-triggered (preview keyboard)
        if self._pending:
            self._pending = False
            return True

        if not self._enabled:
            return False

        now = time.monotonic()
        try:
            state = not GPIO.input(self._pin)  # active-LOW
        except Exception:
            return False

        # Rising edge + debounce
        if state and not self._last_state and (now - self._last_trigger) > self._debounce:
            self._last_state = True
            self._last_trigger = now
            return True

        if not state:
            self._last_state = False

        return False

    @property
    def expression(self) -> str:
        return self._expr

    @property
    def duration(self) -> float:
        return self._duration

    def close(self):
        if self._enabled and _AVAILABLE:
            GPIO.cleanup(self._pin)
