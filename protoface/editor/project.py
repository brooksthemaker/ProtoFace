"""
FaceProject — in-memory model of a face folder for the editor.

Pure logic (numpy + PIL + json, no pygame) so it can be unit-tested headless.
Reads and writes the exact faces/<name>/ layout the renderer consumes:

    <name>/
      neutral.png, happy.png, ...   expression sprites (RGBA)
      blink.png                     eye-closed frame (optional)
      config.json                   expressions map + regions + fit settings

Editing happens at the sprite's native resolution; that resolution is written
back as ``draw_size`` so the region boxes stay in the same coordinate space the
renderer scales from.  Unknown config.json keys (visemes, boop faces, etc.) and
their PNG files are preserved untouched.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
from PIL import Image

# Filenames that are never treated as expressions when scanning a folder.
NON_EXPRESSION = {
    'blink', 'mouth_open', 'mouth_small', 'mouth_smile', 'mouth_round',
    'boop_snout', 'boop_left', 'boop_right', 'boop_both',
}
REGION_KEYS = ('eye_left', 'eye_right', 'mouth')


def _load_rgba(path: Path, size: tuple[int, int]) -> np.ndarray:
    img = Image.open(path).convert('RGBA')
    if img.size != size:
        img = img.resize(size, Image.NEAREST)
    return np.array(img, dtype=np.uint8)


def _scale_region(region: dict, sx: float, sy: float) -> dict:
    """Scale a region's coordinates (rect or polygon) by (sx, sy)."""
    if 'points' in region:
        return {'points': [[int(round(px * sx)), int(round(py * sy))]
                            for px, py in region['points']]}
    return {
        'x': int(round(region.get('x', 0) * sx)),
        'y': int(round(region.get('y', 0) * sy)),
        'w': max(1, int(round(region.get('w', 1) * sx))),
        'h': max(1, int(round(region.get('h', 1) * sy))),
    }


class FaceProject:
    def __init__(self, folder: Path, size: tuple[int, int]):
        self.folder = Path(folder)
        self.size = (int(size[0]), int(size[1]))     # (w, h) authoring resolution
        self.order: list[str] = []                   # expression names, in order
        self.arrays: dict[str, np.ndarray] = {}      # name -> (H, W, 4) uint8
        self.filenames: dict[str, str] = {}          # name -> png filename
        self.blink: np.ndarray | None = None
        self.blink_file = 'blink.png'
        self.regions: dict[str, dict] = {}           # eye_left / eye_right / mouth
        self.fit = 'stretch'
        self.scale = 1.0
        self.offset = (0, 0)
        self._raw_cfg: dict = {}                     # preserved unknown keys

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def new(cls, folder, size=(64, 32), expressions=('neutral',)) -> 'FaceProject':
        p = cls(folder, size)
        w, h = p.size
        for name in expressions:
            p.order.append(name)
            p.arrays[name] = np.zeros((h, w, 4), dtype=np.uint8)
            p.filenames[name] = f'{name}.png'
        p.blink = np.zeros((h, w, 4), dtype=np.uint8)
        return p

    @classmethod
    def load(cls, folder, default_size=(64, 32)) -> 'FaceProject':
        folder = Path(folder)
        cfg_path = folder / 'config.json'
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}

        expr_map = dict(cfg.get('expressions', {}))
        if not expr_map:
            for f in sorted(folder.glob('*.png')):
                if f.stem.lower() not in NON_EXPRESSION:
                    expr_map[f.stem] = f.name

        # Choose the authoring resolution: prefer the first real PNG's native
        # size, else draw_size, else the default.
        size = None
        for filename in expr_map.values():
            fp = folder / filename
            if fp.exists():
                with Image.open(fp) as im:
                    size = im.size
                break
        if size is None and cfg.get('draw_size'):
            ds = cfg['draw_size']
            size = (int(ds[0]), int(ds[1]))
        if size is None:
            size = default_size

        p = cls(folder, size)
        p._raw_cfg = copy.deepcopy(cfg)
        p.fit = str(cfg.get('fit', 'stretch')).lower()
        if p.fit not in ('stretch', 'contain', 'cover'):
            p.fit = 'stretch'
        try:
            p.scale = float(cfg.get('scale', 1.0)) or 1.0
        except (TypeError, ValueError):
            p.scale = 1.0
        p.offset = (int(cfg.get('offset_x', 0)), int(cfg.get('offset_y', 0)))

        for name, filename in expr_map.items():
            fp = folder / filename
            if fp.exists():
                p.order.append(name)
                p.arrays[name] = _load_rgba(fp, p.size)
                p.filenames[name] = filename
        if not p.order:   # empty/new folder — start with a blank neutral
            p.order.append('neutral')
            p.arrays['neutral'] = np.zeros((p.size[1], p.size[0], 4), dtype=np.uint8)
            p.filenames['neutral'] = 'neutral.png'

        p.blink_file = cfg.get('blink', 'blink.png')
        blink_path = folder / p.blink_file
        if blink_path.exists():
            p.blink = _load_rgba(blink_path, p.size)
        else:
            p.blink = np.zeros((p.size[1], p.size[0], 4), dtype=np.uint8)

        # Regions — scale from the stored draw_size into our authoring space.
        sx = sy = 1.0
        ds = cfg.get('draw_size')
        if ds and ds[0] and ds[1]:
            sx = p.size[0] / float(ds[0])
            sy = p.size[1] / float(ds[1])
        for key in REGION_KEYS:
            if key in cfg and isinstance(cfg[key], dict):
                p.regions[key] = _scale_region(cfg[key], sx, sy)

        return p

    # ── Mutation helpers ──────────────────────────────────────────────────────

    def current_names(self) -> list[str]:
        return list(self.order)

    def get(self, name: str) -> np.ndarray:
        return self.arrays[name]

    def set(self, name: str, arr: np.ndarray):
        self.arrays[name] = arr

    def add_expression(self, name: str, copy_from: str | None = None) -> bool:
        if not name or name in self.arrays:
            return False
        w, h = self.size
        if copy_from and copy_from in self.arrays:
            self.arrays[name] = self.arrays[copy_from].copy()
        else:
            self.arrays[name] = np.zeros((h, w, 4), dtype=np.uint8)
        self.filenames[name] = f'{name}.png'
        self.order.append(name)
        return True

    # ── Save ──────────────────────────────────────────────────────────────────

    def config_dict(self) -> dict:
        """The config.json that would be written (preserving unknown keys)."""
        cfg = copy.deepcopy(self._raw_cfg)
        cfg['expressions'] = {n: self.filenames.get(n, f'{n}.png') for n in self.order}
        cfg['blink'] = self.blink_file
        cfg['draw_size'] = [self.size[0], self.size[1]]
        cfg['fit'] = self.fit
        cfg['scale'] = self.scale
        cfg['offset_x'] = int(self.offset[0])
        cfg['offset_y'] = int(self.offset[1])
        for key in REGION_KEYS:
            if key in self.regions:
                cfg[key] = self.regions[key]
            else:
                cfg.pop(key, None)
        return cfg

    def write(self, folder) -> list[str]:
        """Write PNGs + config.json into *folder*. Returns the files written."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        for name in self.order:
            filename = self.filenames.get(name, f'{name}.png')
            Image.fromarray(self.arrays[name], 'RGBA').save(folder / filename)
            written.append(filename)
        if self.blink is not None:
            Image.fromarray(self.blink, 'RGBA').save(folder / self.blink_file)
            written.append(self.blink_file)
        (folder / 'config.json').write_text(json.dumps(self.config_dict(), indent=2))
        written.append('config.json')
        return written

    def save(self) -> list[str]:
        """Write PNGs + config.json to the project's own folder."""
        written = self.write(self.folder)
        self._raw_cfg = self.config_dict()
        return written
