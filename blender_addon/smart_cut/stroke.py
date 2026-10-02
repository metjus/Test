"""Skladanie čiary z viacerých ťahov. Medzery medzi ťahmi (napr. po otočení pohľadu) sa premostia po povrchu."""
from __future__ import annotations

import numpy as np
from mathutils import Vector

from . import geom, surface


class SurfaceGraph:
    """Mesh ako graf (vrcholy a hrany) s hľadaním najkratšej cesty po povrchu."""

    def __init__(self, obj):
        self.obj = obj
        mesh = obj.data
        self.co, self.edges = surface.mesh_arrays(mesh)
        self.avg = surface.mean_edge_length(mesh)
        self.tree = surface.build_bvh(mesh)
        n = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
        mesh.vertex_normals.foreach_get("vector", n)
        self.normals = n.reshape(-1, 3)

    def nearest_vertex(self, p_local) -> int:
        hit = self.tree.find_nearest(Vector(p_local))
        poly = self.obj.data.polygons[hit[2]]
        verts = list(poly.vertices)
        d = np.linalg.norm(self.co[verts] - np.asarray(p_local), axis=1)
        return int(verts[int(d.argmin())])

    def path(self, a_local, b_local):
        """Vrcholy najkratšej cesty od a po b (lokálne súradnice a normály) alebo None."""
        va, vb = self.nearest_vertex(a_local), self.nearest_vertex(b_local)
        if va == vb:
            return np.empty((0, 3)), np.empty((0, 3))
        p = geom.shortest_path(self.co, self.edges, va, vb)
        if p is None:
            return None
        return self.co[p], self.normals[p]


class StrokeBuilder:
    """Zoznam ťahov ako body (svetové súradnice, normála). Nový ťah naviaže na koniec predošlého."""

    def __init__(self, obj, initial=None):
        self.obj = obj
        self.pieces: list[list] = []
        if initial is not None and len(initial):
            self.pieces.append([(Vector(p), Vector(n)) for p, n in initial])
        self._graph: SurfaceGraph | None = None

    @property
    def graph(self) -> SurfaceGraph:
        if self._graph is None:
            self._graph = SurfaceGraph(self.obj)
        return self._graph

    def points(self):
        return [pt for piece in self.pieces for pt in piece]

    def last_point(self):
        pts = self.points()
        return pts[-1] if pts else None

    def begin(self, hit):
        """Začne nový ťah. Ak už nejaká čiara existuje, medzera sa premostí po povrchu."""
        piece = []
        last = self.last_point()
        if last is not None:
            piece.extend(self._bridge(last, hit))
        piece.append(hit)
        self.pieces.append(piece)

    def add(self, hit):
        if not self.pieces:
            self.pieces.append([])
        self.pieces[-1].append(hit)

    def undo_piece(self) -> bool:
        if self.pieces:
            self.pieces.pop()
            return True
        return False

    def _bridge(self, a, b):
        g = self.graph
        inv = self.obj.matrix_world.inverted()
        a_l, b_l = inv @ a[0], inv @ b[0]
        if (a_l - b_l).length < 3.0 * g.avg:
            return []  # krátka medzera: stačí priama spojnica
        res = g.path(np.array(a_l), np.array(b_l))
        if res is None:
            return []
        co, nrm = res
        mw = self.obj.matrix_world
        m3 = mw.to_3x3()
        return [(mw @ Vector(c), (m3 @ Vector(n)).normalized()) for c, n in zip(co, nrm)]
