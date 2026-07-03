"""
Autonomous face reactions that mirror ProtoHUD's native face controller.

  * Expression-coupled "mood" effects — swap the particle effect to a preset as
    the face expression changes (angry→fire, happy→celebration, sad→rain,
    shocked/surprised→galaxy).  Neutral / unmapped expressions restore the base
    effect (the one set in config.yaml or over IPC set_effect).

  * Rapid-boop "animated eyes" easter egg — boop the sensor `count` times within
    `window_s` seconds and a procedural eye animation takes over the panels for
    `duration_s` (see protoface/eye_anim.py).

Config (config.yaml → behaviors:):

    behaviors:
      expression_effects:
        enabled: true
      eye_trigger:
        enabled: true
        count: 3
        window_s: 4.0
        anim: random      # spiral|rings|hearts|swirl|starburst|glitch|random
        speed: 1.0
        size: 1.0
        duration: 2.5
        color: [0, 220, 180]
"""

from __future__ import annotations

import random

from .eye_anim import EYE_ANIMS

# Expression stem → particle preset. Mirrors NativeFaceController::expr_effect_map_.
MOOD_EFFECTS: dict[str, object] = {
    'angry':     {'preset': 'fire'},
    'happy':     {'preset': 'celebration'},
    'sad':       'rain',
    'shocked':   {'preset': 'galaxy'},
    'surprised': {'preset': 'galaxy'},
}


class ReactionController:
    def __init__(self, cfg: dict):
        beh = (cfg or {}).get('behaviors', {}) or {}
        ee  = beh.get('expression_effects', {}) or {}
        et  = beh.get('eye_trigger', {}) or {}

        self.mood_enabled = bool(ee.get('enabled', False))

        self.eye_enabled  = bool(et.get('enabled', False))
        self.eye_count    = max(1, int(et.get('count', 3)))
        self.eye_window   = float(et.get('window_s', 4.0))
        self.eye_anim     = et.get('anim', 'random')
        self.eye_speed    = float(et.get('speed', 1.0))
        self.eye_size     = float(et.get('size', 1.0))
        self.eye_duration = float(et.get('duration', 2.5))
        col = et.get('color', [0, 220, 180]) or [0, 220, 180]
        self.eye_color = tuple(int(c) for c in col)[:3]

        self._boop_times: list[float] = []
        self._last_expr: dict[int, str] = {}

    # ── Expression-coupled mood effects ───────────────────────────────────────

    def apply_mood_effects(self, panels: list):
        """Swap each panel's particle effect to match its expression."""
        if not self.mood_enabled:
            return
        for i, p in enumerate(panels):
            s = p['state']
            expr = s.expression
            if self._last_expr.get(i) == expr:
                continue
            self._last_expr[i] = expr
            mood = MOOD_EFFECTS.get(expr)
            if mood is not None:
                effect = mood
            elif s.base_particles is not None:
                effect = s.base_particles
            else:
                effect = 'none'
            p['particles'].set_effect(effect)

    # ── Rapid-boop → eye animation ────────────────────────────────────────────

    def register_boop(self, now: float) -> bool:
        """Record a boop at time *now*; return True if it completes a burst."""
        if not self.eye_enabled:
            return False
        self._boop_times.append(now)
        cutoff = now - self.eye_window
        self._boop_times = [t for t in self._boop_times if t >= cutoff]
        if len(self._boop_times) >= self.eye_count:
            self._boop_times.clear()
            return True
        return False

    def pick_anim(self) -> str:
        if self.eye_anim == 'random' or self.eye_anim not in EYE_ANIMS:
            return random.choice(EYE_ANIMS)
        return self.eye_anim
