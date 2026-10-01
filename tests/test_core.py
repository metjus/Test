import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon" / "split_by_color"))
import core  # noqa: E402


def grid_adjacency(w, h):
    """Mriežka w×h štvorcov = plochy; sused vľavo/vpravo a hore/dole."""
    idx = np.arange(w * h).reshape(h, w)
    right = np.stack([idx[:, :-1].ravel(), idx[:, 1:].ravel()], axis=1)
    down = np.stack([idx[:-1, :].ravel(), idx[1:, :].ravel()], axis=1)
    return np.concatenate([right, down])


RED, BLACK, SKIN = (0.8, 0.1, 0.1), (0.02, 0.02, 0.02), (0.9, 0.7, 0.55)


def test_flat_colors_are_found_without_knowing_count():
    rgb = np.array([SKIN] * 60 + [RED] * 30 + [BLACK] * 10)
    labels, palette = core.cluster_colors(rgb)
    assert len(palette) == 3
    assert np.bincount(labels).tolist() == [60, 30, 10]
    assert np.allclose(palette[0], SKIN, atol=0.01)


def test_similar_shades_merge_but_distinct_colors_do_not():
    rng = np.random.default_rng(1)
    rgb = np.array([RED] * 50) + rng.normal(0, 0.01, (50, 3))
    rgb = np.concatenate([rgb, np.array([SKIN] * 50)])
    labels, palette = core.cluster_colors(rgb, tolerance=10)
    assert len(palette) == 2


def test_max_colors_merges_smallest_into_nearest():
    rgb = np.array([SKIN] * 50 + [RED] * 30 + [(0.75, 0.15, 0.1)] * 3 + [BLACK] * 17)
    labels, palette = core.cluster_colors(rgb, tolerance=2, max_colors=3)
    assert len(palette) == 3
    # (0.75,0.15,0.1) je takmer červená, takže skončí v nej a nie v čiernej
    assert labels[80] == labels[50]


def test_adjacency_from_two_triangles_sharing_an_edge():
    # trojuholníky (0,1,2) a (1,2,3) majú spoločnú hranu 1-2
    face = np.array([0, 0, 0, 1, 1, 1])
    a = np.array([0, 1, 2, 1, 2, 3])
    b = np.array([1, 2, 0, 2, 3, 1])
    adj = core.face_adjacency(face, a, b)
    assert adj.tolist() == [[0, 1]]


def test_components_and_small_island_cleanup():
    w = h = 10
    adj = grid_adjacency(w, h)
    labels = np.zeros(w * h, dtype=np.int64)
    labels[5 * w + 5] = 1  # osamelá plocha inej farby uprostred
    cleaned = core.merge_small_islands(labels, adj, min_faces=3)
    assert cleaned.max() == 0
    # väčšia škvrna (2x2) sa nechá
    labels[4 * w + 4 : 4 * w + 6] = 1
    labels[5 * w + 4 : 5 * w + 6] = 1
    kept = core.merge_small_islands(labels, adj, min_faces=3)
    assert (kept == 1).sum() == 4


def test_disconnected_small_part_is_kept():
    # dve samostatné časti siete: veľká červená a 2-plošné čierne oko bez spojenia
    adj = np.concatenate([grid_adjacency(5, 5), np.array([[25, 26]])])
    labels = np.array([0] * 25 + [1, 1])
    out = core.merge_small_islands(labels, adj, min_faces=5)
    assert out.tolist() == labels.tolist()


def test_analyze_end_to_end_with_edge_noise():
    w, h = 20, 20
    adj = grid_adjacency(w, h)
    g = np.tile(np.array(SKIN), (h, w, 1))
    g[:, 10:] = RED  # pravá polovica červená
    g[8:12, 3:6] = BLACK  # čierne "oko"
    g[2, 15] = (0.5, 0.5, 0.5)  # šum: jedna sivá plocha v červenej
    rgb = g.reshape(-1, 3)
    res = core.analyze(rgb, adj, tolerance=10, min_island_faces=3)
    assert len(res.palette) == 3
    assert res.counts.sum() == w * h
    assert res.labels[2 * w + 15] == res.labels[2 * w + 14]  # šum sa pripojil k červenej


def test_island_ids_split_same_color_in_two_places():
    adj = grid_adjacency(7, 1)
    labels = np.array([0, 0, 1, 1, 1, 0, 0])
    ids = core.island_ids(labels, adj)
    assert len(np.unique(ids)) == 3
    assert ids[0] == ids[1] and ids[5] == ids[6] and ids[0] != ids[5]


def test_performance_on_large_mesh():
    import time

    w = h = 700  # ~490 000 plôch
    adj = grid_adjacency(w, h)
    g = np.tile(np.array(SKIN), (h, w, 1))
    g[:, 350:] = RED
    rgb = g.reshape(-1, 3)
    t = time.time()
    res = core.analyze(rgb, adj)
    assert len(res.palette) == 2
    assert time.time() - t < 30


def test_blend_band_between_two_colors_is_absorbed_but_real_small_color_stays():
    w, h = 30, 10
    adj = grid_adjacency(w, h)
    g = np.tile(np.array(SKIN), (h, w, 1))
    g[:, 15:] = RED
    mix = (np.array(SKIN) + np.array(RED)) / 2
    g[:, 14:16] = mix  # rozmazaný pás medzi pleťou a červenou
    g[3:6, 3:6] = BLACK  # skutočná malá farba mimo hranice
    res = core.analyze(g.reshape(-1, 3), adj, tolerance=10, min_island_faces=3)
    assert len(res.palette) == 3  # pleť, červená, čierna; pás sa pripojil
    black = res.labels[4 * w + 4]
    assert res.counts[black] == 9
    assert not np.any(res.labels[:, None] == -1)


def test_merge_blends_can_be_switched_off():
    w, h = 30, 10
    adj = grid_adjacency(w, h)
    g = np.tile(np.array(SKIN), (h, w, 1))
    g[:, 15:] = RED
    g[:, 14:16] = (np.array(SKIN) + np.array(RED)) / 2
    res = core.analyze(g.reshape(-1, 3), adj, tolerance=10, min_island_faces=3, merge_blends=False)
    assert len(res.palette) == 3
