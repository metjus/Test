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
    check(small.hit(small.chips[1][1].x + 2, small.chips[1][1].y + 2, 120) == ('CHIP', 'AREA_PLANE'), "hit chip")

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


def make_palette(tab, width, height, search="", hover=None, prefix_only=False):
    from brush_palette import palette, prefs
    op = palette.BPAL_OT_palette

    class Fake:
        pass
    for name in ("draw_palette", "draw_thumb", "draw_marks", "draw_footer", "compute_layout", "reload", "refresh_filter",
                 "load_pending"):
        setattr(Fake, name, op.__dict__[name])
    pal = Fake()
    pal.region = FakeRegion(width, height)
    pal.prefs = prefs.get_prefs()
    pal.anchor = (width / 2, height / 2)
    pal.search = ""
    pal.prefix_only = False
    pal.scroll_row = 0
    pal.hover = None
    pal.kbd_index = None
    pal.message = ""
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
    pal = make_palette('ALPHAS', w, h)
    pal.hover = ('ITEM', 3)
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
