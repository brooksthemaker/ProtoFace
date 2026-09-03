"""
Protoface face editor — a standalone pixel editor for face PNGs.

A Python/pygame port of ProtoHUD's in-HMD FaceEditor (src/menu/face_editor.*),
adapted to Protoface's asset model: whole-face PNGs at panel resolution in a
faces/<name>/ folder, with rectangular eye/mouth hit-boxes round-tripped
through the folder's config.json. ProtoHUD's camera features are deliberately
NOT ported — this build has no camera section.

Run it on a desktop (or over VNC/X-forwarding on the Pi):

    python editor.py                       # edits faces/main at 64x32
    python editor.py --face example_fox    # another face folder
    python editor.py --scale 18            # bigger pixels

While the Protoface daemon is running on the panels, V pushes the canvas onto
the physical panels for ~10 s (IPC preview_face over /tmp/protoface.sock), and
T overlays the daemon's live composited frame (read from /dev/shm) so you can
see material + particle effects applied to your art while you draw.

Keys (mirroring ProtoHUD's FaceEditor where it has them):
    arrows      move cursor            space   paint at cursor
    1-7         tool: pencil eraser bucket eyedrop line rect eyebox
    p/e/b/i/l/r tool aliases (pencil eraser bucket eyedrop line rect)
    7 again     eyebox target: eye_left -> eye_right -> mouth
    m           toggle mirror brush    [ ]     cycle palette colour
    - =         brush size             z       undo (16 deep)
    tab / , .   next / prev image (expressions, blink, mouth_open)
    v           push preview to the physical panels (needs running daemon)
    t           toggle live overlay (daemon's composited frame from /dev/shm)
    s           save (PNG + config.json regions)
    esc / q     quit (warns if unsaved)

Tools:
    pencil/eraser  freehand (mouse drag paints); brush 1px/3x3/5x5
    bucket         flood fill the clicked colour
    eyedrop        pick the colour under the cursor
    line/rect      two clicks: anchor, then commit
    eyebox         two clicks define a rectangle written to config.json as the
                   current target region (eye_left / eye_right / mouth) — these
                   are the blink / mouth-open hit-boxes face.py blends
Mouse: click paints (any tool), drag freehand-paints (pencil/eraser only),
wheel cycles the palette.

Faces are white-on-transparent (the daemon tints them with the material
colour), so the default palette leads with white — but any colour works; the
material multiplies it.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys

import numpy as np
import yaml
from PIL import Image

import pygame

# ── Constants ─────────────────────────────────────────────────────────────────

TOOLS = ['pencil', 'eraser', 'bucket', 'eyedrop', 'line', 'rect', 'eyebox']
REGION_TARGETS = ['eye_left', 'eye_right', 'mouth']
REGION_COLORS = {                       # outline colours for the region overlay
    'eye_left':  (80, 200, 255),
    'eye_right': (80, 130, 255),
    'mouth':     (255, 160, 60),
}

# White first — faces are white shapes tinted by the daemon's material.
DEFAULT_PALETTE = [
    (255, 255, 255),
    (0, 220, 180),      # teal
    (255, 0, 0),
    (255, 110, 0),
    (255, 230, 0),
    (0, 255, 0),
    (0, 90, 255),
    (160, 0, 255),
    (255, 0, 150),
    (128, 128, 128),
]

UNDO_DEPTH       = 16
PREVIEW_DURATION = 10.0
SIDEBAR_W        = 270
STATUS_H         = 24


# ── Face folder document ──────────────────────────────────────────────────────

class FaceDoc:
    """One faces/<name>/ folder: its editable PNGs and its config.json."""

    def __init__(self, folder: str, w: int, h: int):
        self.folder = folder
        self.w, self.h = w, h
        self.cfg_path = os.path.join(folder, 'config.json')
        self.cfg: dict = {}
        if os.path.exists(self.cfg_path):
            with open(self.cfg_path) as f:
                self.cfg = json.load(f)

        # Editable files: expressions (config.json map or folder scan), then
        # blink + mouth_open — same discovery rules as protoface/face.py.
        entries: list[tuple[str, str]] = []       # (label, filename)
        expr_map = self.cfg.get('expressions', {})
        if not expr_map:
            for fn in sorted(os.listdir(folder)):
                stem, ext = os.path.splitext(fn)
                if ext.lower() == '.png' and stem.lower() not in ('blink', 'mouth_open'):
                    expr_map[stem.lower()] = fn
        entries += [(name, fn) for name, fn in expr_map.items()]
        blink_fn = self.cfg.get('blink', 'blink.png')
        if os.path.exists(os.path.join(folder, blink_fn)):
            entries.append(('blink', blink_fn))
        if os.path.exists(os.path.join(folder, 'mouth_open.png')):
            entries.append(('mouth_open', 'mouth_open.png'))
        if not entries:
            entries = [('neutral', 'neutral.png')]     # start a fresh face
        self.entries = entries

        # Regions in panel space. If the config was authored at another
        # resolution (draw_size), scale it in — we re-save in panel space.
        draw = self.cfg.get('draw_size')
        sx = self.w / float(draw[0]) if draw else 1.0
        sy = self.h / float(draw[1]) if draw else 1.0
        self.regions: dict[str, dict] = {}
        for key in REGION_TARGETS:
            r = self.cfg.get(key)
            if r:
                self.regions[key] = {
                    'x': int(round(r['x'] * sx)), 'y': int(round(r['y'] * sy)),
                    'w': max(1, int(round(r['w'] * sx))),
                    'h': max(1, int(round(r['h'] * sy))),
                }

    def load_canvas(self, idx: int) -> np.ndarray:
        path = os.path.join(self.folder, self.entries[idx][1])
        if os.path.exists(path):
            img = Image.open(path).convert('RGBA')
            if img.size != (self.w, self.h):
                img = img.resize((self.w, self.h), Image.NEAREST)
            return np.array(img, dtype=np.uint8)
        return np.zeros((self.h, self.w, 4), dtype=np.uint8)

    def save(self, idx: int, canvas: np.ndarray):
        os.makedirs(self.folder, exist_ok=True)
        path = os.path.join(self.folder, self.entries[idx][1])
        Image.fromarray(canvas, 'RGBA').save(path)

        # Round-trip config.json: update only what the editor owns (regions,
        # and drop draw_size since art + regions are now in panel space).
        for key in REGION_TARGETS:
            if key in self.regions:
                self.cfg[key] = dict(self.regions[key])
        self.cfg.pop('draw_size', None)
        if not self.cfg.get('expressions'):
            self.cfg['expressions'] = {
                name: fn for name, fn in self.entries
                if name not in ('blink', 'mouth_open')}
        with open(self.cfg_path, 'w') as f:
            json.dump(self.cfg, f, indent=2)
            f.write('\n')


# ── Daemon links (preview push + live overlay) ────────────────────────────────

def push_preview(sock_path: str, canvas: np.ndarray,
                 duration: float = PREVIEW_DURATION) -> bool:
    """Send the canvas to a running Protoface daemon as a transient face."""
    h, w = canvas.shape[:2]
    msg = {'cmd': 'preview_face', 'w': w, 'h': h,
           'rgba': base64.b64encode(canvas.tobytes()).decode('ascii'),
           'duration': duration}
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(sock_path)
        s.sendall((json.dumps(msg) + '\n').encode())
        s.close()
        return True
    except OSError as e:
        print(f'[editor] preview push failed ({sock_path}): {e}')
        return False


class LiveFrame:
    """Reader for the daemon's /dev/shm frame (seq byte + W*H RGB)."""

    def __init__(self, path: str, w: int, h: int):
        self.path, self.w, self.h = path, w, h

    def read(self) -> np.ndarray | None:
        try:
            with open(self.path, 'rb') as f:
                data = f.read(1 + self.w * self.h * 3)
        except OSError:
            return None
        if len(data) < 1 + self.w * self.h * 3:
            return None
        return np.frombuffer(data[1:], dtype=np.uint8).reshape(self.h, self.w, 3)


# ── Editor ────────────────────────────────────────────────────────────────────

class Editor:
    def __init__(self, doc: FaceDoc, scale: int, sock_path: str,
                 live: LiveFrame, mirror_axis_x: int = -1):
        self.doc    = doc
        self.scale  = scale
        self.sock   = sock_path
        self.live   = live
        self.w, self.h = doc.w, doc.h

        self.file_idx = 0
        self.canvas   = doc.load_canvas(0)
        self.dirty    = False

        self.tool        = 'pencil'
        self.region_target = 0           # index into REGION_TARGETS (eyebox)
        self.mirror      = False
        # Mirror brush fence: canvas column the mirror reflects across
        # (<0 = canvas centre), same convention as ProtoHUD's mirror_axis_x.
        self.mirror_axis = mirror_axis_x
        self.brush       = 0             # radius: 0=1px 1=3x3 2=5x5
        self.palette     = list(DEFAULT_PALETTE)
        self.pal_idx     = 0
        self.cursor      = [self.w // 2, self.h // 2]
        self.anchor: tuple[int, int] | None = None   # line/rect/eyebox
        self.undo_stack: list[np.ndarray] = []
        self.live_mode   = False
        self.status      = 'ready'

        pygame.init()
        pygame.display.set_caption(f'Protoface Editor — {doc.folder}')
        self.grid_w = self.w * scale
        self.grid_h = self.h * scale
        self.screen = pygame.display.set_mode(
            (self.grid_w + SIDEBAR_W, max(self.grid_h, 420) + STATUS_H))
        self.font   = pygame.font.SysFont('monospace', 13)
        self.clock  = pygame.time.Clock()

    # ── Canvas ops (ports of face_editor.cpp helpers) ─────────────────────────

    def push_undo(self):
        self.undo_stack.append(self.canvas.copy())
        if len(self.undo_stack) > UNDO_DEPTH:
            self.undo_stack.pop(0)

    def undo(self):
        if self.undo_stack:
            self.canvas = self.undo_stack.pop()
            self.dirty = True
        self.anchor = None

    def _color(self) -> tuple[int, int, int, int]:
        if self.tool == 'eraser':
            return (0, 0, 0, 0)
        r, g, b = self.palette[self.pal_idx]
        return (r, g, b, 255)

    def _mirror_x(self, x: int) -> int:
        axis2 = (self.mirror_axis * 2 + 1) if self.mirror_axis >= 0 else (self.w - 1)
        return axis2 - x

    def paint_pixel(self, x: int, y: int):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.canvas[y, x] = self._color()
            self.dirty = True

    def paint_brush(self, cx: int, cy: int):
        r = self.brush
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                self.paint_pixel(x, y)
                if self.mirror:
                    self.paint_pixel(self._mirror_x(x), y)

    def flood_fill(self, sx: int, sy: int):
        if not (0 <= sx < self.w and 0 <= sy < self.h):
            return
        target = self.canvas[sy, sx].copy()
        col = np.array(self._color(), dtype=np.uint8)
        if (target == col).all():
            return
        mask = (self.canvas == target).all(axis=2)
        stack = [(sx, sy)]
        while stack:
            x, y = stack.pop()
            if 0 <= x < self.w and 0 <= y < self.h and mask[y, x]:
                mask[y, x] = False
                self.canvas[y, x] = col
                stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
        self.dirty = True

    def eyedrop(self, x: int, y: int):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        r, g, b, a = self.canvas[y, x]
        if a == 0:
            return
        rgb = (int(r), int(g), int(b))
        if rgb in self.palette:
            self.pal_idx = self.palette.index(rgb)
        else:
            self.palette.append(rgb)
            self.pal_idx = len(self.palette) - 1
        self.status = f'picked {rgb}'

    def draw_line(self, x0, y0, x1, y1):
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.paint_brush(x0, y0)
            if (x0, y0) == (x1, y1):
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy; x0 += sx
            if e2 <= dx:
                err += dx; y0 += sy

    def draw_rect(self, x0, y0, x1, y1):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            for x in range(min(x0, x1), max(x0, x1) + 1):
                self.paint_pixel(x, y)
                if self.mirror:
                    self.paint_pixel(self._mirror_x(x), y)

    # ── Primary action (paint / anchor-commit), per tool ──────────────────────

    def primary(self):
        x, y = self.cursor
        if self.tool in ('pencil', 'eraser'):
            self.push_undo()
            self.paint_brush(x, y)
        elif self.tool == 'bucket':
            self.push_undo()
            self.flood_fill(x, y)
        elif self.tool == 'eyedrop':
            self.eyedrop(x, y)
        elif self.tool in ('line', 'rect'):
            if self.anchor is None:
                self.anchor = (x, y)
                self.status = f'{self.tool}: anchor set — click the far end'
            else:
                self.push_undo()
                ax, ay = self.anchor
                if self.tool == 'line':
                    self.draw_line(ax, ay, x, y)
                else:
                    self.draw_rect(ax, ay, x, y)
                self.anchor = None
        elif self.tool == 'eyebox':
            target = REGION_TARGETS[self.region_target]
            if self.anchor is None:
                self.anchor = (x, y)
                self.status = f'{target}: corner set — click the opposite corner'
            else:
                ax, ay = self.anchor
                self.doc.regions[target] = {
                    'x': min(ax, x), 'y': min(ay, y),
                    'w': abs(x - ax) + 1, 'h': abs(y - ay) + 1,
                }
                self.anchor = None
                self.dirty = True
                self.status = f'{target} = {self.doc.regions[target]}'

    def set_tool(self, tool: str):
        if tool == 'eyebox' and self.tool == 'eyebox':
            # 7 again cycles which region the eyebox writes.
            self.region_target = (self.region_target + 1) % len(REGION_TARGETS)
            self.status = f'eyebox target: {REGION_TARGETS[self.region_target]}'
        self.tool = tool
        self.anchor = None

    # ── File switching / save / preview ───────────────────────────────────────

    def switch_file(self, step: int):
        self.file_idx = (self.file_idx + step) % len(self.doc.entries)
        self.canvas   = self.doc.load_canvas(self.file_idx)
        self.undo_stack.clear()
        self.anchor = None
        self.dirty  = False
        self.status = f'editing {self.doc.entries[self.file_idx][1]}'

    def save(self):
        self.doc.save(self.file_idx, self.canvas)
        self.dirty = False
        self.status = f'saved {self.doc.entries[self.file_idx][1]} + config.json'
        print(f'[editor] {self.status}')

    def preview(self):
        ok = push_preview(self.sock, self.canvas)
        self.status = ('previewing on panels for '
                       f'{PREVIEW_DURATION:.0f}s') if ok else 'preview failed — daemon running?'

    # ── Event handling ────────────────────────────────────────────────────────

    def _cell_at(self, mx: int, my: int) -> tuple[int, int] | None:
        x, y = mx // self.scale, my // self.scale
        if 0 <= x < self.w and 0 <= y < self.h:
            return x, y
        return None

    def handle_key(self, key, mods) -> bool:
        """Returns False to quit."""
        if key in (pygame.K_ESCAPE, pygame.K_q):
            if self.dirty:
                self.dirty = False
                self.status = 'unsaved changes — press again to quit, s to save'
                return True
            return False
        if   key == pygame.K_LEFT:  self.cursor[0] = max(0, self.cursor[0] - 1)
        elif key == pygame.K_RIGHT: self.cursor[0] = min(self.w - 1, self.cursor[0] + 1)
        elif key == pygame.K_UP:    self.cursor[1] = max(0, self.cursor[1] - 1)
        elif key == pygame.K_DOWN:  self.cursor[1] = min(self.h - 1, self.cursor[1] + 1)
        elif key == pygame.K_SPACE: self.primary()
        elif key == pygame.K_z:     self.undo()
        elif key == pygame.K_v:     self.preview()
        elif key == pygame.K_t:
            self.live_mode = not self.live_mode
            self.status = f'live overlay {"on" if self.live_mode else "off"}'
        elif key == pygame.K_s:     self.save()
        elif key == pygame.K_m:
            self.mirror = not self.mirror
            self.status = f'mirror {"on" if self.mirror else "off"}'
        elif key in (pygame.K_1, pygame.K_p): self.set_tool('pencil')
        elif key in (pygame.K_2, pygame.K_e): self.set_tool('eraser')
        elif key in (pygame.K_3, pygame.K_b): self.set_tool('bucket')
        elif key in (pygame.K_4, pygame.K_i): self.set_tool('eyedrop')
        elif key in (pygame.K_5, pygame.K_l): self.set_tool('line')
        elif key in (pygame.K_6, pygame.K_r): self.set_tool('rect')
        elif key == pygame.K_7:               self.set_tool('eyebox')
        elif key == pygame.K_LEFTBRACKET:
            self.pal_idx = (self.pal_idx - 1) % len(self.palette)
        elif key == pygame.K_RIGHTBRACKET:
            self.pal_idx = (self.pal_idx + 1) % len(self.palette)
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.brush = max(0, self.brush - 1)
        elif key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.brush = min(2, self.brush + 1)
        elif key in (pygame.K_TAB, pygame.K_PERIOD):
            self.switch_file(+1)
        elif key == pygame.K_COMMA:
            self.switch_file(-1)
        return True

    def run(self):
        running = True
        mouse_held = False
        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.KEYDOWN:
                    running = self.handle_key(ev.key, ev.mod)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        cell = self._cell_at(*ev.pos)
                        if cell:
                            self.cursor = list(cell)
                            self.primary()
                            mouse_held = True
                    elif ev.button == 4:
                        self.pal_idx = (self.pal_idx - 1) % len(self.palette)
                    elif ev.button == 5:
                        self.pal_idx = (self.pal_idx + 1) % len(self.palette)
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    mouse_held = False
                elif ev.type == pygame.MOUSEMOTION:
                    cell = self._cell_at(*ev.pos)
                    if cell:
                        self.cursor = list(cell)
                        # Freehand stroke: drag paints for pencil/eraser only
                        # (two-step and point tools ignore drags, so a click
                        # can't re-fire primary()) — as in ProtoHUD.
                        if mouse_held and self.tool in ('pencil', 'eraser'):
                            self.paint_brush(*cell)
            self.draw()
            self.clock.tick(60)
        pygame.quit()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self):
        scr = self.screen
        scr.fill((24, 24, 28))
        cs = self.scale

        # Pixel grid (checkerboard shows transparency)
        live_frame = self.live.read() if self.live_mode else None
        for y in range(self.h):
            for x in range(self.w):
                r, g, b, a = self.canvas[y, x]
                if a == 0:
                    c = (40, 40, 46) if (x + y) % 2 else (32, 32, 38)
                else:
                    c = (int(r), int(g), int(b))
                pygame.draw.rect(scr, c, (x * cs, y * cs, cs - 1, cs - 1))

        # Live overlay: the daemon's composited frame for this panel size,
        # blended over the art so material tint + particles are visible.
        if live_frame is not None:
            lw = min(self.w, live_frame.shape[1])
            for y in range(min(self.h, live_frame.shape[0])):
                for x in range(lw):
                    lr, lg, lb = live_frame[y, x]
                    if lr or lg or lb:
                        pygame.draw.rect(
                            scr, (int(lr), int(lg), int(lb)),
                            (x * cs + cs // 4, y * cs + cs // 4,
                             cs // 2, cs // 2))

        # Region outlines (eye/mouth hit-boxes)
        for key, reg in self.doc.regions.items():
            col = REGION_COLORS.get(key, (200, 200, 200))
            pygame.draw.rect(
                scr, col,
                (reg['x'] * cs, reg['y'] * cs, reg['w'] * cs, reg['h'] * cs), 1)

        # Mirror axis
        if self.mirror:
            ax = (self.mirror_axis if self.mirror_axis >= 0 else self.w // 2)
            pygame.draw.line(scr, (90, 90, 120),
                             (ax * cs, 0), (ax * cs, self.h * cs), 1)

        # Anchor + cursor
        if self.anchor:
            axp, ayp = self.anchor
            pygame.draw.rect(scr, (255, 255, 0),
                             (axp * cs, ayp * cs, cs - 1, cs - 1), 2)
        cxp, cyp = self.cursor
        pygame.draw.rect(scr, (255, 255, 255),
                         (cxp * cs, cyp * cs, cs - 1, cs - 1), 2)

        self._draw_sidebar()
        pygame.display.flip()

    def _draw_sidebar(self):
        scr = self.screen
        x0 = self.grid_w + 12
        y = 10

        def line(text, color=(200, 200, 205)):
            nonlocal y
            scr.blit(self.font.render(text, True, color), (x0, y))
            y += 17

        name, fn = self.doc.entries[self.file_idx]
        line(f'{self.doc.folder}', (140, 200, 255))
        line(f'file  : {fn} ({name}){" *" if self.dirty else ""}')
        line(f'tool  : {self.tool}'
             + (f' -> {REGION_TARGETS[self.region_target]}'
                if self.tool == 'eyebox' else ''))
        line(f'brush : {2 * self.brush + 1}px   mirror: '
             f'{"on" if self.mirror else "off"}')
        line(f'cursor: {self.cursor[0]},{self.cursor[1]}')
        y += 6

        # Palette swatches
        line('palette  [ ] or wheel', (150, 150, 160))
        sw = 22
        for i, (r, g, b) in enumerate(self.palette):
            px = x0 + (i % 10) * (sw + 3)
            py = y + (i // 10) * (sw + 3)
            pygame.draw.rect(scr, (r, g, b), (px, py, sw, sw))
            if i == self.pal_idx:
                pygame.draw.rect(scr, (255, 255, 255), (px - 2, py - 2, sw + 4, sw + 4), 2)
        y += ((len(self.palette) - 1) // 10 + 1) * (sw + 3) + 10

        for text in (
            '1-7 tools  p/e/b/i/l/r',
            '7 again: eyebox target',
            'space paint  z undo',
            'tab/,/. switch image',
            'v preview on panels',
            't live overlay',
            's save   esc quit',
        ):
            line(text, (150, 150, 160))

        # Status bar
        scr.blit(self.font.render(self.status, True, (255, 220, 120)),
                 (8, self.screen.get_height() - STATUS_H + 4))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='Protoface pixel editor for face PNGs')
    ap.add_argument('--face', default=None,
                    help='face folder name under faces/ (default: first '
                         'panel\'s face.active from config)')
    ap.add_argument('--config', default='config.yaml')
    ap.add_argument('--scale', type=int, default=14, help='pixel size on screen')
    args = ap.parse_args()

    cfg = {}
    if os.path.exists(args.config):
        with open(args.config) as f:
            cfg = yaml.safe_load(f) or {}

    panel = cfg.get('panel', {})
    w = panel.get('panel_width',  panel.get('width', 64))
    h = panel.get('panel_height', panel.get('height', 32))

    face = args.face
    if face is None:
        panels = cfg.get('panels') or []
        face = (panels[0].get('face', {}) if panels else {}).get('active', 'main')

    folder = os.path.join('faces', face)
    if not os.path.isdir(folder):
        print(f'[editor] no such face folder: {folder}')
        sys.exit(1)

    sock_path = cfg.get('ipc', {}).get('socket', '/tmp/protoface.sock')
    shm_path  = cfg.get('ipc', {}).get('shm_path', '/dev/shm/protoface_frame')
    # The live frame is the whole canvas; the editor edits one panel, and
    # panel 0 sits at canvas origin, so reading the full canvas and cropping
    # (LiveFrame returns full rows; draw() crops to panel w/h) works.
    canvas_w = w * panel.get('chain_length', 2)
    canvas_h = h * panel.get('parallel', 1)
    live = LiveFrame(shm_path, canvas_w, canvas_h)

    doc = FaceDoc(folder, w, h)
    Editor(doc, args.scale, sock_path, live).run()


if __name__ == '__main__':
    main()
