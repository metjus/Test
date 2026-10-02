"""Čistá geometria bez Blenderu (numpy): vyhladenie čiary, hľadanie cesty po sieti, určenie strán rezu."""
from __future__ import annotations

import heapq

import numpy as np


# --------------------------------------------------------------------------- čiary


def polyline_length(pts: np.ndarray, closed: bool = False) -> float:
    d = np.diff(pts, axis=0)
    total = float(np.linalg.norm(d, axis=1).sum())
    if closed:
        total += float(np.linalg.norm(pts[0] - pts[-1]))
    return total


def resample(pts: np.ndarray, count: int, closed: bool = False) -> np.ndarray:
    """Rovnomerne rozloží `count` bodov po dĺžke čiary."""
    pts = np.asarray(pts, dtype=np.float64)
    work = np.vstack([pts, pts[:1]]) if closed else pts
    seg = np.linalg.norm(np.diff(work, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] <= 1e-12:
        return np.repeat(pts[:1], count, axis=0)
    t = np.linspace(0.0, s[-1], count, endpoint=not closed)
    return np.stack([np.interp(t, s, work[:, k]) for k in range(3)], axis=1)


def smooth_polyline(pts: np.ndarray, strength: float, closed: bool = False) -> np.ndarray:
    """Vyhladí ručne nakreslenú čiaru low-pass filtrom (FFT).

    strength 0 = nič, 1 = veľmi plynulá krivka. Určuje najmenší detail, ktorý ostane (1 % až 26 % dĺžky čiary).
    Uzavretá čiara: najnižšia harmonická (celková veľkosť slučky) ostáva nezmenená, takže sa slučka nezmršťuje.
    Otvorená čiara: koncové body ostávajú na mieste. Rozloženie bodov sa najprv vyrovná, takže tempo ruky nehrá rolu.
    """
    pts = np.asarray(pts, dtype=np.float64)
    if strength <= 0 or len(pts) < 4:
        return pts.copy()
    n = max(len(pts), 128)
    p = resample(pts, n, closed)
    cutoff = 1.0 / (0.01 + 0.25 * strength ** 2)  # počet harmonických, ktoré ešte prejdú
    if closed:
        spec = np.fft.rfft(p, axis=0)
        k = np.arange(spec.shape[0], dtype=np.float64)
        gain = np.exp(-0.5 * (np.maximum(k - 1.0, 0.0) / cutoff) ** 2)
        return np.fft.irfft(spec * gain[:, None], n=n, axis=0)
    line = p[0] + np.linspace(0.0, 1.0, n)[:, None] * (p[-1] - p[0])
    resid = p - line
    ext = np.vstack([resid, -resid[-2:0:-1]])  # nepárne rozšírenie, takže konce ostanú na nule
    spec = np.fft.rfft(ext, axis=0)
    k = np.arange(spec.shape[0], dtype=np.float64)
    gain = np.exp(-0.5 * (k / (2.0 * cutoff)) ** 2)
    out = np.fft.irfft(spec * gain[:, None], n=len(ext), axis=0)[:n]
    return line + out


def tangents(pts: np.ndarray, closed: bool = True) -> np.ndarray:
    if closed:
        d = np.roll(pts, -1, axis=0) - np.roll(pts, 1, axis=0)
    else:
        d = np.gradient(pts, axis=0)
    n = np.linalg.norm(d, axis=1, keepdims=True)
    return d / np.maximum(n, 1e-12)


def smooth_vectors(vecs: np.ndarray, rounds: int = 3) -> np.ndarray:
    """Priemeruje susedné smery pozdĺž uzavretej čiary a znovu ich normalizuje."""
    v = vecs.copy()
    for _ in range(rounds):
        v = 0.25 * np.roll(v, 1, axis=0) + 0.5 * v + 0.25 * np.roll(v, -1, axis=0)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def nearest_on_polyline(points: np.ndarray, line: np.ndarray, closed: bool = True):
    """Najbližší bod na lomenej čiare pre každý bod. Vráti (bod, vzdialenosť)."""
    a = line
    b = np.roll(line, -1, axis=0) if closed else line[1:]
    if not closed:
        a = line[:-1]
    ab = b - a
    ab2 = np.maximum((ab * ab).sum(axis=1), 1e-18)
    best = np.full(len(points), np.inf)
    out = np.zeros_like(points, dtype=np.float64)
    for start in range(0, len(points), 2048):
        p = points[start : start + 2048]
        t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(axis=2) / ab2[None], 0, 1)
        proj = a[None] + t[..., None] * ab[None]
        d = np.linalg.norm(p[:, None, :] - proj, axis=2)
        k = d.argmin(axis=1)
        idx = np.arange(len(p))
        best[start : start + 2048] = d[idx, k]
        out[start : start + 2048] = proj[idx, k]
    return out, best


# --------------------------------------------------------------------------- cesta po sieti


def shortest_path(positions: np.ndarray, edges: np.ndarray, start: int, goal: int, cost: np.ndarray | None = None):
    """A* po hranách meshu. `cost` (na vrchol, >= 1) zdražuje vrcholy, ktorým sa má cesta vyhnúť.

    Vráti zoznam indexov vrcholov od start po goal alebo None, ak cesta neexistuje.
    """
    n = len(positions)
    if cost is None:
        cost = np.ones(n)
    both = np.concatenate([edges, edges[:, ::-1]])
    order = np.argsort(both[:, 0], kind="stable")
    nbr = both[order, 1]
    indptr = np.zeros(n + 1, dtype=np.int64)
    np.add.at(indptr, both[:, 0] + 1, 1)
    indptr = np.cumsum(indptr)

    pos = positions
    goal_pos = pos[goal]
    g = {start: 0.0}
    came: dict[int, int] = {}
    heap = [(float(np.linalg.norm(pos[start] - goal_pos)), start)]
    closed_set: set[int] = set()
    while heap:
        _, u = heapq.heappop(heap)
        if u == goal:
            path = [u]
            while u in came:
                u = came[u]
                path.append(u)
            return path[::-1]
        if u in closed_set:
            continue
        closed_set.add(u)
        gu = g[u]
        for v in nbr[indptr[u] : indptr[u + 1]].tolist():
            if v in closed_set:
                continue
            w = float(np.linalg.norm(pos[u] - pos[v])) * 0.5 * (cost[u] + cost[v])
            ng = gu + w
            if ng < g.get(v, np.inf):
                g[v] = ng
                came[v] = u
                heapq.heappush(heap, (ng + float(np.linalg.norm(pos[v] - goal_pos)), v))
    return None


# --------------------------------------------------------------------------- strany rezu


def _components(n: int, mask: np.ndarray, adj: np.ndarray) -> np.ndarray:
    """Zložky grafu uzlov, kde mask=True. Ostatné dostanú -1."""
    parent = np.arange(n)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ok = mask[adj[:, 0]] & mask[adj[:, 1]]
    for a, b in adj[ok].tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    comp = np.full(n, -1, dtype=np.int64)
    roots = np.array([find(i) for i in np.nonzero(mask)[0].tolist()], dtype=np.int64)
    if len(roots):
        comp[mask] = np.unique(roots, return_inverse=True)[1]
    return comp


def classify_sides(
    centroids: np.ndarray,
    curve: np.ndarray,
    axes: np.ndarray,
    band: float,
    adj: np.ndarray,
):
    """Rozdelí plochy na dve strany uzavretej čiary.

    Plochy do vzdialenosti `band` od čiary sa zaradia podľa toho, na ktorej strane lokálnej roviny čiary ležia
    (rovina je kolmá na `axes`). Ostatné sa pripoja k strane, ku ktorej súvisle patria.
    Vráti (strana 0/1 pre každú plochu, konflikt 0..1). Konflikt blízko 0 znamená čistý rez.
    """
    n = len(centroids)
    best = np.full(n, np.inf)
    nearest = np.zeros(n, dtype=np.int64)
    for start in range(0, n, 4096):
        c = centroids[start : start + 4096]
        d = np.linalg.norm(c[:, None, :] - curve[None], axis=2)
        k = d.argmin(axis=1)
        nearest[start : start + 4096] = k
        best[start : start + 4096] = d[np.arange(len(c)), k]
    near = best <= band
    side = np.full(n, -1, dtype=np.int64)
    sgn = ((centroids[near] - curve[nearest[near]]) * axes[nearest[near]]).sum(axis=1)
    side[near] = (sgn >= 0).astype(np.int64)

    comp = _components(n, ~near, adj)
    conflict_weight = 0
    total_weight = 0
    if comp.max(initial=-1) >= 0:
        k = int(comp.max()) + 1
        votes = np.zeros((k, 2), dtype=np.int64)
        a, b = adj[:, 0], adj[:, 1]
        for x, y in ((a, b), (b, a)):
            m = (comp[x] >= 0) & near[y]
            np.add.at(votes, (comp[x][m], side[y][m]), 1)
        pick = (votes[:, 1] > votes[:, 0]).astype(np.int64)
        tot = votes.sum(axis=1)
        minority = votes.min(axis=1)
        size = np.bincount(comp[comp >= 0], minlength=k)
        # konflikt = veľké súvislé oblasti, ktoré susedia s oboma stranami
        mixed = (minority > 0) & (minority >= 0.15 * np.maximum(tot, 1))
        conflict_weight = int(size[mixed].sum())
        total_weight = int(size.sum())
        side[comp >= 0] = pick[comp[comp >= 0]]
    side[side < 0] = 0
    conflict = conflict_weight / max(total_weight, 1)
    return side, conflict
