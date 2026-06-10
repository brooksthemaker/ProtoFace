"""
Pygame preview window for development on non-Pi hardware.

Shows the LED panel output scaled up so individual pixels are visible.
Keyboard shortcuts (when window is focused):
  0-8        — switch particle effect  (1=sparkle 2=snow 3=embers 4=confetti
                                        5=rings   6=rain  7=fireflies 8=clouds
                                        0=none)
  q/e        — previous / next expression
  b          — trigger a manual blink
  ESC / Q    — quit
"""

import numpy as np

try:
    import pygame
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_EFFECT_KEYS = {
    pygame.K_0: 'none',
    pygame.K_1: 'sparkle',
    pygame.K_2: 'snow',
    pygame.K_3: 'embers',
    pygame.K_4: 'confetti',
    pygame.K_5: 'rings',
    pygame.K_6: 'rain',
    pygame.K_7: 'fireflies',
    pygame.K_8: 'clouds',
} if _AVAILABLE else {}


class PreviewOutput:
    def __init__(self, cfg: dict):
        panel = cfg.get('panel', {})
        disp  = cfg.get('display', {})
        # Canvas size computed the same way run.py does: panel size (config
        # uses panel_width/panel_height; plain width/height is the legacy
        # spelling) times the chain/parallel panel counts.
        panel_w = panel.get('panel_width',  panel.get('width',  64))
        panel_h = panel.get('panel_height', panel.get('height', 32))
        self._w     = panel_w * panel.get('chain_length', 2)
        self._h     = panel_h * panel.get('parallel', 2)
        self._scale = disp.get('preview_scale', 8)
        self._screen = None
        self._clock  = None
        self._events: list = []   # buffered events for run.py to consume

        if not _AVAILABLE:
            print("[preview] pygame not available")
            return

        pygame.init()
        pygame.display.set_caption('Protoface Preview')
        self._screen = pygame.display.set_mode(
            (self._w * self._scale, self._h * self._scale))
        self._clock = pygame.time.Clock()

    def show(self, frame: np.ndarray):
        """Display a (H, W, 3) uint8 frame in the preview window."""
        if self._screen is None:
            return

        # Scale up using nearest-neighbour so pixels are crisp
        surf = pygame.surfarray.make_surface(
            np.transpose(frame, (1, 0, 2)))   # pygame is (W,H,3)
        scaled = pygame.transform.scale(
            surf, (self._w * self._scale, self._h * self._scale))
        self._screen.blit(scaled, (0, 0))
        pygame.display.flip()

    def poll_events(self) -> list[dict]:
        """
        Drain pygame event queue and return a list of action dicts for run.py.
        Call once per frame BEFORE show().
        """
        if not _AVAILABLE or self._screen is None:
            return []

        actions = []
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                actions.append({'type': 'quit'})
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    actions.append({'type': 'quit'})
                elif event.key in _EFFECT_KEYS:
                    actions.append({'type': 'particle', 'name': _EFFECT_KEYS[event.key]})
                elif event.key == pygame.K_b:
                    actions.append({'type': 'blink'})
                elif event.key == pygame.K_e:
                    actions.append({'type': 'next_expression'})
                elif event.key == pygame.K_w:
                    actions.append({'type': 'prev_expression'})
        return actions

    def close(self):
        if _AVAILABLE:
            pygame.quit()

    @property
    def available(self) -> bool:
        return _AVAILABLE and self._screen is not None
