"""Zistí farbu každej plochy meshu v Blenderi (z textúry, farieb vrcholov alebo materiálu)."""
from __future__ import annotations

import bpy
import numpy as np

from . import core

SOURCES = ("AUTO", "TEXTURE", "VERTEX", "MATERIAL")


class NoColorData(Exception):
    pass


# --------------------------------------------------------------------------- pomocné


def _mode_color(samples: np.ndarray) -> np.ndarray:
    """samples (N,S,3) sRGB 0..1 -> (N,3): najčastejšia farba medzi vzorkami plochy (pri remíze prvá).

    Plocha na hranici dvoch farieb tak dostane jednu z čistých farieb, nie ich zmes.
    """
    q = np.round(samples * 255).astype(np.int64)
    key = (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]
    votes = (key[:, :, None] == key[:, None, :]).sum(axis=2)
    best = votes.argmax(axis=1)
    return samples[np.arange(len(samples)), best]


def _polygon_arrays(mesh):
    n = len(mesh.polygons)
    start = np.empty(n, dtype=np.int32)
    total = np.empty(n, dtype=np.int32)
    mat = np.empty(n, dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", start)
    mesh.polygons.foreach_get("loop_total", total)
    mesh.polygons.foreach_get("material_index", mat)
    return start, total, mat


def _by_polygon_size(total: np.ndarray):
    for n in np.unique(total):
        yield int(n), np.nonzero(total == n)[0]


def _linear_color_to_srgb(rgb) -> np.ndarray:
    return core.linear_to_srgb(np.asarray(rgb, dtype=np.float64)[..., :3])


# --------------------------------------------------------------------------- materiály a textúry


def _principled(mat):
    if not mat or not mat.node_tree:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def material_image(mat):
    """Obrázok pripojený k Base Color (alebo prvý obrázok v materiáli)."""
    if not mat or not mat.node_tree:
        return None
    p = _principled(mat)
    if p is not None:
        links = p.inputs["Base Color"].links
        if links and links[0].from_node.type == "TEX_IMAGE" and links[0].from_node.image:
            return links[0].from_node.image
    return next((n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None)


def material_base_srgb(mat) -> np.ndarray:
    if mat is None:
        return np.array([0.8, 0.8, 0.8])
    p = _principled(mat)
    if p is not None:
        return _linear_color_to_srgb(p.inputs["Base Color"].default_value)
    return _linear_color_to_srgb(mat.diffuse_color)


def image_pixels_srgb(img) -> np.ndarray | None:
    """(h,w,3) sRGB 0..1. 8-bitové sRGB obrázky vracia Blender už v sRGB, float/lineárne sú lineárne."""
    w, h = img.size
    if w == 0 or h == 0:
        return None
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    rgb = buf.reshape(h, w, 4)[..., :3].astype(np.float64)
    if img.is_float or img.colorspace_settings.name not in ("sRGB", "Non-Color"):
        rgb = core.linear_to_srgb(rgb)
    return np.clip(rgb, 0, 1)


def _texture_colors(mesh, obj, start, total, mat_idx, rgb_out, filled):
    if not mesh.uv_layers.active:
        return
    uv = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    mesh.uv_layers.active.uv.foreach_get("vector", uv)
    uv = uv.reshape(-1, 2).astype(np.float64)

    slots = len(obj.material_slots)
    cache: dict[str, np.ndarray | None] = {}
    for slot in range(max(slots, 1)):
        img = material_image(obj.material_slots[slot].material) if slot < slots else None
        if img is None:
            continue
        if img.name not in cache:
            cache[img.name] = image_pixels_srgb(img)
        pix = cache[img.name]
        if pix is None:
            continue
        h, w, _ = pix.shape
        in_slot = (np.clip(mat_idx, 0, max(slots - 1, 0)) == slot)
        for n, faces in _by_polygon_size(total):
            faces = faces[in_slot[faces]]
            if len(faces) == 0:
                continue
            loops = start[faces, None] + np.arange(n)[None, :]
            pts = uv[loops]  # (N,n,2)
            centroid = pts.mean(axis=1, keepdims=True)
            # stred plochy + body na polceste od stredu k rohom (nezasahujú do susednej farby)
            samples = np.concatenate([centroid, 0.5 * (pts + centroid)], axis=1) if n <= 16 else centroid
            x = np.clip(np.floor((samples[..., 0] % 1.0) * w).astype(np.int64), 0, w - 1)
            y = np.clip(np.floor((samples[..., 1] % 1.0) * h).astype(np.int64), 0, h - 1)
            rgb_out[faces] = _mode_color(pix[y, x])
            filled[faces] = True


def _material_colors(obj, mat_idx, rgb_out, filled, only_missing=True):
    slots = len(obj.material_slots)
    for slot in range(max(slots, 1)):
        mat = obj.material_slots[slot].material if slot < slots else None
        sel = np.clip(mat_idx, 0, max(slots - 1, 0)) == slot
        if only_missing:
            sel &= ~filled
        if sel.any():
            rgb_out[sel] = material_base_srgb(mat)
            filled[sel] = True


# --------------------------------------------------------------------------- farby vrcholov


def _vertex_colors(mesh, start, total, rgb_out, filled):
    attrs = mesh.color_attributes
    if len(attrs) == 0:
        return
    attr = attrs.active_color or attrs[0]
    raw = np.empty(len(attr.data) * 4, dtype=np.float32)
    attr.data.foreach_get("color", raw)
    col = _linear_color_to_srgb(raw.reshape(-1, 4))
    if attr.domain == "POINT":
        vert = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get("vertex_index", vert)
        per_loop = col[vert]
    else:
        per_loop = col
    for n, faces in _by_polygon_size(total):
        loops = start[faces, None] + np.arange(n)[None, :]
        rgb_out[faces] = _mode_color(per_loop[loops])
        filled[faces] = True


# --------------------------------------------------------------------------- hlavný vstup


def available_sources(obj) -> list[str]:
    mesh = obj.data
    out = []
    if mesh.uv_layers.active and any(material_image(s.material) for s in obj.material_slots):
        out.append("TEXTURE")
    if len(mesh.color_attributes):
        out.append("VERTEX")
    out.append("MATERIAL")
    return out


def face_colors(obj, source: str = "AUTO"):
    """Vráti (rgb (F,3) sRGB, použitý zdroj, poznámky)."""
    mesh = obj.data
    n = len(mesh.polygons)
    if n == 0:
        raise NoColorData("Mesh has no faces.")
    avail = available_sources(obj)
    notes: list[str] = []
    used = source
    if source == "AUTO":
        used = avail[0]
    elif source not in avail:
        raise NoColorData(f"Source '{source}' is not available on this object (found: {', '.join(avail)}).")

    start, total, mat_idx = _polygon_arrays(mesh)
    rgb = np.zeros((n, 3))
    filled = np.zeros(n, dtype=bool)
    if used == "TEXTURE":
        _texture_colors(mesh, obj, start, total, mat_idx, rgb, filled)
        if not filled.all():
            notes.append(f"{int((~filled).sum())} faces had no texture; used material color.")
            _material_colors(obj, mat_idx, rgb, filled)
    elif used == "VERTEX":
        _vertex_colors(mesh, start, total, rgb, filled)
    else:
        _material_colors(obj, mat_idx, rgb, filled, only_missing=False)
    return rgb, used, notes


def mesh_adjacency(mesh) -> np.ndarray:
    """Dvojice plôch, ktoré zdieľajú hranu."""
    start, total, _ = _polygon_arrays(mesh)
    count = len(mesh.loops)
    vert = np.empty(count, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", vert)
    face_of_loop = np.repeat(np.arange(len(total)), total)
    first = np.repeat(start, total)
    size = np.repeat(total, total)
    idx = np.arange(count)
    nxt = first + (idx - first + 1) % size
    return core.face_adjacency(face_of_loop, vert, vert[nxt])
