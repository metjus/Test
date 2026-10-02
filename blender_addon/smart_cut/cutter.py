"""Rez meshu podľa uzavretej krivky na povrchu: rozdelenie na strany, spresnenie hranice, uzavretie dielov."""
from __future__ import annotations

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import geom, surface


class CutError(Exception):
    pass


class CutPlan:
    """Krivka pripravená na rez: husté body na povrchu a smer osi v každom bode."""

    def __init__(self, obj, curve_world: np.ndarray):
        mesh = obj.data
        self.avg_edge = surface.mean_edge_length(mesh)
        tree = surface.build_bvh(mesh)
        local = surface.to_local(obj, curve_world)
        if len(local) < 8:
            raise CutError("The curve has too few points.")
        length = geom.polyline_length(local, closed=True)
        count = int(np.clip(length / (0.35 * self.avg_edge), 96, 6000))
        dense = geom.resample(local, count, closed=True)
        pts, nrm = surface.project_to_surface(tree, dense)
        pts, nrm = surface.project_to_surface(tree, geom.resample(pts, count, closed=True))
        self.points = pts
        t = geom.tangents(pts, closed=True)
        ax = np.cross(t, nrm)
        for i in range(1, len(ax)):  # jednotná orientácia pozdĺž slučky
            if ax[i] @ ax[i - 1] < 0:
                ax[i] = -ax[i]
        self.axes = geom.smooth_vectors(ax, rounds=6)
        self.tree = tree

    def side_labels(self, mesh):
        cent = surface.face_centroids(mesh)
        adj = surface.face_adjacency(mesh)
        if len(adj) == 0:
            raise CutError("The mesh has no connected faces.")
        d = np.linalg.norm(cent[adj[:, 0]] - cent[adj[:, 1]], axis=1)
        band = 2.5 * float(np.median(d))
        side, conflict = geom.classify_sides(cent, self.points, self.axes, band, adj)
        return side, adj, conflict


def _subdivide_border(mesh, labels: np.ndarray, adj: np.ndarray):
    differ = labels[adj[:, 0]] != labels[adj[:, 1]]
    if not differ.any():
        return False
    faces = np.unique(adj[differ].ravel())
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    edges = {e for fi in faces.tolist() for e in bm.faces[fi].edges}
    bmesh.ops.subdivide_edges(bm, edges=list(edges), cuts=1, use_grid_fill=True)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return True


def _parts_from_bmesh(bm, src_obj, name_base: str):
    """Rozdelí bmesh na súvislé časti a vytvorí z nich objekty."""
    bm.faces.ensure_lookup_table()
    comp = [-1] * len(bm.faces)
    n = 0
    for f in bm.faces:
        if comp[f.index] != -1:
            continue
        stack = [f]
        comp[f.index] = n
        while stack:
            cur = stack.pop()
            for e in cur.edges:
                for g in e.link_faces:
                    if comp[g.index] == -1:
                        comp[g.index] = n
                        stack.append(g)
        n += 1
    objs = []
    sizes = [comp.count(i) for i in range(n)]
    order = sorted(range(n), key=lambda i: -sizes[i])
    for rank, c in enumerate(order):
        part = bm.copy()
        part.faces.ensure_lookup_table()
        drop = [f for f in part.faces if comp[f.index] != c]
        bmesh.ops.delete(part, geom=drop, context="FACES")
        mesh = bpy.data.meshes.new(f"{name_base}_part{rank + 1}")
        part.to_mesh(mesh)
        part.free()
        for m in src_obj.data.materials:
            mesh.materials.append(m)
        ob = bpy.data.objects.new(mesh.name, mesh)
        ob.matrix_world = src_obj.matrix_world
        ob.parent = src_obj.parent
        for coll in src_obj.users_collection:
            coll.objects.link(ob)
        objs.append(ob)
    return objs


def cut_object(obj, curve_world: np.ndarray, refine_levels: int = 3, keep_original: bool = True, max_conflict: float = 0.2):
    """Rozreže `obj` podľa uzavretej krivky. Vráti (zoznam nových objektov, informácie)."""
    mesh = obj.data
    plan = CutPlan(obj, curve_world)

    faces0 = len(mesh.polygons)
    labels, adj, conflict = plan.side_labels(mesh)
    if conflict > max_conflict:
        raise CutError(
            "This loop does not split the model into two parts (it may not go all the way around). "
            "Try Complete Loop or adjust the curve."
        )
    if labels.min() == labels.max():
        raise CutError("The curve is not on the model surface, nothing was cut.")
    for _ in range(max(0, refine_levels)):
        if not _subdivide_border(mesh, labels, adj):
            break
        labels, adj, conflict = plan.side_labels(mesh)

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    layer = bm.faces.layers.int.new("smartcut_side")
    for f in bm.faces:
        f[layer] = int(labels[f.index])

    border = [e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0][layer] != e.link_faces[1][layer]]
    if not border:
        bm.free()
        raise CutError("No border found along the curve.")
    border_verts = {v for e in border for v in e.verts}
    blen = float(np.mean([e.calc_length() for e in border]))

    # vrcholy na hranici sa presunú na krivku, takže rez ide presne po nakreslenej čiare
    pts = np.array([tuple(v.co) for v in border_verts])
    snapped, dist = geom.nearest_on_polyline(pts, plan.points, closed=True)
    for v, q, d in zip(border_verts, snapped, dist):
        if d <= 1.5 * blen:
            v.co = Vector(q)
    bmesh.ops.remove_doubles(bm, verts=list(border_verts), dist=0.02 * blen)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    border = [e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0][layer] != e.link_faces[1][layer]]
    bmesh.ops.split_edges(bm, edges=border)
    holes = [e for e in bm.edges if len(e.link_faces) == 1]
    if holes:
        mids = np.array([tuple((e.verts[0].co + e.verts[1].co) * 0.5) for e in holes])
        _, d = geom.nearest_on_polyline(mids, plan.points, closed=True)
        holes = [e for e, dd in zip(holes, d) if dd <= 2.0 * blen]
    if holes:
        res = bmesh.ops.holes_fill(bm, edges=holes, sides=0)
        if res["faces"]:
            bmesh.ops.triangulate(bm, faces=res["faces"], quad_method="BEAUTY", ngon_method="BEAUTY")
    bm.normal_update()

    parts = _parts_from_bmesh(bm, obj, obj.name)
    bm.free()
    if len(parts) < 2:
        for p in parts:
            bpy.data.objects.remove(p, do_unlink=True)
        raise CutError("The cut did not separate the model into parts.")
    if keep_original:
        obj.hide_set(True)
    info = {"parts": len(parts), "faces_before": faces0, "conflict": conflict}
    return parts, info
