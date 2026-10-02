"""Práca s povrchom meshu a krivkami v Blenderi."""
from __future__ import annotations

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector, geometry
from mathutils.bvhtree import BVHTree

from . import geom

CURVE_PROP = "smartcut_target"  # meno objektu, na ktorý krivka patrí


# --------------------------------------------------------------------------- mesh


def mesh_arrays(mesh):
    n = len(mesh.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    e = np.empty(len(mesh.edges) * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", e)
    return co.reshape(-1, 3), e.reshape(-1, 2)


def face_centroids(mesh) -> np.ndarray:
    co, _ = mesh_arrays(mesh)
    start = np.empty(len(mesh.polygons), dtype=np.int64)
    total = np.empty(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("loop_start", start)
    mesh.polygons.foreach_get("loop_total", total)
    vert = np.empty(len(mesh.loops), dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", vert)
    sums = np.add.reduceat(co[vert], start, axis=0)
    return sums / total[:, None]


def face_adjacency(mesh) -> np.ndarray:
    """Dvojice plôch so spoločnou hranou."""
    start = np.empty(len(mesh.polygons), dtype=np.int64)
    total = np.empty(len(mesh.polygons), dtype=np.int64)
    mesh.polygons.foreach_get("loop_start", start)
    mesh.polygons.foreach_get("loop_total", total)
    count = len(mesh.loops)
    vert = np.empty(count, dtype=np.int64)
    mesh.loops.foreach_get("vertex_index", vert)
    face_of_loop = np.repeat(np.arange(len(total)), total)
    first = np.repeat(start, total)
    size = np.repeat(total, total)
    idx = np.arange(count)
    nxt = first + (idx - first + 1) % size
    a, b = vert, vert[nxt]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = lo * (int(hi.max(initial=0)) + 1) + hi
    order = np.argsort(key, kind="stable")
    k, f = key[order], face_of_loop[order]
    same = (k[1:] == k[:-1]) & (f[1:] != f[:-1])
    return np.stack([f[:-1][same], f[1:][same]], axis=1)


def mean_edge_length(mesh) -> float:
    co, e = mesh_arrays(mesh)
    return float(np.linalg.norm(co[e[:, 0]] - co[e[:, 1]], axis=1).mean()) if len(e) else 1.0


def build_bvh(mesh) -> BVHTree:
    co, _ = mesh_arrays(mesh)
    verts = [Vector(v) for v in co]
    polys = [tuple(p.vertices) for p in mesh.polygons]
    return BVHTree.FromPolygons(verts, polys, all_triangles=False)


def project_to_surface(tree: BVHTree, pts: np.ndarray):
    """Najbližší bod na povrchu a jeho normála pre každý bod."""
    out = np.empty_like(pts, dtype=np.float64)
    nrm = np.empty_like(pts, dtype=np.float64)
    for i, p in enumerate(pts):
        hit = tree.find_nearest(Vector(p))
        out[i], nrm[i] = hit[0], hit[1]
    return out, nrm


def _to_local(obj, pts_world: np.ndarray) -> np.ndarray:
    inv = np.array(obj.matrix_world.inverted())
    return pts_world @ inv[:3, :3].T + inv[:3, 3]


def _to_world(obj, pts_local: np.ndarray) -> np.ndarray:
    m = np.array(obj.matrix_world)
    return pts_local @ m[:3, :3].T + m[:3, 3]


to_local, to_world = _to_local, _to_world


# --------------------------------------------------------------------------- krivky


def make_curve_object(name: str, world_pts: np.ndarray, closed: bool, target, size_hint: float = 1.0):
    """Bezierova krivka s automatickými úchytmi. Body sa dajú v Edit Mode ľubovoľne upravovať."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.resolution_u = 12
    cu.bevel_depth = 0.004 * size_hint  # tenká rúrka, aby bola čiara dobre viditeľná
    cu.bevel_resolution = 2
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(world_pts) - 1)
    for bp, p in zip(sp.bezier_points, world_pts):
        bp.co = Vector(p)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    sp.use_cyclic_u = closed
    obj = bpy.data.objects.new(name, cu)
    coll = target.users_collection[0] if target and target.users_collection else bpy.context.scene.collection
    coll.objects.link(obj)
    obj.show_in_front = True
    if target is not None:
        obj[CURVE_PROP] = target.name
    return obj


def curve_points_world(curve_obj, per_segment: int = 12) -> tuple[np.ndarray, bool]:
    """Hustá lomená čiara pozdĺž krivky vo svetových súradniciach a či je uzavretá."""
    sp = curve_obj.data.splines[0]
    pts = []
    if sp.type == "BEZIER":
        bps = sp.bezier_points
        n = len(bps)
        last = n if sp.use_cyclic_u else n - 1
        for i in range(last):
            a, b = bps[i], bps[(i + 1) % n]
            seg = geometry.interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, per_segment + 1)
            pts.extend(seg[:-1])
        if not sp.use_cyclic_u:
            pts.append(bps[-1].co.copy())
    else:
        pts = [p.co.xyz for p in sp.points]
    local = np.array([tuple(p) for p in pts], dtype=np.float64)
    return to_world(curve_obj, local), bool(sp.use_cyclic_u)


def control_points_world(curve_obj) -> np.ndarray:
    sp = curve_obj.data.splines[0]
    pts = sp.bezier_points if sp.type == "BEZIER" else sp.points
    return to_world(curve_obj, np.array([tuple(p.co.xyz) for p in pts]))


def set_control_points_world(curve_obj, world_pts: np.ndarray):
    inv = to_local(curve_obj, world_pts)
    sp = curve_obj.data.splines[0]
    for bp, p in zip(sp.bezier_points, inv):
        bp.co = Vector(p)


# --------------------------------------------------------------------------- dokončenie slučky


def complete_loop(obj, stroke_local: np.ndarray, flip: bool = False, waypoints_local=()):
    """Dopojí otvorený oblúk do uzavretej slučky po povrchu. Vráti hrubú uzavretú lomenú čiaru (lokálne súradnice).

    Cesta od konca späť k začiatku vedie po hranách meshu a vyhýba sa už nakreslenému oblúku, takže ide okolo
    druhej strany. `flip` skúsi opačnú trasu. `waypoints` je dokáže usmerniť.
    """
    mesh = obj.data
    co, edges = mesh_arrays(mesh)
    avg = mean_edge_length(mesh)
    stroke = geom.resample(stroke_local, max(24, int(geom.polyline_length(stroke_local) / avg)))

    tree = build_bvh(mesh)

    def nearest_vertex(p):
        hit = tree.find_nearest(Vector(p))
        poly = mesh.polygons[hit[2]]
        verts = list(poly.vertices)
        d = np.linalg.norm(co[verts] - np.asarray(p), axis=1)
        return int(verts[int(d.argmin())])

    start_v = nearest_vertex(stroke[-1])  # cesta začína na konci oblúka
    goal_v = nearest_vertex(stroke[0])

    def cost_for(extra_paths):
        lo, hi = stroke.min(axis=0) - 3 * avg, stroke.max(axis=0) + 3 * avg
        cand = np.nonzero(((co >= lo) & (co <= hi)).all(axis=1))[0]
        cost = np.ones(len(co))
        if len(cand):
            _, d = geom.nearest_on_polyline(co[cand], stroke, closed=False)
            near_end = np.minimum(
                np.linalg.norm(co[cand] - stroke[0], axis=1), np.linalg.norm(co[cand] - stroke[-1], axis=1)
            )
            pen = (d < 1.6 * avg) & (near_end > 3.5 * avg)
            cost[cand[pen]] = 40.0
        for path in extra_paths:
            interior = path[3:-3] if len(path) > 8 else []
            cost[interior] = 40.0
        return cost

    def route(extra):
        stops = [start_v] + [nearest_vertex(w) for w in waypoints_local] + [goal_v]
        cost = cost_for(extra)
        full = [stops[0]]
        for a, b in zip(stops[:-1], stops[1:]):
            seg = geom.shortest_path(co, edges, a, b, cost)
            if seg is None:
                return None
            full.extend(seg[1:])
        return full

    path = route([])
    if path is None:
        return None
    if flip:
        alt = route([path])
        if alt is not None:
            path = alt
    return np.vstack([stroke, co[path][1:-1]])
