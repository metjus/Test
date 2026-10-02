"""Rez meshu podľa uzavretej krivky na povrchu: rozdelenie na strany, spresnenie hranice, uzavretie dielov."""
from __future__ import annotations

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from . import caps, geom, surface


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
        bmesh.ops.recalc_face_normals(part, faces=part.faces)  # vonkajšie normály po pridaní rezu
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


def _thin_border(bm, layer, plan, target_len: float):
    """Zrieďuje body na hrane rezu (zlučuje najkratšie hrany), kým nie sú porovnateľné s okolitou sieťou.

    Spresnenie hrany nechá hranicu niekoľkonásobne hustejšiu než zvyšok modelu; z takej slučky by vznikla
    obrovská mriežka drobných štvoruholníkov. Vrcholy po zlúčení sa vrátia na krivku.
    """
    for _ in range(10):
        border = caps.border_edges(bm, layer)
        short = sorted((e for e in border if e.calc_length() < 0.75 * target_len), key=lambda e: e.calc_length())
        used: set = set()
        pick = []
        for e in short:
            if e.verts[0] in used or e.verts[1] in used:
                continue
            pick.append(e)
            used.update(e.verts)
        pick = pick[: max(0, len(border) - 12)]  # slučka ostane dosť podrobná
        if not pick:
            break
        bmesh.ops.collapse(bm, edges=pick)
        verts = list({v for e in caps.border_edges(bm, layer) for v in e.verts})
        if verts:
            pts = np.array([tuple(v.co) for v in verts])
            snapped, _ = geom.nearest_on_polyline(pts, plan.points, closed=True)
            for v, q in zip(verts, snapped):
                v.co = Vector(q)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()


def _band(bm, layer, rings: int = 3):
    """Vrcholy a plochy do `rings` krokov od hrany rezu."""
    verts = {v for e in caps.border_edges(bm, layer) for v in e.verts}
    faces: set = set()
    for _ in range(rings):
        faces = {f for v in verts for f in v.link_faces}
        verts = {v for f in faces for v in f.verts}
    return verts, faces


def _delaunay_flip(bm, layer, protected: set, rings: int = 3, rounds: int = 12) -> int:
    """Preklápa hrany medzi dvoma trojuholníkmi, kým súčet protiľahlých uhlov nie je <= 180°.
    To zväčšuje najmenšie uhly (odstraňuje úzke trojuholníky). Hrana rezu sa nikdy nepreklopí."""
    total = 0
    for _ in range(rounds):
        _verts, faces = _band(bm, layer, rings)
        edges = {e for f in faces if len(f.verts) == 3 for e in f.edges}
        flipped = 0
        for e in edges:
            if not e.is_valid or e in protected or len(e.link_faces) != 2:
                continue
            f1, f2 = e.link_faces
            if len(f1.verts) != 3 or len(f2.verts) != 3:
                continue
            a, b = e.verts
            c = next(v for v in f1.verts if v is not a and v is not b)
            d = next(v for v in f2.verts if v is not a and v is not b)
            if bm.edges.get((c, d)) is not None:
                continue
            if f1.normal.dot(f2.normal) < 0.5:
                continue  # hrana na záhybe tvaru
            ang_c = (a.co - c.co).angle(b.co - c.co, 0.0)
            ang_d = (a.co - d.co).angle(b.co - d.co, 0.0)
            if ang_c + ang_d > np.pi + 1e-6:
                bmesh.utils.edge_rotate(e, True)
                flipped += 1
        total += flipped
        if not flipped:
            break
    return total


def _relax_band(bm, layer, plan):
    """Po zjednodušení hrany zostanú pri nej úzke trojuholníky. Preklopením hrán (Delaunay) a vyrovnaním vrcholov
    v pásme okolo rezu sa vyrovnajú. Vrcholy sa vracajú na pôvodný povrch, takže sa tvar nezmení."""
    protected = set(caps.border_edges(bm, layer))
    border_verts = {v for e in protected for v in e.verts}
    for _ in range(3):
        _delaunay_flip(bm, layer, protected)
        verts, _faces = _band(bm, layer, 3)
        movable = [v for v in verts if v not in border_verts and not v.is_boundary]
        if not movable:
            break
        bmesh.ops.smooth_vert(
            bm, verts=movable, factor=0.6, use_axis_x=True, use_axis_y=True, use_axis_z=True,
            mirror_clip_x=False, mirror_clip_y=False, mirror_clip_z=False, clip_dist=0.0,
        )
        for v in movable:
            hit = plan.tree.find_nearest(v.co)
            if hit[0] is not None:
                v.co = hit[0]
    _delaunay_flip(bm, layer, protected)


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

    layer_cap = bm.faces.layers.int.new("smartcut_cap")
    perimeter = geom.polyline_length(plan.points, closed=True)
    target = max(plan.avg_edge, perimeter / 200.0)
    _thin_border(bm, layer, plan, target)
    _relax_band(bm, layer, plan)
    border, loops = caps.make_even(bm, layer)
    bm.faces.ensure_lookup_table()
    bmesh.ops.split_edges(bm, edges=border)
    cap_stats = {"quads": 0, "tris": 0, "fallback": 0}
    pairs = caps.twin_loops(bm, loops, layer) if loops else None
    if pairs:
        cap_stats = caps.add_caps(bm, pairs, layer, layer_cap)
    else:
        # nejednoduchá hranica: záloha, trojuholníkové vyplnenie
        holes = [e for e in bm.edges if len(e.link_faces) == 1]
        if holes:
            mids = np.array([tuple((e.verts[0].co + e.verts[1].co) * 0.5) for e in holes])
            _, d = geom.nearest_on_polyline(mids, plan.points, closed=True)
            holes = [e for e, dd in zip(holes, d) if dd <= 2.0 * blen]
        if holes:
            res = bmesh.ops.holes_fill(bm, edges=holes, sides=0)
            if res["faces"]:
                bmesh.ops.triangulate(bm, faces=res["faces"], quad_method="BEAUTY", ngon_method="BEAUTY")
                for f in res["faces"]:
                    f[layer_cap] = 1
        cap_stats["fallback"] = 1
    bm.normal_update()

    parts = _parts_from_bmesh(bm, obj, obj.name)
    bm.free()
    if len(parts) < 2:
        for p in parts:
            bpy.data.objects.remove(p, do_unlink=True)
        raise CutError("The cut did not separate the model into parts.")
    if len(parts) == 2:  # dvojica dielov, ktoré k sebe patria (pre kolíky)
        parts[0]["smartcut_partner"], parts[1]["smartcut_partner"] = parts[1].name, parts[0].name
    if keep_original:
        obj.hide_set(True)
    info = {"parts": len(parts), "faces_before": faces0, "conflict": conflict, "cap": cap_stats}
    return parts, info
