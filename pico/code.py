"""Protoface — Raspberry Pi Pico 2 / Pico 2 W entry point (CircuitPython).

Copy the contents of this `pico/` folder to the root of the CIRCUITPY drive so
that `code.py`, `config.json`, the `protoface_pico/` package, and the baked
`assets/` all sit at the drive root. CircuitPython runs `code.py` on boot.

Pipeline (mirrors the CM5 build, standalone — no ProtoHUD IPC):
    config -> HUB75 display -> material/face/particles -> main loop
Controls: single keys over the USB serial console (see protoface_pico/controls).
"""

import time
import gc

import displayio

from protoface_pico import config as cfg_mod
from protoface_pico import matrix as matrix_mod
from protoface_pico import material as material_mod
from protoface_pico.face import FaceEngine
from protoface_pico.particles import ParticleSystem
from protoface_pico.state import FaceState
from protoface_pico import controls

# Cycle palettes for the standalone controls.
_COLOR_CYCLE = ["teal", "red", "orange", "yellow", "green",
                "blue", "purple", "magenta", "white"]
_EFFECT_CYCLE = ["none", "sparkle", "embers", "confetti", "rain",
                 "snow", "fireflies"]


def main():
    cfg = cfg_mod.load("config.json")
    canvas_w, canvas_h = cfg_mod.canvas_size(cfg)

    display = matrix_mod.build_display(cfg)

    disp = cfg["display"]
    fps = disp.get("fps", 30)
    brightness = int(disp.get("brightness", 255))

    # Material + face + particles.
    face_cfg = cfg["face"]
    mat = material_mod.make(cfg["material"].get("active", "teal"),
                            cfg_mod.resolve_color)
    face = FaceEngine(
        "assets", face_cfg.get("active", "main"),
        mat, canvas_w, canvas_h,
        mirror=face_cfg.get("mirror", True),
    )
    face.set_brightness(brightness)

    particles = ParticleSystem(canvas_w, canvas_h)
    particles.set_effect(cfg["particles"].get("active", "none"))

    state = FaceState(face_cfg, face.expression_names())
    state.brightness = brightness

    # Root group: face below, particles above.
    root = displayio.Group()
    root.append(face.group)
    root.append(particles.group)
    display.root_group = root

    color_i = 0
    effect_i = _EFFECT_CYCLE.index(cfg["particles"].get("active", "none")) \
        if cfg["particles"].get("active", "none") in _EFFECT_CYCLE else 0

    print("Protoface (Pico) running: %dx%d @ %d fps target" %
          (canvas_w, canvas_h, fps))
    print("Serial keys: c/v colour  x/z effect  e/w expr  b blink  +/- bright")

    target_dt = 1.0 / fps
    prev = time.monotonic()
    gc.collect()

    while True:
        now = time.monotonic()
        dt = now - prev
        prev = now
        if dt > 0.1:
            dt = 0.1

        # -- Controls -------------------------------------------------------
        key = controls.poll_key()
        if key:
            if key in ("c", "v"):
                color_i = (color_i + (1 if key == "c" else -1)) % len(_COLOR_CYCLE)
                mat = material_mod.make(_COLOR_CYCLE[color_i], cfg_mod.resolve_color)
                face.set_material(mat, state.brightness)
                print("colour:", _COLOR_CYCLE[color_i])
            elif key in ("x", "z"):
                effect_i = (effect_i + (1 if key == "x" else -1)) % len(_EFFECT_CYCLE)
                particles.set_effect(_EFFECT_CYCLE[effect_i])
                print("effect:", _EFFECT_CYCLE[effect_i])
            elif key == "e":
                state.next_expression()
            elif key == "w":
                state.prev_expression_cmd()
            elif key == "b":
                state.trigger_blink()
            elif key in ("+", "="):
                state.brightness = min(255, state.brightness + 16)
                face.set_brightness(state.brightness)
            elif key in ("-", "_"):
                state.brightness = max(16, state.brightness - 16)
                face.set_brightness(state.brightness)

        # -- Update + render ------------------------------------------------
        state.update(dt)
        face.update(state)
        particles.update(dt)
        particles.render()

        # -- Frame cap ------------------------------------------------------
        elapsed = time.monotonic() - now
        sleep = target_dt - elapsed
        if sleep > 0:
            time.sleep(sleep)


main()
