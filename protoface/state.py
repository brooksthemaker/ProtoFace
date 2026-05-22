"""
Shared face animation state.

FaceState is the single source of truth passed to face.get_frame() each tick.
run.py owns the FaceState instance and updates it from inputs before rendering.
"""

from __future__ import annotations

import math
import random
import time


class FaceState:
    def __init__(self, cfg: dict, expression_names: list[str]):
        # `cfg` IS the panel's face config dict (run.py passes pcfg['face']),
        # so use it directly — do NOT look for a nested 'face' key, or the
        # wiggle / blink / expression_fade settings get silently ignored.
        face_cfg  = cfg or {}
        blink_cfg = face_cfg.get('blink', {})

        self._expressions    = expression_names
        self._expr_idx       = 0
        self._boop_remaining = 0.0
        self._boop_expr      = 'neutral'
        self._boop_prev      = 'neutral'

        # Expression crossfade
        self.expression      = expression_names[0] if expression_names else 'neutral'
        self.prev_expression = self.expression
        self.transition_t    = 1.0    # 1.0 = fully arrived at current expression

        self._fade_speed = 1.0 / max(0.01, face_cfg.get('expression_fade', 0.3))

        # Blink state machine
        self.blink_weight    = 0.0    # 0=open, 1=closed
        self._blink_phase    = 'open' # open | closing | closed | opening
        self._blink_t        = 0.0
        self._blink_duration = blink_cfg.get('duration', 0.15)
        self._next_blink     = random.uniform(
            blink_cfg.get('interval_min', 3.0),
            blink_cfg.get('interval_max', 7.0),
        )
        self._blink_interval_min = blink_cfg.get('interval_min', 3.0)
        self._blink_interval_max = blink_cfg.get('interval_max', 7.0)

        # Wiggle config (passed through to face.py)
        self.wiggle_cfg = face_cfg.get('wiggle', {
            'speed': 0.3, 'amplitude_x': 2.0, 'amplitude_y': 1.0})

        # Audio
        self.audio_volume = 0.0
        self.mouth_open   = 0.0
        self.spectrum     = []

        # Gyro
        self.gyro_offset: tuple[float, float] = (0.0, 0.0)

        # Timing
        self.time = 0.0

        # Brightness (0-255, applied as a scale factor in renderer)
        self.brightness = 255

        # IPC requests (consumed once by run.py each tick)
        self.custom_color: tuple[int,int,int] | None = None  # (r,g,b) or None
        self.gif_request:  int | None = None                 # gif_id index or None
        self.material_request: str | None = None             # material name or None
        self._ipc_release = False

    # ── Expression control ────────────────────────────────────────────────────

    def set_expression(self, name: str):
        if name == self.expression:
            return
        self.prev_expression = self.expression
        self.expression = name
        self.transition_t = 0.0

    def set_expression_by_index(self, idx: int):
        """Select an expression (face) by its position in the loaded set.

        Out-of-range indices are ignored so an over-eager id (e.g. face 9 on a
        5-face set) is a no-op rather than an error.
        """
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

    def trigger_boop(self, expression: str, duration: float):
        """Override expression for *duration* seconds, then revert."""
        if self._boop_remaining <= 0:
            self._boop_prev = self.expression
        self._boop_expr      = expression
        self._boop_remaining = duration
        self.set_expression(expression)

    def trigger_blink(self):
        """Force a blink immediately."""
        if self._blink_phase == 'open':
            self._blink_phase = 'closing'
            self._blink_t = 0.0

    # ── Per-frame update ──────────────────────────────────────────────────────

    def update(self, dt: float):
        self.time += dt

        # Expression crossfade
        if self.transition_t < 1.0:
            self.transition_t = min(1.0, self.transition_t + dt * self._fade_speed)

        # Boop timer
        if self._boop_remaining > 0:
            self._boop_remaining -= dt
            if self._boop_remaining <= 0:
                self.set_expression(self._boop_prev)

        # Blink state machine
        self._update_blink(dt)

    def _update_blink(self, dt: float):
        half = self._blink_duration / 2.0

        if self._blink_phase == 'open':
            self._next_blink -= dt
            if self._next_blink <= 0:
                self._blink_phase = 'closing'
                self._blink_t = 0.0

        elif self._blink_phase == 'closing':
            self._blink_t += dt
            self.blink_weight = min(1.0, self._blink_t / half)
            if self._blink_t >= half:
                self._blink_phase = 'closed'
                self._blink_t = 0.0

        elif self._blink_phase == 'closed':
            self._blink_t += dt
            if self._blink_t >= 0.04:   # hold closed briefly
                self._blink_phase = 'opening'
                self._blink_t = 0.0

        elif self._blink_phase == 'opening':
            self._blink_t += dt
            self.blink_weight = max(0.0, 1.0 - self._blink_t / half)
            if self._blink_t >= half:
                self.blink_weight = 0.0
                self._blink_phase = 'open'
                self._next_blink = random.uniform(
                    self._blink_interval_min, self._blink_interval_max)

    # ── IPC requests (thread-safe setters, consumed once per tick by run.py) ──

    def set_custom_color(self, r: int, g: int, b: int):
        self.custom_color = (r, g, b)

    def request_gif(self, gif_id: int):
        self.gif_request = gif_id

    def request_material(self, name: str):
        self.material_request = name

    def release_ipc_control(self):
        self._ipc_release = True

    def consume_ipc_requests(self) -> dict:
        """Return and clear all pending IPC requests."""
        reqs = {
            'custom_color':    self.custom_color,
            'gif_request':     self.gif_request,
            'material_request': self.material_request,
            'release':         self._ipc_release,
        }
        self.custom_color     = None
        self.gif_request      = None
        self.material_request = None
        self._ipc_release     = False
        return reqs
