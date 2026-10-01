"""The ZBrush-style popup palette.

A modal operator draws a grid of large thumbnails over the 3D viewport with
the ``gpu`` module:

* **Brushes** / **Alphas** tabs (Tab switches),
* a *Quick Pick* row with favorites and recently used items,
* an A-Z letter bar and type-to-search,
* click to pick, Shift+Click to pick and keep the palette open,
  Ctrl+Click to toggle a favorite, Esc / right click / click outside to close.

Layout and hit testing are plain Python (``PaletteLayout``) so they can be
tested without a GPU.
"""

import math
import re
import time
import traceback

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from . import alphas, brushes, thumbs
from . import prefs as _prefs

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ#"

COL_BG = (0.105, 0.105, 0.11, 0.97)
COL_SHADOW = (0.0, 0.0, 0.0, 0.35)
COL_HEADER = (0.065, 0.065, 0.07, 1.0)
COL_BORDER = (0.28, 0.28, 0.3, 1.0)
COL_CELL = (0.16, 0.16, 0.17, 1.0)
COL_CELL_HOVER = (0.27, 0.27, 0.29, 1.0)
COL_ACCENT = (1.0, 0.56, 0.13, 1.0)
COL_FAV = (1.0, 0.8, 0.25, 1.0)
COL_TEXT = (0.9, 0.9, 0.9, 1.0)
COL_TEXT_DIM = (0.55, 0.55, 0.58, 1.0)
COL_TEXT_OFF = (0.32, 0.32, 0.34, 1.0)
COL_CHIP = (0.2, 0.2, 0.21, 1.0)
COL_CHIP_ON = (0.36, 0.25, 0.12, 1.0)

TAB_LABELS = (('BRUSHES', "Brushes"), ('ALPHAS', "Alphas"))
CHIP_LABELS = tuple((ident, label) for ident, label, _desc in _prefs.MAP_MODES)
STROKE_LABELS = (('SPACE', "Space"), ('DRAG_DOT', "Drag Dot"), ('ANCHORED', "DragRect"))

# Bottom button rows per tab: (kind, ident, label).
STROKE_ROW = [('STROKE', ident, label) for ident, label in STROKE_LABELS] + [
    ('SAVE_BRUSH', None, "Save as New Brush…")]
BUTTON_ROWS = {
    'BRUSHES': [STROKE_ROW],
    'ALPHAS': [
        [('CHIP', ident, label) for ident, label in CHIP_LABELS] + [('FOLDERS', None, "Add Folder…")],
        STROKE_ROW,
    ],
}

# Footer help shown while hovering a button.
BUTTON_HELP = {
    ('STROKE', 'SPACE'): "Space: normal continuous stroke",
    ('STROKE', 'DRAG_DOT'): "Drag Dot: one stamp you can slide into place before releasing",
    ('STROKE', 'ANCHORED'): "DragRect: click and drag one stamp – distance sets size (and depth), direction sets rotation",
    ('SAVE_BRUSH', None): "Save the current brush (with its alpha and settings) into an asset library",
    ('FOLDERS', None): "Add a folder of alpha images",
    ('CHIP', 'VIEW_PLANE'): "Alpha projected from the view",
    ('CHIP', 'AREA_PLANE'): "Alpha follows the surface under the brush",
    ('CHIP', 'TILED'): "Alpha repeats across the surface",
    ('CHIP', 'RANDOM'): "Alpha with random offset and rotation per dab",
    ('CHIP', 'STENCIL'): "Alpha used as a screen-space stencil",
}

_open_palette = None


class Box:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    def contains(self, px, py):
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def __repr__(self):
        return "Box(%.0f, %.0f, %.0f, %.0f)" % (self.x, self.y, self.w, self.h)


def letter_of(name):
    ch = name[:1].upper()
    return ch if ch in LETTERS[:-1] else "#"


class PaletteLayout:
    """Geometry of the palette in region pixel coordinates (origin bottom-left)."""

    def __init__(self, region_w, region_h, anchor, n_items, n_quick, tab, scale,
                 thumb_size=72, columns=12, show_labels=True, scroll_row=0, top=None, bounds=None):
        # ``bounds`` (x0, y0, x1, y1) is the part of the region not covered by overlapping
        # header / toolbar / sidebar regions; the panel stays inside it.
        bx0, by0, bx1, by1 = bounds if bounds else (0, 0, region_w, region_h)
        region_w, region_h = bx1 - bx0, by1 - by0
        s = scale
        self.scale = s
        self.pad = pad = round(10 * s)
        self.gap = gap = round(6 * s)
        self.cell = cell = round(thumb_size * s)
        self.label_h = label_h = round(15 * s) if show_labels else 0
        margin = round(8 * s)

        cols = int((region_w - 2 * margin - 2 * pad + gap) // (cell + gap))
        self.cols = cols = max(1, min(columns, cols))
        self.width = width = cols * cell + (cols - 1) * gap + 2 * pad

        self.header_h = header_h = round(30 * s)
        self.letters_h = letters_h = round(20 * s)
        self.qcell = qcell = round(cell * 0.72)
        self.qcols = max(1, int((width - 2 * pad + gap) // (qcell + gap)))
        self.n_quick = n_quick = min(n_quick, self.qcols)
        self.quick_title_h = round(16 * s)
        self.quick_h = quick_h = (self.quick_title_h + qcell + gap) if n_quick else 0
        self.button_row_h = round(28 * s)
        button_rows = BUTTON_ROWS.get(tab, [])
        self.chips_h = chips_h = self.button_row_h * len(button_rows)
        self.footer_h = footer_h = round(34 * s)
        self.row_h = row_h = cell + label_h + gap

        self.rows_total = rows_total = max(1, math.ceil(n_items / cols))
        fixed = header_h + letters_h + quick_h + chips_h + footer_h + 2 * pad
        avail = region_h - 2 * margin - fixed
        self.visible_rows = visible_rows = max(1, min(rows_total, int((avail + gap) // row_h)))
        self.grid_h = grid_h = visible_rows * row_h - gap
        self.height = height = fixed + grid_h

        ax, ay = anchor[0] - bx0, anchor[1] - by0
        x = min(max(ax - width / 2, margin), max(margin, region_w - width - margin)) + bx0
        if top is None:
            # First layout: centre on the mouse. Afterwards the caller passes the top edge
            # back in, so the tabs and letter bar stay put while the list grows or shrinks.
            top = ay + height / 2 + by0
        top = min(max(top - by0, height + margin), region_h - margin) + by0
        self.panel = Box(round(x), round(top - height), width, height)
        px, py = self.panel.x, self.panel.y

        y = py + height
        self.header = Box(px, y - header_h, width, header_h)
        y -= header_h
        self.tabs = []
        tx = px + pad
        for ident, label in TAB_LABELS:
            tw = round((len(label) * 8 + 26) * s)
            self.tabs.append((ident, Box(tx, self.header.y, tw, header_h)))
            tx += tw
        self.close = Box(px + width - header_h, self.header.y, header_h, header_h)
        self.search = Box(tx + gap, self.header.y + round(5 * s),
                          max(0, self.close.x - gap - (tx + gap)), header_h - round(10 * s))

        y -= pad // 2
        self.letters = []
        lw = (width - 2 * pad) / len(LETTERS)
        for i, ch in enumerate(LETTERS):
            self.letters.append((ch, Box(px + pad + i * lw, y - letters_h, lw, letters_h)))
        y -= letters_h + pad // 2

        self.quick_title_y = y - self.quick_title_h
        self.quick = []
        if n_quick:
            qy = y - self.quick_title_h - qcell
            for i in range(n_quick):
                self.quick.append(Box(px + pad + i * (qcell + gap), qy, qcell, qcell))
            y -= quick_h

        self.grid = Box(px + pad, y - grid_h, width - 2 * pad, grid_h)
        y -= grid_h + pad

        # Buttons: list of (kind, ident, label, box).
        self.buttons = []
        for row in button_rows:
            bw = (width - 2 * pad - (len(row) - 1) * gap) / len(row)
            by = y - self.button_row_h + round(4 * s)
            for i, (kind, ident, label) in enumerate(row):
                box = Box(px + pad + i * (bw + gap), by, bw, self.button_row_h - round(6 * s))
                self.buttons.append((kind, ident, label, box))
            y -= self.button_row_h

        self.footer = Box(px, py, width, footer_h)

        # The grid scrolls by whole rows, so a row is always either fully visible or hidden.
        self.max_scroll_row = max(0, rows_total - visible_rows)
        self.scroll_row = min(max(scroll_row, 0), self.max_scroll_row)

    def button(self, kind, ident=None):
        """Box of the button ``(kind, ident)``, or None."""
        return next((box for k, i, _l, box in self.buttons if k == kind and i == ident), None)

    def item_box(self, index):
        """Thumbnail square of grid item ``index`` (may lie outside the visible grid)."""
        row, col = divmod(index, self.cols)
        x = self.grid.x + col * (self.cell + self.gap)
        top = self.grid.y + self.grid.h - (row - self.scroll_row) * self.row_h
        return Box(x, top - self.cell, self.cell, self.cell)

    def visible_range(self, n_items):
        first = self.scroll_row * self.cols
        return range(first, min(n_items, first + self.visible_rows * self.cols))

    def row_of(self, index):
        return index // self.cols

    def hit(self, mx, my, n_items):
        if not self.panel.contains(mx, my):
            return None
        if self.close.contains(mx, my):
            return ('CLOSE', None)
        for ident, box in self.tabs:
            if box.contains(mx, my):
                return ('TAB', ident)
        for ch, box in self.letters:
            if box.contains(mx, my):
                return ('LETTER', ch)
        for i, box in enumerate(self.quick):
            if box.contains(mx, my):
                return ('QUICK', i)
        if self.grid.contains(mx, my):
            for i in self.visible_range(n_items):
                box = self.item_box(i)
                cell = Box(box.x, box.y - self.label_h, box.w + self.gap, box.h + self.label_h + self.gap)
                if cell.contains(mx, my):
                    return ('ITEM', i)
        for kind, ident, _label, box in self.buttons:
            if box.contains(mx, my):
                return (kind, ident)
        return ('PANEL', None)


OVERLAP_SIDE = {'UI', 'TOOLS'}
OVERLAP_BARS = {'HEADER', 'TOOL_HEADER', 'ASSET_SHELF', 'ASSET_SHELF_HEADER', 'FOOTER'}


def free_bounds(area, region):
    """Part of ``region`` (region coordinates) not covered by overlapping regions.

    With "Region Overlap" on, the header, tool header, toolbar and sidebar are drawn on top of
    the 3D viewport; the palette must avoid them or it ends up hidden behind them.
    """
    x0, y0 = region.x, region.y
    x1, y1 = x0 + region.width, y0 + region.height
    for other in getattr(area, "regions", ()):
        if other.type not in OVERLAP_SIDE | OVERLAP_BARS or other.width <= 1 or other.height <= 1:
            continue
        ox0, oy0 = other.x, other.y
        ox1, oy1 = ox0 + other.width, oy0 + other.height
        if ox1 <= x0 or ox0 >= x1 or oy1 <= y0 or oy0 >= y1:
            continue  # not overlapping (region overlap is off or it is elsewhere)
        if other.type in OVERLAP_SIDE:
            if (ox0 + ox1) / 2 > (x0 + x1) / 2:
                x1 = min(x1, ox0)
            else:
                x0 = max(x0, ox1)
        else:
            if (oy0 + oy1) / 2 > (y0 + y1) / 2:
                y1 = min(y1, oy0)
            else:
                y0 = max(y0, oy1)
    if x1 - x0 < 200 or y1 - y0 < 150:  # too little room left: use the whole region
        return (0, 0, region.width, region.height)
    return (x0 - region.x, y0 - region.y, x1 - region.x, y1 - region.y)


def filter_items(items, query, prefix_only=False):
    """Search: prefix matches first, then word-prefix matches, then substrings."""
    if not query:
        return list(items)
    q = query.lower()
    scored = []
    for item in items:
        name = item.name.lower()
        if q == "#":
            if letter_of(item.name) == "#":
                scored.append((0, name, item))
            continue
        if name.startswith(q):
            score = 0
        elif prefix_only:
            continue
        elif any(w.startswith(q) for w in re.split(r"[\s/_\-.()]+", name)):
            score = 1
        elif q in name:
            score = 2
        else:
            continue
        scored.append((score, name, item))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in scored]


# ---------------------------------------------------------------------------
# Drawing helpers


class Painter:
    def __init__(self):
        import gpu
        from gpu_extras.batch import batch_for_shader
        self.gpu = gpu
        self.batch_for_shader = batch_for_shader
        self.color_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        self.image_shader = gpu.shader.from_builtin('IMAGE')
        self.rects = {}

    def rect(self, box, color):
        self.rects.setdefault(color, []).append(box)

    def outline(self, box, color, t=1.0):
        self.rect(Box(box.x, box.y, box.w, t), color)
        self.rect(Box(box.x, box.y + box.h - t, box.w, t), color)
        self.rect(Box(box.x, box.y + t, t, box.h - 2 * t), color)
        self.rect(Box(box.x + box.w - t, box.y + t, t, box.h - 2 * t), color)

    def flush(self):
        # Text drawing (blf) resets the blend mode, so set it before every batch.
        self.gpu.state.blend_set('ALPHA')
        sh = self.color_shader
        for color, boxes in self.rects.items():
            pos = []
            for b in boxes:
                x0, y0, x1, y1 = b.x, b.y, b.x + b.w, b.y + b.h
                pos += [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
            batch = self.batch_for_shader(sh, 'TRIS', {"pos": pos})
            sh.bind()
            sh.uniform_float("color", color)
            batch.draw(sh)
        self.rects.clear()

    def image(self, box, texture):
        self.gpu.state.blend_set('ALPHA')
        sh = self.image_shader
        x0, y0, x1, y1 = box.x, box.y, box.x + box.w, box.y + box.h
        batch = self.batch_for_shader(sh, 'TRIS', {
            "pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)],
            "texCoord": [(0, 0), (1, 0), (1, 1), (0, 0), (1, 1), (0, 1)],
        })
        sh.bind()
        sh.uniform_sampler("image", texture)
        batch.draw(sh)


def text_width(txt, size):
    import blf
    blf.size(0, size)
    return blf.dimensions(0, txt)[0]


def fit_text(txt, size, max_w):
    if text_width(txt, size) <= max_w:
        return txt
    while txt and text_width(txt + "…", size) > max_w:
        txt = txt[:-1]
    return txt + "…" if txt else ""


def draw_text(txt, x, y, size, color, align='LEFT', max_w=None):
    import blf
    if max_w is not None:
        txt = fit_text(txt, size, max_w)
    blf.size(0, size)
    w = blf.dimensions(0, txt)[0]
    if align == 'CENTER':
        x -= w / 2
    elif align == 'RIGHT':
        x -= w
    blf.color(0, *color)
    blf.position(0, round(x), round(y), 0)
    blf.draw(0, txt)


def _draw_callback(palette):
    try:
        if bpy.context.region != palette.region:
            return
        palette.draw_palette()
    except Exception:
        if not palette.draw_error_reported:
            palette.draw_error_reported = True
            traceback.print_exc()


# ---------------------------------------------------------------------------
# Operator


class BPAL_OT_palette(Operator):
    """Open the brush / alpha palette under the mouse"""
    bl_idname = "brush_palette.open"
    bl_label = "Brush & Alpha Palette"
    bl_options = {'REGISTER'}

    tab: EnumProperty(
        name="Tab",
        items=(('BRUSHES', "Brushes", ""), ('ALPHAS', "Alphas", ""), ('LAST', "Last Used", "")),
        default='BRUSHES',
    )

    last_tab = 'BRUSHES'

    @classmethod
    def poll(cls, context):
        return brushes.supported(context)

    # -- setup -------------------------------------------------------------

    def invoke(self, context, event):
        global _open_palette
        if _open_palette is not None:
            _open_palette.request_close = True
            return {'CANCELLED'}

        area = context.area
        if area is None or area.type != 'VIEW_3D':
            area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
            if area is None:
                self.report({'WARNING'}, "The palette needs a 3D Viewport")
                return {'CANCELLED'}
        region = next((r for r in area.regions if r.type == 'WINDOW'
                       and r.x <= event.mouse_x < r.x + r.width
                       and r.y <= event.mouse_y < r.y + r.height), None)
        if region is None:
            region = max((r for r in area.regions if r.type == 'WINDOW'), key=lambda r: r.width * r.height)

        self.area = area
        self.region = region
        self.region_ptr = region.as_pointer()
        self.prefs = _prefs.get_prefs(context)
        self.mouse = self.region_mouse(event)
        self.anchor = self.mouse if region.x <= event.mouse_x < region.x + region.width \
            and region.y <= event.mouse_y < region.y + region.height \
            else (region.width / 2, region.height / 2)
        self.search = ""
        self.prefix_only = False
        self.scroll_row = 0
        self.panel_top = None
        self.hover = None
        self.kbd_index = None
        self.message = ""
        self.request_close = False
        self.draw_error_reported = False
        self.invoke_key = (event.type, event.ctrl, event.alt, event.shift) \
            if event.type not in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'} else None
        self.opened_at = time.time()

        tab = BPAL_OT_palette.last_tab if self.tab == 'LAST' else self.tab
        if tab == 'ALPHAS' and not alphas.supported(context):
            tab = 'BRUSHES'
        self.current_tab = tab
        self.reload(context)

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (self,), 'WINDOW', 'POST_PIXEL')
        self._timer = context.window_manager.event_timer_add(0.02, window=context.window)
        context.window_manager.modal_handler_add(self)
        _open_palette = self
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    def region_alive(self, context):
        """True while the palette's region still exists (screen layouts can change under us).

        Compared by pointer so a freed region is never dereferenced.
        """
        screen = context.window.screen if context.window else None
        if screen is None:
            return False
        return any(r.as_pointer() == self.region_ptr for a in screen.areas for r in a.regions)

    def region_mouse(self, event):
        return (event.mouse_x - self.region.x, event.mouse_y - self.region.y)

    def reload(self, context):
        if self.current_tab == 'BRUSHES':
            self.all_items = brushes.collect(context, self.prefs)
            self.active_key = brushes.active_key(context)
        else:
            self.all_items = [alphas.NONE_ITEM] + alphas.collect(self.prefs)
            self.active_key = alphas.active_key(context)
        self.by_key = {item.key: item for item in self.all_items}
        self.letters_present = {letter_of(i.name) for i in self.all_items if i.key != alphas.NONE_KEY}
        self.refresh_filter()

    def refresh_filter(self):
        self.items = filter_items(self.all_items, self.search, self.prefix_only)
        if self.search:
            self.items = [i for i in self.items if i.key != alphas.NONE_KEY]
        favs = _prefs.favorites(self.prefs)
        self.favorites = set(favs)
        quick = []
        if not self.search:
            for key in favs + _prefs.recents(self.prefs):
                item = self.by_key.get(key)
                if item is not None and item not in quick:
                    quick.append(item)
        self.quick_items = quick
        self.scroll_row = 0
        self.kbd_index = 0 if self.search and self.items else None
        # Load what is on screen first.
        order = self.quick_items + self.items + self.all_items
        seen = set()
        self.pending = []
        for item in order:
            if item.key in seen or item.key == alphas.NONE_KEY or thumbs.has(item.thumb_key):
                continue
            seen.add(item.key)
            self.pending.append(item)

    def compute_layout(self):
        ctx = bpy.context
        scale = ctx.preferences.system.ui_scale or 1.0  # 0 in background mode
        lay = PaletteLayout(self.region.width, self.region.height, self.anchor,
                            len(self.items), len(self.quick_items), self.current_tab, scale,
                            self.prefs.thumb_size, self.prefs.columns, self.prefs.show_labels, self.scroll_row,
                            self.panel_top, free_bounds(self.area, self.region))
        self.scroll_row = lay.scroll_row
        if self.panel_top is None:
            self.panel_top = lay.panel.y + lay.panel.h
        return lay

    # -- teardown ----------------------------------------------------------

    def finish(self, context, result=None):
        global _open_palette
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        if getattr(self, "_timer", None) is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if _open_palette is self:
            _open_palette = None
        BPAL_OT_palette.last_tab = self.current_tab
        if self.region_alive(context):
            self.area.tag_redraw()
        return result or {'CANCELLED'}

    def cancel(self, context):
        self.finish(context)

    # -- picking -----------------------------------------------------------

    def pick(self, context, item, keep_open):
        try:
            if self.current_tab == 'BRUSHES':
                if not brushes.activate(context, item):
                    raise RuntimeError("Could not activate %s" % item.name)
                self.message = item.name
            else:
                self.message = alphas.apply(context, item, self.prefs)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            self.message = str(ex)
            return {'RUNNING_MODAL'}
        if item.key != alphas.NONE_KEY:
            _prefs.push_recent(self.prefs, item.key)
        if self.current_tab == 'ALPHAS' and item.key != alphas.NONE_KEY:
            self.report({'INFO'}, self.message)
        if keep_open or not self.prefs.close_on_pick:
            # A local brush copy may have been created: refresh everything.
            self.reload_keep_search(context)
            return {'RUNNING_MODAL'}
        return self.finish(context, {'FINISHED'})

    def reload_keep_search(self, context):
        search, prefix, scroll_row = self.search, self.prefix_only, self.scroll_row
        self.reload(context)
        self.search, self.prefix_only = search, prefix
        self.refresh_filter()
        self.scroll_row = scroll_row

    def switch_tab(self, context, tab):
        if tab == self.current_tab:
            return
        if tab == 'ALPHAS' and not alphas.supported(context):
            self.message = "Alphas are available in Sculpt and Texture Paint mode"
            return
        self.current_tab = tab
        self.search = ""
        self.prefix_only = False
        self.reload(context)

    # -- events ------------------------------------------------------------

    def load_pending(self, budget=0.03):
        if not self.pending:
            return False
        start = time.perf_counter()
        loader = brushes.load_thumb if self.current_tab == 'BRUSHES' else alphas.load_thumb
        loaded = False
        while self.pending and time.perf_counter() - start < budget:
            item = self.pending.pop(0)
            loader(item)
            loaded = True
        return loaded

    def modal(self, context, event):
        if not self.region_alive(context) or self.request_close:
            return self.finish(context)

        etype, value = event.type, event.value
        if etype == 'TIMER':
            if self.load_pending():
                self.area.tag_redraw()
            return {'PASS_THROUGH'}

        self.area.tag_redraw()
        self.mouse = self.region_mouse(event)
        lay = self.compute_layout()

        if etype in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.hover = lay.hit(*self.mouse, len(self.items))
            if self.hover and self.hover[0] in {'ITEM', 'QUICK'}:
                self.kbd_index = None
            return {'RUNNING_MODAL'}

        if etype in {'MIDDLEMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE'} or etype.startswith('NDOF'):
            return {'PASS_THROUGH'}
        if etype == 'WINDOW_DEACTIVATE':
            return self.finish(context)

        if value == 'PRESS' and self.invoke_key and time.time() - self.opened_at > 0.15 and \
                (etype, event.ctrl, event.alt, event.shift) == self.invoke_key:
            return self.finish(context)

        if etype in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            direction = -1 if etype == 'WHEELUPMOUSE' else 1
            if event.ctrl and self.prefs is not _prefs._Defaults:
                self.prefs.thumb_size = max(32, min(192, self.prefs.thumb_size - direction * 8))
            else:
                self.scroll_row = max(0, min(lay.max_scroll_row, self.scroll_row + direction))
            return {'RUNNING_MODAL'}

        if value != 'PRESS':
            return {'RUNNING_MODAL'}

        if etype == 'LEFTMOUSE':
            return self.click(context, event, lay.hit(*self.mouse, len(self.items)))
        if etype in {'RIGHTMOUSE', 'ESC'}:
            if etype == 'ESC' and self.search:
                self.search = ""
                self.prefix_only = False
                self.refresh_filter()
                return {'RUNNING_MODAL'}
            return self.finish(context)
        if etype == 'TAB':
            self.switch_tab(context, 'ALPHAS' if self.current_tab == 'BRUSHES' else 'BRUSHES')
            return {'RUNNING_MODAL'}
        if etype in {'RET', 'NUMPAD_ENTER'}:
            index = self.kbd_index
            if index is None and self.hover and self.hover[0] == 'ITEM':
                index = self.hover[1]
            if index is None and self.items:
                index = 0
            if index is not None and index < len(self.items):
                return self.pick(context, self.items[index], event.shift)
            return {'RUNNING_MODAL'}
        if etype in {'LEFT_ARROW', 'RIGHT_ARROW', 'UP_ARROW', 'DOWN_ARROW'}:
            self.move_cursor(lay, etype)
            return {'RUNNING_MODAL'}
        if etype == 'BACK_SPACE':
            self.search = "" if event.ctrl else self.search[:-1]
            self.prefix_only = False
            self.refresh_filter()
            return {'RUNNING_MODAL'}
        if event.unicode and event.unicode.isprintable() and not (event.ctrl or event.alt or event.oskey):
            if self.prefix_only:
                self.search = ""
            self.search += event.unicode
            self.prefix_only = False
            self.refresh_filter()
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    def move_cursor(self, lay, etype):
        if not self.items:
            return
        index = self.kbd_index
        if index is None:
            index = self.hover[1] if self.hover and self.hover[0] == 'ITEM' else 0
        else:
            step = {'LEFT_ARROW': -1, 'RIGHT_ARROW': 1, 'UP_ARROW': -lay.cols, 'DOWN_ARROW': lay.cols}[etype]
            index = min(max(index + step, 0), len(self.items) - 1)
        self.kbd_index = index
        row = lay.row_of(index)
        if row < self.scroll_row:
            self.scroll_row = row
        elif row >= self.scroll_row + lay.visible_rows:
            self.scroll_row = row - lay.visible_rows + 1

    def click(self, context, event, hit):
        if hit is None or hit[0] == 'CLOSE':
            return self.finish(context)
        kind, value = hit
        if kind in {'ITEM', 'QUICK'}:
            item = self.items[value] if kind == 'ITEM' else self.quick_items[value]
            if event.ctrl:
                if item.key != alphas.NONE_KEY:
                    _prefs.toggle_favorite(self.prefs, item.key)
                    scroll_row = self.scroll_row
                    self.refresh_filter()
                    self.scroll_row = scroll_row
                return {'RUNNING_MODAL'}
            return self.pick(context, item, event.shift)
        if kind == 'TAB':
            self.switch_tab(context, value)
        elif kind == 'LETTER':
            if self.prefix_only and self.search.upper() == value:
                self.search, self.prefix_only = "", False
            elif value in self.letters_present:
                self.search, self.prefix_only = value.lower(), True
            self.refresh_filter()
        elif kind == 'CHIP':
            if self.prefs is not _prefs._Defaults:
                self.prefs.alpha_map_mode = value
            if alphas.set_mapping(context, value):
                self.message = "Alpha mapping: " + value.replace("_", " ").title()
            else:
                self.message = "Default mapping for new alphas: " + value.replace("_", " ").title()
        elif kind == 'STROKE':
            if brushes.set_stroke(context, value):
                self.message = dict(STROKE_LABELS)[value] + " stroke on " + brushes.active_brush(context).name
            else:
                self.message = "This brush does not support that stroke"
        elif kind == 'SAVE_BRUSH':
            self.finish(context)
            bpy.ops.brush.asset_save_as('INVOKE_DEFAULT')
            return {'FINISHED'}
        elif kind == 'FOLDERS':
            self.finish(context)
            bpy.ops.brush_palette.add_alpha_folder('INVOKE_DEFAULT')
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    # -- drawing -----------------------------------------------------------

    def draw_palette(self):
        import gpu

        lay = self.compute_layout()
        s = lay.scale
        p = Painter()
        font = round(11 * s)
        small = round(10 * s)
        hover_kind, hover_value = self.hover if self.hover else (None, None)

        gpu.state.blend_set('ALPHA')

        # Panel, shadow, header.
        panel = lay.panel
        sh = round(6 * s)
        p.rect(Box(panel.x + sh, panel.y - sh, panel.w, panel.h), COL_SHADOW)
        p.rect(panel, COL_BG)
        p.rect(lay.header, COL_HEADER)
        p.rect(lay.footer, COL_HEADER)
        for ident, box in lay.tabs:
            if ident == self.current_tab:
                p.rect(Box(box.x, box.y, box.w, round(2 * s)), COL_ACCENT)
            elif hover_kind == 'TAB' and hover_value == ident:
                p.rect(box, COL_CELL)
        p.rect(lay.search, COL_CELL)
        if hover_kind == 'CLOSE':
            p.rect(lay.close, (0.55, 0.16, 0.14, 1.0))
        p.outline(panel, COL_BORDER)

        for ch, box in lay.letters:
            active = self.prefix_only and self.search.upper() == ch
            if active:
                p.rect(box, COL_CHIP_ON)
            elif hover_kind == 'LETTER' and hover_value == ch and ch in self.letters_present:
                p.rect(box, COL_CELL)

        grid_cells = [(i, lay.item_box(i)) for i in lay.visible_range(len(self.items))]

        for i, box in enumerate(lay.quick):
            hovered = hover_kind == 'QUICK' and hover_value == i
            p.rect(box, COL_CELL_HOVER if hovered else COL_CELL)
        for i, box in grid_cells:
            hovered = (hover_kind == 'ITEM' and hover_value == i) or self.kbd_index == i
            p.rect(box, COL_CELL_HOVER if hovered else COL_CELL)

        button_on = self.button_states()
        for kind, ident, _label, box in lay.buttons:
            hovered = hover_kind == kind and hover_value == ident
            on = button_on.get((kind, ident), False)
            p.rect(box, COL_CHIP_ON if on else (COL_CELL_HOVER if hovered else COL_CHIP))
        p.flush()

        # Thumbnails.
        inset = round(3 * s)
        for i, box in enumerate(lay.quick):
            self.draw_thumb(p, self.quick_items[i], box, inset)
        for i, box in grid_cells:
            self.draw_thumb(p, self.items[i], box, inset)

        # Outlines for active / hovered / favorite.
        for i, box in grid_cells:
            self.draw_marks(p, self.items[i], box, s,
                            (hover_kind == 'ITEM' and hover_value == i) or self.kbd_index == i)
        p.flush()
        if lay.label_h:
            for i, box in grid_cells:
                item = self.items[i]
                color = COL_ACCENT if item.key == self.active_key else COL_TEXT
                draw_text(item.name, box.x + box.w / 2, box.y - lay.label_h + round(3 * s),
                          small, color, 'CENTER', box.w + lay.gap - 2)
        for i, box in grid_cells:
            if self.items[i].key in self.favorites:
                draw_text("★", box.x + box.w - round(4 * s), box.y + box.h - round(13 * s),
                          round(11 * s), COL_FAV, 'RIGHT')

        for i, box in enumerate(lay.quick):
            self.draw_marks(p, self.quick_items[i], box, s, hover_kind == 'QUICK' and hover_value == i)
        p.flush()

        if lay.max_scroll_row > 0:
            track = Box(lay.panel.x + lay.panel.w - round(6 * s), lay.grid.y, round(3 * s), lay.grid.h)
            frac = lay.visible_rows / lay.rows_total
            th = max(round(20 * s), track.h * frac)
            ty = track.y + (track.h - th) * (1 - lay.scroll_row / lay.max_scroll_row)
            p.rect(track, COL_CELL)
            p.rect(Box(track.x, ty, track.w, th), COL_TEXT_DIM)
            p.flush()

        # Text.
        mid = lambda box: box.y + box.h / 2 - font * 0.35
        for ident, box in lay.tabs:
            label = dict(TAB_LABELS)[ident]
            enabled = ident == 'BRUSHES' or alphas.supported(bpy.context)
            color = COL_TEXT if ident == self.current_tab else (COL_TEXT_DIM if enabled else COL_TEXT_OFF)
            draw_text(label, box.x + box.w / 2, mid(box), round(12 * s), color, 'CENTER')
        if self.search:
            query = self.search.upper() + "…" if self.prefix_only else self.search
            draw_text(query, lay.search.x + round(6 * s), mid(lay.search), font, COL_TEXT,
                      max_w=lay.search.w - round(60 * s))
        else:
            draw_text("Type to search…", lay.search.x + round(6 * s), mid(lay.search), font, COL_TEXT_OFF,
                      max_w=lay.search.w - round(60 * s))
        count = "%d" % len(self.items) if not self.search else "%d / %d" % (len(self.items), len(self.all_items))
        draw_text(count, lay.search.x + lay.search.w - round(6 * s), mid(lay.search), small, COL_TEXT_DIM, 'RIGHT')
        draw_text("×", lay.close.x + lay.close.w / 2, mid(lay.close) - round(1 * s), round(16 * s), COL_TEXT, 'CENTER')

        for ch, box in lay.letters:
            if self.prefix_only and self.search.upper() == ch:
                color = COL_ACCENT
            elif ch in self.letters_present:
                color = COL_TEXT
            else:
                color = COL_TEXT_OFF
            draw_text(ch, box.x + box.w / 2, box.y + box.h / 2 - small * 0.35, small, color, 'CENTER')

        if lay.quick:
            draw_text("Quick Pick", lay.grid.x, lay.quick_title_y + round(3 * s), small, COL_TEXT_DIM)
            draw_text("Ctrl+Click: favorite", lay.panel.x + lay.panel.w - lay.pad,
                      lay.quick_title_y + round(3 * s), small, COL_TEXT_OFF, 'RIGHT')

        if not self.items:
            draw_text("No matches for “%s”" % self.search if self.search else "Nothing here yet",
                      lay.grid.x + lay.grid.w / 2, lay.grid.y + lay.grid.h / 2, round(12 * s), COL_TEXT_DIM, 'CENTER')

        for kind, ident, label, box in lay.buttons:
            on = button_on.get((kind, ident), False)
            draw_text(label, box.x + box.w / 2, mid(box), small, COL_TEXT if on else COL_TEXT_DIM, 'CENTER',
                      box.w - 4)

        self.draw_footer(lay, s, font, small)
        gpu.state.blend_set('NONE')

    def button_states(self):
        """Which bottom buttons are lit: the alpha mapping and the brush stroke method."""
        ctx = bpy.context
        states = {}
        if self.current_tab == 'ALPHAS':
            mapping = alphas.current_mapping(ctx) or self.prefs.alpha_map_mode
            states[('CHIP', mapping)] = True
        states[('STROKE', brushes.current_stroke(ctx))] = True
        return states

    def draw_thumb(self, p, item, box, inset):
        inner = Box(box.x + inset, box.y + inset, box.w - 2 * inset, box.h - 2 * inset)
        if item.key == alphas.NONE_KEY:
            s = box.w / 72.0
            p.outline(Box(inner.x + inner.w * 0.2, inner.y + inner.h * 0.2, inner.w * 0.6, inner.h * 0.6),
                      COL_TEXT_DIM, max(1, round(2 * s)))
            p.flush()
            draw_text("Off", box.x + box.w / 2, box.y + box.h / 2 - 5 * s, round(12 * s), COL_TEXT_DIM, 'CENTER')
            return
        p.image(inner, thumbs.texture(item.thumb_key))

    def draw_marks(self, p, item, box, s, hovered):
        if item.key == self.active_key:
            p.outline(box, COL_ACCENT, max(2, round(2 * s)))
        elif hovered:
            p.outline(box, COL_TEXT_DIM, max(1, round(1 * s)))

    def draw_footer(self, lay, s, font, small):
        foot = lay.footer
        item = None
        if self.hover and self.hover[0] == 'ITEM' and self.hover[1] < len(self.items):
            item = self.items[self.hover[1]]
        elif self.hover and self.hover[0] == 'QUICK' and self.hover[1] < len(self.quick_items):
            item = self.quick_items[self.hover[1]]
        elif self.kbd_index is not None and self.kbd_index < len(self.items):
            item = self.items[self.kbd_index]
        x = foot.x + lay.pad
        top_line = foot.y + foot.h - round(15 * s)
        bottom_line = foot.y + round(6 * s)
        help_text = BUTTON_HELP.get(tuple(self.hover)) if item is None and self.hover else None
        if help_text:
            # Button help gets the whole footer.
            title, _sep, body = help_text.partition(": ")
            draw_text(title if body else "", x, top_line, font, COL_TEXT, max_w=foot.w - 2 * lay.pad)
            body = body[:1].upper() + body[1:] if body else help_text
            draw_text(body, x, bottom_line, small, COL_TEXT_DIM, max_w=foot.w - 2 * lay.pad)
            return
        if item is not None:
            draw_text(item.name, x, top_line, font, COL_TEXT, max_w=foot.w * 0.5)
            draw_text(item.subtitle, x, bottom_line, small, COL_TEXT_DIM, max_w=foot.w * 0.5)
        elif self.message:
            draw_text(self.message, x, top_line, font, COL_TEXT, max_w=foot.w * 0.5)
        else:
            active = self.by_key.get(self.active_key)
            label = "Current: " + (active.name if active else ("—" if not self.active_key else "(not listed)"))
            draw_text(label, x, top_line, font, COL_TEXT, max_w=foot.w * 0.5)
        hints = "Click pick · Shift+Click keep open · Tab " + ("alphas" if self.current_tab == 'BRUSHES' else "brushes")
        draw_text(hints, foot.x + foot.w - lay.pad, top_line, small, COL_TEXT_DIM, 'RIGHT', foot.w * 0.48)
        draw_text("Type to search · Enter pick · Ctrl+Wheel size · Esc close",
                  foot.x + foot.w - lay.pad, bottom_line, small, COL_TEXT_OFF, 'RIGHT', foot.w * 0.48)


def close_open_palette():
    """Remove the draw handler of a palette that is still open (used on unregister)."""
    global _open_palette
    pal = _open_palette
    if pal is None:
        return
    if getattr(pal, "_handle", None) is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(pal._handle, 'WINDOW')
        except ValueError:
            pass
        pal._handle = None
    pal.request_close = True
    _open_palette = None


classes = (BPAL_OT_palette,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    close_open_palette()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
