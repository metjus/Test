"""End-to-end tests. Run with Blender's Python, e.g.:

    blender --background --factory-startup --python tests/test_fox.py
    python tests/test_fox.py          # with the `bpy` module from PyPI
"""

import math
import os
import sys
import tempfile

import bpy  # must come first when using the bpy module from PyPI
import bmesh  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fox_parametric  # noqa: E402
from fox_parametric import core  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def close(a, b, tol=1e-3):
    return abs(a - b) <= tol * max(1.0, abs(b))


def evaluated(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    bm = bmesh.new()
    bm.from_object(obj, dg)
    vol = bm.calc_volume(signed=True)
    manifold = all(e.is_manifold for e in bm.edges)
    nverts = len(bm.verts)
    bm.free()
    return vol, manifold, nverts


def fox_mods(obj):
    """Feature modifiers (without the smooth-shading one)."""
    return [m for m in obj.modifiers if m.name.startswith(core.MOD_PREFIX)
            and m.name not in (core.SMOOTH_MOD, core.NORMALS_MOD)]


def add(obj, ftype, **values):
    bpy.ops.fox.add_feature(type=ftype)
    f = obj.fox_part.features[obj.fox_part.active_index]
    with core.batch():
        for k, v in values.items():
            setattr(f, k, v)
    core.rebuild(obj)
    return f


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    fox_parametric.register()
    print("Blender", bpy.app.version_string)

    # --- base box --------------------------------------------------------
    bpy.ops.fox.new_part(kind="BOX")
    obj = bpy.context.active_object
    base = obj.fox_part.features[0]
    vol, man, _ = evaluated(obj)
    check(close(vol, 1.0 * 0.6 * 0.3), "box base volume = 1 x 0.6 x 0.3 (got %.4f)" % vol)
    check(man, "box is a closed solid")

    base.distance = 0.5  # editing a parameter rebuilds right away
    vol, _, _ = evaluated(obj)
    check(close(vol, 0.3), "changing base distance rebuilds (got %.4f)" % vol)
    base.distance = 0.3

    # --- hole --------------------------------------------------------------
    hole = add(obj, "HOLE", hole_diameter=0.1, through_all=True, pos_u=0.2, pos_v=0.1, segments=64)
    check(abs(hole.offset - 0.3) < 1e-6, "new hole sketches on the top face (offset %.3f)" % hole.offset)
    v_hole = math.pi * 0.05 ** 2 * 0.3 * (64 / (2 * math.pi)) * math.sin(2 * math.pi / 64) / 0.05 ** 0 * 1
    polygon_area = 0.5 * 64 * 0.05 ** 2 * math.sin(2 * math.pi / 64)
    vol, man, _ = evaluated(obj)
    check(close(vol, 0.18 - polygon_area * 0.3), "through hole removes its volume (got %.5f)" % vol)
    check(man, "part with hole is closed")
    check(len(fox_mods(obj)) == 1 and fox_mods(obj)[0].type == "BOOLEAN", "hole = one boolean modifier")
    check(hole.tool is not None and hole.tool.hide_viewport, "hole tool object exists and is hidden")

    hole.hole_diameter = 0.12
    vol2, _, _ = evaluated(obj)
    check(vol2 < vol, "bigger hole diameter removes more material")
    hole.hole_diameter = 0.1

    hole.pattern = "LINEAR"
    with core.batch():
        hole.count_u, hole.spacing_u = 3, -0.2
    core.rebuild(obj)
    vol, man, _ = evaluated(obj)
    check(close(vol, 0.18 - 3 * polygon_area * 0.3), "linear pattern makes 3 holes (got %.5f)" % vol)

    hole.through_all = False
    hole.hole_depth = 0.1
    vol, man, _ = evaluated(obj)
    check(close(vol, 0.18 - 3 * polygon_area * 0.1, tol=5e-3), "blind holes 0.1 deep (got %.5f)" % vol)
    check(man, "blind holes keep the solid closed")

    # --- extrude join / cut ---------------------------------------------------
    boss = add(obj, "EXTRUDE", profile="RECT", width=0.2, height=0.2, distance=0.1, pos_u=-0.3, pos_v=0.0)
    vol_boss, man, _ = evaluated(obj)
    check(close(vol_boss, vol + 0.004), "extrude join adds a 0.2x0.2x0.1 boss (got %.5f)" % vol_boss)
    boss.operation = "CUT"
    vol_cut, man, _ = evaluated(obj)
    check(vol_cut < vol, "switching the extrude to Cut removes material")
    boss.operation = "JOIN"

    # --- revolve join ---------------------------------------------------------
    rev = add(obj, "REVOLVE")
    rev_name = rev.name  # collection items can move: keep names, not references
    vol_rev, man, _ = evaluated(obj)
    check(vol_rev > vol_boss and man, "revolve adds a closed ring (%.5f > %.5f)" % (vol_rev, vol_boss))

    # --- fillet ----------------------------------------------------------------
    _, _, nv = evaluated(obj)
    fil = add(obj, "FILLET", size=0.01)
    fil_name = fil.name
    vol_f, man, nv2 = evaluated(obj)
    check(nv2 > nv and vol_f < vol_rev, "fillet rounds edges (verts %d -> %d)" % (nv, nv2))
    check(fox_mods(obj)[-1].type == "BEVEL", "fillet is the last modifier")

    # --- mirror ----------------------------------------------------------------
    add(obj, "MIRROR", mirror_x=False, mirror_z=True)
    mir = obj.fox_part.features[obj.fox_part.active_index]
    vol_m, _, _ = evaluated(obj)
    check(vol_m > vol_f * 1.9, "mirror across Z doubles the part (%.4f -> %.4f)" % (vol_f, vol_m))
    mir.suppressed = True
    check(close(evaluated(obj)[0], vol_f), "suppressing mirror switches it off")
    mir.suppressed = False

    # --- rollback -------------------------------------------------------------
    obj.fox_part.rollback = 0
    check(close(evaluated(obj)[0], 0.18), "rolled back to base = plain box")
    obj.fox_part.rollback = -1
    check(close(evaluated(obj)[0], vol_m), "roll forward restores everything")

    # --- reorder ----------------------------------------------------------------
    part = obj.fox_part
    part.active_index = [f.name for f in part.features].index(fil_name)
    bpy.ops.fox.move_feature(direction="UP")
    order = [m.name for m in fox_mods(obj)]
    want = [core.MOD_PREFIX + f.uid for f in part.features[1:]]
    check(order == want, "modifier order follows the history after moving a feature")
    check([m.name for m in obj.modifiers][:len(want)] == want, "our modifiers stay at the top of the stack")

    # --- smooth shading -----------------------------------------------------------
    names = [m.name for m in obj.modifiers]
    check(names[len(want):len(want) + 2] == [core.SMOOTH_MOD, core.NORMALS_MOD],
          "smooth shading sits right after the features")
    v = evaluated(obj)[0]
    obj.fox_part.smooth = False
    check(core.SMOOTH_MOD not in obj.modifiers and core.NORMALS_MOD not in obj.modifiers
          and close(evaluated(obj)[0], v),
          "smooth shading can be switched off and doesn't change the shape")
    obj.fox_part.smooth = True
    dg = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(dg).data
    smooth_faces = sum(p.use_smooth for p in me.polygons)
    check(0 < smooth_faces, "smooth shading marks faces smooth (%d)" % smooth_faces)

    # --- user's own modifier survives ----------------------------------------
    obj.modifiers.new("My Subsurf", "SUBSURF")
    core.rebuild(obj)
    check(obj.modifiers[-1].name == "My Subsurf", "user's own modifier kept after ours")
    obj.modifiers.remove(obj.modifiers["My Subsurf"])

    # --- delete a feature --------------------------------------------------------
    part.active_index = [f.name for f in part.features].index(rev_name)
    rev_tool = part.features[part.active_index].tool.name
    bpy.ops.fox.remove_feature()
    check(rev_tool not in bpy.data.objects, "deleting a feature removes its tool")
    check(len(fox_mods(obj)) == len(part.features) - 1, "one modifier per feature after delete")

    # --- duplicate feature ----------------------------------------------------------
    part.active_index = 1
    src_diam = part.features[1].hole_diameter
    bpy.ops.fox.duplicate_feature()
    dup = part.features[2]
    check(dup.type == part.features[1].type and dup.uid != part.features[1].uid, "duplicate feature gets its own id")
    check(dup.hole_diameter == src_diam and dup.pattern == part.features[1].pattern,
          "duplicate feature copies the values")
    check(dup.tool is not None and dup.tool != part.features[1].tool, "duplicate feature gets its own tool")
    bpy.ops.fox.remove_feature()

    # --- animation: keyframed parameter ----------------------------------------------
    scene = bpy.context.scene
    base = obj.fox_part.features[0]
    base.distance = 0.3
    base.keyframe_insert("distance", frame=1)
    base.distance = 0.6
    base.keyframe_insert("distance", frame=10)
    scene.frame_set(1)
    v1 = evaluated(obj)[0]
    scene.frame_set(10)
    v10 = evaluated(obj)[0]
    check(v10 > v1 * 1.5, "keyframed base distance changes the model per frame (%.4f -> %.4f)" % (v1, v10))
    obj.animation_data_clear()
    base.distance = 0.3
    core.rebuild(obj)

    # --- duplicate the whole object (Shift+D) ---------------------------------
    for o in bpy.context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.duplicate()
    copy = bpy.context.active_object
    check(copy != obj and core.is_part(copy), "duplicated object is still a part")
    core.rebuild(copy)
    tools_ok = all(f.tool is None or f.tool.parent == copy for f in copy.fox_part.features[1:])
    check(tools_ok, "duplicate gets its own tool objects")
    v_orig = evaluated(obj)[0]
    copy.fox_part.features[1].hole_diameter = 0.02
    check(close(evaluated(obj)[0], v_orig) and close(obj.fox_part.features[1].hole_diameter, 0.1)
          and evaluated(copy)[0] > v_orig, "editing the copy leaves the original alone")

    # --- hybrid: your own mesh as base ------------------------------------------------
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.5, subdivisions=3, location=(3, 0, 0))
    ball = bpy.context.active_object
    bpy.ops.fox.make_part()
    check(core.is_part(ball) and ball.fox_part.features[0].type == "BASE_MESH", "mesh became a part")
    v_ball = evaluated(ball)[0]
    add(ball, "HOLE", through_all=True, hole_diameter=0.2, pos_u=0.0, pos_v=0.0)
    check(evaluated(ball)[0] < v_ball * 0.95, "hole through a hand-made mesh")
    # edit the base mesh by hand: scale it; the hole stays parametric
    for v in ball.data.vertices:
        v.co.x *= 1.5
    ball.data.update()
    check(evaluated(ball)[0] > v_ball, "hand edits on the base mesh are kept")

    # --- generated base -> hand-editable ----------------------------------------------
    bpy.context.view_layer.objects.active = obj
    bpy.ops.fox.base_to_mesh()
    check(obj.fox_part.features[0].type == "BASE_MESH" and len(obj.data.vertices) == 8,
          "'Edit Base By Hand' keeps the box as a normal mesh")

    # --- file opens without the add-on --------------------------------------------------
    path = os.path.join(tempfile.mkdtemp(), "fox_test.blend")
    v_before = evaluated(obj)[0]
    name = obj.name
    bpy.ops.wm.save_as_mainfile(filepath=path)
    fox_parametric.unregister()
    bpy.ops.wm.open_mainfile(filepath=path)
    o = bpy.data.objects[name]
    check(close(evaluated(o)[0], v_before), "saved file shows the same model without the add-on")
    fox_parametric.register()
    bpy.ops.wm.open_mainfile(filepath=path)
    obj = bpy.data.objects[name]
    check(core.is_part(obj), "history is still there after reopening with the add-on")

    # --- convert to regular mesh ---------------------------------------------------------
    for o in bpy.context.selected_objects:
        o.select_set(False)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    v_before = evaluated(obj)[0]
    bpy.ops.fox.apply_part()
    check(not core.is_part(obj) and not fox_mods(obj), "convert to mesh removes history and modifiers")
    check(not [c for c in obj.children if "fox_uid" in c], "convert to mesh removes tool objects")
    check(close(evaluated(obj)[0], v_before), "convert to mesh keeps the shape")

    # --- every feature type from scratch, all profiles -------------------------------------
    bpy.ops.fox.new_part(kind="CYLINDER")
    cyl = bpy.context.active_object
    check(evaluated(cyl)[1], "cylinder base is closed")
    bpy.ops.fox.new_part(kind="REVOLVE")
    ring = bpy.context.active_object
    check(evaluated(ring)[1] and evaluated(ring)[0] > 0, "revolved base is a closed solid")
    for prof in ("RECT", "CIRCLE", "POLYGON", "SLOT"):
        f = add(cyl, "EXTRUDE", profile=prof, operation="CUT", distance=0.05)
        vol, man, _ = evaluated(cyl)
        check(man and vol > 0, "%s cut keeps the part closed" % prof.lower())
    f = add(cyl, "CHAMFER", size=0.01)
    check(evaluated(cyl)[1], "chamfer keeps the part closed")
    f = add(cyl, "EXTRUDE", plane="XZ", profile="CIRCLE", radius=0.1, direction="SYMMETRIC",
            distance=2.0, operation="CUT", pos_u=0.0, pos_v=0.25)
    check(evaluated(cyl)[1], "cross hole on the front plane keeps the part closed")
    f = add(cyl, "HOLE", pattern="CIRCULAR", circ_count=6, pos_u=0.3, pos_v=0.0, hole_diameter=0.05,
            through_all=True)
    check(evaluated(cyl)[1], "circular pattern of holes works")

    fox_parametric.unregister()
    print()
    print("FAILED: %d" % len(FAILS) if FAILS else "ALL TESTS PASSED")
    return 1 if FAILS else 0


if __name__ == "__main__":
    code = main()
    if not bpy.app.background:
        pass
    sys.exit(code)
