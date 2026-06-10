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

set_menu_item menu_index 8 → material colour preset (matches ProtoTracer list).
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

_MATERIAL_COLOR_MAP = {
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
            for p in self._panels:
                p['state'].set_custom_color(r, g, b)
            self._track(material=f'solid:{r},{g},{b}')

        elif cmd == 'set_effect':
            # Accept either a numeric effect_id or a raw 'layers' list/dict.
            if 'layers' in msg:
                effect_cfg = {'layers': msg['layers']}
            elif 'effect_id' in msg:
                effect_id  = int(msg['effect_id'])
                effect_cfg = _EFFECT_MAP.get(effect_id, 'none')
            else:
                effect_cfg = 'none'

            for p in self._panels:
                p['particles'].set_effect(effect_cfg)
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
            pass  # no palette concept in Protoface

        elif cmd == 'set_menu_item':
            idx   = int(msg.get('menu_index', 0))
            value = int(msg.get('value', 0))
            if idx == 8:
                mat_name = _MATERIAL_COLOR_MAP.get(value, 'teal')
                for p in self._panels:
                    p['state'].request_material(mat_name)
                self._track(material=mat_name)

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
