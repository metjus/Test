"""Kolíky a otvory na lepenie."""
import sys
from pathlib import Path

import numpy as np
import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon"))
import smart_cut  # noqa: E402
from smart_cut import connectors, surface  # noqa: E402
from test_smart_cut import cap_mask, select, tube, volume_and_open_edges  # noqa: E402

R, HALF = 10.0, 20.0  # rúra s polomerom 10 mm a dĺžkou 40 mm


@pytest.fixture(autouse=True)
def addon():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    smart_cut.register()
    yield
    smart_cut.unregister()


def limb_cut(wobble=0.0, z=3.0, radius=R):
    zs = np.linspace(-HALF, HALF, 41)
    limb = tube(np.stack([0 * zs, 0 * zs, zs], axis=1), radius=radius, sides=60)
    a = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    pts = np.stack([radius * np.cos(a), radius * np.sin(a), z + wobble * np.sin(2 * a)], axis=1)
    curve = surface.make_curve_object("Loop", pts, True, limb, 40.0)
    select(curve)
    assert bpy.ops.smartcut.cut() == {"FINISHED"}
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]
    parts.sort(key=lambda o: -np.mean([v.co.z for v in o.data.vertices]))  # horný diel prvý
    return parts


# --------------------------------------------------------------------------- návrh polohy


def _disc(radius, step=0.5):
    g = np.arange(-radius, radius + 1e-9, step)
    x, y = np.meshgrid(g, g)
    pts = np.stack([x.ravel(), y.ravel(), 0 * x.ravel()], axis=1)
    pts = pts[np.linalg.norm(pts[:, :2], axis=1) <= radius]
    ang = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    ring = np.stack([radius * np.cos(ang), radius * np.sin(ang), 0 * ang], axis=1)
    return pts, ring


def test_small_cut_gets_one_pin_in_the_middle():
    cap, border = _disc(8.0)
    centers, dia, ln = connectors.plan_pins(cap, border)
    assert len(centers) == 1
    assert np.linalg.norm(centers[0][:2]) < 1.0
    assert 2.0 <= dia <= 6.0 and ln >= dia


def test_big_cut_gets_several_separated_pins_away_from_the_edge():
    cap, border = _disc(30.0)
    centers, dia, ln = connectors.plan_pins(cap, border)
    assert len(centers) >= 2
    d_edge = 30.0 - np.linalg.norm(centers[:, :2], axis=1)
    assert (d_edge >= dia / 2 + 0.8 * dia - 0.6).all()
    pair = np.linalg.norm(centers[0] - centers[1])
    assert pair >= 2.5 * dia - 1e-6


def test_manual_count_and_diameter():
    cap, border = _disc(30.0)
    centers, dia, ln = connectors.plan_pins(cap, border, count=4, diameter=5.0, length=9.0)
    assert len(centers) == 4 and dia == 5.0 and ln == 9.0


def test_pin_never_larger_than_the_cut_allows():
    cap, border = _disc(3.0, 0.2)
    centers, dia, ln = connectors.plan_pins(cap, border, diameter=6.0)
    assert dia <= 3.0 / 1.6 + 1e-9 and len(centers) >= 1


# --------------------------------------------------------------------------- v Blenderi


def _pins():
    return [o for o in bpy.context.scene.objects if o.get(connectors.PIN_PROP)]


def test_add_places_pins_on_the_cut_pointing_into_the_other_part():
    top, bottom = limb_cut()
    select(top)
    assert bpy.ops.smartcut.connectors_add() == {"FINISHED"}
    pins = _pins()
    assert len(pins) >= 1
    for p in pins:
        axis = np.array(p.matrix_world.to_3x3() @ __import__("mathutils").Vector((0, 0, 1)))
        # horný diel: vonkajšia normála jeho plochy rezu smeruje dole, kolík teda smeruje dole
        assert axis[2] < -0.95
        assert abs(p.location.z - 3.0) < 0.5  # leží na reze
        assert np.hypot(p.location.x, p.location.y) < R - 3.0  # nie pri okraji
        assert p["smartcut_pin_part"] == top.name and p["smartcut_pin_other"] == bottom.name


def test_apply_adds_pin_and_cuts_a_hole_with_clearance_and_keeps_parts_closed():
    top, bottom = limb_cut()
    v_top0, _ = volume_and_open_edges(top)
    v_bot0, _ = volume_and_open_edges(bottom)
    select(top)
    bpy.ops.smartcut.connectors_add(count=1, diameter=4.0, length=8.0)
    pin = _pins()[0]
    axis_dir = np.array(pin.matrix_world.to_3x3() @ __import__("mathutils").Vector((0, 0, 1)))
    origin = np.array(pin.location)
    assert bpy.ops.smartcut.connectors_apply(clearance=0.3) == {"FINISHED"}
    assert not _pins()

    v_top, o_top = volume_and_open_edges(top)
    v_bot, o_bot = volume_and_open_edges(bottom)
    assert o_top == 0 and o_bot == 0 and v_top > 0 and v_bot > 0
    r, ln, c = 2.0, 8.0, 0.3
    pin_vol = np.pi * ln * (r * r + r * 0.85 * r + (0.85 * r) ** 2) / 3.0
    hole_vol = np.pi * (r + c) ** 2 * (ln + c)
    assert (v_top - v_top0) == pytest.approx(pin_vol, rel=0.12)
    assert (v_bot0 - v_bot) == pytest.approx(hole_vol, rel=0.12)

    def radial_and_axial(obj):
        m = np.array(obj.matrix_world)
        co = np.array([tuple(v.co) for v in obj.data.vertices]) @ m[:3, :3].T + m[:3, 3] - origin
        axial = co @ axis_dir
        radial = np.linalg.norm(co - np.outer(axial, axis_dir), axis=1)
        return axial, radial

    ax_t, rad_t = radial_and_axial(top)
    ax_b, rad_b = radial_and_axial(bottom)
    # špička kolíka (prstenec o priemere 0,85 r) a horný okraj otvoru (prstenec o polomere r + vôľa)
    pin_top = rad_t[(ax_t > 0.5 * ln) & (rad_t < r + 0.6)]
    hole_top = rad_b[(ax_b > 0.5 * ln) & (rad_b > r) & (rad_b < r + c + 0.6)]
    assert len(pin_top) >= 8 and len(hole_top) >= 8
    assert hole_top.min() == pytest.approx(r + c, abs=0.02)  # otvor má polomer kolíka + vôľa
    assert pin_top.max() <= r + 1e-6  # kolík nepresahuje svoj polomer
    assert hole_top.min() - pin_top.max() >= c - 0.02


def test_clearance_is_adjustable_at_apply_time():
    results = []
    for clearance in (0.1, 0.5):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        top, bottom = limb_cut()
        v0, _ = volume_and_open_edges(bottom)
        select(top)
        bpy.ops.smartcut.connectors_add(count=1, diameter=4.0, length=8.0)
        bpy.ops.smartcut.connectors_apply(clearance=clearance)
        results.append(v0 - volume_and_open_edges(bottom)[0])
    assert results[1] > results[0] * 1.2  # väčšia vôľa = väčší otvor


def test_pins_on_a_curved_cut_still_give_closed_parts_and_alternate_sides():
    top, bottom = limb_cut(wobble=1.5, radius=14.0)
    select(top)
    bpy.ops.smartcut.connectors_add(count=2, diameter=3.0, length=6.0, alternate=True)
    pins = _pins()
    assert len(pins) == 2
    assert {p["smartcut_pin_part"] for p in pins} == {top.name, bottom.name}
    assert bpy.ops.smartcut.connectors_apply(clearance=0.2) == {"FINISHED"}
    for part in (top, bottom):
        v, o = volume_and_open_edges(part)
        assert o == 0 and v > 0


def test_pin_can_be_moved_before_applying():
    top, bottom = limb_cut(radius=14.0)
    select(top)
    bpy.ops.smartcut.connectors_add(count=1, diameter=3.0, length=6.0)
    pin = _pins()[0]
    pin.location.x += 4.0
    v0, _ = volume_and_open_edges(bottom)
    assert bpy.ops.smartcut.connectors_apply(clearance=0.2) == {"FINISHED"}
    assert volume_and_open_edges(bottom)[0] < v0


def test_add_without_a_cut_pair_is_not_available():
    zs = np.linspace(-HALF, HALF, 11)
    limb = tube(np.stack([0 * zs, 0 * zs, zs], axis=1), radius=R, sides=40)
    select(limb)
    assert not bpy.ops.smartcut.connectors_add.poll()
