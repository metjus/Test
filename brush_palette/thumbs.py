"""Thumbnail pixels (CPU + on-disk cache) and their GPU textures.

Thumbnails are square RGBA ``uint8`` numpy arrays of THUMB x THUMB pixels,
stored bottom-up like Blender image pixels. GPU textures are only created
lazily from the draw callback, where a GPU context is guaranteed.
"""

import hashlib
import os

import numpy as np

from . import prefs

THUMB = 128

_pixels = {}      # thumb key -> np.ndarray (THUMB, THUMB, 4) uint8, or None if it failed
_textures = {}    # thumb key -> gpu.types.GPUTexture
_placeholder = None


def cache_dir():
    path = os.path.join(prefs.user_data_dir(), "thumbs")
    os.makedirs(path, exist_ok=True)
    return path


def stamp(path):
    """Cheap identity of a file's contents: size + mtime."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return "%d-%d" % (st.st_size, int(st.st_mtime))


def disk_name(*parts):
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest() + ".npy"


def resize(pixels, width, height):
    """Resize a flat float RGBA pixel buffer to a THUMB x THUMB uint8 array.

    The image is fitted (letterboxed) into the square so non-square alphas
    keep their proportions.
    """
    src = np.asarray(pixels, dtype=np.float32).reshape(height, width, 4)
    size = THUMB * 2
    scale = size / max(width, height)
    new_w = max(1, round(width * scale))
    new_h = max(1, round(height * scale))
    ys = np.minimum((np.arange(new_h) + 0.5) / scale, height - 1).astype(np.int32)
    xs = np.minimum((np.arange(new_w) + 0.5) / scale, width - 1).astype(np.int32)
    sampled = src[ys][:, xs]
    canvas = np.zeros((size, size, 4), dtype=np.float32)
    oy = (size - new_h) // 2
    ox = (size - new_w) // 2
    canvas[oy:oy + new_h, ox:ox + new_w] = sampled
    # 2x2 box filter down to the final size.
    canvas = canvas.reshape(THUMB, 2, THUMB, 2, 4).mean(axis=(1, 3))
    return (np.clip(canvas, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def has(key):
    return key in _pixels


def get(key):
    return _pixels.get(key)


def put(key, arr):
    _pixels[key] = arr
    _textures.pop(key, None)


def load_disk(key, name):
    path = os.path.join(cache_dir(), name)
    if not os.path.exists(path):
        return False
    try:
        arr = np.load(path, allow_pickle=False)
    except (OSError, ValueError):
        return False
    if arr.shape != (THUMB, THUMB, 4) or arr.dtype != np.uint8:
        return False
    put(key, arr)
    return True


def save_disk(name, arr):
    try:
        np.save(os.path.join(cache_dir(), name), arr, allow_pickle=False)
    except OSError:
        pass


def placeholder_pixels():
    """A shaded grey sphere, used until (or instead of) a real preview."""
    global _placeholder
    if _placeholder is None:
        c = (np.arange(THUMB) + 0.5) / THUMB * 2.0 - 1.0
        x, y = np.meshgrid(c, c)
        r2 = x * x + y * y
        inside = r2 < 0.72
        z = np.sqrt(np.clip(0.72 - r2, 0.0, None)) / np.sqrt(0.72)
        nx, ny = x / np.sqrt(0.72), y / np.sqrt(0.72)
        light = np.clip(nx * -0.45 + ny * 0.55 + z * 0.7, 0.0, 1.0)
        shade = 0.18 + 0.55 * light
        edge = np.clip((0.72 - r2) * 40.0, 0.0, 1.0)
        arr = np.zeros((THUMB, THUMB, 4), dtype=np.float32)
        arr[..., 0] = shade
        arr[..., 1] = shade
        arr[..., 2] = shade * 1.04
        arr[..., 3] = np.where(inside, edge, 0.0)
        _placeholder = (np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)
    return _placeholder


def _make_texture(arr):
    import gpu
    flat = (arr.astype(np.float32) / 255.0).ravel()
    try:
        buf = gpu.types.Buffer('FLOAT', flat.size, flat)
    except TypeError:
        buf = gpu.types.Buffer('FLOAT', flat.size, flat.tolist())
    return gpu.types.GPUTexture((THUMB, THUMB), format='RGBA8', data=buf)


def texture(key):
    """GPU texture for a thumbnail key, or the placeholder while not loaded.

    Only call from a draw callback.
    """
    tex = _textures.get(key)
    if tex is not None:
        return tex
    arr = _pixels.get(key)
    if arr is None:
        key = "__placeholder__"
        tex = _textures.get(key)
        if tex is not None:
            return tex
        arr = placeholder_pixels()
    tex = _make_texture(arr)
    _textures[key] = tex
    return tex


def clear(memory=True, disk=False):
    _textures.clear()
    if memory:
        _pixels.clear()
    if disk:
        folder = cache_dir()
        for name in os.listdir(folder):
            if name.endswith((".npy", ".json")):
                try:
                    os.remove(os.path.join(folder, name))
                except OSError:
                    pass


def free_gpu():
    _textures.clear()
