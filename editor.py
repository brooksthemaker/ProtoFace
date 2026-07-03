"""
Protoface face editor — a standalone pixel-art editor for face folders.

    python editor.py                     # edit config.yaml's active face
    python editor.py main                # edit faces/main
    python editor.py faces/example_fox   # edit by path
    python editor.py --new myface --size 64x32
    python editor.py --config other.yaml

Edit-only: this never touches the render daemon (run.py). It reads and writes
the same faces/<name>/ folders — PNGs + config.json — that the panels render,
so what you draw is what shows up on the hardware. Save with Ctrl+S.
"""

import argparse
import os
import sys

try:
    import yaml
except ImportError:
    yaml = None


def _active_face_from_config(config_path: str) -> str:
    if yaml is None or not os.path.exists(config_path):
        return 'main'
    try:
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return 'main'
    panels = cfg.get('panels') or []
    if panels:
        return panels[0].get('face', {}).get('active', 'main')
    return cfg.get('face', {}).get('active', 'main')


def _load_cfg(config_path: str) -> dict:
    if yaml is None or not os.path.exists(config_path):
        return {}
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split('x')
        return int(w), int(h)
    except Exception:
        raise SystemExit(f"--size must look like 64x32, got {text!r}")


def resolve_folder(face_arg: str | None, faces_dir: str, config_path: str) -> str:
    if face_arg:
        # A path (has a separator or exists) is used verbatim; otherwise it's a
        # face name under faces/.
        if os.sep in face_arg or (os.altsep and os.altsep in face_arg) \
                or os.path.isdir(face_arg):
            return face_arg
        return os.path.join(faces_dir, face_arg)
    return os.path.join(faces_dir, _active_face_from_config(config_path))


def main():
    ap = argparse.ArgumentParser(description='Protoface standalone face editor')
    ap.add_argument('face', nargs='?', help='face name (under faces/) or a folder path')
    ap.add_argument('--config', default='config.yaml', help='config.yaml for the preview panel size')
    ap.add_argument('--faces-dir', default='faces', help='root folder holding face folders')
    ap.add_argument('--new', metavar='NAME', help='create a new blank face folder and edit it')
    ap.add_argument('--size', default='64x32', help='canvas size for --new, e.g. 64x32')
    args = ap.parse_args()

    # project.py is pygame-free, so validate/build the model (and fail fast on a
    # bad path) before importing the pygame UI.
    from protoface.editor.project import FaceProject

    cfg = _load_cfg(args.config)

    if args.new:
        folder = os.path.join(args.faces_dir, args.new)
        if os.path.exists(os.path.join(folder, 'config.json')):
            print(f"[editor] {folder} already exists — opening it instead of overwriting.")
            project = FaceProject.load(folder)
        else:
            project = FaceProject.new(folder, size=_parse_size(args.size),
                                      expressions=('neutral', 'happy', 'angry'))
            print(f"[editor] new face at {folder}")
    else:
        folder = resolve_folder(args.face, args.faces_dir, args.config)
        if not os.path.isdir(folder):
            print(f"[editor] no such face folder: {folder}\n"
                  f"         create one with:  python editor.py --new <name>", file=sys.stderr)
            sys.exit(1)
        project = FaceProject.load(folder)
        print(f"[editor] editing {folder}  ({len(project.order)} expressions, "
              f"{project.size[0]}x{project.size[1]})")

    from protoface.editor.app import EditorApp
    EditorApp(project, cfg).run()


if __name__ == '__main__':
    main()
