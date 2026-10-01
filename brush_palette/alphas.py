"""Alpha backend: scan alpha folders, build thumbnails and apply an alpha in one click.

In Blender an "alpha" is an image texture assigned to the brush. Doing that by
hand means: create a texture, set it to Image, open the image, set mapping,
set extension... This module does all of it at once and reuses the texture
and image data-blocks when the same alpha is picked again.

Brushes that come from an asset library (e.g. the Essentials) are linked and
cannot point to local textures, so the first time an alpha is applied to one
of them a local copy of the brush is made (``"<Brush> Alpha"``) and activated.
Later alpha changes reuse that copy.
"""

import os
import struct
import zlib
from dataclasses import dataclass

import bpy
import numpy as np

from . import brushes
from . import prefs as _prefs
from . import thumbs

EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".psd", ".bmp",
    ".tga", ".webp", ".hdr", ".dds", ".jp2",
}

NONE_KEY = "A|NONE"

# context.mode -> (texture attribute, texture slot attribute, slot mapping attribute)
TARGETS = {
    'SCULPT': ("texture", "texture_slot", "map_mode"),
    'PAINT_TEXTURE': ("mask_texture", "mask_texture_slot", "mask_map_mode"),
}

SOURCE_PROP = "brush_palette_source"
STROKE_SETTINGS = ("stroke_method", "spacing", "use_edge_to_edge")
ALPHA_PROP = "brush_palette_alpha"


@dataclass
class AlphaItem:
    key: str
    name: str
    path: str
    folder: str
    thumb_key: str

    @property
    def subtitle(self):
        return self.path if self.path else "Remove the alpha from the brush"


NONE_ITEM = AlphaItem(NONE_KEY, "Off", "", "", NONE_KEY)


def supported(context):
    return context.mode in TARGETS


def item_key(path):
    return "A|" + brushes.norm(path)


# ---------------------------------------------------------------------------
# Scanning


def folders(prefs):
    result = [(_prefs.default_alpha_dir(), True)]
    for folder in prefs.alpha_folders:
        path = bpy.path.abspath(folder.path) if folder.path else ""
        if path and os.path.isdir(path):
            result.append((path, folder.recursive))
    return result


def iter_images(folder, recursive, limit=5000):
    count = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() in EXTENSIONS:
                yield os.path.join(dirpath, fn)
                count += 1
                if count >= limit:
                    return
        if not recursive:
            return


def collect(prefs=None):
    prefs = prefs or _prefs.get_prefs()
    ensure_starter_alphas()
    seen = set()
    items = []
    for folder, recursive in folders(prefs):
        for path in iter_images(folder, recursive):
            key = item_key(path)
            if key in seen:
                continue
            seen.add(key)
            name = os.path.splitext(os.path.basename(path))[0]
            items.append(AlphaItem(key, name, path, folder, key))
    items.sort(key=lambda i: i.name.lower())
    return items


# ---------------------------------------------------------------------------
# Thumbnails


def _read_image_pixels(path):
    """Load an image file through Blender and return a THUMB x THUMB uint8 array.

    A temporary image data-block is used and removed again, so the user's
    images are never touched.
    """
    img = bpy.data.images.load(path, check_existing=False)
    try:
        width, height = img.size
        if not width or not height:
            return None
        if width > thumbs.THUMB * 2 or height > thumbs.THUMB * 2:
            factor = thumbs.THUMB * 2 / max(width, height)
            img.scale(max(1, round(width * factor)), max(1, round(height * factor)))
            width, height = img.size
        buf = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        rgba = buf.reshape(-1, 4)
        if img.channels < 4 or not np.any(rgba[:, 3] < 0.999):
            # Grey alphas: show the grey value as coverage so they read like ZBrush alphas.
            grey = rgba[:, :3].mean(axis=1)
            rgba[:, 0] = rgba[:, 1] = rgba[:, 2] = 1.0
            rgba[:, 3] = grey
        return thumbs.resize(buf, width, height)
    finally:
        bpy.data.images.remove(img)


def load_thumb(item):
    if thumbs.has(item.thumb_key) or item.key == NONE_KEY:
        return True
    stamp = thumbs.stamp(item.path)
    name = thumbs.disk_name("alpha", brushes.norm(item.path), stamp or "")
    if thumbs.load_disk(item.thumb_key, name):
        return True
    arr = None
    try:
        arr = _read_image_pixels(item.path)
    except (RuntimeError, OSError, ValueError) as ex:
        print("Brush Palette: could not read alpha %r: %s" % (item.path, ex))
    if arr is not None:
        thumbs.save_disk(name, arr)
    thumbs.put(item.thumb_key, arr)
    return True


# ---------------------------------------------------------------------------
# Applying


def current_texture(context):
    brush = brushes.active_brush(context)
    target = TARGETS.get(context.mode)
    if brush is None or target is None:
        return None
    return getattr(brush, target[0], None)


def active_key(context):
    tex = current_texture(context)
    if tex is None:
        return NONE_KEY
    image = getattr(tex, "image", None)
    if image is None or not image.filepath:
        return ""
    return item_key(bpy.path.abspath(image.filepath, library=image.library))


def _find_texture(path):
    for tex in bpy.data.textures:
        if tex.library is None and tex.type == 'IMAGE' and tex.get(ALPHA_PROP) == path:
            return tex
    return None


def ensure_texture(path, prefs):
    path = brushes.norm(path)
    tex = _find_texture(path)
    if tex is None:
        name = os.path.splitext(os.path.basename(path))[0]
        tex = bpy.data.textures.new("Alpha " + name, 'IMAGE')
        tex[ALPHA_PROP] = path
    image = tex.image
    if image is None or brushes.norm(bpy.path.abspath(image.filepath, library=image.library)) != path:
        image = bpy.data.images.load(path, check_existing=True)
        tex.image = image
    if prefs.alpha_non_color:
        try:
            image.colorspace_settings.is_data = True
        except (AttributeError, TypeError):
            pass
    return tex


def _editable_brush(context, brush):
    """Return a brush that can reference local textures, activating a local copy if needed."""
    if brush.library is None:
        return brush
    source = brushes.brush_key(brush)
    local = None
    for candidate in bpy.data.brushes:
        if candidate.library is None and candidate.get(SOURCE_PROP) == source:
            local = candidate
            break
    if local is None:
        local = brush.copy()
        local.name = brush.name + " Alpha"
        local[SOURCE_PROP] = source
        if local.asset_data is None:
            local.asset_mark()
    else:
        # Reusing an older copy: carry over the stroke the user just set on the original
        # (e.g. DragRect), otherwise the copy would silently keep its old stroke.
        for attr in STROKE_SETTINGS:
            try:
                setattr(local, attr, getattr(brush, attr))
            except (AttributeError, TypeError):
                pass
    if not brushes.activate_local(context, local):
        raise RuntimeError("Could not activate the local brush %r" % local.name)
    return local


def _set_mapping(slot, attr, mode):
    try:
        setattr(slot, attr, mode)
    except TypeError:
        # e.g. 'AREA_PLANE' is sculpt-only; fall back to the closest mode.
        setattr(slot, attr, 'VIEW_PLANE')


def apply(context, item, prefs=None):
    """Apply ``item`` (or remove the alpha for NONE_ITEM) to the active brush.

    Returns a message describing what happened. Raises RuntimeError on failure.
    """
    prefs = prefs or _prefs.get_prefs(context)
    target = TARGETS.get(context.mode)
    if target is None:
        raise RuntimeError("Alphas are available in Sculpt and Texture Paint mode")
    tex_attr, slot_attr, map_attr = target
    brush = brushes.active_brush(context)
    if brush is None:
        raise RuntimeError("No active brush")

    if item.key == NONE_KEY:
        if getattr(brush, tex_attr) is not None:
            setattr(brush, tex_attr, None)
        return "Alpha removed from %s" % brush.name

    had_alpha = getattr(brush, tex_attr) is not None
    original_name = brush.name
    brush = _editable_brush(context, brush)
    tex = ensure_texture(item.path, prefs)
    setattr(brush, tex_attr, tex)
    if getattr(brush, tex_attr) != tex:
        raise RuntimeError("Brush %r does not accept textures" % brush.name)

    slot = getattr(brush, slot_attr)
    if not had_alpha or brush.name != original_name:
        _set_mapping(slot, map_attr, prefs.alpha_map_mode)
    tex.extension = 'REPEAT' if getattr(slot, map_attr) == 'TILED' else 'CLIP'
    if prefs.alpha_stroke != 'KEEP':
        try:
            brush.stroke_method = prefs.alpha_stroke
        except TypeError:
            pass
    if brush.name != original_name:
        return "Alpha %s applied to local copy %r" % (item.name, brush.name)
    return "Alpha %s applied to %s" % (item.name, brush.name)


def set_mapping(context, mode):
    """Change the mapping of the active brush alpha (used by the palette chips)."""
    target = TARGETS.get(context.mode)
    brush = brushes.active_brush(context)
    if target is None or brush is None or getattr(brush, target[0]) is None:
        return False
    slot = getattr(brush, target[1])
    try:
        _set_mapping(slot, target[2], mode)
    except (TypeError, AttributeError):
        return False
    tex = getattr(brush, target[0])
    tex.extension = 'REPEAT' if getattr(slot, target[2]) == 'TILED' else 'CLIP'
    return True


def current_mapping(context):
    target = TARGETS.get(context.mode)
    brush = brushes.active_brush(context)
    if target is None or brush is None or getattr(brush, target[0]) is None:
        return ""
    return getattr(getattr(brush, target[1]), target[2], "")


# ---------------------------------------------------------------------------
# Starter alphas


def write_png_grey(path, pixels):
    """Write an 8-bit greyscale PNG. ``pixels`` is (h, w) uint8, top row first."""
    h, w = pixels.shape
    raw = b"".join(b"\x00" + pixels[y].tobytes() for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        fh.write(chunk(b"IEND", b""))


def _smooth(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _value_noise(size, cells, rng):
    grid = rng.random((cells + 1, cells + 1))
    coords = np.linspace(0, cells, size, endpoint=False)
    i = coords.astype(int)
    f = _smooth(0.0, 1.0, coords - i)
    top = grid[i][:, i] * (1 - f)[None, :] + grid[i][:, i + 1] * f[None, :]
    bottom = grid[i + 1][:, i] * (1 - f)[None, :] + grid[i + 1][:, i + 1] * f[None, :]
    return top * (1 - f)[:, None] + bottom * f[:, None]


def starter_alpha_images(size=256):
    """Procedural alphas so the palette is useful out of the box."""
    c = (np.arange(size) + 0.5) / size * 2.0 - 1.0
    x, y = np.meshgrid(c, -c)
    r = np.sqrt(x * x + y * y)
    a = np.arctan2(y, x)
    falloff = 1.0 - _smooth(0.75, 1.0, r)
    rng = np.random.default_rng(7)

    images = {}
    images["Round Soft"] = 1.0 - _smooth(0.0, 1.0, r)
    images["Round Hard"] = 1.0 - _smooth(0.9, 0.95, r)
    images["Square"] = (1.0 - _smooth(0.8, 0.85, np.abs(x))) * (1.0 - _smooth(0.8, 0.85, np.abs(y)))
    images["Ring"] = np.exp(-((r - 0.6) / 0.12) ** 2)
    star_r = 0.55 + 0.3 * np.cos(5 * a)
    images["Star"] = 1.0 - _smooth(star_r - 0.04, star_r + 0.02, r)
    images["Cross"] = np.maximum(
        np.exp(-(x / 0.12) ** 2) * (1 - _smooth(0.8, 0.9, np.abs(y))),
        np.exp(-(y / 0.12) ** 2) * (1 - _smooth(0.8, 0.9, np.abs(x))),
    )
    images["Crater"] = np.clip(np.exp(-((r - 0.55) / 0.18) ** 2) - 0.6 * np.exp(-(r / 0.35) ** 2) + 0.35, 0, 1) * falloff
    images["Stripes"] = (0.5 + 0.5 * np.cos(x * np.pi * 6)) * falloff
    dots = (0.5 + 0.5 * np.cos(x * np.pi * 5)) * (0.5 + 0.5 * np.cos(y * np.pi * 5))
    images["Dots"] = _smooth(0.45, 0.8, dots) * falloff
    noise = (_value_noise(size, 4, rng) * 0.5 + _value_noise(size, 12, rng) * 0.3
             + _value_noise(size, 32, rng) * 0.2)
    images["Noise"] = np.clip((noise - 0.2) * 1.6, 0, 1) * falloff
    cells = _value_noise(size, 24, rng)
    images["Skin Pores"] = np.clip(1.0 - _smooth(0.0, 0.35, cells) * 0.9, 0, 1) * falloff
    images["Scales"] = _smooth(0.2, 0.7, np.abs(np.sin(x * 9) + np.sin(y * 9 + np.sin(x * 9)))) * falloff
    return images


def ensure_starter_alphas(force=False):
    """Fill the built-in alpha folder the first time (or when forced)."""
    folder = _prefs.default_alpha_dir()
    if os.path.isdir(folder) and not force:
        return folder
    os.makedirs(folder, exist_ok=True)
    for name, img in starter_alpha_images().items():
        path = os.path.join(folder, name + ".png")
        if force or not os.path.exists(path):
            write_png_grey(path, (np.clip(img, 0.0, 1.0) * 255 + 0.5).astype(np.uint8))
    return folder
