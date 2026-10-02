"""Kolík a otvor na lepenie: návrh polohy, rozmery, vôľa, prehodenie strany."""
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


def _pins():
    return [o for o in bpy.context.scene.objects if o.get(connectors.PIN_PROP)]


def _set(**kw):
    """Nastaví hodnoty v paneli (Scene.smartcut), tak ako to robí používateľ."""
    s = bpy.context.scene.smartcut
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def add_peg(**kw):
    _set(**kw)
    return bpy.ops.smartcut.connectors_add()


def apply_peg(**kw):
    _set(**kw)
    return bpy.ops.smartcut.connectors_apply()


def _rings(obj, frame, origin, zmin, wmax=4.0):
    """Polovičné šírky vrcholov nad rovinou rezu (kolík má vrcholy len na koncoch, nie po dĺžke)."""
    m = np.array(obj.matrix_world)
    co = np.array([tuple(v.co) for v in obj.data.vertices]) @ m[:3, :3].T + m[:3, 3] - origin
    x, y, z = co @ frame[:3, 0], co @ frame[:3, 1], co @ frame[:3, 2]
    w = np.maximum(abs(x), abs(y))
    return w[(z > zmin) & (w < wmax)]


def _frame_of(pin):
    f = np.array(pin.matrix_world)
    return f, f[:3, 3]


# --------------------------------------------------------------------------- návrh polohy (numpy)


def _disc(radius, step=0.5):
    g = np.arange(-radius, radius + 1e-9, step)
    x, y = np.meshgrid(g, g)
    pts = np.stack([x.ravel(), y.ravel(), 0 * x.ravel()], axis=1)
    pts = pts[np.linalg.norm(pts[:, :2], axis=1) <= radius]
    ang = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    ring = np.stack([radius * np.cos(ang), radius * np.sin(ang), 0 * ang], axis=1)
    return pts, ring


def test_automatic_size_is_offered_in_the_middle_of_the_cut():
    cap, border = _disc(8.0)
    centers, dia, ln, max_fit = connectors.plan_pins(cap, border, count=1)
    assert len(centers) == 1
    assert np.linalg.norm(centers[0][:2]) < 1.0
    assert 0 < dia <= max_fit and ln >= dia


def test_explicit_size_is_respected_but_the_fit_limit_is_reported():
    cap, border = _disc(3.0, 0.2)
    centers, dia, ln, max_fit = connectors.plan_pins(cap, border, diameter=6.0)
    assert dia == 6.0 and len(centers) >= 1  # moja hodnota sa nemení
    assert max_fit < 6.0  # ale addon vie, že je väčšia než sa pohodlne zmestí


def test_suggested_size_scales_with_the_cut():
    small = connectors.plan_pins(*_disc(3.0, 0.2), count=1)[1]
    big = connectors.plan_pins(*_disc(30.0, 1.0), count=1)[1]
    assert big > 3 * small


# --------------------------------------------------------------------------- panel a tlačidlá


def test_panel_has_only_the_three_values():
    s = bpy.context.scene.smartcut
    names = {p.identifier for p in s.bl_rna.properties if not p.is_readonly and p.identifier != "name"}
    assert names == {"size", "taper", "clearance"}
    assert s.size == pytest.approx(4.0) and s.taper == pytest.approx(0.96) and s.clearance == pytest.approx(0.05)
    assert s.size > 0  # žiadne mätúce nuly


def test_fit_to_cut_fills_in_a_usable_number():
    top, _bottom = limb_cut()
    _set(size=200.0)  # nezmyselná hodnota
    select(top)
    assert bpy.ops.smartcut.connectors_fit() == {"FINISHED"}
    s = bpy.context.scene.smartcut
    assert 1.0 < s.size < R  # dopočítané z rezu
    assert add_peg() == {"FINISHED"}
    assert _pins()[0]["smartcut_pin_size"] == pytest.approx(s.size)


def test_size_from_the_panel_is_used_exactly():
    top, bottom = limb_cut()
    select(top)
    assert add_peg(size=5.0, clearance=0.12) == {"FINISHED"}
    pin = _pins()[0]
    assert pin["smartcut_pin_size"] == pytest.approx(5.0)
    assert pin["smartcut_pin_shape"] == "SQUARE"
    frame, origin = _frame_of(pin)
    ln = pin["smartcut_pin_length"]
    assert apply_peg() == {"FINISHED"}
    hole = _rings(bottom, frame, origin, 0.5 * ln, wmax=5.0).max()
    assert hole == pytest.approx(2.5 * 0.96 + 0.12, abs=0.02)  # na špičke: zúžený kolík + vôľa


def test_only_one_peg_and_pressing_add_again_rebuilds_it():
    top, _bottom = limb_cut()
    select(top)
    add_peg(size=4.0)
    assert len(_pins()) == 1
    select(top)
    add_peg(size=6.0)
    pins = _pins()
    assert len(pins) == 1
    assert pins[0]["smartcut_pin_size"] == pytest.approx(6.0)


def test_peg_points_into_the_other_part():
    from mathutils import Vector

    top, bottom = limb_cut()
    select(top)
    add_peg(size=4.0)
    pin = _pins()[0]
    axis = np.array(pin.matrix_world.to_3x3() @ Vector((0, 0, 1)))
    assert axis[2] < -0.95  # horný diel: kolík mieri nadol, do spodného
    assert pin["smartcut_pin_part"] == top.name and pin["smartcut_pin_other"] == bottom.name


# --------------------------------------------------------------------------- flip


def test_flip_swaps_the_sides_and_keeps_the_position():
    from mathutils import Vector

    top, bottom = limb_cut()
    select(top)
    add_peg(size=4.0)
    pin = _pins()[0]
    before = np.array(pin.location)
    assert bpy.ops.smartcut.connectors_flip() == {"FINISHED"}
    pin = _pins()[0]
    assert pin["smartcut_pin_part"] == bottom.name and pin["smartcut_pin_other"] == top.name
    assert np.allclose(np.array(pin.location), before, atol=1e-6)  # poloha ostáva
    axis = np.array(pin.matrix_world.to_3x3() @ Vector((0, 0, 1)))
    assert axis[2] > 0.95  # smeruje opačne, hore do vrchného dielu


def test_flip_then_apply_puts_the_peg_on_the_other_part():
    top, bottom = limb_cut()
    v_top0, _ = volume_and_open_edges(top)
    v_bot0, _ = volume_and_open_edges(bottom)
    select(top)
    add_peg(size=4.0)
    bpy.ops.smartcut.connectors_flip()
    assert apply_peg(clearance=0.05) == {"FINISHED"}
    v_top, o_top = volume_and_open_edges(top)
    v_bot, o_bot = volume_and_open_edges(bottom)
    assert o_top == 0 and o_bot == 0
    assert v_bot > v_bot0 and v_top < v_top0  # kolík pribudol dole, diera hore


def test_flip_twice_is_back_where_it_started():
    top, bottom = limb_cut()
    select(top)
    add_peg(size=4.0)
    m0 = np.array(_pins()[0].matrix_world)
    bpy.ops.smartcut.connectors_flip()
    bpy.ops.smartcut.connectors_flip()
    pin = _pins()[0]
    assert pin["smartcut_pin_part"] == top.name
    assert np.allclose(np.array(pin.matrix_world), m0, atol=1e-6)


# --------------------------------------------------------------------------- vôľa a rozmery


@pytest.mark.parametrize("clearance", [0.0, 0.05, 0.15])
def test_side_gap_equals_the_clearance_setting(clearance):
    top, bottom = limb_cut()
    select(top)
    add_peg(size=4.0, taper=1.0)  # rovný kolík: vôľa je všade rovnaká
    pin = _pins()[0]
    frame, origin = _frame_of(pin)
    ln = pin["smartcut_pin_length"]
    assert apply_peg(clearance=clearance) == {"FINISHED"}
    peg = _rings(top, frame, origin, 0.5 * ln)
    hole = _rings(bottom, frame, origin, 0.5 * ln)
    assert len(peg) >= 4 and len(hole) >= 4
    assert peg.max() == pytest.approx(2.0, abs=0.01)
    assert hole.max() == pytest.approx(2.0 + clearance, abs=0.01)


def test_default_taper_keeps_the_fit_along_the_whole_peg():
    top, bottom = limb_cut()
    select(top)
    add_peg(size=4.0)
    pin = _pins()[0]
    frame, origin = _frame_of(pin)
    ln = pin["smartcut_pin_length"]
    assert apply_peg() == {"FINISHED"}
    hole = _rings(bottom, frame, origin, 0.5 * ln).max()
    tip = _rings(top, frame, origin, 0.5 * ln).max()
    assert tip == pytest.approx(0.96 * 2.0, abs=0.02)  # špička je len mierne zúžená
    assert hole - tip == pytest.approx(0.05, abs=0.01)  # diera kopíruje skosenie: vôľa je rovnaká aj na špičke


def test_taper_setting_changes_the_tip():
    top, _bottom = limb_cut()
    select(top)
    add_peg(size=4.0, taper=0.7)
    pin = _pins()[0]
    frame, origin = _frame_of(pin)
    ln = pin["smartcut_pin_length"]
    assert apply_peg() == {"FINISHED"}
    tip = _rings(top, frame, origin, 0.5 * ln).max()
    assert tip == pytest.approx(0.7 * 2.0, abs=0.03)


def test_apply_keeps_both_parts_closed_and_moves_the_right_volumes():
    top, bottom = limb_cut()
    v_top0, _ = volume_and_open_edges(top)
    v_bot0, _ = volume_and_open_edges(bottom)
    select(top)
    add_peg(size=4.0, taper=0.96)
    ln = _pins()[0]["smartcut_pin_length"]
    assert apply_peg(clearance=0.05) == {"FINISHED"}
    v_top, o_top = volume_and_open_edges(top)
    v_bot, o_bot = volume_and_open_edges(bottom)
    assert o_top == 0 and o_bot == 0
    s_, k, c = 4.0, 0.96, 0.05
    peg_vol = ln * (s_ * s_ + s_ * s_ * k + (s_ * k) ** 2) / 3.0
    hole_vol = (s_ + 2 * c) ** 2 * (ln + max(2 * c, 0.08 * s_))
    assert (v_top - v_top0) == pytest.approx(peg_vol, rel=0.12)
    assert (v_bot0 - v_bot) == pytest.approx(hole_vol, rel=0.12)


def test_peg_can_be_moved_before_applying():
    top, bottom = limb_cut(radius=14.0)
    select(top)
    add_peg(size=4.0)
    pin = _pins()[0]
    pin.location.x += 4.0
    moved = np.array(pin.location)
    frame, origin = _frame_of(pin)
    v0, _ = volume_and_open_edges(bottom)
    assert apply_peg(clearance=0.05) == {"FINISHED"}
    assert volume_and_open_edges(bottom)[0] < v0
    # diera je tam, kam som kolík posunul
    m = np.array(bottom.matrix_world)
    co = np.array([tuple(v.co) for v in bottom.data.vertices]) @ m[:3, :3].T + m[:3, 3]
    near = np.linalg.norm(co[:, :2] - moved[:2], axis=1) < 3.5
    assert near.sum() >= 8


def test_peg_on_a_curved_cut_keeps_both_parts_closed():
    top, bottom = limb_cut(wobble=1.5, radius=14.0)
    select(top)
    add_peg(size=4.0)
    assert apply_peg(clearance=0.05) == {"FINISHED"}
    for part in (top, bottom):
        v, o = volume_and_open_edges(part)
        assert o == 0 and v > 0


def test_square_peg_is_keyed_to_the_long_side_of_the_cut():
    from mathutils import Vector

    zs = np.linspace(-HALF, HALF, 41)
    limb = tube(np.stack([0 * zs, 0 * zs, zs], axis=1), radius=R, sides=60)
    for v in limb.data.vertices:
        v.co.x *= 1.8  # eliptický prierez, dlhšia strana pozdĺž X
    a = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    pts = np.stack([1.8 * R * np.cos(a), R * np.sin(a), 3.0 + 0 * a], axis=1)
    curve = surface.make_curve_object("Loop", pts, True, limb, 40.0)
    select(curve)
    assert bpy.ops.smartcut.cut() == {"FINISHED"}
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]
    select(parts[0])
    add_peg(size=4.0)
    x_axis = np.array(_pins()[0].matrix_world.to_3x3() @ Vector((1, 0, 0)))
    assert abs(x_axis[0]) > 0.95


@pytest.mark.parametrize("radius", [1.0, 5.0, 25.0])
def test_fit_to_cut_works_at_any_model_scale(radius):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=radius)
    ball = bpy.context.active_object
    a = np.linspace(0, 2 * np.pi, 24, endpoint=False)
    pts = np.stack([radius * np.cos(a), radius * np.sin(a), 0.1 * radius * np.sin(2 * a)], axis=1)
    curve = surface.make_curve_object("Loop", pts, True, ball, 2 * radius)
    select(curve)
    assert bpy.ops.smartcut.cut() == {"FINISHED"}
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.hide_get()]
    select(parts[0])
    bpy.ops.smartcut.connectors_fit()
    assert add_peg() == {"FINISHED"}
    pin = _pins()[0]
    reach = pin["smartcut_pin_base"] + pin["smartcut_pin_length"]
    assert reach < 1.1 * radius  # kolík nikdy nepreráža cez celý model
    assert bpy.context.scene.smartcut.size < radius


def test_preview_peg_is_wireframe_and_visible_through_the_model():
    top, bottom = limb_cut()
    select(top)
    add_peg(size=4.0)
    pin = _pins()[0]
    assert pin.display_type == "WIRE" and pin.show_in_front
    assert not top.hide_get() and not bottom.hide_get()


def test_add_without_a_cut_pair_is_not_available():
    zs = np.linspace(-HALF, HALF, 11)
    limb = tube(np.stack([0 * zs, 0 * zs, zs], axis=1), radius=R, sides=40)
    select(limb)
    assert not bpy.ops.smartcut.connectors_add.poll()
    assert not bpy.ops.smartcut.connectors_flip.poll()


def test_hole_follows_the_taper_so_the_gap_is_the_same_everywhere():
    top, bottom = limb_cut()
    select(top)
    add_peg(size=4.0, taper=0.8)  # výrazné skosenie, aby bol rozdiel jasný
    pin = _pins()[0]
    frame, origin = _frame_of(pin)
    ln = pin["smartcut_pin_length"]
    assert apply_peg(clearance=0.1) == {"FINISHED"}

    def widths(obj, zmin, zmax):
        m = np.array(obj.matrix_world)
        co = np.array([tuple(v.co) for v in obj.data.vertices]) @ m[:3, :3].T + m[:3, 3] - origin
        x, y, z = co @ frame[:3, 0], co @ frame[:3, 1], co @ frame[:3, 2]
        w = np.maximum(abs(x), abs(y))
        return w[(z > zmin) & (z < zmax) & (w < 4.0)]

    tip_peg = widths(top, 0.5 * ln, ln + 1.0).max()
    tip_hole = widths(bottom, 0.5 * ln, ln + 1.0).max()
    assert tip_peg == pytest.approx(0.8 * 2.0, abs=0.02)  # kolík je na špičke zúžený
    assert tip_hole - tip_peg == pytest.approx(0.1, abs=0.02)  # a diera tam má rovnakú vôľu
    # pri rovine rezu musí byť vôľa tá istá, hoci sú oba tvary širšie
    base_peg = widths(top, -0.05, 0.05).min()
    base_hole = widths(bottom, -0.05, 0.05).min()
    assert base_peg > tip_peg  # kolík je dole naozaj širší
    assert base_hole - base_peg == pytest.approx(0.1, abs=0.02)


def test_preview_shows_both_the_peg_and_the_hole():
    top, _bottom = limb_cut()
    select(top)
    add_peg(size=4.0, taper=1.0, clearance=0.4)  # veľká vôľa, aby bol obrys diery jasne väčší
    pin = _pins()[0]
    co = np.array([tuple(v.co) for v in pin.data.vertices])
    w = np.maximum(abs(co[:, 0]), abs(co[:, 1]))
    assert w.max() == pytest.approx(2.0 + 0.4, abs=0.02)  # vonkajší obrys = diera
    assert w.min() < 2.01  # vnútorný obrys = kolík


def test_changing_a_value_redraws_the_preview_immediately():
    top, _bottom = limb_cut()
    select(top)
    add_peg(size=4.0, clearance=0.05)
    pin = _pins()[0]
    before = np.array([tuple(v.co) for v in pin.data.vertices])
    pos = np.array(pin.matrix_world)
    _set(size=7.0)  # len zmena hodnoty v paneli, žiadne tlačidlo
    after = np.array([tuple(v.co) for v in pin.data.vertices])
    assert np.abs(after[:, :2]).max() > np.abs(before[:, :2]).max() * 1.5
    assert pin["smartcut_pin_size"] == pytest.approx(7.0)
    assert np.allclose(np.array(pin.matrix_world), pos)  # poloha ostáva


def test_moving_the_peg_then_changing_a_value_keeps_the_new_position():
    top, _bottom = limb_cut(radius=14.0)
    select(top)
    add_peg(size=4.0)
    pin = _pins()[0]
    pin.location.x += 3.0
    moved = np.array(pin.location)
    _set(clearance=0.3)
    assert np.allclose(np.array(_pins()[0].location), moved)
