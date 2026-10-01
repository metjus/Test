"""Headless tests for the Brush & Alpha Palette add-on.

Run with a Python that has the ``bpy`` module (pip install bpy==<version>)::

    python tests/run_tests.py [--screenshot-dir DIR]

A throw-away Blender user folder is used, so your real preferences are not touched.
With --screenshot-dir the palette is rendered off-screen (requires a GPU/EGL
context; a tiny EEVEE render is used to initialise it) and saved as PNGs.
"""

import argparse
import os
import shutil
import struct
import sys
import tempfile
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_DIR = tempfile.mkdtemp(prefix="bpal_user_")
os.environ["BLENDER_USER_RESOURCES"] = USER_DIR

import bpy  # noqa: E402
import addon_utils  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILURES.append(msg)


def install_addon():
    addons = bpy.utils.user_resource('SCRIPTS', path="addons", create=True)
    target = os.path.join(addons, "brush_palette")
    if os.path.lexists(target):
        os.remove(target) if os.path.islink(target) else shutil.rmtree(target)
    os.symlink(os.path.join(ROOT, "brush_palette"), target)
    bpy.utils.refresh_script_paths()
    addon_utils.modules_refresh()
    addon_utils.enable("brush_palette", default_set=True, handle_error=None)
    check("brush_palette" in bpy.context.preferences.addons, "add-on enabled")
    import brush_palette
    return brush_palette


def enter_sculpt():
    # Note: read_factory_settings() would also reset the preferences (and the add-on).
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)
    bpy.ops.mesh.primitive_uv_sphere_add()
    bpy.ops.object.mode_set(mode='SCULPT')


def test_brushes(pkg):
    print("brushes")
    from brush_palette import brushes, thumbs
    items = brushes.collect(bpy.context)
    names = [i.name for i in items]
    check(len(items) > 40, "found %d sculpt brushes" % len(items))
    check("Clay Strips" in names and "Grab" in names, "essential brushes listed")
    check(names == sorted(names, key=str.lower), "sorted by name")
    clay = next(i for i in items if i.name == "Clay Strips")
    check(clay.lib_type == 'ESSENTIALS' and clay.catalog != "", "catalog resolved: %r" % clay.catalog)
    check(brushes.activate(bpy.context, clay), "activate Clay Strips")
    check(brushes.active_key(bpy.context) == clay.key, "active key matches")
    check(brushes.load_thumb(clay) and thumbs.get(clay.thumb_key) is not None, "thumbnail loaded")
    arr = thumbs.get(clay.thumb_key)
    check(arr.shape == (thumbs.THUMB, thumbs.THUMB, 4) and arr[..., 3].max() > 0, "thumbnail has content")

    # Second collect must come from the cached index (no re-read) and be identical.
    brushes.refresh()
    again = brushes.collect(bpy.context)
    check([i.key for i in again] == [i.key for i in items], "cached index gives same result")

    # Other paint modes.
    for mode, expected in (('TEXTURE_PAINT', "Paint Hard"), ('VERTEX_PAINT', "Paint Hard"), ('WEIGHT_PAINT', "Paint")):
        bpy.ops.object.mode_set(mode=mode)
        names = [i.name for i in brushes.collect(bpy.context)]
        check(any(n.startswith(expected) for n in names), "%s: %d brushes" % (mode, len(names)))
    bpy.ops.object.mode_set(mode='SCULPT')


def test_alphas(pkg):
    print("alphas")
    from brush_palette import alphas, brushes, thumbs, prefs
    items = alphas.collect()
    check(len(items) >= 12, "starter alphas generated: %d" % len(items))
    for item in items:
        alphas.load_thumb(item)
    check(all(thumbs.get(i.thumb_key) is not None for i in items), "all alpha thumbnails loaded")
    check(len(bpy.data.images) == 0, "thumbnail loading leaves no images behind")

    # Extra folder with a non-square alpha.
    extra = tempfile.mkdtemp(prefix="bpal_alphas_")
    import numpy as np
    alphas.write_png_grey(os.path.join(extra, "wide.png"), np.full((32, 96), 200, np.uint8))
    p = prefs.get_prefs()
    f = p.alpha_folders.add()
    f.path = extra
    items = alphas.collect()
    wide = next((i for i in items if i.name == "wide"), None)
    check(wide is not None, "extra folder scanned")
    alphas.load_thumb(wide)
    arr = thumbs.get(wide.thumb_key)
    check(arr[0, 64, 3] == 0 and arr[64, 64, 3] > 150, "non-square alpha letterboxed")

    clay = next(i for i in brushes.collect(bpy.context) if i.name == "Clay Strips")
    brushes.activate(bpy.context, clay)
    star = next(i for i in items if i.name == "Star")
    msg = alphas.apply(bpy.context, star)
    brush = brushes.active_brush(bpy.context)
    check(brush.library is None and brush.name == "Clay Strips Alpha", "local copy made: %s (%s)" % (brush.name, msg))
    check(brush.texture is not None and brush.texture.image is not None, "texture assigned")
    check(brush.texture_slot.map_mode == 'AREA_PLANE', "mapping set to Area Plane")
    check(brush.texture.image.colorspace_settings.is_data, "image loaded as non-color")
    check(alphas.active_key(bpy.context) == star.key, "active alpha key matches")

    ring = next(i for i in items if i.name == "Ring")
    n_brushes = len(bpy.data.brushes)
    alphas.apply(bpy.context, ring)
    brush = brushes.active_brush(bpy.context)
    check(len(bpy.data.brushes) == n_brushes and brush.name == "Clay Strips Alpha", "local copy reused")
    check(alphas.active_key(bpy.context) == ring.key, "alpha switched to Ring")

    # Picking the linked original again and applying an alpha must reuse the same copy.
    brushes.activate(bpy.context, clay)
    alphas.apply(bpy.context, star)
    check(len(bpy.data.brushes) == n_brushes, "copy reused after re-picking the original")
    textures_before = len(bpy.data.textures)
    alphas.apply(bpy.context, star)
    check(len(bpy.data.textures) == textures_before, "texture reused for the same alpha")

    local = [i for i in brushes.collect(bpy.context) if i.lib_type == 'LOCAL']
    check(any(i.name == "Clay Strips Alpha" for i in local), "local brush listed in palette")
    brushes.load_thumb(local[0])

    check(alphas.set_mapping(bpy.context, 'TILED'), "mapping chip works")
    check(brushes.active_brush(bpy.context).texture.extension == 'REPEAT', "tiled uses repeat")
    alphas.apply(bpy.context, alphas.NONE_ITEM)
    check(brushes.active_brush(bpy.context).texture is None, "alpha removed")

    # Texture paint uses the mask texture.
    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
    alphas.apply(bpy.context, star)
    brush = brushes.active_brush(bpy.context)
    check(brush.mask_texture is not None, "texture paint: mask texture set on %s" % brush.name)
    bpy.ops.object.mode_set(mode='SCULPT')


def test_layout(pkg):
    print("layout")
    from brush_palette.palette import PaletteLayout, filter_items
    lay = PaletteLayout(1600, 900, (800, 450), 120, 5, 'BRUSHES', 1.0)
    check(lay.cols == 12, "12 columns")
    check(lay.panel.x >= 0 and lay.panel.x + lay.panel.w <= 1600, "panel inside region horizontally")
    check(lay.panel.y >= 0 and lay.panel.y + lay.panel.h <= 900, "panel inside region vertically")
    box = lay.item_box(13)
    check(lay.hit(box.x + 5, box.y + 5, 120) == ('ITEM', 13), "hit item 13")
    check(lay.hit(lay.quick[2].x + 3, lay.quick[2].y + 3, 120) == ('QUICK', 2), "hit quick 2")
    check(lay.hit(5, 5, 120) is None, "outside is None")
    check(lay.hit(*[v + 2 for v in (lay.letters[3][1].x, lay.letters[3][1].y)], 120) == ('LETTER', 'D'), "hit letter")
    check(lay.max_scroll_row > 0, "long lists scroll")
    small = PaletteLayout(500, 300, (10, 10), 120, 0, 'ALPHAS', 1.0)
    check(small.panel.x >= 0 and small.panel.y >= 0 and small.cols >= 1, "small region still fits")
    check(small.hit(small.button('CHIP', 'AREA_PLANE').x + 2, small.button('CHIP', 'AREA_PLANE').y + 2, 120) == ('CHIP', 'AREA_PLANE'), "hit chip")

    class It:
        def __init__(self, name):
            self.name, self.key = name, name
    names = ["Clay", "Clay Strips", "Draw Sharp", "Smooth", "Snake Hook", "Scrape/Fill", "Elastic Grab"]
    items = [It(n) for n in names]
    check([i.name for i in filter_items(items, "s")][:3] == ["Scrape/Fill", "Smooth", "Snake Hook"], "prefix first")
    check("Clay Strips" in [i.name for i in filter_items(items, "stri")], "word prefix match")
    check([i.name for i in filter_items(items, "s", prefix_only=True)] == ["Scrape/Fill", "Smooth", "Snake Hook"],
          "letter bar is prefix-only")
    check([i.name for i in filter_items(items, "grab")] == ["Elastic Grab"], "word match")




def ev(etype, value='PRESS', x=0, y=0, ctrl=False, alt=False, shift=False, unicode=""):
    from types import SimpleNamespace
    return SimpleNamespace(type=etype, value=value, mouse_x=x, mouse_y=y, ctrl=ctrl, alt=alt,
                           shift=shift, oskey=False, unicode=unicode)


def center(box):
    return box.x + box.w / 2, box.y + box.h / 2


def test_events(pkg):
    """Drive the palette's modal() with synthetic events."""
    print("events")
    from brush_palette import alphas, brushes, prefs
    ctx = bpy.context
    W, H = 1280, 800
    p = prefs.get_prefs()
    p.recents = "[]"
    p.favorites = "[]"

    pal = make_palette('BRUSHES', W, H)
    lay = pal.compute_layout()
    check(pal.modal(ctx, ev('TIMER')) == {'PASS_THROUGH'}, "timer passes through")
    check(pal.modal(ctx, ev('MIDDLEMOUSE')) == {'PASS_THROUGH'}, "middle mouse navigates the viewport")
    x, y = center(lay.item_box(3))
    pal.modal(ctx, ev('MOUSEMOVE', 'NOTHING', x, y))
    check(pal.hover == ('ITEM', 3), "hover follows mouse")

    for ch in "cl":
        pal.modal(ctx, ev(ch.upper(), unicode=ch))
    check(pal.search == "cl" and pal.items and pal.items[0].name == "Clay", "typing filters: %s" %
          [i.name for i in pal.items[:4]])
    check(pal.kbd_index == 0, "first match highlighted")
    pal.modal(ctx, ev('BACK_SPACE'))
    check(pal.search == "c", "backspace")
    pal.modal(ctx, ev('L', unicode="l"))
    pal.modal(ctx, ev('RIGHT_ARROW'))
    check(pal.kbd_index == 1, "arrow moves highlight")
    target = pal.items[1]
    result = pal.modal(ctx, ev('RET'))
    check(result == {'FINISHED'}, "enter picks and closes")
    check(brushes.active_key(ctx) == target.key, "enter activated %s" % target.name)
    check(prefs.recents(p)[:1] == [target.key], "pick recorded in recents")

    pal = make_palette('BRUSHES', W, H)
    lay = pal.compute_layout()
    letter_box = dict(lay.letters)["S"]
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(letter_box)))
    check(pal.prefix_only and pal.items and all(i.name.lower().startswith("s") for i in pal.items),
          "letter bar filters to S (%d)" % len(pal.items))
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(letter_box)))
    check(not pal.search and len(pal.items) == len(pal.all_items), "clicking the letter again clears it")
    pal.modal(ctx, ev('S', unicode="s"))
    pal.modal(ctx, ev('ESC'))
    check(pal.search == "" and pal._timer is None, "esc clears search first")

    lay = pal.compute_layout()
    fav = pal.items[2]
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.item_box(2)), ctrl=True))
    check(fav.key in prefs.favorites(p) and fav in pal.quick_items, "ctrl+click adds favorite to quick pick")
    lay = pal.compute_layout()
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.item_box(2)), ctrl=True))
    check(fav.key not in prefs.favorites(p), "ctrl+click again removes it")

    lay = pal.compute_layout()
    if lay.max_scroll_row > 0:
        pal.modal(ctx, ev('WHEELDOWNMOUSE'))
        check(pal.scroll_row == 1, "wheel scrolls one row")
        pal.modal(ctx, ev('WHEELUPMOUSE'))
        check(pal.scroll_row == 0, "wheel scrolls back")
    small = make_palette('BRUSHES', 900, 420)
    lay = small.compute_layout()
    check(lay.max_scroll_row > 0, "small viewport needs scrolling")
    small.modal(ctx, ev('WHEELDOWNMOUSE'))
    small.modal(ctx, ev('WHEELDOWNMOUSE'))
    check(small.scroll_row == 2, "wheel scrolls rows")
    small.modal(ctx, ev('WHEELUPMOUSE'))
    check(small.scroll_row == 1, "wheel scrolls back")
    for _ in range(50):
        small.modal(ctx, ev('WHEELDOWNMOUSE'))
    check(small.scroll_row == lay.max_scroll_row, "scroll stops at the end")
    top = lay.panel.y + lay.panel.h
    small.modal(ctx, ev('Q', unicode="q"))
    lay2 = small.compute_layout()
    check(lay2.panel.y + lay2.panel.h == top and lay2.header.y == lay.header.y, "panel top stays put while filtering")

    size = p.thumb_size
    pal.modal(ctx, ev('WHEELUPMOUSE', ctrl=True))
    check(p.thumb_size == size + 8, "ctrl+wheel grows thumbnails")
    p.thumb_size = size

    lay = pal.compute_layout()
    shift_target = pal.items[5]
    result = pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.item_box(5)), shift=True))
    check(result == {'RUNNING_MODAL'} and pal.active_key == shift_target.key, "shift+click picks and stays open")
    quick_box = pal.compute_layout().quick[0]
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(quick_box), shift=True))
    check(pal.active_key == pal.quick_items[0].key, "quick pick slot picks")

    # Stroke buttons act on the active brush.
    lay = pal.compute_layout()
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.button('STROKE', 'ANCHORED'))))
    check(brushes.active_brush(ctx).stroke_method == 'ANCHORED', "DragRect button sets Anchored stroke")
    pal.modal(ctx, ev('MOUSEMOVE', 'NOTHING', *center(lay.button('STROKE', 'DRAG_DOT'))))
    check(pal.hover == ('STROKE', 'DRAG_DOT'), "hovering a stroke button")
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.button('STROKE', 'SPACE'))))
    check(brushes.active_brush(ctx).stroke_method == 'SPACE', "Space button sets Space stroke")
    bpy.ops.brush_palette.set_stroke(method='DRAG_DOT')
    check(brushes.active_brush(ctx).stroke_method == 'DRAG_DOT', "sidebar stroke operator")
    brushes.set_stroke(ctx, 'SPACE')

    # Alphas: Tab, mapping chip, pick.
    pal.modal(ctx, ev('TAB'))
    check(pal.current_tab == 'ALPHAS' and pal.items[0].key == alphas.NONE_KEY, "tab switches to alphas")
    lay = pal.compute_layout()
    star_index = next(i for i, it in enumerate(pal.items) if it.name == "Star")
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.button('CHIP', 'VIEW_PLANE'))))
    check(p.alpha_map_mode == 'VIEW_PLANE', "chip sets default mapping")
    result = pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.item_box(star_index))))
    brush = brushes.active_brush(ctx)
    check(result == {'FINISHED'} and brush.texture is not None, "click applies alpha to %s" % brush.name)
    check(brush.texture_slot.map_mode == 'VIEW_PLANE', "new alpha uses chosen mapping")
    p.alpha_map_mode = 'AREA_PLANE'

    pal = make_palette('ALPHAS', W, H)
    lay = pal.compute_layout()
    pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.button('CHIP', 'TILED'))))
    check(brushes.active_brush(ctx).texture_slot.map_mode == 'TILED', "chip changes mapping of current alpha")
    check(lay.button('STROKE', 'ANCHORED') is not None, "alpha tab also has stroke buttons")
    result = pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.item_box(0))))
    check(result == {'FINISHED'} and brushes.active_brush(ctx).texture is None, "Off removes the alpha")

    # Closing.
    pal = make_palette('BRUSHES', W, H)
    check(pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', 2, 2)) == {'CANCELLED'}, "click outside closes")
    pal = make_palette('BRUSHES', W, H)
    check(pal.modal(ctx, ev('RIGHTMOUSE')) == {'CANCELLED'}, "right click closes")
    pal = make_palette('BRUSHES', W, H)
    check(pal.modal(ctx, ev('B', alt=True, unicode="b")) == {'CANCELLED'}, "hotkey again closes")
    pal = make_palette('BRUSHES', W, H)
    check(pal.modal(ctx, ev('ESC')) == {'CANCELLED'}, "esc closes")
    pal = make_palette('BRUSHES', W, H)
    lay = pal.compute_layout()
    check(pal.modal(ctx, ev('LEFTMOUSE', 'PRESS', *center(lay.close))) == {'CANCELLED'}, "close button")

    # Modes without alphas.
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    pal = make_palette('BRUSHES', W, H)
    pal.modal(ctx, ev('TAB'))
    check(pal.current_tab == 'BRUSHES' and "Alphas" in pal.message, "no alpha tab in weight paint")
    bpy.ops.object.mode_set(mode='SCULPT')


def test_user_library(pkg):
    """Brushes saved by the user into an asset library show up in the palette."""
    print("user library")
    from brush_palette import alphas, brushes
    ctx = bpy.context
    lib_dir = tempfile.mkdtemp(prefix="bpal_lib_")
    bpy.ops.preferences.asset_library_add(directory=lib_dir)
    lib = bpy.context.preferences.filepaths.asset_libraries[-1]

    items = {i.name: i for i in brushes.collect(ctx)}
    brushes.activate(ctx, items["Clay Strips"])
    star = next(i for i in alphas.collect() if i.name == "Star")
    alphas.apply(ctx, star)                      # -> local "Clay Strips Alpha" with a texture
    brushes.set_stroke(ctx, 'ANCHORED')
    result = bpy.ops.brush.asset_save_as(name="My Star Clay", asset_library_reference=lib.name,
                                         catalog_path="My Brushes")
    check(result == {'FINISHED'}, "brush saved into user library")

    brushes.refresh()
    items = {i.name: i for i in brushes.collect(ctx)}
    mine = items.get("My Star Clay")
    check(mine is not None and mine.lib_type == 'CUSTOM' and mine.lib_id == lib.name,
          "saved brush listed from user library: %r" % (mine and mine.subtitle))
    check(mine is not None and mine.catalog == "My Brushes", "catalog of saved brush")
    brushes.activate(ctx, items["Grab"])
    check(brushes.activate(ctx, mine), "saved brush activates from the palette")
    brush = brushes.active_brush(ctx)
    check(brushes.active_key(ctx) == mine.key, "active key of user library brush")
    check(brush.texture is not None and brush.stroke_method == 'ANCHORED',
          "saved brush keeps its alpha and DragRect stroke")
    brushes.load_thumb(mine)
    brushes.activate(ctx, items["Clay Strips"])  # don't leave a brush from a library we remove
    bpy.ops.preferences.asset_library_remove(index=len(bpy.context.preferences.filepaths.asset_libraries) - 1)


# ---------------------------------------------------------------------------
# Off-screen rendering of the palette


def write_png_rgba(path, width, height, data):
    rows = [bytes(data[(height - 1 - y) * width * 4:(height - y) * width * 4]) for y in range(height)]
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def init_gpu():
    scene = bpy.context.scene
    scene.render.resolution_x = scene.render.resolution_y = 8
    cam = bpy.data.objects.new("GPUInitCam", bpy.data.cameras.new("GPUInitCam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    bpy.ops.render.render()
    bpy.data.objects.remove(cam)


class FakeRegion:
    def __init__(self, w, h):
        self.width, self.height, self.x, self.y = w, h, 0, 0


class FakeArea:
    type = 'VIEW_3D'

    def tag_redraw(self):
        pass


def make_palette(tab, width, height, search="", hover=None, prefix_only=False):
    """Palette operator logic bound to a plain object (operators can't be instantiated directly)."""
    import inspect
    import time
    from brush_palette import palette, prefs
    op = palette.BPAL_OT_palette

    class Fake:
        reports = []

        def region_alive(self, context):
            return True

        def report(self, kind, msg):
            self.reports.append((kind, msg))
    for name, value in op.__dict__.items():
        if inspect.isfunction(value) and name not in Fake.__dict__:
            setattr(Fake, name, value)
    pal = Fake()
    pal.region = FakeRegion(width, height)
    pal.area = FakeArea()
    pal._handle = pal._timer = None
    pal.prefs = prefs.get_prefs()
    pal.anchor = (width / 2, height / 2)
    pal.search = ""
    pal.prefix_only = False
    pal.scroll_row = 0
    pal.panel_top = None
    pal.hover = None
    pal.kbd_index = None
    pal.message = ""
    pal.request_close = False
    pal.invoke_key = ('B', False, True, False)
    pal.opened_at = time.time() - 1.0
    pal.current_tab = tab
    pal.reload(bpy.context)
    if search:
        pal.search, pal.prefix_only = search, prefix_only
        pal.refresh_filter()
    while pal.load_pending(budget=10.0):
        pass
    pal.hover = hover
    return pal


def render(pal, path, width, height, background):
    import gpu
    from mathutils import Matrix
    off = gpu.types.GPUOffScreen(width, height)
    with off.bind():
        fb = gpu.state.active_framebuffer_get()
        fb.clear(color=background)
        with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
            gpu.matrix.load_identity()
            proj = Matrix.Identity(4)
            proj[0][0], proj[1][1] = 2.0 / width, 2.0 / height
            proj[0][3], proj[1][3] = -1.0, -1.0
            gpu.matrix.load_projection_matrix(proj)
            pal.draw_palette()
        buf = fb.read_color(0, 0, width, height, 4, 0, 'UBYTE')
        buf.dimensions = width * height * 4
        data = bytes(buf)
    off.free()
    write_png_rgba(path, width, height, data)
    print("  wrote", path)


def screenshots(out_dir):
    print("screenshots")
    from brush_palette import brushes, prefs
    os.makedirs(out_dir, exist_ok=True)
    init_gpu()
    enter_sculpt()
    p = prefs.get_prefs()
    items = brushes.collect(bpy.context)
    by_name = {i.name: i for i in items}
    brushes.activate(bpy.context, by_name["Clay Strips"])
    for name in ("Draw Sharp", "Crease Sharp", "Snake Hook", "Clay Strips"):
        prefs.push_recent(p, by_name[name].key)
    for name in ("Clay Strips", "Grab"):
        prefs.toggle_favorite(p, by_name[name].key)

    w, h = 1280, 800
    bg = (0.235, 0.235, 0.235, 1.0)
    pal = make_palette('BRUSHES', w, h)
    lay = pal.compute_layout()
    pal.hover = ('ITEM', 5)
    render(pal, os.path.join(out_dir, "palette_brushes.png"), w, h, bg)
    check(lay.cols == 12, "screenshot layout has 12 columns")

    pal = make_palette('BRUSHES', w, h, search="c", prefix_only=True)
    render(pal, os.path.join(out_dir, "palette_letter_c.png"), w, h, bg)

    from brush_palette import alphas
    stars = next(i for i in alphas.collect() if i.name == "Star")
    alphas.apply(bpy.context, stars)
    brushes.set_stroke(bpy.context, 'ANCHORED')
    pal = make_palette('ALPHAS', w, h)
    pal.hover = ('STROKE', 'ANCHORED')
    render(pal, os.path.join(out_dir, "palette_alphas.png"), w, h, bg)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot-dir")
    args = parser.parse_args()
    print("Blender", bpy.app.version_string, "user dir", USER_DIR)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    pkg = install_addon()
    enter_sculpt()
    test_brushes(pkg)
    test_alphas(pkg)
    test_layout(pkg)
    test_events(pkg)
    test_user_library(pkg)
    if args.screenshot_dir:
        screenshots(args.screenshot_dir)
    addon_utils.disable("brush_palette", default_set=True)
    check("brush_palette" not in bpy.context.preferences.addons, "add-on disabled cleanly")
    shutil.rmtree(USER_DIR, ignore_errors=True)
    print("\n%d failure(s)" % len(FAILURES))
    for f in FAILURES:
        print("  -", f)
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
