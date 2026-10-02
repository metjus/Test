"""Zakrytie rezu: pravidelné štvoruholníky namiesto vejára trojuholníkov, a rovnaká plocha na oboch dieloch."""
from __future__ import annotations

import bmesh
import numpy as np


def border_edges(bm, layer):
    return [e for e in bm.edges if len(e.link_faces) == 2 and e.link_faces[0][layer] != e.link_faces[1][layer]]


def ordered_loops(edges):
    """Hrany hranice zoradené do uzavretých slučiek (zoznamy vrcholov). Vráti None, ak hranica nie je jednoduchá."""
    by_vert: dict = {}
    for e in edges:
        for v in e.verts:
            by_vert.setdefault(v, []).append(e)
    if any(len(es) != 2 for es in by_vert.values()):
        return None
    seen: set = set()
    loops = []
    for e0 in edges:
        if e0 in seen:
            continue
        loop = []
        e, v = e0, e0.verts[0]
        while e not in seen:
            seen.add(e)
            loop.append(v)
            v = e.other_vert(v)
            nxt = [x for x in by_vert[v] if x is not e]
            e = nxt[0]
        if v is not loop[0]:
            return None
        loops.append(loop)
    return loops


def make_even(bm, layer):
    """Mriežka (Grid Fill) potrebuje párny počet hrán. V nepárnej slučke sa rozpolí najdlhšia hrana (aj v susedných plochách)."""
    for _ in range(4):
        border = border_edges(bm, layer)
        loops = ordered_loops(border)
        if loops is None:
            return border, None
        odd = [lp for lp in loops if len(lp) % 2]
        if not odd:
            return border, loops
        for lp in odd:
            n = len(lp)
            edges = [e for i in range(n) for e in lp[i].link_edges if e.other_vert(lp[i]) is lp[(i + 1) % n] and e in set(border)]
            longest = max(edges, key=lambda e: e.calc_length())
            _new_edge, new_v = bmesh.utils.edge_split(longest, longest.verts[0], 0.5)
            ngons = [f for f in new_v.link_faces if len(f.verts) > 3 and len(f.verts) != 4]
            if ngons:
                bmesh.ops.triangulate(bm, faces=ngons)
    return border_edges(bm, layer), ordered_loops(border_edges(bm, layer))


def _side_cost(pts: np.ndarray, s: int, p: int) -> float:
    """Čím rovnomernejšie bunky (dĺžka strany / počet hrán na všetkých štyroch stranách), tým nižšia cena."""
    n = len(pts)
    q = n // 2 - p
    idx = np.arange(n)
    seg = np.linalg.norm(pts[(idx + 1) % n] - pts[idx], axis=1)

    def length(a, count):
        return float(seg[(s + a + np.arange(count)) % n].sum())

    la, lb, lc, ld = length(0, p), length(p, q), length(p + q, p), length(2 * p + q, q)
    cells = np.array([la / p, lb / q, lc / p, ld / q])
    return float(cells.std() / max(cells.mean(), 1e-12))


def quad_patch(points: np.ndarray, relax: int = 8):
    """Vyplní uzavretú slučku bodov mriežkou štvoruholníkov (Coonsova plocha medzi štyrmi stranami).

    Vráti (súradnice, plochy ako indexy) alebo None. Prvých n súradníc je hranica v pôvodnom poradí, ďalšie sú
    vnútorné body. Potrebuje párny počet bodov.
    """
    pts = np.asarray(points, dtype=np.float64)
    n = len(pts)
    if n < 4 or n % 2:
        return None
    half = n // 2
    best = None
    for p in {max(1, half // 2 - 1), max(1, half // 2), max(1, half // 2 + 1)}:
        if p >= half:
            continue
        for s in range(0, n, max(1, n // 16)):
            c = _side_cost(pts, s, p)
            if best is None or c < best[0]:
                best = (c, s, p)
    if best is None:
        return None
    _, s, p = best
    q = half - p
    loop = lambda k: pts[(s + k) % n]  # noqa: E731
    A = np.array([loop(i) for i in range(p + 1)])
    R = np.array([loop(p + j) for j in range(q + 1)])
    T = np.array([loop(2 * p + q - i) for i in range(p + 1)])
    L = np.array([loop(n - j) for j in range(q + 1)])
    u = (np.arange(p + 1) / p)[:, None, None]
    v = (np.arange(q + 1) / q)[None, :, None]
    P = (
        (1 - v) * A[:, None, :] + v * T[:, None, :]
        + (1 - u) * L[None, :, :] + u * R[None, :, :]
        - ((1 - u) * (1 - v) * A[0] + u * (1 - v) * A[p] + (1 - u) * v * T[0] + u * v * T[p])
    )
    # vyrovnanie vnútorných bodov (hranica sa nehýbe)
    for _ in range(relax):
        inner = 0.25 * (P[:-2, 1:-1] + P[2:, 1:-1] + P[1:-1, :-2] + P[1:-1, 2:])
        P[1:-1, 1:-1] = 0.5 * P[1:-1, 1:-1] + 0.5 * inner

    # indexy uzlov: hranica podľa pôvodného poradia, vnútro nasleduje
    index = -np.ones((p + 1, q + 1), dtype=np.int64)
    for i in range(p + 1):
        index[i, 0] = (s + i) % n
        index[i, q] = (s + 2 * p + q - i) % n
    for j in range(q + 1):
        index[p, j] = (s + p + j) % n
        index[0, j] = (s + n - j) % n
    inner_pts = []
    for i in range(1, p):
        for j in range(1, q):
            index[i, j] = n + len(inner_pts)
            inner_pts.append(P[i, j])
    coords = np.vstack([pts] + ([np.array(inner_pts)] if inner_pts else []))
    faces = [
        (int(index[i, j]), int(index[i + 1, j]), int(index[i + 1, j + 1]), int(index[i, j + 1]))
        for i in range(p)
        for j in range(q)
    ]
    # kontrola: žiadny štvoruholník nesmie byť preklopený voči ostatným
    f = np.array(faces)
    d1 = coords[f[:, 2]] - coords[f[:, 0]]
    d2 = coords[f[:, 3]] - coords[f[:, 1]]
    nrm = np.cross(d1, d2)
    mean = nrm.sum(axis=0)
    if np.linalg.norm(mean) < 1e-12 or ((nrm @ mean) <= 0).any():
        return None
    return coords, faces


def triangle_patch(points: np.ndarray):
    """Záloha: trojuholníkové vyplnenie, keď sa mriežka nedá vytvoriť."""
    n = len(points)
    tmp = bmesh.new()
    try:
        tv = [tmp.verts.new(tuple(p)) for p in points]
        te = [tmp.edges.new((tv[i], tv[(i + 1) % n])) for i in range(n)]
        res = bmesh.ops.holes_fill(tmp, edges=te, sides=0)
        if res["faces"]:
            bmesh.ops.triangulate(tmp, faces=res["faces"], quad_method="BEAUTY", ngon_method="BEAUTY")
        tmp.verts.index_update()
        coords = np.array([tuple(v.co) for v in tmp.verts])
        idx = [tuple(v.index for v in f.verts) for f in tmp.faces]
        return coords, idx
    finally:
        tmp.free()


def twin_loops(bm, loops, layer):
    """Po rozdelení hrán nájde pre každý vrchol slučky jeho dvojicu na druhej strane. Vráti [(strana0, strana1)]."""
    index: dict = {}
    for v in bm.verts:
        if any(len(e.link_faces) == 1 for e in v.link_edges):
            index.setdefault(tuple(v.co), []).append(v)
    out = []
    for loop in loops:
        a, b = [], []
        for v in loop:
            cands = index.get(tuple(v.co), [])
            by_side = {}
            for c in cands:
                if c.link_faces:
                    by_side[c.link_faces[0][layer]] = c
            if len(by_side) != 2:
                return None
            a.append(by_side[0])
            b.append(by_side[1])
        out.append((a, b))
    return out


def add_caps(bm, pairs, layer_side, layer_cap) -> dict:
    """Do oboch dielov vloží tú istú sieť štvoruholníkov (druhá strana zrkadlovo), takže plochy rezu presne lícujú."""
    stats = {"quads": 0, "tris": 0, "fallback": 0}
    for side0, side1 in pairs:
        pts = np.array([tuple(v.co) for v in side0])
        patch = quad_patch(pts)
        if patch is None:
            patch = triangle_patch(pts)
            stats["fallback"] += 1
        coords, faces = patch
        n = len(side0)
        for side, ring in ((0, side0), (1, side1)):
            verts = list(ring) + [bm.verts.new(tuple(c)) for c in coords[n:]]
            for f in faces:
                vs = [verts[i] for i in f]
                if side == 1:
                    vs.reverse()
                try:
                    face = bm.faces.new(vs)
                except ValueError:
                    continue
                face[layer_side] = side
                face[layer_cap] = 1
        for f in faces:
            if len(f) == 4:
                stats["quads"] += 1
            else:
                stats["tris"] += 1
    return stats
