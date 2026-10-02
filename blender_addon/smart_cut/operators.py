import bpy
import gpu
import numpy as np
from bpy.props import BoolProperty, FloatProperty, IntProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from . import cutter, geom, surface

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


class SMARTCUT_OT_draw(bpy.types.Operator):
    bl_idname = "smartcut.draw"
    bl_label = "Draw Cut Line"
    bl_description = "Draw the cut line directly on the model. Left mouse drag draws, release finishes, Esc cancels"
    bl_options = {"REGISTER", "UNDO"}

    smooth: FloatProperty(
        name="Smoothing", description="How much the hand-drawn line is smoothed", default=0.5, min=0.0, max=1.0
    )
    control_points: IntProperty(
        name="Control points", description="Fewer points = smoother and easier to edit", default=12, min=4, max=64
    )

    @classmethod
    def poll(cls, context):
        o = context.active_object
        return o is not None and o.type == "MESH" and context.mode == "OBJECT" and context.area and context.area.type == "VIEW_3D"

    def invoke(self, context, event):
        self._obj = context.active_object
        self._pts = []  # (svetový bod, normála)
        self._drawing = False
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw_overlay, (), "WINDOW", "POST_VIEW")
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set("PAINT_BRUSH")
        context.workspace.status_text_set("Smart Cut: drag with left mouse on the model to draw  |  Esc cancel")
        return {"RUNNING_MODAL"}

    def _cleanup(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        if context.area:
            context.area.tag_redraw()

    def _hit(self, context, event):
        region, rv3d = context.region, context.region_data
        if region is None or rv3d is None or region.type != "WINDOW":
            return None
        x, y = event.mouse_region_x, event.mouse_region_y
        if not (0 <= x < region.width and 0 <= y < region.height):
            return None
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
        inv = self._obj.matrix_world.inverted()
        ok, loc, nrm, _ = self._obj.ray_cast(inv @ origin, (inv.to_3x3() @ direction).normalized())
        if not ok:
            return None
        mw = self._obj.matrix_world
        return mw @ loc, (mw.to_3x3() @ nrm).normalized()

    def _add(self, context, event):
        hit = self._hit(context, event)
        if hit is None:
            return
        if self._pts and (hit[0] - self._pts[-1][0]).length < 1e-5 * max(self._obj.dimensions):
            return
        self._pts.append(hit)

    def modal(self, context, event):
        if event.type in {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE"} or event.type.startswith("NUMPAD"):
            return {"PASS_THROUGH"}  # otáčanie pohľadu počas kreslenia
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            self._cleanup(context)
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE":
            if event.value == "PRESS":
                self._drawing, self._pts = True, []
                self._add(context, event)
            elif event.value == "RELEASE" and self._drawing:
                self._drawing = False
                self._cleanup(context)
                if len(self._pts) < 8:
                    self.report({"WARNING"}, "The line is too short, draw a longer stroke.")
                    return {"CANCELLED"}
                _last_stroke["target"] = self._obj.name
                _last_stroke["points"] = np.array([tuple(p) for p, _ in self._pts])
                return self.execute(context)
        elif event.type == "MOUSEMOVE" and self._drawing:
            self._add(context, event)
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def execute(self, context):
        pts, name = _last_stroke["points"], _last_stroke["target"]
        target = bpy.data.objects.get(name) if name else None
        if pts is None or target is None:
            return {"CANCELLED"}
        build_open_curve(context, target, pts, self.smooth, self.control_points)
        return {"FINISHED"}

    def _draw_overlay(self):
        pts = [p + n * 0.003 * max(self._obj.dimensions) for p, n in self._pts]
        if len(pts) < 2:
            return
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINE_STRIP", {"pos": [tuple(p) for p in pts]})
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL")
        shader.bind()
        shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        shader.uniform_float("lineWidth", 3.0)
        shader.uniform_float("color", COLOR_STROKE)
        batch.draw(shader)
        gpu.state.depth_test_set("NONE")
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
        description="How many times faces along the cut are subdivided so the edge follows the curve closely",
        default=3, min=0, max=5,
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


class VIEW3D_PT_smart_cut(bpy.types.Panel):
    bl_label = "Smart Cut"
    bl_idname = "VIEW3D_PT_smart_cut"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Smart Cut"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="1. Select the model, draw the line")
        col.operator("smartcut.draw", icon="GREASEPENCIL")
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


CLASSES = (
    SMARTCUT_OT_draw,
    SMARTCUT_OT_complete,
    SMARTCUT_OT_snap,
    SMARTCUT_OT_cut,
    VIEW3D_PT_smart_cut,
)
