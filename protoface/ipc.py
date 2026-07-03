"""
Unix socket IPC server for Protoface.

Listens on /tmp/protoface.sock (or a path from config) for newline-delimited
JSON commands sent by ProtoHUD's ProtofaceController.

Supported commands (JSON objects, one per line):
    {"cmd": "set_color",      "r":0, "g":220, "b":180, "layer":0}
    {"cmd": "set_effect",     "effect_id":3, "p1":0, "p2":0}
    {"cmd": "set_effect",     "layers":[{"effect":"embers",...}, ...]}
    {"cmd": "set_face",       "face_id":1}
    {"cmd": "play_gif",       "gif_id":2}
    {"cmd": "set_brightness", "value":200}
    {"cmd": "set_palette",    "palette_id":1}
    {"cmd": "set_menu_item",  "menu_index":8, "value":1}
    {"cmd": "request_status"}
    {"cmd": "release_control"}
    {"cmd": "shutdown"}          # clean exit (used by ProtoHUD restart)

set_effect effect_id mapping (numeric IDs, matches ProtoTracer indices):
    0=none,       1=sparkle,   2=embers,    3=rain,
    4=snow,       5=confetti,  6=rings,     7=fireflies,
    8=fire,       9=aurora,    10=blizzard, 11=sonar,
    12=plasma,    13=celebration,  14=galaxy,   15=party
    16=clouds,    17=nebula   (Protoface-only extensions; not ProtoTracer indices)

set_effect with "layers" key accepts a full multi-layer config instead of
a numeric ID — any structure accepted by ParticleSystem.set_effect() works.

set_face face_id is the 0-based index of an expression in the active face's
loaded set (order from the face's config.json). Out-of-range IDs are ignored.

set_menu_item menu_index (mirrors ProtoHUD's Protoface / ProtoTracer menus):
    0  → face index (same effect as set_face)
    2  → accent LED brightness   (Teensy-only; accepted, no-op here)
    3  → microphone on/off       (0/1)
    4  → mic level               (0-10)
    5  → touch/boop sensor on/off (0/1)
    6  → spectrum mirror         (Teensy-only; accepted, no-op here)
    7  → face size               (0-10; accepted, no-op here)
    8  → material colour preset  (see _MATERIAL_COLOR_MAP, index 0-33)
    9  → "use drawn colours" — draw each expression's own RGB art instead of
         tinting it with the material (0/1)
    12 → fan speed               (Teensy-only; accepted, no-op here)
Unknown indices are accepted and ignored rather than raising.

set_palette palette_id maps through the same table as menu_index 8.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from typing import TYPE_CHECKING

from .persistence import save_state

if TYPE_CHECKING:
    from .state import FaceState
    from .persistence import LiveSettings

_EFFECT_MAP: dict[int, str | dict] = {
    0:  'none',
    1:  'sparkle',
    2:  'embers',
    3:  'rain',
    4:  'snow',
    5:  'confetti',
    6:  'rings',
    7:  'fireflies',
    # Multi-layer presets
    8:  {'preset': 'fire'},
    9:  {'preset': 'aurora'},
    10: {'preset': 'blizzard'},
    11: {'preset': 'sonar'},
    12: {'preset': 'plasma'},
    13: {'preset': 'celebration'},
    14: {'preset': 'galaxy'},
    15: {'preset': 'party'},
    # Protoface-only extensions (no ProtoTracer equivalent)
    16: 'clouds',
    17: {'preset': 'nebula'},
    # Star field family
    18: {'preset': 'starfield'},
    19: {'preset': 'warp'},
    20: {'preset': 'constellation'},
    21: {'preset': 'shooting_stars'},
    22: {'preset': 'night_sky'},
}

# Material colour presets (set_menu_item menu_index 8).  Mirrors ProtoHUD's
# NativeFaceController::preset_material and the pf_mats / pf_pride tables in
# build_face_display.cpp — keep the ordering in lock-step with the HUD menu.
_MATERIAL_COLOR_MAP = {
    # Solids
    0:  'teal',
    1:  'solid:255,220,0',
    2:  'solid:255,140,0',
    3:  'solid:255,255,255',
    4:  'solid:30,220,60',
    5:  'solid:180,30,220',
    6:  'solid:220,30,30',
    7:  'solid:30,100,255',
    8:  'rainbow',
    9:  'cool',
    10: 'warm',
    11: 'solid:0,0,0',
    # Multi-colour gradient presets (horizontal smooth blends, static)
    12: 'gradient:h:s:0:FF8C00-FF3D7F-8A2BE2',   # Sunset
    13: 'gradient:h:s:0:00E5FF-0077FF-001F7F',   # Ocean
    14: 'gradient:h:s:0:7CFF6B-1E9E3C-0B3D1A',   # Forest
    15: 'gradient:h:s:0:FFE000-FF7A00-E01E1E',   # Fire
    16: 'gradient:h:s:0:00FFA3-00D0FF-B14BFF',   # Aurora
    17: 'gradient:h:s:0:2A0A0A-C81E00-FF8C00',   # Lava
    18: 'gradient:h:s:0:2B0B5E-7A1EB4-FF4FD8',   # Galaxy
    19: 'gradient:h:s:0:FFB3BA-BAE1FF-BAFFC9',   # Pastel
    20: 'gradient:h:s:0:FF4FA3-FFD24F-4FC3FF',   # Candy
    21: 'gradient:h:s:0:AEFF00-00FFB3-00A3FF',   # Toxic
    # Pride flags (vertical smooth gradients, top→bottom stripes)
    22: 'gradient:v:s:0:E40303-FF8C00-FFED00-008026-004DFF-750787',                                    # Rainbow
    23: 'gradient:v:s:0:000000-613915-5BCEFA-F5A9B8-FFFFFF-E40303-FF8C00-FFED00-008026-004DFF-750787',  # Progress
    24: 'gradient:v:s:0:5BCEFA-F5A9B8-FFFFFF-F5A9B8-5BCEFA',                                            # Trans
    25: 'gradient:v:s:0:D60270-D60270-9B4F96-0038A8-0038A8',                                            # Bisexual
    26: 'gradient:v:s:0:FF218C-FFD800-21B1FF',                                                          # Pansexual
    27: 'gradient:v:s:0:D52D00-FF9A56-FFFFFF-D362A4-A30262',                                            # Lesbian
    28: 'gradient:v:s:0:FCF434-FFFFFF-9C59D1-2C2C2C',                                                   # Nonbinary
    29: 'gradient:v:s:0:000000-A3A3A3-FFFFFF-800080',                                                   # Asexual
    30: 'gradient:v:s:0:FF75A2-FFFFFF-BE18D6-000000-333EBD',                                            # Genderfluid
    31: 'gradient:v:s:0:B57EDC-FFFFFF-4A8123',                                                          # Genderqueer
    32: 'gradient:v:s:0:3DA542-A7D379-FFFFFF-A9A9A9-000000',                                            # Aromantic
    33: 'gradient:v:s:0:FFD800-7902AA-FFD800',                                                          # Intersex
}


class IpcServer:
    """
    Starts a background thread listening on a Unix domain socket.
    Dispatches received commands to all panel states and particle systems.
    """

    def __init__(self, state: 'FaceState', cfg: dict,
                 live: 'LiveSettings | None' = None, state_path: str | None = None):
        ipc_cfg          = cfg.get('ipc', {})
        self._path       = ipc_cfg.get('socket', '/tmp/protoface.sock')
        self._state      = state
        self._panels     = []    # set via set_panels()
        self._live       = live          # serializable mirror of the current look
        self._state_path = state_path    # where save_config writes state.yaml
        self._thread     = None
        self._running    = False

    def set_panels(self, panels: list):
        """Provide the list of panel context dicts from run.py."""
        self._panels = panels

    # Legacy single-panel API kept for backward compatibility
    def set_particles(self, particles):
        pass  # superseded by set_panels()

    def set_material(self, material_ref):
        pass  # superseded by set_panels()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(self._path)
            s.close()
        except OSError:
            pass

    # ── Server loop ───────────────────────────────────────────────────────────

    def _serve(self):
        try:
            os.unlink(self._path)
        except OSError:
            pass

        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            srv.bind(self._path)
            os.chmod(self._path, 0o660)
            srv.listen(4)
        except OSError as e:
            print(f'[ipc] cannot bind {self._path}: {e}')
            return

        srv.settimeout(1.0)
        while self._running:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

        srv.close()
        try:
            os.unlink(self._path)
        except OSError:
            pass

    def _handle(self, conn: socket.socket):
        buf = b''
        with conn:
            conn.settimeout(30.0)
            while self._running:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    line = line.strip()
                    if line:
                        self._dispatch(line, conn)

    def _dispatch(self, raw: bytes, conn: 'socket.socket | None' = None):
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            print(f'[ipc] bad JSON: {raw[:80]}')
            return

        cmd = msg.get('cmd', '')

        if cmd == 'set_color':
            r = int(msg.get('r', 0))
            g = int(msg.get('g', 0))
            b = int(msg.get('b', 0))
            # 'layer' is accepted for wire-compatibility with ProtoHUD; the
            # Protoface renderer has a single material layer so it's a no-op.
            for p in self._panels:
                p['state'].set_custom_color(r, g, b)
            self._track(material=f'solid:{r},{g},{b}')

        elif cmd == 'set_effect':
            # Accept either a numeric effect_id or a raw 'layers' list/dict.
            # 'p1'/'p2' are accepted for wire-compatibility with ProtoHUD's
            # set_effect(effect_id, p1, p2); the Protoface presets don't take
            # per-command params, so they're ignored.
            if 'layers' in msg:
                effect_cfg = {'layers': msg['layers']}
            elif 'effect_id' in msg:
                effect_id  = int(msg['effect_id'])
                effect_cfg = _EFFECT_MAP.get(effect_id, 'none')
            else:
                effect_cfg = 'none'

            for p in self._panels:
                p['particles'].set_effect(effect_cfg)
                # Remember it as the base effect so expression-coupled mood
                # effects revert to it (see reactions / run.py).
                p['state'].base_particles = effect_cfg
            self._track(particles=effect_cfg)

        elif cmd == 'set_face':
            face_id = int(msg.get('face_id', 0))
            for p in self._panels:
                p['state'].set_expression_by_index(face_id)

        elif cmd == 'play_gif':
            gif_id = int(msg.get('gif_id', 0))
            for p in self._panels:
                p['state'].request_gif(gif_id)

        elif cmd == 'set_brightness':
            value = max(0, min(255, int(msg.get('value', 255))))
            for p in self._panels:
                p['state'].brightness = value
            self._track(brightness=value)

        elif cmd == 'set_palette':
            # Protoface has no separate palette concept — treat a palette id as
            # a material colour preset (same table as menu_index 8).
            pid = int(msg.get('palette_id', 0))
            mat_name = _MATERIAL_COLOR_MAP.get(pid)
            if mat_name is not None:
                for p in self._panels:
                    p['state'].request_material(mat_name)
                self._track(material=mat_name)

        elif cmd == 'set_menu_item':
            idx   = int(msg.get('menu_index', 0))
            value = int(msg.get('value', 0))
            if idx == 8:
                mat_name = _MATERIAL_COLOR_MAP.get(value, 'teal')
                for p in self._panels:
                    p['state'].request_material(mat_name)
                self._track(material=mat_name)
            elif idx == 9:
                # "Use drawn colours" — draw the expression's own RGB art
                # instead of tinting it with the material.
                on = bool(value)
                for p in self._panels:
                    p['state'].face_colors = on
                self._track(face_colors=on)
            elif idx == 0:
                for p in self._panels:
                    p['state'].set_expression_by_index(value)
            elif idx == 3:
                for p in self._panels:
                    p['state'].mic_enabled = bool(value)
            elif idx == 4:
                for p in self._panels:
                    p['state'].mic_level = value
            elif idx == 5:
                for p in self._panels:
                    p['state'].touch_enabled = bool(value)
            elif idx == 7:
                for p in self._panels:
                    p['state'].face_size = value
            # idx 2/6/12 (accent brightness, spectrum mirror, fan speed) are
            # Teensy/ProtoTracer-only — accepted and ignored here.

        elif cmd == 'save_config':
            ok = False
            if self._live is not None and self._state_path:
                ok = save_state(self._state_path, self._live.snapshot())
            self._reply(conn, {'cmd': 'save_config', 'ok': ok})

        elif cmd == 'request_status':
            snap = self._live.snapshot() if self._live is not None else {}
            snap['cmd'] = 'status'
            self._reply(conn, snap)

        elif cmd == 'release_control':
            for p in self._panels:
                p['state'].release_ipc_control()

        elif cmd == 'shutdown':
            # Clean exit: raise SIGINT in the main thread so run.py's
            # KeyboardInterrupt path runs (blank panels, unlink socket, release
            # the single-instance lock). Used by ProtoHUD's "Restart Protoface".
            self._reply(conn, {'cmd': 'shutdown', 'ok': True})
            import signal
            os.kill(os.getpid(), signal.SIGINT)

        else:
            print(f'[ipc] unknown cmd: {cmd!r}')

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _track(self, **kw):
        """Mirror a look change into LiveSettings so save_config can persist it."""
        if self._live is not None:
            self._live.update(**kw)

    def _reply(self, conn, obj: dict):
        if conn is None:
            return
        try:
            conn.sendall((json.dumps(obj) + '\n').encode())
        except OSError:
            pass
