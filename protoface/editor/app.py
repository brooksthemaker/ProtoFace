"""
Pygame face editor — the interactive layer.

Immediate-mode UI around FaceProject (model) and canvas.py (tools).  The live
preview is rendered with the real FaceLoader + Renderer + FaceState so what you
see is exactly what the panels show, including polygon eye regions, fit/scale
and material tint.

Layout:  [ tools + palette + expressions + regions ]  [ pixel canvas ]  [ preview ]
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pygame

from . import canvas as C
from .project import FaceProject, REGION_KEYS
from ..face import FaceLoader
from ..renderer import Renderer
from ..material import load_material
from ..state import FaceState

# ── Colours ───────────────────────────────────────────────────────────────────
BG        = (24, 26, 30)
PANEL     = (34, 37, 43)
PANEL2    = (44, 48, 55)
INK       = (225, 228, 232)
MUTED     = (140, 146, 156)
ACCENT    = (0, 200, 170)
WARN      = (230, 120, 60)
LINE      = (60, 64, 72)

PALETTE = [
    (0, 0, 0, 255), (255, 255, 255, 255), (0, 220, 180, 255), (0, 120, 255, 255),
    (140, 0, 255, 255), (255, 0, 150, 255), (255, 40, 40, 255), (255, 120, 0, 255),
    (255, 220, 0, 255), (60, 220, 60, 255), (0, 200, 255, 255), (180, 180, 190, 255),
    (90, 90, 100, 255), (120, 70, 30, 255), (255, 180, 120, 255), (10, 10, 16, 255),
]
PREVIEW_MATERIALS = [
    'teal', 'rainbow', 'warm', 'cool',
    'gradient:h:s:0:FF8C00-FF3D7F-8A2BE2', 'solid:255,255,255',
]
TOOL_KEYS = {'pencil': 'P', 'eraser': 'E', 'bucket': 'G',
             'eyedrop': 'K', 'line': 'L', 'rect': 'R'}


class EditorApp:
    def __init__(self, project: FaceProject, cfg: dict | None = None,
                 size=(1180, 690)):
        self.project = project
        cfg = cfg or {}
        panel = cfg.get('panel', {})
        pw = panel.get('panel_width', panel.get('width', project.size[0]))
        ph = panel.get('panel_height', panel.get('height', project.size[1]))
        self.preview_size = (int(pw), int(ph))

        pygame.init()
        pygame.display.set_caption(f'Protoface Editor — {project.folder.name}')
        self.screen = pygame.display.set_mode(size, pygame.RESIZABLE)
        self.font   = pygame.font.Font(None, 20)
        self.small  = pygame.font.Font(None, 16)
        self.big    = pygame.font.Font(None, 26)
        self.clock  = pygame.time.Clock()

        # Editing state
        self.tool = 'pencil'
        self.brush = 1
        self.color = (0, 220, 180, 255)
        self.current = project.order[0]
        self.region_tool: str | None = None    # None | eye_left | eye_right | mouth
        self.region_mode = 'rect'               # rect | poly
        self.undo = C.UndoStack()
        self.status = 'Ready. Draw with the mouse; Ctrl+S saves.'
        self.focus: str | None = None           # None | 'hex' | 'newexpr'
        self.text_buf = ''

        # Canvas interaction
        self._hover = None
        self._stroke_last = None
        self._anchor = None
        self._poly: list[tuple[int, int]] = []

        # Preview
        self._preview_dir = Path(tempfile.mkdtemp(prefix='pf_editor_'))
        self._renderer = Renderer(*self.preview_size)
        self._mat_idx = 0
        self._pmaterial = load_material(PREVIEW_MATERIALS[0], *self.preview_size)
        self._face: FaceLoader | None = None
        self._pstate: FaceState | None = None
        self._preview_play = True
        self._preview_mouth = 0.0
        self._preview_err = ''
        self._dirty = True

        self.running = True
        self.compute_layout()
        self.rebuild_preview()

    # ── Layout ────────────────────────────────────────────────────────────────

    def compute_layout(self):
        w, h = self.screen.get_size()
        self.left_w = 214
        self.right_w = max(230, min(300, w // 4))
        pad = 10
        self.rects = {}
        self.buttons = {}       # name -> (Rect, group, value)

        # Left panel sections built top-down
        x = pad
        y = pad
        colw = self.left_w - 2 * pad

        def row(hgt):
            nonlocal y
            r = pygame.Rect(x, y, colw, hgt)
            y += hgt + 6
            return r

        self.rects['title'] = row(24)
        # Tools (2 cols x 3)
        self.tool_rects = {}
        tools = C.TOOLS
        bw = (colw - 6) // 2
        for i, t in enumerate(tools):
            rx = x + (i % 2) * (bw + 6)
            ry = y + (i // 2) * 30
            self.tool_rects[t] = pygame.Rect(rx, ry, bw, 26)
        y += 3 * 30 + 6
        # Brush sizes
        self.rects['brush_lbl'] = row(16)
        self.brush_rects = {}
        for i, b in enumerate((1, 2, 3, 4)):
            self.brush_rects[b] = pygame.Rect(x + i * ((colw - 18) // 4 + 6), y,
                                              (colw - 18) // 4, 24)
        y += 24 + 8
        # Colour + hex
        self.rects['color_lbl'] = row(16)
        self.rects['color_swatch'] = pygame.Rect(x, y, 34, 24)
        self.rects['hex'] = pygame.Rect(x + 42, y, colw - 42, 24)
        y += 24 + 6
        # Palette grid 8 x 2
        self.swatch_rects = []
        sw = (colw - 7 * 4) // 8
        for i, col in enumerate(PALETTE):
            rx = x + (i % 8) * (sw + 4)
            ry = y + (i // 8) * (sw + 4)
            self.swatch_rects.append((pygame.Rect(rx, ry, sw, sw), col))
        y += 2 * (sw + 4) + 8
        # Expressions
        self.rects['expr_lbl'] = row(16)
        self.expr_rects = []
        for name in self.project.order:
            self.expr_rects.append((row(22), name))
        self.rects['add_expr'] = row(22)
        # Regions
        self.rects['region_lbl'] = row(16)
        self.region_rects = {}
        rbw = (colw - 12) // 3
        for i, rn in enumerate(REGION_KEYS):
            self.region_rects[rn] = pygame.Rect(x + i * (rbw + 6), y, rbw, 24)
        y += 24 + 6
        self.mode_rects = {}
        for i, m in enumerate(('rect', 'poly')):
            self.mode_rects[m] = pygame.Rect(x + i * ((colw - 6) // 2 + 6), y,
                                             (colw - 6) // 2, 22)
        y += 22 + 4
        self.rects['clear_region'] = row(20)
        # Fit / scale / offset
        self.rects['fit'] = row(22)
        self.rects['scale_minus'] = pygame.Rect(x, y, 24, 22)
        self.rects['scale_lbl'] = pygame.Rect(x + 28, y, colw - 60, 22)
        self.rects['scale_plus'] = pygame.Rect(x + colw - 24, y, 24, 22)
        y += 22 + 6
        # Bottom actions
        self.rects['undo'] = pygame.Rect(x, y, (colw - 12) // 3, 26)
        self.rects['redo'] = pygame.Rect(x + (colw - 12) // 3 + 6, y, (colw - 12) // 3, 26)
        self.rects['save'] = pygame.Rect(x + 2 * ((colw - 12) // 3 + 6), y, (colw - 12) // 3, 26)

        # Canvas area (centre) and preview (right)
        cx = self.left_w + pad
        cw = w - self.left_w - self.right_w - 2 * pad
        self.rects['canvas'] = pygame.Rect(cx, pad + 24, max(80, cw), h - 2 * pad - 24)
        self.rects['status'] = pygame.Rect(cx, h - 24, max(80, cw), 20)
        px = w - self.right_w + 2
        self.rects['preview'] = pygame.Rect(px, pad + 24, self.right_w - pad - 4, 200)
        self.rects['mat'] = pygame.Rect(px, pad + 24 + 210, self.right_w - pad - 4, 24)
        self.rects['play'] = pygame.Rect(px, pad + 24 + 240, (self.right_w - pad - 10) // 2, 24)
        self.rects['mouth'] = pygame.Rect(px + (self.right_w - pad - 10) // 2 + 6,
                                          pad + 24 + 240, (self.right_w - pad - 10) // 2, 24)
        self.rects['help'] = pygame.Rect(px, pad + 24 + 276, self.right_w - pad - 4, 300)

    # ── Canvas geometry ───────────────────────────────────────────────────────

    def _canvas_geom(self):
        area = self.rects['canvas']
        w, h = self.project.size
        zoom = max(1, min(area.w // w, area.h // h))
        ox = area.x + (area.w - w * zoom) // 2
        oy = area.y + (area.h - h * zoom) // 2
        return zoom, ox, oy

    def screen_to_pixel(self, pos):
        zoom, ox, oy = self._canvas_geom()
        w, h = self.project.size
        px = (pos[0] - ox) // zoom
        py = (pos[1] - oy) // zoom
        if 0 <= px < w and 0 <= py < h:
            return int(px), int(py)
        return None

    @property
    def art(self) -> np.ndarray:
        return self.project.arrays[self.current]

    # ── Actions ───────────────────────────────────────────────────────────────

    def set_tool(self, t):
        self.tool = t
        self.region_tool = None
        self._poly.clear()

    def set_color(self, rgba):
        self.color = tuple(int(v) for v in rgba)
        if len(self.color) == 3:
            self.color = self.color + (255,)

    def select_expression(self, name):
        if name in self.project.arrays:
            self.current = name
            self._dirty = True

    def toggle_region(self, rn):
        self.region_tool = None if self.region_tool == rn else rn
        self._poly.clear()
        if self.region_tool:
            self.status = f'{rn}: {"click vertices, click first to close" if self.region_mode=="poly" else "drag a box"}'

    def clear_region(self):
        if self.region_tool and self.region_tool in self.project.regions:
            del self.project.regions[self.region_tool]
            self._dirty = True
            self.status = f'cleared {self.region_tool}'

    def cycle_fit(self):
        modes = ['stretch', 'contain', 'cover']
        self.project.fit = modes[(modes.index(self.project.fit) + 1) % 3]
        self._dirty = True

    def adjust_scale(self, d):
        self.project.scale = round(max(0.25, min(3.0, self.project.scale + d)), 2)
        self._dirty = True

    def do_undo(self):
        res = self.undo.undo(self.current, self.art)
        if res:
            name, arr = res
            self.project.set(name, arr)
            self.current = name
            self._dirty = True
            self.status = 'undo'

    def do_redo(self):
        res = self.undo.redo(self.current, self.art)
        if res:
            name, arr = res
            self.project.set(name, arr)
            self.current = name
            self._dirty = True
            self.status = 'redo'

    def do_save(self):
        try:
            files = self.project.save()
            self.status = f'saved {len(files)} files → {self.project.folder}'
        except Exception as e:                       # noqa: BLE001
            self.status = f'save failed: {e}'

    def add_expression(self, name):
        name = name.strip()
        if self.project.add_expression(name, copy_from=self.current):
            self.current = name
            self.compute_layout()
            self._dirty = True
            self.status = f'added expression "{name}"'
        else:
            self.status = 'name empty or already exists'

    def cycle_material(self):
        self._mat_idx = (self._mat_idx + 1) % len(PREVIEW_MATERIALS)
        self._pmaterial = load_material(PREVIEW_MATERIALS[self._mat_idx], *self.preview_size)

    # ── Preview ───────────────────────────────────────────────────────────────

    def rebuild_preview(self):
        try:
            self.project.write(self._preview_dir)
            self._face = FaceLoader(str(self._preview_dir), *self.preview_size)
            self._pstate = FaceState({}, self._face.expression_names)
            self._preview_err = ''
        except Exception as e:                       # noqa: BLE001
            self._face = None
            self._preview_err = str(e)
        self._dirty = False

    def render_preview(self, dt=0.0):
        if self._face is None or self._pstate is None:
            return None
        st = self._pstate
        if self.current in self._face.expression_names:
            st.expression = self.current
            st.prev_expression = self.current
            st.transition_t = 1.0
        st.mouth_open = self._preview_mouth
        if self._preview_play:
            st.update(dt)
        face_rgba = self._face.get_frame(st)
        mat = self._pmaterial.get_frame()
        layer = self._renderer.apply_material(face_rgba, mat)
        bg = self._renderer.solid_layer((0, 0, 0))
        return self._renderer.composite(bg, [layer])

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
        elif ev.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode((ev.w, ev.h), pygame.RESIZABLE)
            self.compute_layout()
        elif ev.type == pygame.KEYDOWN:
            self._on_key(ev)
        elif ev.type == pygame.MOUSEBUTTONDOWN:
            self._on_mouse_down(ev.pos, ev.button)
        elif ev.type == pygame.MOUSEBUTTONUP:
            self._on_mouse_up(ev.pos, ev.button)
        elif ev.type == pygame.MOUSEMOTION:
            self._on_mouse_move(ev.pos, ev.buttons)

    def _on_key(self, ev):
        if self.focus:                               # text entry mode
            if ev.key == pygame.K_RETURN:
                self._commit_text()
            elif ev.key == pygame.K_ESCAPE:
                self.focus = None; self.text_buf = ''
            elif ev.key == pygame.K_BACKSPACE:
                self.text_buf = self.text_buf[:-1]
            elif ev.unicode and ev.unicode.isprintable():
                self.text_buf += ev.unicode
            return

        mods = pygame.key.get_mods()
        if mods & pygame.KMOD_CTRL:
            if ev.key == pygame.K_z:
                self.do_undo()
            elif ev.key == pygame.K_y:
                self.do_redo()
            elif ev.key == pygame.K_s:
                self.do_save()
            return
        key = pygame.key.name(ev.key)
        keymap = {'p': 'pencil', 'e': 'eraser', 'g': 'bucket',
                  'k': 'eyedrop', 'l': 'line', 'r': 'rect'}
        if key in keymap:
            self.set_tool(keymap[key])
        elif key in ('1', '2', '3', '4'):
            self.brush = int(key)
        elif ev.key == pygame.K_LEFTBRACKET:
            self._step_expression(-1)
        elif ev.key == pygame.K_RIGHTBRACKET:
            self._step_expression(1)
        elif ev.key == pygame.K_ESCAPE:
            self._poly.clear(); self.region_tool = None
        elif ev.key == pygame.K_RETURN and self.region_tool and self.region_mode == 'poly':
            self._close_polygon()

    def _step_expression(self, d):
        i = (self.project.order.index(self.current) + d) % len(self.project.order)
        self.select_expression(self.project.order[i])

    def _commit_text(self):
        if self.focus == 'hex':
            txt = self.text_buf.lstrip('#')
            try:
                if len(txt) >= 6:
                    v = int(txt[:6], 16)
                    self.set_color(((v >> 16) & 255, (v >> 8) & 255, v & 255, 255))
                    self.status = f'colour #{txt[:6].upper()}'
            except ValueError:
                self.status = 'bad hex'
        elif self.focus == 'newexpr':
            self.add_expression(self.text_buf)
        self.focus = None
        self.text_buf = ''

    def _on_mouse_down(self, pos, button):
        # UI hit-tests first
        if self._hit_ui(pos, button):
            return
        if not self.rects['canvas'].collidepoint(pos):
            return
        px = self.screen_to_pixel(pos)
        if px is None:
            return
        if button == 3:                              # right-click = quick eyedrop
            c = C.pick(self.art, *px)
            if c:
                self.set_color(c)
            return
        if self.region_tool:
            self._region_down(px)
            return
        # Drawing tools
        if self.tool in ('pencil', 'eraser'):
            self.undo.record(self.current, self.art)
            self._paint(px)
            self._stroke_last = px
        elif self.tool == 'bucket':
            self.undo.record(self.current, self.art)
            C.bucket_fill(self.art, *px, self.color)
            self._dirty = True
        elif self.tool == 'eyedrop':
            c = C.pick(self.art, *px)
            if c:
                self.set_color(c)
        elif self.tool in ('line', 'rect'):
            self._anchor = px

    def _on_mouse_up(self, pos, button):
        px = self.screen_to_pixel(pos)
        if self.tool in ('line', 'rect') and self._anchor and px and not self.region_tool:
            self.undo.record(self.current, self.art)
            if self.tool == 'line':
                C.draw_line(self.art, *self._anchor, *px, self.color, self.brush)
            else:
                C.draw_rect(self.art, *self._anchor, *px, self.color, self.brush,
                            filled=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
            self._dirty = True
        elif self.region_tool and self.region_mode == 'rect' and self._anchor and px:
            self._set_rect_region(self._anchor, px)
        self._anchor = None
        self._stroke_last = None

    def _on_mouse_move(self, pos, buttons):
        self._hover = self.screen_to_pixel(pos)
        if buttons[0] and self._stroke_last and self._hover and \
                self.tool in ('pencil', 'eraser') and not self.region_tool:
            C.draw_line(self.art, *self._stroke_last, *self._hover,
                        self._paint_color(), self.brush)
            self._stroke_last = self._hover
            self._dirty = True

    def _paint_color(self):
        return C.TRANSPARENT if self.tool == 'eraser' else self.color

    def _paint(self, px):
        C.stamp(self.art, *px, self._paint_color(), self.brush)
        self._dirty = True

    # ── Region authoring ──────────────────────────────────────────────────────

    def _region_down(self, px):
        if self.region_mode == 'rect':
            self._anchor = px
        else:                                        # polygon
            if self._poly and abs(px[0] - self._poly[0][0]) <= 1 and \
                    abs(px[1] - self._poly[0][1]) <= 1 and len(self._poly) >= 3:
                self._close_polygon()
            else:
                self._poly.append(px)

    def _set_rect_region(self, a, b):
        x0, x1 = sorted((a[0], b[0]))
        y0, y1 = sorted((a[1], b[1]))
        self.project.regions[self.region_tool] = {
            'x': x0, 'y': y0, 'w': max(1, x1 - x0), 'h': max(1, y1 - y0)}
        self._dirty = True
        self.status = f'set {self.region_tool}'

    def _close_polygon(self):
        if len(self._poly) >= 3:
            self.project.regions[self.region_tool] = {
                'points': [[p[0], p[1]] for p in self._poly]}
            self._dirty = True
            self.status = f'set {self.region_tool} ({len(self._poly)}-pt polygon)'
        self._poly.clear()

    def _hit_ui(self, pos, button):
        for t, r in self.tool_rects.items():
            if r.collidepoint(pos):
                self.set_tool(t); return True
        for b, r in self.brush_rects.items():
            if r.collidepoint(pos):
                self.brush = b; return True
        for r, col in self.swatch_rects:
            if r.collidepoint(pos):
                self.set_color(col); return True
        if self.rects['hex'].collidepoint(pos):
            self.focus = 'hex'; self.text_buf = ''; return True
        for r, name in self.expr_rects:
            if r.collidepoint(pos):
                self.select_expression(name); return True
        if self.rects['add_expr'].collidepoint(pos):
            self.focus = 'newexpr'; self.text_buf = ''; self.status = 'type a name, Enter'; return True
        for rn, r in self.region_rects.items():
            if r.collidepoint(pos):
                self.toggle_region(rn); return True
        for m, r in self.mode_rects.items():
            if r.collidepoint(pos):
                self.region_mode = m; self._poly.clear(); return True
        if self.rects['clear_region'].collidepoint(pos):
            self.clear_region(); return True
        if self.rects['fit'].collidepoint(pos):
            self.cycle_fit(); return True
        if self.rects['scale_minus'].collidepoint(pos):
            self.adjust_scale(-0.25); return True
        if self.rects['scale_plus'].collidepoint(pos):
            self.adjust_scale(0.25); return True
        if self.rects['undo'].collidepoint(pos):
            self.do_undo(); return True
        if self.rects['redo'].collidepoint(pos):
            self.do_redo(); return True
        if self.rects['save'].collidepoint(pos):
            self.do_save(); return True
        if self.rects['mat'].collidepoint(pos):
            self.cycle_material(); return True
        if self.rects['play'].collidepoint(pos):
            self._preview_play = not self._preview_play; return True
        if self.rects['mouth'].collidepoint(pos):
            self._preview_mouth = 0.0 if self._preview_mouth > 0 else 1.0; return True
        return False

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _text(self, s, pos, color=INK, font=None, center=False):
        font = font or self.font
        surf = font.render(s, True, color)
        r = surf.get_rect()
        if center:
            r.center = pos
        else:
            r.topleft = pos
        self.screen.blit(surf, r)

    def _button(self, rect, label, active=False, font=None):
        pygame.draw.rect(self.screen, ACCENT if active else PANEL2, rect, border_radius=4)
        pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=4)
        self._text(label, rect.center, BG if active else INK,
                   font or self.small, center=True)

    def _surface_from_rgba(self, arr):
        arr = np.ascontiguousarray(arr)
        h, w = arr.shape[:2]
        return pygame.image.frombuffer(arr.tobytes(), (w, h), 'RGBA').convert_alpha()

    def _surface_from_rgb(self, arr):
        arr = np.ascontiguousarray(arr)
        h, w = arr.shape[:2]
        return pygame.image.frombuffer(arr.tobytes(), (w, h), 'RGB')

    def draw(self, dt=0.0):
        s = self.screen
        s.fill(BG)
        w, h = s.get_size()
        pygame.draw.rect(s, PANEL, (0, 0, self.left_w, h))
        pygame.draw.rect(s, PANEL, (w - self.right_w, 0, self.right_w, h))

        self._text('PROTOFACE EDITOR', (10, 8), ACCENT, self.small)

        for t, r in self.tool_rects.items():
            self._button(r, f'{t[:5]} {TOOL_KEYS[t]}', active=(self.tool == t and not self.region_tool))
        self._text('Brush', self.rects['brush_lbl'].topleft, MUTED, self.small)
        for b, r in self.brush_rects.items():
            self._button(r, str(b), active=(self.brush == b))

        self._text('Colour', self.rects['color_lbl'].topleft, MUTED, self.small)
        pygame.draw.rect(s, self.color[:3], self.rects['color_swatch'], border_radius=3)
        pygame.draw.rect(s, LINE, self.rects['color_swatch'], 1, border_radius=3)
        hexr = self.rects['hex']
        pygame.draw.rect(s, PANEL2, hexr, border_radius=3)
        pygame.draw.rect(s, ACCENT if self.focus == 'hex' else LINE, hexr, 1, border_radius=3)
        hx = ('#' + self.text_buf) if self.focus == 'hex' else \
             '#%02X%02X%02X' % self.color[:3]
        self._text(hx, (hexr.x + 6, hexr.y + 4), INK, self.small)
        for r, col in self.swatch_rects:
            pygame.draw.rect(s, col[:3], r)
            if tuple(col) == tuple(self.color):
                pygame.draw.rect(s, ACCENT, r, 2)

        self._text('Expressions', self.rects['expr_lbl'].topleft, MUTED, self.small)
        for r, name in self.expr_rects:
            self._button(r, name, active=(self.current == name))
        self._button(self.rects['add_expr'], '+ add expression',
                     active=(self.focus == 'newexpr'))

        self._text('Regions', self.rects['region_lbl'].topleft, MUTED, self.small)
        for rn, r in self.region_rects.items():
            lbl = {'eye_left': 'eyeL', 'eye_right': 'eyeR', 'mouth': 'mouth'}[rn]
            has = rn in self.project.regions
            self._button(r, ('•' if has else '') + lbl, active=(self.region_tool == rn))
        for m, r in self.mode_rects.items():
            self._button(r, m, active=(self.region_mode == m))
        self._button(self.rects['clear_region'], 'clear region')

        self._button(self.rects['fit'], f'fit: {self.project.fit}')
        self._button(self.rects['scale_minus'], '-')
        self._text(f'scale {self.project.scale:.2f}',
                   self.rects['scale_lbl'].center, INK, self.small, center=True)
        self._button(self.rects['scale_plus'], '+')

        self._button(self.rects['undo'], 'undo', active=self.undo.can_undo())
        self._button(self.rects['redo'], 'redo', active=self.undo.can_redo())
        self._button(self.rects['save'], 'SAVE', active=True)

        self._draw_canvas()
        self._draw_preview(dt)

        pygame.draw.rect(s, PANEL2, self.rects['status'], border_radius=3)
        self._text(self.status, (self.rects['status'].x + 6, self.rects['status'].y + 3),
                   MUTED, self.small)

    def _draw_canvas(self):
        s = self.screen
        area = self.rects['canvas']
        pygame.draw.rect(s, (16, 17, 20), area)
        zoom, ox, oy = self._canvas_geom()
        w, h = self.project.size
        # transparency checker
        chk = 8
        for yy in range(0, h * zoom, chk):
            for xx in range(0, w * zoom, chk):
                if ((xx // chk) + (yy // chk)) % 2 == 0:
                    pygame.draw.rect(s, (40, 42, 47), (ox + xx, oy + yy, chk, chk))
        art_surf = self._surface_from_rgba(self.art)
        s.blit(pygame.transform.scale(art_surf, (w * zoom, h * zoom)), (ox, oy))
        if zoom >= 8:
            for xx in range(w + 1):
                pygame.draw.line(s, (0, 0, 0, 40), (ox + xx * zoom, oy),
                                 (ox + xx * zoom, oy + h * zoom))
            for yy in range(h + 1):
                pygame.draw.line(s, (0, 0, 0, 40), (ox, oy + yy * zoom),
                                 (ox + w * zoom, oy + yy * zoom))
        # region overlays
        self._draw_region_overlays(ox, oy, zoom)
        # live line/rect preview
        if self._anchor and self._hover and not self.region_tool and self.tool in ('line', 'rect'):
            self._draw_shape_preview(ox, oy, zoom)
        # brush cursor
        if self._hover and not self.region_tool:
            r = self.brush // 2
            cur = pygame.Rect(ox + (self._hover[0] - r) * zoom,
                              oy + (self._hover[1] - r) * zoom,
                              self.brush * zoom, self.brush * zoom)
            pygame.draw.rect(s, ACCENT, cur, 1)

    def _draw_region_overlays(self, ox, oy, zoom):
        s = self.screen
        colors = {'eye_left': (0, 200, 255), 'eye_right': (0, 200, 255), 'mouth': (255, 120, 200)}
        for rn, region in self.project.regions.items():
            col = colors.get(rn, ACCENT)
            if 'points' in region:
                pts = [(ox + p[0] * zoom, oy + p[1] * zoom) for p in region['points']]
                if len(pts) >= 2:
                    pygame.draw.lines(s, col, True, pts, 1)
            else:
                r = pygame.Rect(ox + region['x'] * zoom, oy + region['y'] * zoom,
                                region['w'] * zoom, region['h'] * zoom)
                pygame.draw.rect(s, col, r, 1)
        # in-progress polygon
        if self._poly and self.region_tool:
            pts = [(ox + p[0] * zoom, oy + p[1] * zoom) for p in self._poly]
            for p in pts:
                pygame.draw.circle(s, WARN, p, 3)
            if len(pts) >= 2:
                pygame.draw.lines(s, WARN, False, pts, 1)

    def _draw_shape_preview(self, ox, oy, zoom):
        s = self.screen
        a, b = self._anchor, self._hover
        if self.tool == 'line':
            pygame.draw.line(s, self.color[:3],
                             (ox + a[0] * zoom + zoom // 2, oy + a[1] * zoom + zoom // 2),
                             (ox + b[0] * zoom + zoom // 2, oy + b[1] * zoom + zoom // 2), 1)
        else:
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            pygame.draw.rect(s, self.color[:3],
                             (ox + x0 * zoom, oy + y0 * zoom,
                              (x1 - x0 + 1) * zoom, (y1 - y0 + 1) * zoom), 1)

    def _draw_preview(self, dt):
        s = self.screen
        if self._dirty:
            self.rebuild_preview()
        self._text('LIVE PREVIEW', (self.rects['preview'].x, self.rects['preview'].y - 18),
                   ACCENT, self.small)
        area = self.rects['preview']
        pygame.draw.rect(s, (10, 11, 13), area)
        frame = self.render_preview(dt)
        if frame is not None:
            surf = self._surface_from_rgb(frame)
            ph, pw = frame.shape[:2]
            z = max(1, min(area.w // pw, area.h // ph))
            img = pygame.transform.scale(surf, (pw * z, ph * z))
            s.blit(img, (area.x + (area.w - pw * z) // 2, area.y + (area.h - ph * z) // 2))
        elif self._preview_err:
            self._text('preview error', (area.x + 6, area.y + 6), WARN, self.small)
        self._button(self.rects['mat'], f'mat: {PREVIEW_MATERIALS[self._mat_idx][:16]}')
        self._button(self.rects['play'], 'pause' if self._preview_play else 'play',
                     active=self._preview_play)
        self._button(self.rects['mouth'], 'mouth', active=self._preview_mouth > 0)
        help_lines = [
            'Tools: P pencil E eraser G fill',
            '  K eyedrop L line R rect',
            'Shift+drag rect = filled',
            '1-4 brush   [ ] change expr',
            'Right-click = pick colour',
            'Region: pick eyeL/eyeR/mouth,',
            '  rect=drag, poly=click+close',
            'Ctrl+Z/Y undo/redo  Ctrl+S save',
        ]
        hy = self.rects['help'].y
        for ln in help_lines:
            self._text(ln, (self.rects['help'].x, hy), MUTED, self.small)
            hy += 18

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            for ev in pygame.event.get():
                self.handle_event(ev)
            self.draw(dt)
            pygame.display.flip()
        pygame.quit()
