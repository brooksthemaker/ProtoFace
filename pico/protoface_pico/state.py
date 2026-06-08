"""Face animation state for the Pico port.

A near-verbatim port of the CM5 ``protoface/state.py`` FaceState, with the
ProtoHUD IPC request plumbing removed (the Pico build is standalone). All the
animation logic — expression crossfade, the blink state machine, idle wiggle
parameters, and the boop override timer — is pure Python and behaves
identically to the desktop/CM5 build.

CircuitPython note: no ``from __future__`` import and no subscripted-builtin
type annotations (e.g. ``tuple[float, float]``) so this parses on the device.
"""

import math
import random


class FaceState:
    def __init__(self, cfg, expression_names):
        face_cfg = cfg or {}
        blink_cfg = face_cfg.get("blink", {})

        self._expressions = list(expression_names)
        self._expr_idx = 0
        self._boop_remaining = 0.0
        self._boop_expr = "neutral"
        self._boop_prev = "neutral"

        # Expression crossfade
        self.expression = self._expressions[0] if self._expressions else "neutral"
        self.prev_expression = self.expression
        self.transition_t = 1.0  # 1.0 = fully arrived at current expression

        self._fade_speed = 1.0 / max(0.01, face_cfg.get("expression_fade", 0.3))

        # Blink state machine
        self.blink_weight = 0.0       # 0=open, 1=closed
        self._blink_phase = "open"    # open | closing | closed | opening
        self._blink_t = 0.0
        self._blink_duration = blink_cfg.get("duration", 0.15)
        self._blink_interval_min = blink_cfg.get("interval_min", 3.0)
        self._blink_interval_max = blink_cfg.get("interval_max", 7.0)
        self._next_blink = random.uniform(
            self._blink_interval_min, self._blink_interval_max
        )

        # Idle wiggle (consumed by face.py)
        self.wiggle_cfg = face_cfg.get(
            "wiggle", {"speed": 0.3, "amplitude_x": 2.0, "amplitude_y": 1.0}
        )

        # Audio (driven by the mic input in a later phase)
        self.audio_volume = 0.0
        self.mouth_open = 0.0
        self.spectrum = []

        # Gyro pixel offset (dx, dy)
        self.gyro_offset = (0.0, 0.0)

        # Timing
        self.time = 0.0

        # Brightness 0-255 (applied via the matrix / palette scale)
        self.brightness = 255

    # -- Expression control --------------------------------------------------

    def set_expression(self, name):
        if name == self.expression:
            return
        self.prev_expression = self.expression
        self.expression = name
        self.transition_t = 0.0

    def set_expression_by_index(self, idx):
        if 0 <= idx < len(self._expressions):
            self._expr_idx = idx
            self.set_expression(self._expressions[idx])

    def next_expression(self):
        if not self._expressions:
            return
        self._expr_idx = (self._expr_idx + 1) % len(self._expressions)
        self.set_expression(self._expressions[self._expr_idx])

    def prev_expression_cmd(self):
        if not self._expressions:
            return
        self._expr_idx = (self._expr_idx - 1) % len(self._expressions)
        self.set_expression(self._expressions[self._expr_idx])

    def trigger_boop(self, expression, duration):
        """Override the expression for *duration* seconds, then revert."""
        if self._boop_remaining <= 0:
            self._boop_prev = self.expression
        self._boop_expr = expression
        self._boop_remaining = duration
        self.set_expression(expression)

    def trigger_blink(self):
        if self._blink_phase == "open":
            self._blink_phase = "closing"
            self._blink_t = 0.0

    # -- Per-frame update ----------------------------------------------------

    def update(self, dt):
        self.time += dt

        if self.transition_t < 1.0:
            self.transition_t = min(1.0, self.transition_t + dt * self._fade_speed)

        if self._boop_remaining > 0:
            self._boop_remaining -= dt
            if self._boop_remaining <= 0:
                self.set_expression(self._boop_prev)

        self._update_blink(dt)

    def _update_blink(self, dt):
        half = self._blink_duration / 2.0

        if self._blink_phase == "open":
            self._next_blink -= dt
            if self._next_blink <= 0:
                self._blink_phase = "closing"
                self._blink_t = 0.0

        elif self._blink_phase == "closing":
            self._blink_t += dt
            self.blink_weight = min(1.0, self._blink_t / half)
            if self._blink_t >= half:
                self._blink_phase = "closed"
                self._blink_t = 0.0

        elif self._blink_phase == "closed":
            self._blink_t += dt
            if self._blink_t >= 0.04:  # hold closed briefly
                self._blink_phase = "opening"
                self._blink_t = 0.0

        elif self._blink_phase == "opening":
            self._blink_t += dt
            self.blink_weight = max(0.0, 1.0 - self._blink_t / half)
            if self._blink_t >= half:
                self.blink_weight = 0.0
                self._blink_phase = "open"
                self._next_blink = random.uniform(
                    self._blink_interval_min, self._blink_interval_max
                )

    # -- Wiggle helper (used by face.py) -------------------------------------

    def wiggle_offset(self):
        """Return the current (dx, dy) idle-wiggle offset in pixels.

        Combined with gyro_offset by the face engine. displayio TileGrid
        positions are integer, so the engine rounds the sum.
        """
        c = self.wiggle_cfg
        dx = c["amplitude_x"] * math.sin(2 * math.pi * c["speed"] * self.time)
        dy = c["amplitude_y"] * math.sin(2 * math.pi * c["speed"] * self.time * 1.3)
        return dx, dy
