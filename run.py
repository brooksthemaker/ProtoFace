"""
Protoface — entry point.

Run with:
    python run.py                   # uses config.yaml
    python run.py --config myface.yaml

Preview window keyboard shortcuts (when display.preview: true):
    0-9    switch particle effect/preset on all panels
    e / w  cycle next / previous expression
    b      trigger a manual blink
    ESC    quit
"""

import argparse
import os
import sys
import time

try:
    import fcntl              # POSIX file lock for the single-instance guard
except ImportError:
    fcntl = None

import yaml
import numpy as np

from protoface.renderer   import Renderer
from protoface.face       import FaceLoader
from protoface.material   import load_material, SolidMaterial
from protoface.particles  import ParticleSystem
from protoface.gif_player import GifPlayer
from protoface.state      import FaceState
from protoface.ipc        import IpcServer
from protoface.shm_writer import ShmWriter
from protoface.inputs.microphone import Microphone
from protoface.inputs.gyro       import Gyro
from protoface.inputs.boop       import BoopSensor
from protoface.keyboard          import KeyReader
from protoface.persistence       import LiveSettings, load_state, save_state


# Solo-mode (terminal) control palettes — cycled with the keyboard when running
# directly on the panels (no ProtoHUD/IPC).
FACE_COLORS = [
    ("teal",    (  0, 220, 180)),
    ("red",     (255,   0,   0)),
    ("orange",  (255, 110,   0)),
    ("yellow",  (255, 230,   0)),
    ("green",   (  0, 255,   0)),
    ("blue",    (  0,  90, 255)),
    ("purple",  (160,   0, 255)),
    ("magenta", (255,   0, 150)),
    ("white",   (255, 255, 255)),
]
EFFECTS = ["none", "sparkle", "embers", "confetti", "rain", "snow", "rings", "fireflies"]


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_output(cfg: dict):
    disp = cfg.get('display', {})
    if disp.get('preview', True):
        from protoface.output.preview import PreviewOutput
        return PreviewOutput(cfg)
    else:
        from protoface.output.hub75 import HUB75Output
        return HUB75Output(cfg)


# ── Panel context builder ─────────────────────────────────────────────────────

def _build_panels(cfg: dict) -> list[dict]:
    """
    Build a list of panel context dicts from config.

    Each context contains:
        region     (x, y, w, h) in canvas pixels
        name       str
        face       FaceLoader
        material   Material  (wrapped in list for IPC mutation)
        particles  ParticleSystem
        state      FaceState
        gif        GifPlayer
        face_cfg   raw face config dict
    """
    panels_cfg = cfg.get('panels')
    if panels_cfg:
        return [_panel_from_cfg(pcfg) for pcfg in panels_cfg]

    # Legacy: single panel from top-level face/material/particles keys
    panel = cfg.get('panel', {})
    w = panel.get('panel_width', panel.get('width', 64))
    h = panel.get('panel_height', panel.get('height', 32))
    synthetic = {
        'name':     'main',
        'region':   [0, 0, w, h],
        'face':     cfg.get('face', {}),
        'material': cfg.get('material', {}),
        'particles': cfg.get('particles', {}),
    }
    return [_panel_from_cfg(synthetic)]


def _panel_from_cfg(pcfg: dict) -> dict:
    x, y, w, h = pcfg['region']
    face_cfg  = pcfg.get('face', {})
    mat_cfg   = pcfg.get('material', {})
    part_cfg  = pcfg.get('particles', {})

    faces_dir = os.path.join('faces', face_cfg.get('active', 'example_fox'))
    face      = FaceLoader(faces_dir, w, h)

    mat = load_material(
        mat_cfg.get('active', 'solid:0,0,0'), w, h,
        scroll_x=mat_cfg.get('scroll_x', 0.0),
        scroll_y=mat_cfg.get('scroll_y', 0.0),
    )

    particles = ParticleSystem(w, h, part_cfg)
    gif       = GifPlayer(w, h)
    state     = FaceState(face_cfg, face.expression_names)

    return {
        'name':     pcfg.get('name', 'panel'),
        'region':   (x, y, w, h),
        'mirror_of': pcfg.get('mirror_of'),   # if set, this panel = source flipped
        'face':     face,
        'material': [mat],     # wrapped in list so IPC can swap
        'particles': particles,
        'gif':      gif,
        'state':    state,
        'face_cfg': face_cfg,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def _single_instance_lock(path='/tmp/protoface.lock'):
    """Hold an exclusive lock so a second Protoface can't start. Two instances
    would both drive /dev/pio0 and garble the panels with static. Returns the
    lock file object (keep a reference for the process lifetime); the lock is
    released automatically when the process exits or is killed."""
    if fcntl is None:
        return None
    fd = open(path, 'w')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"[protoface] already running (lock held on {path}) — exiting.")
        sys.exit(0)
    return fd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yaml')
    args = parser.parse_args()

    # Refuse to start a second instance (prevents the /dev/pio0 contention that
    # shows up as static on the panels). Keep the handle alive for the run.
    _instance_lock = _single_instance_lock()

    cfg = load_config(args.config)

    # Runtime state overlay saved by ProtoHUD (save_config); applied over config.
    state_path = os.path.join(
        os.path.dirname(os.path.abspath(args.config)) or '.', 'state.yaml')
    saved = load_state(state_path)

    panel_cfg  = cfg.get('panel', {})
    panel_w    = panel_cfg.get('panel_width',  panel_cfg.get('width',  64))
    panel_h    = panel_cfg.get('panel_height', panel_cfg.get('height', 32))
    chain      = panel_cfg.get('chain_length', 2)
    parallel   = panel_cfg.get('parallel', 2)
    canvas_w   = panel_w * chain
    canvas_h   = panel_h * parallel

    fps        = cfg.get('display', {}).get('fps', 30)
    bg_color   = tuple(cfg.get('display', {}).get('background', [0, 0, 0]))
    gif_cfg    = cfg.get('gif', {})

    # ── Build panels ──────────────────────────────────────────────────────────
    panels   = _build_panels(cfg)
    renderer = Renderer(canvas_w, canvas_h)

    gif_folder   = gif_cfg.get('folder', 'gifs')
    gif_files    = GifPlayer.scan_folder(gif_folder)
    gif_idx      = 0
    gif_auto     = gif_cfg.get('auto_cycle', False)
    gif_interval = gif_cfg.get('cycle_interval', 30.0)
    gif_timer    = gif_interval

    mic  = Microphone(cfg)
    gyro = Gyro(cfg)
    boop = BoopSensor(cfg)

    out  = build_output(cfg)

    primary_state = panels[0]['state']   # panel[0] is the primary IPC/state handle

    # ── Look overlay (precedence, last wins): per-panel config -> enabled
    #    'effects:' section -> runtime state.yaml saved by ProtoHUD. ────────────
    def _first(key, default):
        pl = cfg.get('panels') or []
        return pl[0].get(key, default) if pl else default

    # particles
    effect_layers = []
    for _name, ecfg in (cfg.get('effects') or {}).items():
        if isinstance(ecfg, dict) and ecfg.get('enabled'):
            if ecfg.get('layers'):
                effect_layers.extend(ecfg['layers'])
            elif ecfg.get('effect'):
                effect_layers.append({k: v for k, v in ecfg.items() if k != 'enabled'})
    final_particles = _first('particles', {'active': 'none'})
    particles_override = False
    if effect_layers:
        final_particles = {'layers': effect_layers}; particles_override = True
    if 'particles' in saved:
        final_particles = saved['particles']; particles_override = True
    if particles_override:
        for p in panels:
            p['particles'].set_effect(final_particles)

    # material
    final_material = (_first('material', {}) or {}).get('active', 'teal')
    if 'material' in saved:
        final_material = saved['material']
        for p in panels:
            _, _, pw, ph = p['region']
            p['material'][0] = load_material(final_material, pw, ph)

    # brightness
    final_brightness = int(saved.get('brightness', 255))
    primary_state.brightness = final_brightness

    live = LiveSettings(brightness=final_brightness,
                        material=final_material,
                        particles=final_particles)

    # ── IPC server — share state and particle refs for all panels ─────────────
    # IPC commands apply to all panels unless targeting a named panel.
    # Use panel[0] state as the primary IPC state handle.
    ipc = IpcServer(primary_state, cfg, live=live, state_path=state_path)
    # Give IPC access to all panels' particles and materials
    ipc.set_panels(panels)
    ipc.start()

    # ── Shared memory frame writer ─────────────────────────────────────────────
    shm_path = cfg.get('ipc', {}).get('shm_path', '/dev/shm/protoface_frame')
    shm = ShmWriter(shm_path, canvas_w, canvas_h)

    # ── Master canvas ─────────────────────────────────────────────────────────
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

    # ── Solo terminal controls (no-op without a TTY, e.g. under systemd) ───────
    keyboard     = KeyReader()
    keyboard.start()
    face_color_i = 0
    effect_i     = 0
    if sys.stdin.isatty():
        print("Solo controls: c/v colour  x/z effect  e/w expr  b blink  "
              "+/- bright  s save  q quit")

    # ── Main loop ─────────────────────────────────────────────────────────────
    target_dt = 1.0 / fps
    prev_time = time.monotonic()
    running   = True

    try:
        while running:
            now = time.monotonic()
            dt  = now - prev_time
            prev_time = now
            dt = min(dt, 0.1)

            # ── Poll preview window events ────────────────────────────────────
            if hasattr(out, 'poll_events'):
                for event in out.poll_events():
                    etype = event['type']
                    if etype == 'quit':
                        running = False
                    elif etype == 'particle':
                        for p in panels:
                            p['particles'].set_effect(event['name'])
                    elif etype == 'blink':
                        for p in panels:
                            p['state'].trigger_blink()
                        boop.trigger_from_preview()
                    elif etype == 'next_expression':
                        for p in panels:
                            p['state'].next_expression()
                    elif etype == 'prev_expression':
                        for p in panels:
                            p['state'].prev_expression_cmd()

            # ── Terminal key controls (solo mode on the panels) ───────────────
            key = keyboard.get()
            if key:
                if key == 'q':   # not ESC: arrow/function keys send ESC sequences
                    running = False
                elif key in ('c', 'v'):
                    face_color_i = (face_color_i + (1 if key == 'c' else -1)) % len(FACE_COLORS)
                    cname, (cr, cg, cb) = FACE_COLORS[face_color_i]
                    for p in panels:
                        _, _, pw, ph = p['region']
                        p['material'][0] = SolidMaterial(cr, cg, cb, pw, ph)
                    live.update(material=f'solid:{cr},{cg},{cb}')
                    print(f"[face] colour: {cname}")
                elif key in ('x', 'z'):
                    effect_i = (effect_i + (1 if key == 'x' else -1)) % len(EFFECTS)
                    for p in panels:
                        p['particles'].set_effect(EFFECTS[effect_i])
                    live.update(particles=EFFECTS[effect_i])
                    print(f"[fx] effect: {EFFECTS[effect_i]}")
                elif key in ('e', 'w'):
                    for p in panels:
                        if key == 'e':
                            p['state'].next_expression()
                        else:
                            p['state'].prev_expression_cmd()
                    print(f"[expr] {panels[0]['state'].expression}")
                elif key == 'b':
                    for p in panels:
                        p['state'].trigger_blink()
                elif key == 's':
                    if save_state(state_path, live.snapshot()):
                        print(f"[save] wrote {state_path}")
                elif key in ('+', '='):
                    primary_state.brightness = min(255, primary_state.brightness + 16)
                    live.update(brightness=primary_state.brightness)
                    print(f"[brightness] {primary_state.brightness}")
                elif key in ('-', '_'):
                    primary_state.brightness = max(16, primary_state.brightness - 16)
                    live.update(brightness=primary_state.brightness)
                    print(f"[brightness] {primary_state.brightness}")

            # ── Shared inputs ─────────────────────────────────────────────────
            mic.update(dt, sensitivity=panels[0]['face_cfg'].get('mouth_sensitivity', 0.5))
            gyro.update(dt)

            vol        = mic.volume
            mouth_open = mic.mouth_open
            spectrum   = mic.spectrum.tolist()
            gyro_off   = gyro.get_offset()
            booped     = boop.is_booped()

            # ── Per-panel update ──────────────────────────────────────────────
            for p in panels:
                x, y, w, h = p['region']
                s = p['state']

                s.audio_volume = vol
                s.mouth_open   = mouth_open
                s.spectrum     = spectrum
                s.gyro_offset  = gyro_off

                if booped:
                    s.trigger_boop(boop.expression, boop.duration)

                # Consume IPC requests (only primary state holds IPC reqs)
                ipc_reqs = s.consume_ipc_requests()
                if ipc_reqs['custom_color'] is not None:
                    r, g, b = ipc_reqs['custom_color']
                    p['material'][0] = SolidMaterial(r, g, b, w, h)
                if ipc_reqs['material_request'] is not None:
                    p['material'][0] = load_material(ipc_reqs['material_request'], w, h)
                if ipc_reqs['gif_request'] is not None:
                    gi = ipc_reqs['gif_request']
                    if 0 <= gi < len(gif_files):
                        p['gif'].load(gif_files[gi])
                if ipc_reqs['release']:
                    p['gif'].stop()

                s.update(dt)
                p['material'][0].update(dt)
                p['particles'].update(dt)

            # GIF auto-cycle (applies to all panels' gif players)
            if gif_auto and gif_files:
                gif_timer -= dt
                if gif_timer <= 0:
                    gif_timer = gif_interval
                    for p in panels:
                        p['gif'].load(gif_files[gif_idx])
                    gif_idx = (gif_idx + 1) % len(gif_files)
            for p in panels:
                p['gif'].update(dt)

            # ── Per-panel render → blit into canvas ───────────────────────────
            brightness = primary_state.brightness
            for p in panels:
                x, y, w, h = p['region']
                s = p['state']

                # Sub-canvas renderer (uses cached per-panel size)
                sub_renderer = renderer.sub_renderer(w, h)

                bg  = sub_renderer.solid_layer(bg_color)
                mat = p['material'][0].get_frame()

                gif_frame = p['gif'].get_frame()
                if gif_frame is not None:
                    face_layer = gif_frame
                else:
                    face_rgba  = p['face'].get_frame(s)
                    face_layer = sub_renderer.apply_material(face_rgba, mat)

                parts = p['particles'].render()  # RGBA ndarray or None

                layers = [face_layer]
                if parts is not None:
                    layers.append(parts)

                frame = sub_renderer.composite(bg, layers)

                if brightness < 255:
                    frame = (frame * (brightness / 255.0)).astype(np.uint8)

                canvas[y:y+h, x:x+w] = frame[:, :, :3]

            # ── Mirror pass: panels with mirror_of copy a source region, flipped
            region_by_name = {p['name']: p['region'] for p in panels}
            for p in panels:
                src_name = p.get('mirror_of')
                if not src_name:
                    continue
                sx, sy, sw, sh = region_by_name.get(src_name, p['region'])
                x, y, w, h = p['region']
                if (sw, sh) == (w, h):
                    canvas[y:y+h, x:x+w] = np.fliplr(canvas[sy:sy+sh, sx:sx+sw])

            # ── Write to shared memory + output ───────────────────────────────
            shm.write(canvas)
            out.show(canvas)

            # ── Frame rate cap ────────────────────────────────────────────────
            elapsed = time.monotonic() - now
            sleep   = target_dt - elapsed
            if sleep > 0:
                time.sleep(sleep)

    except KeyboardInterrupt:
        pass
    finally:
        out.close()        # blank the panels first, before slower teardown
        keyboard.stop()
        ipc.stop()
        shm.close()
        mic.close()
        gyro.close()
        boop.close()
        print("Protoface stopped.")


if __name__ == '__main__':
    main()
