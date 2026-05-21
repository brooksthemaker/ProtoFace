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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yaml')
    args = parser.parse_args()

    cfg = load_config(args.config)

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

    # ── IPC server — share state and particle refs for all panels ─────────────
    # IPC commands apply to all panels unless targeting a named panel.
    # Use panel[0] state as the primary IPC state handle.
    primary_state = panels[0]['state']
    ipc = IpcServer(primary_state, cfg)
    # Give IPC access to all panels' particles and materials
    ipc.set_panels(panels)
    ipc.start()

    # ── Shared memory frame writer ─────────────────────────────────────────────
    shm_path = cfg.get('ipc', {}).get('shm_path', '/dev/shm/protoface_frame')
    shm = ShmWriter(shm_path, canvas_w, canvas_h)

    # ── Master canvas ─────────────────────────────────────────────────────────
    canvas = np.zeros((canvas_h, canvas_w, 3), dtype=np.uint8)

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
        ipc.stop()
        shm.close()
        mic.close()
        gyro.close()
        boop.close()
        out.close()
        print("Protoface stopped.")


if __name__ == '__main__':
    main()
