"""Testy addonu Smart Cut v skutočnom Blenderi (bpy)."""
import sys
from pathlib import Path

import numpy as np
import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon"))
import bmesh  # noqa: E402
import smart_cut  # noqa: E402
from smart_cut import cutter, geom, operators, surface  # noqa: E402


@pytest.fixture(autouse=True)
def addon():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    smart_cut.register()
    yield
    smart_cut.unregister()


def tube(path, radius=0.4, sides=40, name="Limb"):
    """Uzavretá rúra (s viečkami) vedená po bodoch `path`."""
    path = np.asarray(path, float)
    bm = bmesh.new()
    tang = np.gradient(path, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True)
    up = np.array([0.0, 0.0, 1.0])
    rings = []
    for p, t in zip(path, tang):
        side = np.cross(t, up)
        if np.linalg.norm(side) < 1e-6:
            side = np.cross(t, [0, 1, 0])
        side /= np.linalg.norm(side)
        other = np.cross(side, t)
        ring = [bm.verts.new(p + radius * (np.cos(a) * side + np.sin(a) * other)) for a in np.linspace(0, 2 * np.pi, sides, endpoint=False)]
        rings.append(ring)
    for r0, r1 in zip(rings[:-1], rings[1:]):
        for i in range(sides):
            j = (i + 1) % sides
            bm.faces.new([r0[i], r0[j], r1[j], r1[i]])
    bm.faces.new(rings[0][::-1])
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def straight_tube():
    z = np.linspace(-2, 2, 41)
    return tube(np.stack([np.zeros_like(z), np.zeros_like(z), z], axis=1))


def bent_tube():
    """Rameno s ohybom: štvrťkruh polomeru 2."""
    a = np.linspace(0, np.pi / 2, 41)
    return tube(np.stack([2 * np.sin(a), np.zeros_like(a), 2 * np.cos(a)], axis=1) - [0, 0, 2])


def volume_and_open_edges(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    open_edges = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    vol = bm.calc_volume(signed=True)
    bm.free()
    return vol, open_edges


def ring_curve(obj, z=0.0, wobble=0.0, n=16, radius=0.4):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    pts = np.stack([radius * np.cos(a), radius * np.sin(a), z + wobble * np.sin(2 * a)], axis=1)
    return surface.make_curve_object("Loop", pts, True, obj, 1.0)


def select(obj):
    for o in bpy.context.scene.objects:
        o.select_set(o is obj)
    bpy.context.view_layer.objects.active = obj


def test_straight_cut_gives_two_closed_parts_and_conserves_volume():
    limb = straight_tube()
    v0, o0 = volume_and_open_edges(limb)
    assert o0 == 0
    curve = ring_curve(limb, z=0.3)
    select(curve)
    assert bpy.ops.smartcut.cut(refine_levels=3) == {"FINISHED"}
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]
    assert len(parts) == 2
    vols = []
    for p in parts:
        v, o = volume_and_open_edges(p)
        assert o == 0, "diel musí byť uzavretý"
        assert v > 0
        vols.append(v)
    assert abs(sum(vols) - v0) / v0 < 0.02
    # rez leží pri z = 0,3: objem kratšej časti zodpovedá dĺžke 1,7 z 4
    assert min(vols) / v0 == pytest.approx(1.7 / 4, abs=0.03)


def test_non_planar_cut_on_bent_limb_follows_the_curve():
    limb = bent_tube()
    v0, _ = volume_and_open_edges(limb)
    # šikmá, zvlnená slučka okolo ohybu (nie rovinná)
    a = np.linspace(0, 2 * np.pi, 20, endpoint=False)
    centre = np.array([2 * np.sin(0.8), 0.0, 2 * np.cos(0.8) - 2])
    tangent = np.array([np.cos(0.8), 0.0, -np.sin(0.8)])
    side = np.array([0.0, 1.0, 0.0])
    other = np.cross(tangent, side)
    pts = np.array([centre + 0.4 * (np.cos(t) * side + np.sin(t) * other) + 0.15 * np.sin(2 * t) * tangent for t in a])
    curve = surface.make_curve_object("Loop", pts, True, limb, 1.0)
    select(curve)
    assert bpy.ops.smartcut.cut(refine_levels=3) == {"FINISHED"}
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]
    assert len(parts) == 2
    total = 0.0
    for p in parts:
        v, o = volume_and_open_edges(p)
        assert o == 0 and v > 0
        total += v
    assert abs(total - v0) / v0 < 0.03
    # hrana rezu: vrcholy dielov ležiace na spoločnej hranici sedia na krivke
    dense, _ = surface.curve_points_world(curve, 16)
    a_co = np.array([tuple(v.co) for v in parts[0].data.vertices])
    b_co = np.array([tuple(v.co) for v in parts[1].data.vertices])
    # vrcholy, ktoré existujú v oboch dieloch (zhodná poloha) tvoria hranu rezu
    shared = [p for p in a_co if np.min(np.linalg.norm(b_co - p, axis=1)) < 1e-6]
    assert len(shared) > 30
    _, dist = geom.nearest_on_polyline(np.array(shared), dense, closed=True)
    assert dist.mean() < 0.03 and dist.max() < 0.08


def test_complete_loop_closes_a_partial_arc_around_the_limb():
    limb = straight_tube()
    # 60 % oblúka okolo rúry vo výške z = 0
    t = np.linspace(0, 0.6 * 2 * np.pi, 40)
    arc = np.stack([0.4 * np.cos(t), 0.4 * np.sin(t), np.zeros_like(t)], axis=1)
    curve = operators.build_open_curve(bpy.context, limb, surface.to_world(limb, arc), 0.5, 12)[0]
    assert not curve.data.splines[0].use_cyclic_u
    select(curve)
    assert bpy.ops.smartcut.complete(control_points=16) == {"FINISHED"}
    assert curve.data.splines[0].use_cyclic_u
    pts, closed = surface.curve_points_world(curve, 16)
    assert closed
    # slučka obieha celú rúru: pokrýva všetky uhly a drží sa výšky z ~ 0
    ang = np.degrees(np.arctan2(pts[:, 1], pts[:, 0]))
    covered = np.histogram(ang, bins=12, range=(-180, 180))[0]
    assert (covered > 0).all()
    assert np.abs(pts[:, 2]).max() < 0.15
    assert np.allclose(np.linalg.norm(pts[:, :2], axis=1), 0.4, atol=0.03)  # leží na povrchu
    # a po dokončení sa dá rezať
    assert bpy.ops.smartcut.cut(refine_levels=2) == {"FINISHED"}


def test_complete_loop_flip_goes_the_other_way_round():
    limb = straight_tube()
    t = np.linspace(0, 0.5 * 2 * np.pi, 40)  # presne polovica: obe cesty sú rovnako dlhé
    arc = np.stack([0.4 * np.cos(t), 0.4 * np.sin(t), np.zeros_like(t)], axis=1)
    curve = operators.build_open_curve(bpy.context, limb, surface.to_world(limb, arc), 0.3, 12)[0]
    select(curve)
    bpy.ops.smartcut.complete(control_points=16, flip=False)
    a, _ = surface.curve_points_world(curve, 12)
    assert np.abs(a[:, 2]).max() < 0.2  # aj tu sa slučka zavrie okolo celej rúry


def test_edit_curve_inward_then_cut_moves_the_border():
    limb = straight_tube()
    curve = ring_curve(limb, z=0.0, n=12)
    select(curve)
    # posun jedného bodu "dovnútra" (po osi rúry) o 0,6 a prichytenie späť na povrch
    pts = surface.control_points_world(curve)
    pts[0] = pts[0] + [0, 0, 0.6]
    surface.set_control_points_world(curve, pts)
    assert bpy.ops.smartcut.snap() == {"FINISHED"}
    moved = surface.control_points_world(curve)
    assert moved[0][2] == pytest.approx(0.6, abs=0.05) and np.linalg.norm(moved[0][:2]) == pytest.approx(0.4, abs=0.02)
    assert bpy.ops.smartcut.cut(refine_levels=3) == {"FINISHED"}
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]
    assert len(parts) == 2
    for p in parts:
        v, o = volume_and_open_edges(p)
        assert o == 0 and v > 0
    zs = np.array([v.co.z for v in parts[0].data.vertices] + [v.co.z for v in parts[1].data.vertices])
    assert zs.min() < -1.9 and zs.max() > 1.9


def test_open_curve_cannot_cut():
    limb = straight_tube()
    t = np.linspace(0, np.pi, 30)
    arc = np.stack([0.4 * np.cos(t), 0.4 * np.sin(t), np.zeros_like(t)], axis=1)
    curve = operators.build_open_curve(bpy.context, limb, surface.to_world(limb, arc), 0.5, 10)[0]
    select(curve)
    assert not bpy.ops.smartcut.cut.poll()


def test_small_loop_on_one_side_cuts_out_a_closed_plug():
    limb = straight_tube()
    v0, _ = volume_and_open_edges(limb)
    a = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    pts = np.stack([0.4 + 0 * a, 0.2 * np.cos(a), 0.2 * np.sin(a)], axis=1)
    curve = surface.make_curve_object("Small", pts, True, limb, 1.0)
    select(curve)
    assert bpy.ops.smartcut.cut(refine_levels=2) == {"FINISHED"}
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]
    assert len(parts) == 2
    vols = []
    for p in parts:
        v, o = volume_and_open_edges(p)
        assert o == 0 and v > 0
        vols.append(v)
    assert min(vols) < 0.05 * v0  # vyrezaná záplata je malá


def test_curve_far_from_the_model_is_not_a_cut():
    limb = straight_tube()
    a = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    far = np.stack([5 + 0.2 * np.cos(a), 5 + 0.2 * np.sin(a), 5 + 0 * a], axis=1)
    curve = surface.make_curve_object("Far", far, True, limb, 1.0)
    select(curve)
    # chyba sa z Pythonu ohlási výnimkou, v Blenderi ako červená správa; nič sa nerozreže
    with pytest.raises(RuntimeError, match="nothing was cut|does not split"):
        bpy.ops.smartcut.cut(refine_levels=1)
    assert len([o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]) == 1


def test_drawn_stroke_is_smoothed():
    limb = straight_tube()
    rng = np.random.default_rng(5)
    t = np.linspace(0, 0.7 * 2 * np.pi, 120)
    arc = np.stack([0.4 * np.cos(t), 0.4 * np.sin(t), rng.normal(0, 0.05, t.shape)], axis=1)  # roztrasená ruka
    rough = operators.build_open_curve(bpy.context, limb, surface.to_world(limb, arc), 0.0, 14)[0]
    bpy.data.objects.remove(rough, do_unlink=True)
    smooth = operators.build_open_curve(bpy.context, limb, surface.to_world(limb, arc), 0.8, 14)[0]
    pts, _ = surface.curve_points_world(smooth, 12)
    assert pts[:, 2].std() < 0.03
