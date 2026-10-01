"""Brush backend: find the brush assets usable in the current mode and activate them.

Since Blender 4.3 brushes are assets. They come from three places:

* the bundled *Essentials* library (one .blend per paint mode),
* user asset libraries (Preferences > File Paths > Asset Libraries),
* brush assets stored in the open .blend file.

Library files are indexed once (names, mode flags, catalog, preview) and the
result is cached on disk, keyed by the file's size + mtime, so opening the
palette stays instant.
"""

import json
import os
from dataclasses import dataclass

import bpy
import numpy as np

from . import prefs as _prefs
from . import thumbs

# context.mode -> (essentials file suffix, Brush flag for that mode, ToolSettings paint attribute)
MODE_TABLE = {
    'SCULPT': ("mesh_sculpt", "use_paint_sculpt", "sculpt"),
    'PAINT_VERTEX': ("mesh_vertex", "use_paint_vertex", "vertex_paint"),
    'PAINT_WEIGHT': ("mesh_weight", "use_paint_weight", "weight_paint"),
    'PAINT_TEXTURE': ("mesh_texture", "use_paint_image", "image_paint"),
    'SCULPT_CURVES': ("curve_sculpt", "use_paint_sculpt_curves", "curves_sculpt"),
    'PAINT_GREASE_PENCIL': ("gp_draw", "use_paint_grease_pencil", "gpencil_paint"),
    'PAINT_GPENCIL': ("gp_draw", "use_paint_grease_pencil", "gpencil_paint"),
    'SCULPT_GREASE_PENCIL': ("gp_sculpt", "use_sculpt_grease_pencil", "gpencil_sculpt_paint"),
    'SCULPT_GPENCIL': ("gp_sculpt", "use_sculpt_grease_pencil", "gpencil_sculpt_paint"),
    'WEIGHT_GREASE_PENCIL': ("gp_weight", "use_weight_grease_pencil", "gpencil_weight_paint"),
    'WEIGHT_GPENCIL': ("gp_weight", "use_weight_grease_pencil", "gpencil_weight_paint"),
    'VERTEX_GREASE_PENCIL': ("gp_vertex", "use_vertex_grease_pencil", "gpencil_vertex_paint"),
    'VERTEX_GPENCIL': ("gp_vertex", "use_vertex_grease_pencil", "gpencil_vertex_paint"),
}

INDEX_VERSION = 1


@dataclass
class BrushItem:
    key: str            # unique id, also used for favorites / recents
    name: str
    lib_type: str       # 'ESSENTIALS', 'CUSTOM' or 'LOCAL'
    lib_id: str         # asset library name for 'CUSTOM'
    rel_id: str         # relative asset identifier for brush.asset_activate
    source: str         # human readable library name
    catalog: str
    blend_path: str     # absolute path of the library .blend ('' for local brushes)
    thumb_key: str
    disk_name: str = ""  # thumbnail file in the on-disk cache (library brushes)

    @property
    def subtitle(self):
        return " / ".join(p for p in (self.source, self.catalog) if p)


def norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def library_key(blend_path, name):
    return "B|%s|%s" % (norm(blend_path), name)


def local_key(name):
    return "B|LOCAL|%s" % name


def supported(context):
    return context.mode in MODE_TABLE


def paint_settings(context):
    entry = MODE_TABLE.get(context.mode)
    if entry is None:
        return None
    return getattr(context.tool_settings, entry[2], None)


def active_brush(context):
    paint = paint_settings(context)
    return paint.brush if paint else None


def brush_key(brush):
    if brush is None:
        return ""
    if brush.library is not None:
        return library_key(bpy.path.abspath(brush.library.filepath), brush.name)
    return local_key(brush.name)


def active_key(context):
    return brush_key(active_brush(context))


# ---------------------------------------------------------------------------
# Catalogs


def read_catalogs(library_root):
    """Map catalog UUID -> catalog path from a library's blender_assets.cats.txt."""
    result = {}
    path = os.path.join(library_root, "blender_assets.cats.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(("#", "VERSION")):
                    continue
                parts = line.split(":")
                if len(parts) >= 2:
                    result[parts[0]] = parts[1]
    except OSError:
        pass
    return result


# ---------------------------------------------------------------------------
# Library file index


_index = None  # blend path -> {"stamp": str, "brushes": [{"name", "flags", "catalog_id", "catalog_name"}]}
_flag_names = None


def _index_path():
    return os.path.join(thumbs.cache_dir(), "brush_index.json")


def _load_index():
    global _index
    if _index is None:
        _index = {}
        try:
            with open(_index_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            if data.get("version") == INDEX_VERSION:
                _index = data.get("files", {})
        except (OSError, ValueError):
            pass
    return _index


def _save_index():
    try:
        with open(_index_path(), "w", encoding="utf-8") as fh:
            json.dump({"version": INDEX_VERSION, "files": _index}, fh)
    except OSError:
        pass


def flag_names():
    global _flag_names
    if _flag_names is None:
        props = bpy.types.Brush.bl_rna.properties
        _flag_names = sorted({entry[1] for entry in MODE_TABLE.values() if entry[1] in props})
    return _flag_names


def _thumb_disk_name(blend_path, stamp, name):
    return thumbs.disk_name("brush", norm(blend_path), stamp, name)


def _preview_pixels(brush):
    preview = brush.preview
    if preview is None:
        return None
    w, h = preview.image_size
    if not w or not h:
        return None
    buf = np.empty(w * h * 4, dtype=np.float32)
    preview.image_pixels_float.foreach_get(buf)
    return thumbs.resize(buf, w, h)


def _read_blend(blend_path, stamp):
    """Link all brush assets of a .blend into a throw-away Main and index them."""
    entries = []
    if norm(blend_path) == norm(bpy.data.filepath or "\0"):
        return entries
    try:
        with bpy.data.temp_data() as temp:
            with temp.libraries.load(blend_path, link=True, assets_only=True) as (src, dst):
                dst.brushes = list(src.brushes)
            for brush in dst.brushes:
                if brush is None or brush.asset_data is None:
                    continue
                flags = [f for f in flag_names() if getattr(brush, f, False)]
                entries.append({
                    "name": brush.name,
                    "flags": flags,
                    "catalog_id": brush.asset_data.catalog_id,
                    "catalog_name": brush.asset_data.catalog_simple_name,
                })
                arr = _preview_pixels(brush)
                if arr is not None:
                    thumbs.save_disk(_thumb_disk_name(blend_path, stamp, brush.name), arr)
                    thumbs.put(library_key(blend_path, brush.name), arr)
    except (OSError, RuntimeError, ValueError) as ex:
        print("Brush Palette: could not read %r: %s" % (blend_path, ex))
    return entries


def index_file(blend_path):
    """Return (stamp, entries) for a library .blend, reading it only when it changed."""
    index = _load_index()
    key = norm(blend_path)
    stamp = thumbs.stamp(blend_path)
    if stamp is None:
        return None, []
    cached = index.get(key)
    if cached and cached.get("stamp") == stamp:
        return stamp, cached["brushes"]
    entries = _read_blend(blend_path, stamp)
    index[key] = {"stamp": stamp, "brushes": entries}
    _save_index()
    return stamp, entries


# ---------------------------------------------------------------------------
# Collecting items


def essentials_root():
    return bpy.utils.system_resource('DATAFILES', path="assets")


def _essentials_items(mode):
    suffix = MODE_TABLE[mode][0]
    root = essentials_root()
    rel_file = "brushes/essentials_brushes-%s.blend" % suffix
    blend = os.path.join(root, *rel_file.split("/"))
    if not os.path.exists(blend):
        return []
    catalogs = read_catalogs(root)
    stamp, entries = index_file(blend)
    items = []
    for e in entries:
        items.append(_library_item(
            e, blend, stamp, 'ESSENTIALS', "", rel_file + "/Brush/" + e["name"], "Essentials", catalogs))
    return items


def _library_item(entry, blend, stamp, lib_type, lib_id, rel_id, source, catalogs):
    name = entry["name"]
    key = library_key(blend, name)
    catalog = catalogs.get(entry.get("catalog_id") or "", "") or entry.get("catalog_name", "")
    return BrushItem(key, name, lib_type, lib_id, rel_id, source, catalog, blend, key,
                     _thumb_disk_name(blend, stamp, name))


def _iter_blend_files(root, limit=2000):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.lower().endswith(".blend"):
                yield os.path.join(dirpath, fn)
                count += 1
                if count >= limit:
                    return


def _user_library_items(mode):
    flag = MODE_TABLE[mode][1]
    if flag not in flag_names():
        return []
    items = []
    for lib in bpy.context.preferences.filepaths.asset_libraries:
        root = bpy.path.abspath(lib.path)
        if not root or not os.path.isdir(root):
            continue
        catalogs = read_catalogs(root)
        for blend in _iter_blend_files(root):
            stamp, entries = index_file(blend)
            rel_blend = os.path.relpath(blend, root).replace(os.sep, "/")
            for e in entries:
                if flag not in e["flags"]:
                    continue
                items.append(_library_item(
                    e, blend, stamp, 'CUSTOM', lib.name, rel_blend + "/Brush/" + e["name"], lib.name, catalogs))
    return items


def _local_items(mode):
    flag = MODE_TABLE[mode][1]
    has_flag = flag in flag_names()
    items = []
    for brush in bpy.data.brushes:
        if brush.library is not None or brush.asset_data is None:
            continue
        if has_flag and not getattr(brush, flag, False):
            continue
        key = local_key(brush.name)
        catalog = brush.asset_data.catalog_simple_name
        items.append(BrushItem(key, brush.name, 'LOCAL', "", "Brush/" + brush.name,
                               "Current File", catalog, "", key))
    return items


def collect(context, prefs=None):
    """All brush items for the current mode, sorted by name."""
    prefs = prefs or _prefs.get_prefs(context)
    mode = context.mode
    if mode not in MODE_TABLE:
        return []
    items = []
    if prefs.include_current_file:
        items += _local_items(mode)
    items += _essentials_items(mode)
    if prefs.scan_user_libraries:
        items += _user_library_items(mode)
    seen = set()
    unique = []
    for item in items:
        if item.key not in seen:
            seen.add(item.key)
            unique.append(item)
    unique.sort(key=lambda i: (i.name.lower(), i.source))
    return unique


def load_thumb(item):
    """Make sure the item's thumbnail pixels are in memory. Returns True when done."""
    if thumbs.has(item.thumb_key):
        return True
    if item.lib_type == 'LOCAL':
        brush = bpy.data.brushes.get(item.name)
        arr = None
        if brush is not None and brush.library is None:
            try:
                arr = _preview_pixels(brush)
            except (RuntimeError, ValueError):
                arr = None
        thumbs.put(item.thumb_key, arr)
        return True
    if item.disk_name and thumbs.load_disk(item.thumb_key, item.disk_name):
        return True
    # The thumbnail cache was wiped: re-read the library file once.
    _load_index().pop(norm(item.blend_path), None)
    index_file(item.blend_path)
    if not thumbs.has(item.thumb_key):
        thumbs.put(item.thumb_key, None)
    return True


def refresh():
    """Forget the in-memory index so library files get re-checked."""
    global _index
    _index = None


# ---------------------------------------------------------------------------
# Activation


def activate(context, item):
    """Make ``item`` the active brush of the current paint mode."""
    kwargs = {
        "asset_library_type": item.lib_type,
        "relative_asset_identifier": item.rel_id,
    }
    if item.lib_type == 'CUSTOM':
        kwargs["asset_library_identifier"] = item.lib_id
    result = bpy.ops.brush.asset_activate(**kwargs)
    return 'FINISHED' in result


def current_stroke(context):
    brush = active_brush(context)
    return brush.stroke_method if brush is not None else ""


def set_stroke(context, method):
    """Set the stroke method of the active brush ('SPACE', 'DRAG_DOT', 'ANCHORED', ...)."""
    brush = active_brush(context)
    if brush is None:
        return False
    try:
        brush.stroke_method = method
    except (TypeError, AttributeError):
        return False
    return brush.stroke_method == method


def activate_local(context, brush):
    return 'FINISHED' in bpy.ops.brush.asset_activate(
        asset_library_type='LOCAL', relative_asset_identifier="Brush/" + brush.name)
