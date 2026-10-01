"""Delenie siete podľa farby: čistý numpy, bez Blenderu (preto sa dá testovať samostatne).

Vstup je farba každej plochy (sRGB 0..1) a zoznam susedných plôch. Výstup je číslo skupiny pre každú plochu
a paleta farieb skupín.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_M = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
)
_WHITE = np.array([0.95047, 1.0, 1.08883])


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    xyz = (srgb_to_linear(rgb) @ _M.T) / _WHITE
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


@dataclass
class Result:
    labels: np.ndarray  # (F,) číslo skupiny každej plochy, 0 = najväčšia skupina
    palette: np.ndarray  # (K,3) sRGB farba skupiny
    counts: np.ndarray  # (K,) počet plôch v skupine


# --------------------------------------------------------------------------- susednosť a súvislosť


def face_adjacency(face_of_loop: np.ndarray, vert_a: np.ndarray, vert_b: np.ndarray) -> np.ndarray:
    """Dvojice plôch so spoločnou hranou. Každý loop = hrana (vert_a, vert_b) patriaca ploche face_of_loop."""
    lo = np.minimum(vert_a, vert_b).astype(np.int64)
    hi = np.maximum(vert_a, vert_b).astype(np.int64)
    key = lo * (int(hi.max(initial=0)) + 1) + hi
    order = np.argsort(key, kind="stable")
    k, f = key[order], face_of_loop[order]
    same = (k[1:] == k[:-1]) & (f[1:] != f[:-1])
    return np.stack([f[:-1][same], f[1:][same]], axis=1).astype(np.int64)


def connected_components(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Zložky grafu s n uzlami a hranami (a,b). Vráti číslo zložky pre každý uzol (0..C-1)."""
    parent = list(range(n))

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for x, y in zip(a.tolist(), b.tolist()):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)
    roots = np.fromiter((find(i) for i in range(n)), dtype=np.int64, count=n)
    return np.unique(roots, return_inverse=True)[1].astype(np.int64)


def island_ids(labels: np.ndarray, adj: np.ndarray) -> np.ndarray:
    """Číslo súvislého kusu (plochy rovnakej farby, ktoré na seba nadväzujú)."""
    if len(adj) == 0:
        return np.arange(len(labels), dtype=np.int64)
    same = labels[adj[:, 0]] == labels[adj[:, 1]]
    return connected_components(len(labels), adj[same, 0], adj[same, 1])


# --------------------------------------------------------------------------- zoskupenie farieb


def cluster_colors(rgb: np.ndarray, tolerance: float = 10.0, max_colors: int = 0):
    """Zoskupí podobné farby. tolerance je vzdialenosť v Lab (ΔE, ~2 sotva rozoznateľné, ~10 jasný rozdiel).

    Postup: rovnaké farby sa spočítajú, najčastejšia sa stane stredom skupiny, všetko do `tolerance` od nej
    sa k nej pridá, potom ďalšia najčastejšia z ostatných. Pri plochých farbách tak vzniknú presne tie farby,
    ktoré v modeli sú, a nemusíš poznať ich počet. max_colors > 0 zlúči najmenšie skupiny k najbližším väčším.
    """
    rgb = np.clip(np.asarray(rgb, dtype=np.float64), 0, 1)
    q = np.round(rgb * 255).astype(np.uint8)
    uniq, inverse, counts = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    inverse = inverse.reshape(-1)
    lab = srgb_to_lab(uniq / 255.0)

    order = np.argsort(-counts, kind="stable")
    group = np.full(len(uniq), -1, dtype=np.int64)
    centers: list[int] = []
    for i in order:
        if group[i] != -1:
            continue
        free = np.nonzero(group == -1)[0]
        near = free[np.linalg.norm(lab[free] - lab[i], axis=1) <= tolerance]
        group[near] = len(centers)
        group[i] = len(centers)
        centers.append(i)

    k = len(centers)
    if max_colors and k > max_colors:
        size = np.bincount(group, weights=counts, minlength=k)
        keep = list(np.argsort(-size, kind="stable")[:max_colors])
        keep_lab = lab[[centers[g] for g in keep]]
        remap = np.empty(k, dtype=np.int64)
        for g in range(k):
            if g in keep:
                remap[g] = keep.index(g)
            else:
                remap[g] = int(np.argmin(np.linalg.norm(keep_lab - lab[centers[g]], axis=1)))
        group = remap[group]
        k = max_colors

    face_group = group[inverse]
    return _compact(face_group, rgb)


def _compact(labels: np.ndarray, rgb: np.ndarray):
    """Preusporiada skupiny podľa veľkosti, zahodí prázdne a vypočíta priemernú farbu každej."""
    ids, inv, counts = np.unique(labels, return_inverse=True, return_counts=True)
    order = np.argsort(-counts, kind="stable")
    rank = np.empty(len(ids), dtype=np.int64)
    rank[order] = np.arange(len(ids))
    new = rank[inv.reshape(-1)]
    palette = np.stack([np.bincount(new, weights=rgb[:, c], minlength=len(ids)) for c in range(3)], axis=1)
    counts = np.bincount(new, minlength=len(ids))
    return new, palette / counts[:, None]


# --------------------------------------------------------------------------- prechodové farby


def merge_blend_colors(labels: np.ndarray, rgb: np.ndarray, adj: np.ndarray, tolerance: float = 10.0) -> np.ndarray:
    """Rozmazané hrany medzi dvoma farbami vytvoria "prechodovú" farbu. Tá sa rozpozná tak, že

    - jej farba leží na úsečke medzi dvoma väčšími skupinami A a B (v sRGB, kde sa obrázok rozmazáva) a
    - jej plochy susedia takmer len s A alebo B.

    Plochy takej skupiny sa rozdelia medzi A a B podľa väčšiny susedov. Skutočná farba, ktorá je inde v modeli
    (oko), tieto podmienky nespĺňa, takže ostane.
    """
    labels = labels.copy()
    if len(adj) == 0:
        return labels
    for _ in range(8):
        k = int(labels.max()) + 1
        if k < 3:
            break
        counts = np.bincount(labels, minlength=k)
        pal = np.stack([np.bincount(labels, weights=rgb[:, c], minlength=k) for c in range(3)], axis=1)
        pal = pal / np.maximum(counts, 1)[:, None]
        lab = srgb_to_lab(pal)
        a, b = adj[:, 0], adj[:, 1]
        cross = labels[a] != labels[b]
        la, lb = labels[a][cross], labels[b][cross]
        # počet hranových dotykov skupiny c s každou skupinou
        touch = np.zeros((k, k), dtype=np.int64)
        np.add.at(touch, (la, lb), 1)
        np.add.at(touch, (lb, la), 1)

        changed = False
        for c in np.argsort(counts):  # od najmenších
            if counts[c] == 0 or touch[c].sum() == 0:
                continue
            others = [g for g in range(k) if g != c and counts[g] > 0]
            best = None
            for i, ga in enumerate(others):
                for gb in others[i + 1:]:
                    if max(counts[ga], counts[gb]) < counts[c]:
                        continue  # c je väčšia než oba konce, takže to nie je len hrana medzi nimi
                    d = pal[gb] - pal[ga]
                    denom = float(d @ d)
                    if denom < 1e-9:
                        continue
                    t = float(np.clip((pal[c] - pal[ga]) @ d / denom, 0, 1))
                    if not 0.05 <= t <= 0.95:
                        continue
                    near = srgb_to_lab((pal[ga] + t * d)[None, :])[0]
                    dist = float(np.linalg.norm(lab[c] - near))
                    share = (touch[c, ga] + touch[c, gb]) / touch[c].sum()
                    if dist <= tolerance * 0.8 and share >= 0.7 and (best is None or dist < best[0]):
                        best = (dist, ga, gb, t)
            if best is None:
                continue
            _, ga, gb, t = best
            faces = np.nonzero(labels == c)[0]
            in_c = np.zeros(len(labels), dtype=bool)
            in_c[faces] = True
            votes = np.zeros((len(labels), 2), dtype=np.int64)
            for x, y in ((a, b), (b, a)):
                m = in_c[x]
                np.add.at(votes[:, 0], x[m], (labels[y[m]] == ga).astype(np.int64))
                np.add.at(votes[:, 1], x[m], (labels[y[m]] == gb).astype(np.int64))
            pick_b = np.where(votes[faces, 0] == votes[faces, 1], t >= 0.5, votes[faces, 1] > votes[faces, 0])
            labels[faces] = np.where(pick_b, gb, ga)
            changed = True
            break  # farby sa zmenili, spočítať odznova
        if not changed:
            break
    return _compact(labels, rgb)[0]


def _limit_colors(labels: np.ndarray, rgb: np.ndarray, max_colors: int) -> np.ndarray:
    """Zlúči najmenšie skupiny k najbližšej z `max_colors` najväčších."""
    labels, pal = _compact(labels, rgb)
    if len(pal) <= max_colors:
        return labels
    lab = srgb_to_lab(pal)
    remap = np.arange(len(pal))
    for g in range(max_colors, len(pal)):  # skupiny sú zoradené podľa veľkosti
        remap[g] = int(np.argmin(np.linalg.norm(lab[:max_colors] - lab[g], axis=1)))
    return remap[labels]


# --------------------------------------------------------------------------- čistenie šumu


def merge_small_islands(labels: np.ndarray, adj: np.ndarray, min_faces: int, max_rounds: int = 10) -> np.ndarray:
    """Malé kusy (< min_faces plôch) pripojí k susednej skupine, s ktorou majú najviac spoločných hrán.

    Kus bez suseda (samostatná časť siete, napr. oko) sa nechá, lebo ho nie je k čomu pripojiť.
    """
    labels = labels.copy()
    if min_faces <= 1 or len(adj) == 0:
        return labels
    for _ in range(max_rounds):
        comp = island_ids(labels, adj)
        size = np.bincount(comp)
        small = size[comp] < min_faces
        a, b = adj[:, 0], adj[:, 1]
        cross = labels[a] != labels[b]
        src = np.concatenate([a[cross], b[cross]])
        dst = np.concatenate([b[cross], a[cross]])
        use = small[src]
        if not use.any():
            break
        k = int(labels.max()) + 1
        key = comp[src[use]] * k + labels[dst[use]]
        uk, votes = np.unique(key, return_counts=True)
        best: dict[int, tuple[int, int]] = {}
        for kk, v in zip(uk.tolist(), votes.tolist()):
            c, lab = divmod(kk, k)
            if c not in best or v > best[c][0]:
                best[c] = (v, lab)
        new = labels.copy()
        for f in np.nonzero(small)[0]:
            c = int(comp[f])
            if c in best:
                new[f] = best[c][1]
        if np.array_equal(new, labels):
            break
        labels = new
    return labels


# --------------------------------------------------------------------------- celok


def analyze(
    face_rgb: np.ndarray,
    adj: np.ndarray,
    tolerance: float = 10.0,
    max_colors: int = 0,
    min_island_faces: int = 4,
    merge_blends: bool = True,
) -> Result:
    rgb = np.clip(np.asarray(face_rgb, dtype=np.float64), 0, 1)
    labels, _ = cluster_colors(rgb, tolerance, 0)
    if merge_blends:
        labels = merge_blend_colors(labels, rgb, adj, tolerance)
    if max_colors:
        labels = _limit_colors(labels, rgb, max_colors)
    labels = merge_small_islands(labels, adj, min_island_faces)
    labels, palette = _compact(labels, rgb)
    return Result(labels=labels, palette=palette, counts=np.bincount(labels, minlength=len(palette)))
