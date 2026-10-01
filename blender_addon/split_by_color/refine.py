"""Spresnenie a vyhladenie farebných hraníc, aby delenie netvorilo zuby."""
import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import core, mesh_colors


def groups_for(obj, source, tolerance, max_colors, min_island_faces, merge_blends):
    """(labels, adjacency) pre aktuálny stav meshu."""
    rgb, _, _ = mesh_colors.face_colors(obj, source)
    adj = mesh_colors.mesh_adjacency(obj.data)
    res = core.analyze(rgb, adj, tolerance, max_colors, min_island_faces, merge_blends)
    return res.labels, adj


def refine_boundaries(obj, levels: int, compute_groups) -> int:
    """Rozdelí plochy pri farebnej hranici a farbu zistí znova z textúry. Vráti počet pridaných plôch."""
    mesh = obj.data
    before = len(mesh.polygons)
    for _ in range(levels):
        labels, adj = compute_groups()
        differ = labels[adj[:, 0]] != labels[adj[:, 1]]
        if not differ.any():
            break
        faces = np.unique(adj[differ].ravel())
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bm.faces.ensure_lookup_table()
        edges = {e for fi in faces.tolist() for e in bm.faces[fi].edges}
        bmesh.ops.subdivide_edges(bm, edges=list(edges), cuts=1, use_grid_fill=True)
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
    return len(mesh.polygons) - before


def smooth_boundaries(obj, labels: np.ndarray, strength: float, iterations: int) -> int:
    """Vyhladí línie medzi farbami (Taubinovo vyhladzovanie bez zmršťovania) a vráti vrcholy k pôvodnému
    povrchu, takže sa tvar modelu skoro nemení. Vrcholy zostávajú spoločné pre obe farby, takže diely lícujú.
    Neposúvajú sa body, kde sa stretávajú tri farby, ani okraje otvorenej siete.
    """
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    surface = BVHTree.FromBMesh(bm)  # pôvodný povrch, na ktorý sa vrcholy vracajú

    nbrs: dict[int, list[int]] = {}
    pinned: set[int] = set()
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) != 2:
            pinned.update(v.index for v in e.verts)  # okraj alebo nemanifold
        elif labels[lf[0].index] != labels[lf[1].index]:
            a, b = e.verts
            nbrs.setdefault(a.index, []).append(b.index)
            nbrs.setdefault(b.index, []).append(a.index)
    movable = [v for v, n in nbrs.items() if len(n) == 2 and v not in pinned]
    if not movable or strength <= 0 or iterations <= 0:
        bm.free()
        return 0

    def step(factor: float):
        target = {}
        for v in movable:
            mid = sum((bm.verts[n].co for n in nbrs[v]), Vector()) / 2.0
            target[v] = bm.verts[v].co.lerp(mid, factor)
        for v, p in target.items():
            hit = surface.find_nearest(p)
            bm.verts[v].co = hit[0] if hit[0] is not None else p

    lam = strength
    mu = -(strength + 0.02)  # opačný krok ruší zmršťovanie
    for _ in range(iterations):
        step(lam)
        step(mu)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(movable)
