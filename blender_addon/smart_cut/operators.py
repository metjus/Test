import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import connectors, cutter, geom, settings, stroke, surface

COLOR_STROKE = (1.0, 0.55, 0.05, 1.0)

# posledné nakreslené body (svetové súradnice), aby sa dal po dokreslení meniť Smoothing v paneli „Adjust Last Operation"
_last_stroke: dict = {"target": None, "points": None}


def _target_of(context, curve_obj):
    name = curve_obj.get(surface.CURVE_PROP) if curve_obj else None
    obj = bpy.data.objects.get(name) if name else None
    if obj is None or obj.type != "MESH":
        obj = context.active_object if context.active_object and context.active_object.type == "MESH" else None
    return obj


def _active_curve(context):
    o = context.active_object
    return o if o is not None and o.type == "CURVE" and len(o.data.splines) else None


def _replace_curve_points(curve_obj, world_pts: np.ndarray, closed: bool):
    cu = curve_obj.data
    for sp in list(cu.splines):
        cu.splines.remove(sp)
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(world_pts) - 1)
    local = surface.to_local(curve_obj, world_pts)
    for bp, p in zip(sp.bezier_points, local):
        bp.co = Vector(p)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    sp.use_cyclic_u = closed


def build_open_curve(context, target, world_pts: np.ndarray, smooth: float, n_ctrl: int):
    """Z nakreslených bodov vytvorí vyhladenú otvorenú krivku ležiacu na povrchu."""
    local = surface.to_local(target, np.asarray(world_pts, dtype=np.float64))
    avg = surface.mean_edge_length(target.data)
    sm = geom.smooth_polyline(local, smooth, closed=False)
    tree = surface.build_bvh(target.data)
    on, _ = surface.project_to_surface(tree, sm)
    ctrl = geom.resample(on, n_ctrl, closed=False)
    ctrl, _ = surface.project_to_surface(tree, ctrl)
    size = max(target.dimensions) or 1.0
    obj = surface.make_curve_object("CutLine", surface.to_world(target, ctrl), False, target, size)
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj, avg


# --------------------------------------------------------------------------- 1. kreslenie


NAV_EVENTS = {
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
    "MOUSEROTATE", "MOUSEPAN", "MOUSEZOOM", "TRACKPADPAN", "TRACKPADZOOM",
    "NDOF_MOTION", "NDOF_BUTTON_FIT", "NDOF_BUTTON_PANZOOM",
}


def _view_under_mouse(context, event):
    """3D okno pod myšou: (area, WINDOW region, rv3d) alebo None. Funguje aj keď sa spustí z bočného panela."""
    mx, my = event.mouse_x, event.mouse_y
    for area in context.window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        if not (area.x <= mx < area.x + area.width and area.y <= my < area.y + area.height):
            continue
        for region in area.regions:
            if region.type == "WINDOW" and region.x <= mx < region.x + region.width and region.y <= my < region.y + region.height:
                return area, region, area.spaces.active.region_3d
    return None


class SMARTCUT_OT_draw(bpy.types.Operator):
    bl_idname = "smartcut.draw"
    bl_label = "Draw Cut Line"
    bl_description = (
        "Draw the cut line directly on the model. You can rotate the view and keep drawing. "
        "Enter finishes, Backspace removes the last piece, Esc cancels"
    )
    bl_options = {"REGISTER", "UNDO"}

    smooth: FloatProperty(
        name="Smoothing", description="How much the hand-drawn line is smoothed", default=0.5, min=0.0, max=1.0
    )
    control_points: IntProperty(
        name="Control points", description="Fewer points = smoother and easier to edit", default=12, min=4, max=64
    )
    extend: BoolProperty(
        name="Continue existing line",
        description="Keep the selected open line and continue drawing from its end",
        default=False,
        options={"SKIP_SAVE", "HIDDEN"},
    )

    @classmethod
    def poll(cls, context):
        o = context.active_object
        if o is None or context.mode != "OBJECT" or not context.area or context.area.type != "VIEW_3D":
            return False
        return o.type == "MESH" or (o.type == "CURVE" and bool(o.data.splines) and not o.data.splines[0].use_cyclic_u)

    def invoke(self, context, event):
        active = context.active_object
        self._old_curve = None
        initial = None
        if active.type == "CURVE":
            target = _target_of(context, active)
            if target is None:
                self.report({"ERROR"}, "Target mesh not found for this line.")
                return {"CANCELLED"}
            if self.extend:
                self._old_curve = active
                pts_w, _ = surface.curve_points_world(active, 6)
                mw, tree = target.matrix_world, surface.build_bvh(target.data)
                inv = mw.inverted()
                initial = []
                for p in pts_w:
                    hit = tree.find_nearest(inv @ Vector(p))
                    initial.append((mw @ hit[0], (mw.to_3x3() @ hit[1]).normalized()))
            self._obj = target
        else:
            self._obj = active
        self._drawing = False
        self._builder = stroke.StrokeBuilder(self._obj, initial)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw_overlay, (), "WINDOW", "POST_VIEW")
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set("PAINT_BRUSH")
        self._status(context)
        return {"RUNNING_MODAL"}

    def _status(self, context):
        context.workspace.status_text_set(
            "Smart Cut:  LMB drag = draw (you can rotate the view with MMB and continue)  |  "
            "Enter = finish  |  Backspace = remove last piece  |  Esc = cancel"
        )

    def _cleanup(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        for a in context.window.screen.areas:
            a.tag_redraw()

    def _hit(self, context, event):
        view = _view_under_mouse(context, event)
        if view is None:
            return None
        _area, region, rv3d = view
        coord = (event.mouse_x - region.x, event.mouse_y - region.y)
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
        inv = self._obj.matrix_world.inverted()
        ok, loc, nrm, _ = self._obj.ray_cast(inv @ origin, (inv.to_3x3() @ direction).normalized())
        if not ok:
            return None
        mw = self._obj.matrix_world
        return mw @ loc, (mw.to_3x3() @ nrm).normalized()

    def _finish(self, context):
        pts = self._builder.points()
        self._cleanup(context)
        if len(pts) < 8:
            self.report({"WARNING"}, "The line is too short, draw a longer stroke.")
            return {"CANCELLED"}
        _last_stroke["target"] = self._obj.name
        _last_stroke["points"] = np.array([tuple(p) for p, _ in pts])
        if self._old_curve is not None:
            bpy.data.objects.remove(self._old_curve, do_unlink=True)
        return self.execute(context)

    def modal(self, context, event):
        if event.type in NAV_EVENTS or event.type.startswith("NUMPAD") or (event.alt and event.type == "LEFTMOUSE"):
            return {"PASS_THROUGH"}  # otáčanie, posun a zoom pohľadu počas kreslenia
        if event.type == "ESC" and event.value == "PRESS":
            self._cleanup(context)
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._finish(context)
        if event.type in {"BACK_SPACE", "DEL"} or (event.type == "Z" and event.ctrl):
            if event.value == "PRESS" and self._builder.undo_piece():
                for a in context.window.screen.areas:
                    a.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                hit = self._hit(context, event)
                if hit is None:
                    return {"PASS_THROUGH"}  # kliknutie mimo modelu alebo mimo 3D okna
                self._drawing = True
                self._builder.begin(hit)
            elif event.value == "RELEASE":
                self._drawing = False
            for a in context.window.screen.areas:
                a.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "MOUSEMOVE" and self._drawing:
            hit = self._hit(context, event)
            last = self._builder.last_point()
            if hit is not None and (last is None or (hit[0] - last[0]).length > 1e-5 * max(self._obj.dimensions)):
                self._builder.add(hit)
            for a in context.window.screen.areas:
                a.tag_redraw()
        return {"RUNNING_MODAL"}

    def execute(self, context):
        pts, name = _last_stroke["points"], _last_stroke["target"]
        target = bpy.data.objects.get(name) if name else None
        if pts is None or target is None:
            return {"CANCELLED"}
        build_open_curve(context, target, pts, self.smooth, self.control_points)
        return {"FINISHED"}

    def _draw_overlay(self):
        size = max(self._obj.dimensions) or 1.0
        pts = [tuple(p + n * 0.003 * size) for p, n in self._builder.points()]
        if not pts:
            return
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        if len(pts) >= 2:
            line = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
            batch = batch_for_shader(line, "LINE_STRIP", {"pos": pts})
            line.bind()
            line.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
            line.uniform_float("lineWidth", 3.0)
            line.uniform_float("color", COLOR_STROKE)
            batch.draw(line)
        # koncový bod: odtiaľ sa pokračuje po otočení pohľadu
        gpu.state.depth_test_set("NONE")
        dot = gpu.shader.from_builtin("POINT_UNIFORM_COLOR")
        gpu.state.point_size_set(11.0)
        batch = batch_for_shader(dot, "POINTS", {"pos": [pts[-1]]})
        dot.bind()
        dot.uniform_float("color", (1.0, 1.0, 1.0, 1.0))
        batch.draw(dot)
        gpu.state.blend_set("NONE")


# --------------------------------------------------------------------------- 2. dokončenie slučky


class SMARTCUT_OT_complete(bpy.types.Operator):
    bl_idname = "smartcut.complete"
    bl_label = "Complete Loop"
    bl_description = "Close the open line into a full loop around the model (along the surface, on the far side)"
    bl_options = {"REGISTER", "UNDO"}

    smooth: FloatProperty(name="Smoothing", default=0.4, min=0.0, max=1.0)
    control_points: IntProperty(name="Control points", default=16, min=6, max=96)
    flip: BoolProperty(name="Other way round", description="Close the loop on the opposite side", default=False)

    @classmethod
    def poll(cls, context):
        c = _active_curve(context)
        return c is not None and not c.data.splines[0].use_cyclic_u

    def execute(self, context):
        curve = _active_curve(context)
        target = _target_of(context, curve)
        if target is None:
            self.report({"ERROR"}, "Target mesh not found. Select the curve and keep the model in the scene.")
            return {"CANCELLED"}
        stroke_w, _ = surface.curve_points_world(curve, 24)
        stroke = surface.to_local(target, stroke_w)
        loop = surface.complete_loop(target, stroke, flip=self.flip)
        if loop is None:
            self.report({"ERROR"}, "Could not find a path to close the loop. Draw a longer arc.")
            return {"CANCELLED"}
        tree = surface.build_bvh(target.data)
        n = max(256, self.control_points * 12)
        sm = geom.smooth_polyline(geom.resample(loop, n, closed=True), self.smooth, closed=True)
        for _ in range(2):  # vyhladiť a vrátiť na povrch, aby krivka sedela na modeli aj v zákrutách
            sm, _n = surface.project_to_surface(tree, sm)
            sm = geom.smooth_polyline(sm, self.smooth, closed=True)
        sm, _n = surface.project_to_surface(tree, sm)
        ctrl = geom.resample(sm, self.control_points, closed=True)
        ctrl, _n = surface.project_to_surface(tree, ctrl)
        _replace_curve_points(curve, surface.to_world(target, ctrl), True)
        curve.name = "CutLoop"
        return {"FINISHED"}


# --------------------------------------------------------------------------- 3. úprava


class SMARTCUT_OT_snap(bpy.types.Operator):
    bl_idname = "smartcut.snap"
    bl_label = "Snap Curve to Surface"
    bl_description = "After editing the curve, put its control points back onto the model surface"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _active_curve(context) is not None

    def execute(self, context):
        curve = _active_curve(context)
        target = _target_of(context, curve)
        if target is None:
            self.report({"ERROR"}, "Target mesh not found.")
            return {"CANCELLED"}
        if curve.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        tree = surface.build_bvh(target.data)
        w = surface.control_points_world(curve)
        local, _n = surface.project_to_surface(tree, surface.to_local(target, w))
        surface.set_control_points_world(curve, surface.to_world(target, local))
        return {"FINISHED"}


# --------------------------------------------------------------------------- 4. rez


class SMARTCUT_OT_cut(bpy.types.Operator):
    bl_idname = "smartcut.cut"
    bl_label = "Cut"
    bl_description = "Cut the model along the closed curve into two closed parts"
    bl_options = {"REGISTER", "UNDO"}

    refine_levels: IntProperty(
        name="Edge precision",
        description="How many times faces along the cut are subdivided before the edge is snapped to the curve. "
        "The edge follows the curve exactly at any value; higher values only add small triangles. 1 is usually best",
        default=1, min=0, max=4,
    )
    keep_original: BoolProperty(name="Keep original (hidden)", default=True)

    @classmethod
    def poll(cls, context):
        c = _active_curve(context)
        return c is not None and c.data.splines[0].use_cyclic_u

    def execute(self, context):
        curve = _active_curve(context)
        target = _target_of(context, curve)
        if target is None:
            self.report({"ERROR"}, "Target mesh not found.")
            return {"CANCELLED"}
        pts, _ = surface.curve_points_world(curve, 16)
        try:
            parts, info = cutter.cut_object(target, pts, self.refine_levels, self.keep_original)
        except cutter.CutError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        for o in context.selected_objects:
            o.select_set(False)
        for p in parts:
            p.select_set(True)
        context.view_layer.objects.active = parts[0]
        curve.hide_set(True)
        self.report({"INFO"}, f"Cut into {info['parts']} parts")
        return {"FINISHED"}


# --------------------------------------------------------------------------- 5. kolíky na lepenie


def _part_and_partner(context):
    part = context.active_object
    if part is None or part.type != "MESH":
        return None, None
    name = part.get("smartcut_partner")
    partner = bpy.data.objects.get(name) if name else None
    if partner is None:
        others = [o for o in context.selected_objects if o is not part and o.type == "MESH"]
        partner = others[0] if others else None
    return part, partner


class SMARTCUT_OT_connectors_add(bpy.types.Operator):
    bl_idname = "smartcut.connectors_add"
    bl_label = "Add / Update Pegs"
    bl_description = (
        "Place glue pegs on the cut surface using the settings above. They appear as wireframe previews you can "
        "move (G) or scale (S). Press again after changing a setting to rebuild them. Select one of the two cut parts"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        part, partner = _part_and_partner(context)
        return part is not None and partner is not None

    def execute(self, context):
        s = settings.get(context)
        part, partner = _part_and_partner(context)
        connectors.remove_preview_pins(part, partner)  # opakované kliknutie kolíky prekreslí, nehromadí
        try:
            pins, info = connectors.add_pins(
                part, partner, s.count, s.size, s.length, s.alternate, s.shape, s.taper
            )
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if info["requested"] and info["placed"] < info["requested"]:
            self.report(
                {"WARNING"},
                f"Only {info['placed']} of {info['requested']} pegs fit at {info['size']:.2f}; use a smaller size.",
            )
        if info["size"] > info["max_fit"] * 1.001:
            self.report(
                {"WARNING"},
                f"Peg {info['size']:.2f} is wider than the cut comfortably fits ({info['max_fit']:.2f}); "
                "it may reach past the edge.",
            )
        for o in context.selected_objects:
            o.select_set(False)
        for p in pins:
            p.select_set(True)
        context.view_layer.objects.active = pins[0]
        self.report(
            {"INFO"},
            f"{len(pins)} peg(s) {info['size']:.2f} x {info['length']:.2f}, hole {info['size'] + 2 * s.clearance:.2f}",
        )
        return {"FINISHED"}


class SMARTCUT_OT_connectors_apply(bpy.types.Operator):
    bl_idname = "smartcut.connectors_apply"
    bl_label = "Apply Pegs"
    bl_description = "Join each peg to its part and cut a matching hole (peg + clearance on each side) into the other part"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.get(connectors.PIN_PROP) for o in context.scene.objects)

    def execute(self, context):
        s = settings.get(context)
        pins = [o for o in context.scene.objects if o.get(connectors.PIN_PROP)]
        n = connectors.apply_pins(pins, s.clearance)
        self.report({"INFO"}, f"{n} peg(s) applied with {s.clearance:.3f} clearance per side")
        return {"FINISHED"} if n else {"CANCELLED"}


class VIEW3D_PT_smart_cut(bpy.types.Panel):
    bl_label = "Smart Cut"
    bl_idname = "VIEW3D_PT_smart_cut"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smart Cut"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="1. Select the model, draw the line")
        col.operator("smartcut.draw", icon="GREASEPENCIL").extend = False
        col.operator("smartcut.draw", text="Continue Line", icon="PLUS").extend = True
        col.separator()
        col.label(text="2. Close it into a loop")
        col.operator("smartcut.complete", icon="MESH_CIRCLE")
        col.separator()
        col.label(text="3. Optional: edit the curve")
        col.label(text="Tab into Edit Mode, move points", icon="INFO")
        col.operator("smartcut.snap", icon="SNAP_ON")
        col.separator()
        col.label(text="4. Cut")
        col.operator("smartcut.cut", icon="MOD_BUILD")
        col.separator()
        col.label(text="5. Glue pegs (select a cut part)")

        box = self.layout.box()
        s = settings.get(context)
        c = box.column(align=True)
        c.prop(s, "shape")
        c.prop(s, "size")
        c.prop(s, "length")
        c.prop(s, "count")
        c.prop(s, "taper")
        c.prop(s, "alternate")
        c.separator()
        c.prop(s, "clearance")
        info = box.column(align=True)
        if s.size > 0:
            info.label(text=f"Peg {s.size:.2f} \u2192 hole {s.size + 2 * s.clearance:.2f} (gap {s.clearance:.3f}/side)")
        else:
            info.label(text=f"Hole = peg + {2 * s.clearance:.3f} (gap {s.clearance:.3f}/side)")
        ops = self.layout.column(align=True)
        ops.operator("smartcut.connectors_add", icon="PINNED")
        ops.operator("smartcut.connectors_apply", icon="CHECKMARK")


CLASSES = (
    SMARTCUT_OT_draw,
    SMARTCUT_OT_complete,
    SMARTCUT_OT_snap,
    SMARTCUT_OT_cut,
    SMARTCUT_OT_connectors_add,
    SMARTCUT_OT_connectors_apply,
    VIEW3D_PT_smart_cut,
)
