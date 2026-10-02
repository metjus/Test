import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon" / "smart_cut"))
import geom  # noqa: E402


def circle(n=200, r=1.0):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([r * np.cos(t), r * np.sin(t), np.zeros(n)], axis=1)


def test_resample_is_uniform_and_keeps_ends():
    pts = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [3, 1, 0]], float)
    r = geom.resample(pts, 50)
    assert np.allclose(r[0], pts[0]) and np.allclose(r[-1], pts[-1])
    d = np.linalg.norm(np.diff(r, axis=0), axis=1)
    assert d.std() / d.mean() < 0.3  # na rohoch sa trochu skracuje


def test_smooth_removes_jitter_without_shrinking_a_closed_loop():
    rng = np.random.default_rng(3)
    c = circle(300)
    noisy = c + rng.normal(0, 0.03, c.shape)
    s = geom.smooth_polyline(noisy, 0.6, closed=True)
    r_noisy = np.linalg.norm(noisy[:, :2], axis=1)
    r_smooth = np.linalg.norm(s[:, :2], axis=1)
    assert r_smooth.std() < 0.4 * r_noisy.std()
    assert abs(r_smooth.mean() - 1.0) < 0.02  # kružnica sa nezmrštila


def test_smooth_pins_endpoints_of_open_line():
    rng = np.random.default_rng(4)
    line = np.stack([np.linspace(0, 5, 100), rng.normal(0, 0.05, 100), np.zeros(100)], axis=1)
    s = geom.smooth_polyline(line, 0.8, closed=False)
    assert np.allclose(s[0], geom.resample(line, len(s))[0]) and np.allclose(s[-1], geom.resample(line, len(s))[-1])
    assert np.abs(s[:, 1]).max() < np.abs(line[:, 1]).max()


def test_strength_zero_is_identity():
    pts = circle(50)
    assert np.allclose(geom.smooth_polyline(pts, 0.0, True), pts)


def grid_graph(w, h):
    idx = np.arange(w * h).reshape(h, w)
    pos = np.stack([np.tile(np.arange(w), h), np.repeat(np.arange(h), w), np.zeros(w * h)], axis=1).astype(float)
    edges = np.concatenate(
        [np.stack([idx[:, :-1].ravel(), idx[:, 1:].ravel()], 1), np.stack([idx[:-1].ravel(), idx[1:].ravel()], 1)]
    )
    return pos, edges


def test_shortest_path_straight_and_with_penalty_detour():
    pos, edges = grid_graph(11, 11)
    start, goal = 0, 10  # po spodnom riadku
    p = geom.shortest_path(pos, edges, start, goal)
    assert p[0] == start and p[-1] == goal and len(p) == 11
    cost = np.ones(len(pos))
    cost[1:10] = 50.0  # spodný riadok je "zakázaný", cesta ho obíde
    q = geom.shortest_path(pos, edges, start, goal, cost)
    assert len(q) > len(p) and q[0] == start and q[-1] == goal


def test_shortest_path_unreachable_returns_none():
    pos, edges = grid_graph(4, 1)
    edges = edges[edges[:, 0] != 1]  # rozpojené
    assert geom.shortest_path(pos, edges, 0, 3) is None


def test_nearest_on_polyline():
    line = circle(100)
    pts = np.array([[2.0, 0, 0], [0, 0.5, 0]])
    near, dist = geom.nearest_on_polyline(pts, line, closed=True)
    assert np.allclose(dist, [1.0, 0.5], atol=0.01)


def test_classify_sides_on_a_tube():
    # "plochy" ako body na valci okolo osi z; čiara v rovine z=0, os rezu = +z
    rng = np.random.default_rng(1)
    z = rng.uniform(-2, 2, 4000)
    a = rng.uniform(0, 2 * np.pi, 4000)
    cent = np.stack([np.cos(a), np.sin(a), z], axis=1)
    curve = circle(120)
    axes = np.tile([0.0, 0.0, 1.0], (120, 1))
    # susednosť: zoradi podľa (z) a prepojí susedov; stačí na súvislosť dvoch polovíc
    order = np.argsort(z)
    adj = np.stack([order[:-1], order[1:]], axis=1)
    side, conflict = geom.classify_sides(cent, curve, axes, band=0.3, adj=adj)
    assert conflict < 0.01
    assert (side[z > 0.5] == 1).all() and (side[z < -0.5] == 0).all()
