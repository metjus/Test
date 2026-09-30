"""Face painting for single-mesh models: brush and fill tools with X/Y/Z symmetry.

Painting assigns the active colour's material slot to the faces under the
brush, so the exporter picks the colours up like any other material.
Symmetry mirrors each dab across the object's origin in local space.
"""

import itertools
import math

import blf
import bpy
import gpu
from bpy.props import BoolProperty, EnumProperty, IntProperty, PointerProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

# Events passed on to Blender while painting, so the view can still be navigated.
NAV_EVENTS = {
    "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "WHEELINMOUSE", "WHEELOUTMOUSE",
    "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM",
    "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4", "NUMPAD_5",
    "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9", "NUMPAD_PERIOD",
    "NUMPAD_PLUS", "NUMPAD_MINUS", "NDOF_MOTION",
}
# (keys, action) pairs shown in the panel and the viewport overlay.
CONTROLS = [
    ("LMB drag", "Paint active colour"),
    ("Shift + LMB", "Paint base colour (erase)"),
    ("1 - 9", "Pick colour"),
    ("[  ]", "Brush radius"),
    ("F", "Brush / Fill"),
    ("X  Y  Z", "Toggle symmetry"),
    ("Ctrl+Z", "Undo stroke"),
    ("MMB / Wheel", "Navigate view"),
    ("H", "Show / hide controls"),
    ("Esc / Enter / RMB", "Finish"),
]
NUMBER_KEYS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]

# Default colours for newly added paint colours (linear RGB).
NEW_COLORS = [
    (0.8, 0.02, 0.02), (0.02, 0.12, 0.8), (0.03, 0.5, 0.05), (0.9, 0.6, 0.0),
    (0.0, 0.0, 0.0), (0.5, 0.05, 0.6), (0.9, 0.25, 0.4), (0.3, 0.13, 0.03),
]

_running = None  # the active BAMBU_OT_paint operator, if any


def symmetry_signs(sym_x, sym_y, sym_z):
    """Sign vectors for every mirror copy; the first one is the identity."""
    axes = [(1, -1) if on else (1,) for on in (sym_x, sym_y, sym_z)]
    return [Vector(signs) for signs in itertools.product(*axes)]


class PaintSession:
    """Paints material indices onto one mesh's faces, in object local space."""

    def __init__(self, obj):
        self.obj = obj
        mesh = obj.data
        polys = mesh.polygons
        self.bvh = BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],
                                        [tuple(p.vertices) for p in polys])
        self.kd = KDTree(len(polys))
        for p in polys:
            self.kd.insert(p.center, p.index)
        self.kd.balance()
        self.normals = [p.normal.copy() for p in polys]

        edge_faces = {}
        for p in polys:
            for key in p.edge_keys:
                edge_faces.setdefault(key, []).append(p.index)
        self.neighbors = [[] for _ in polys]
        for faces in edge_faces.values():
            for a in faces:
                self.neighbors[a].extend(b for b in faces if b != a)

        self.undo_stack = []
        self.stroke = None
        self.dirty = False

    # -- strokes / undo ----------------------------------------------------

    def begin_stroke(self):
        self.stroke = {}

    def end_stroke(self):
        if self.stroke:
            self.undo_stack.append(self.stroke)
        self.stroke = None

    def undo(self):
        if not self.undo_stack:
            return False
        polys = self.obj.data.polygons
        for face, old in self.undo_stack.pop().items():
            polys[face].material_index = old
        self.dirty = True
        self.flush()
        return True

    def flush(self):
        """Push pending face changes to the viewport."""
        if self.dirty:
            self.obj.data.update()
            self.dirty = False

    def _apply(self, faces, mat_index):
        polys = self.obj.data.polygons
        for face in faces:
            old = polys[face].material_index
            if old != mat_index:
                if self.stroke is not None:
                    self.stroke.setdefault(face, old)
                polys[face].material_index = mat_index
                self.dirty = True

    # -- tools -------------------------------------------------------------

    def ray_cast(self, origin, direction):
        """(location, normal, face) of the first hit in local space, or None."""
        loc, normal, face, _dist = self.bvh.ray_cast(origin, direction)
        return None if loc is None else (loc, normal, face)

    def _mirrored(self, point, normal, face, signs):
        for sign in signs:
            if all(s > 0 for s in sign):
                yield point, normal, face
                continue
            loc, nrm, idx, _dist = self.bvh.find_nearest(point * sign)
            if loc is not None:
                yield loc, nrm, idx

    def brush(self, point, normal, face, radius, mat_index, signs):
        """Paint faces whose centre is within radius and that face the brush."""
        faces = set()
        for p, n, f in self._mirrored(point, normal, face, signs):
            faces.add(f)
            for _co, idx, _dist in self.kd.find_range(p, radius):
                if self.normals[idx].dot(n) > 0.0:
                    faces.add(idx)
        self._apply(faces, mat_index)

    def fill(self, point, normal, face, mat_index, signs):
        """Paint the connected area that has the same colour as the clicked face."""
        faces = set()
        for _p, _n, f in self._mirrored(point, normal, face, signs):
            faces |= self._region(f)
        self._apply(faces, mat_index)

    def _region(self, seed):
        polys = self.obj.data.polygons
        target = polys[seed].material_index
        seen = {seed}
        stack = [seed]
        while stack:
            for nb in self.neighbors[stack.pop()]:
                if nb not in seen and polys[nb].material_index == target:
                    seen.add(nb)
                    stack.append(nb)
        return seen


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

def new_color_material(name, rgb):
    mat = bpy.data.materials.new(name)
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    mat.diffuse_color = (*rgb, 1.0)
    return mat


def add_color(obj, rgb=None, name="Colour"):
    """Append a new colour material slot to obj and make it active."""
    count = len(obj.material_slots)
    if rgb is None:
        rgb = (0.8, 0.8, 0.8) if count == 0 else NEW_COLORS[(count - 1) % len(NEW_COLORS)]
    mat = new_color_material("Base" if count == 0 and name == "Colour" else name, rgb)
    obj.data.materials.append(mat)
    obj.active_material_index = len(obj.material_slots) - 1
    return mat


def sync_viewport_colors(obj):
    """Make Solid-view colours match the materials' real colours."""
    from . import material_linear_color
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        rgb = material_linear_color(mat)
        if any(abs(a - b) > 1e-5 for a, b in zip(rgb, mat.diffuse_color)):
            mat.diffuse_color = (*rgb, 1.0)


def _sync_handler(scene, depsgraph):
    # Keep Solid view in step with swatch edits on the object being painted.
    op = _running
    if op is None:
        return
    try:
        sync_viewport_colors(op.session.obj)
    except (ReferenceError, AttributeError, RuntimeError):
        pass


# ---------------------------------------------------------------------------
# Settings and operators
# ---------------------------------------------------------------------------

class BambuPaintSettings(bpy.types.PropertyGroup):
    tool: EnumProperty(
        name="Tool",
        items=[("BRUSH", "Brush", "Paint the faces under the brush circle"),
               ("FILL", "Fill", "Fill the connected area that has the same colour")],
        default="BRUSH")
    radius: IntProperty(name="Radius", subtype="PIXEL", default=30, min=2, max=500,
                        description="Brush radius in screen pixels ([ and ] while painting)")
    sym_x: BoolProperty(name="X", description="Mirror painting across the object's X axis")
    sym_y: BoolProperty(name="Y", description="Mirror painting across the object's Y axis")
    sym_z: BoolProperty(name="Z", description="Mirror painting across the object's Z axis")
    show_controls: BoolProperty(name="Controls", default=False,
                                description="Show the painting controls in this panel")
    show_overlay: BoolProperty(name="Show Controls in Viewport", default=True,
                               description="Show the painting controls in the viewport while painting (H)")


class BAMBU_OT_paint_add_color(bpy.types.Operator):
    """Add a new paint colour to the active object"""
    bl_idname = "bambu.paint_add_color"
    bl_label = "Add Colour"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH"

    def execute(self, context):
        add_color(context.active_object)
        return {"FINISHED"}


class BAMBU_OT_paint_set_color(bpy.types.Operator):
    """Paint with this colour (number keys 1-9 while painting)"""
    bl_idname = "bambu.paint_set_color"
    bl_label = "Set Paint Colour"
    bl_options = {"INTERNAL"}

    index: IntProperty()

    def execute(self, context):
        obj = context.active_object
        if obj and self.index < len(obj.material_slots):
            obj.active_material_index = self.index
        return {"FINISHED"}


class BAMBU_OT_paint(bpy.types.Operator):
    """Paint colours onto the active mesh. LMB paint, Shift+LMB paint base colour,
    1-9 pick colour, [ ] radius, F brush/fill, X/Y/Z symmetry, Ctrl+Z undo, Esc finish"""
    bl_idname = "bambu.paint"
    bl_label = "Paint Colours"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (_running is None and context.area is not None and context.area.type == "VIEW_3D"
                and obj is not None and obj.type == "MESH")

    def invoke(self, context, event):
        global _running
        obj = context.active_object
        if obj.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if not obj.data.polygons:
            self.report({"ERROR"}, "Object has no faces to paint")
            return {"CANCELLED"}
        if not obj.material_slots:
            add_color(obj)
            add_color(obj)

        self.area = context.area
        self.region = next(r for r in self.area.regions if r.type == "WINDOW")
        self.rv3d = self.area.spaces.active.region_3d
        self.settings = context.scene.bambu_paint
        self.session = PaintSession(obj)
        self.painting = False
        self.mouse = None
        self.last = None

        sync_viewport_colors(obj)
        shading = self.area.spaces.active.shading
        if shading.type == "SOLID":
            shading.color_type = "MATERIAL"

        self._draw = bpy.types.SpaceView3D.draw_handler_add(_draw_brush, (self,), "WINDOW", "POST_PIXEL")
        bpy.app.handlers.depsgraph_update_post.append(_sync_handler)
        _running = self
        context.window_manager.modal_handler_add(self)
        self._update_status(context)
        return {"RUNNING_MODAL"}

    # -- helpers -------------------------------------------------------------

    def _region_mouse(self, event):
        """Mouse position inside the 3D view's main region, or None when over
        the header, toolbar or sidebar (so panel buttons keep working)."""
        for r in self.area.regions:
            if r.type != "WINDOW" and r.width > 1 and r.height > 1:
                if r.x <= event.mouse_x < r.x + r.width and r.y <= event.mouse_y < r.y + r.height:
                    return None
        r = self.region
        x, y = event.mouse_x - r.x, event.mouse_y - r.y
        return (x, y) if 0 <= x < r.width and 0 <= y < r.height else None

    def _hit(self, coord):
        mw = self.session.obj.matrix_world
        inv = mw.inverted()
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, coord)
        return self.session.ray_cast(inv @ origin, (inv.to_3x3() @ direction).normalized())

    def _local_radius(self, coord, local_point):
        """Convert the pixel radius to object space at the hit depth."""
        mw = self.session.obj.matrix_world
        world = mw @ local_point
        edge = view3d_utils.region_2d_to_location_3d(
            self.region, self.rv3d, (coord[0] + self.settings.radius, coord[1]), world)
        scale = sum(abs(s) for s in mw.to_scale()) / 3.0 or 1.0
        return (edge - world).length / scale

    def _dab(self, coord, erase):
        hit = self._hit(coord)
        if hit is None:
            return
        point, normal, face = hit
        s = self.settings
        mat_index = 0 if erase else self.session.obj.active_material_index
        signs = symmetry_signs(s.sym_x, s.sym_y, s.sym_z)
        if s.tool == "FILL":
            self.session.fill(point, normal, face, mat_index, signs)
        else:
            self.session.brush(point, normal, face, self._local_radius(coord, point), mat_index, signs)

    def _stroke_to(self, coord, erase):
        # Interpolate between mouse events so fast strokes leave no gaps.
        if self.last is None:
            self._dab(coord, erase)
        else:
            dx, dy = coord[0] - self.last[0], coord[1] - self.last[1]
            step = max(2.0, self.settings.radius * 0.4)
            n = max(1, int(math.hypot(dx, dy) / step))
            for i in range(1, n + 1):
                self._dab((self.last[0] + dx * i / n, self.last[1] + dy * i / n), erase)
        self.last = coord
        self.session.flush()

    def _update_status(self, context):
        s = self.settings
        sym = "".join(a for a, on in zip("XYZ", (s.sym_x, s.sym_y, s.sym_z)) if on) or "off"
        context.workspace.status_text_set(
            "Bambu Paint [%s, symmetry %s]  LMB paint · Shift+LMB base colour · 1-9 colour · "
            "[ ] radius · F brush/fill · X/Y/Z symmetry · Ctrl+Z undo · H controls · Esc/Enter finish"
            % (s.tool.title(), sym))

    def _finish(self, context):
        global _running
        self.session.end_stroke()
        self.session.flush()
        bpy.types.SpaceView3D.draw_handler_remove(self._draw, "WINDOW")
        if _sync_handler in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_sync_handler)
        context.workspace.status_text_set(None)
        _running = None
        self.area.tag_redraw()
        return {"FINISHED"}

    # -- event loop ----------------------------------------------------------

    def modal(self, context, event):
        self.area.tag_redraw()
        if event.type in NAV_EVENTS or (event.alt and event.type == "LEFTMOUSE"):
            return {"PASS_THROUGH"}

        coord = self._region_mouse(event)
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            self.mouse = coord
            if self.painting and coord and self.settings.tool == "BRUSH":
                self._stroke_to(coord, event.shift)
                return {"RUNNING_MODAL"}
            return {"PASS_THROUGH"}

        press = event.value == "PRESS"
        if press and event.type in {"ESC", "RET", "NUMPAD_ENTER"}:
            return self._finish(context)
        if coord is None and not self.painting:
            return {"PASS_THROUGH"}  # clicks on the sidebar, header, etc.

        if event.type == "LEFTMOUSE":
            if press and coord:
                self.painting = True
                self.last = None
                self.session.begin_stroke()
                self._stroke_to(coord, event.shift)
            elif event.value == "RELEASE":
                self.painting = False
                self.session.end_stroke()
            return {"RUNNING_MODAL"}

        if not press:
            return {"RUNNING_MODAL"}
        s = self.settings
        if event.type == "RIGHTMOUSE":
            return self._finish(context)
        if event.type == "Z" and (event.ctrl or event.oskey):
            if not self.session.undo():
                self.report({"INFO"}, "Nothing to undo")
        elif event.type == "LEFT_BRACKET":
            s.radius = max(2, int(s.radius / 1.2))
        elif event.type == "RIGHT_BRACKET":
            s.radius = min(500, int(s.radius * 1.2) + 1)
        elif event.type == "H":
            s.show_overlay = not s.show_overlay
        elif event.type == "F":
            s.tool = "FILL" if s.tool == "BRUSH" else "BRUSH"
        elif event.type in {"X", "Y", "Z"}:
            attr = "sym_" + event.type.lower()
            setattr(s, attr, not getattr(s, attr))
        elif event.type in NUMBER_KEYS:
            index = NUMBER_KEYS.index(event.type)
            if index < len(self.session.obj.material_slots):
                self.session.obj.active_material_index = index
        self._update_status(context)
        return {"RUNNING_MODAL"}


def _draw_controls(op):
    """Controls list and current state in the viewport's bottom-left corner."""
    s = op.settings
    scale = bpy.context.preferences.view.ui_scale
    tools = next((r for r in op.area.regions if r.type == "TOOLS"), None)
    x = (tools.width if tools else 0) + 20 * scale
    line = 18 * scale
    font = 0
    obj = op.session.obj
    mat = obj.active_material
    sym = " ".join(a for a, on in zip("XYZ", (s.sym_x, s.sym_y, s.sym_z)) if on) or "off"
    state = "%s · colour %d %s · symmetry %s" % (
        s.tool.title(), obj.active_material_index + 1, mat.name if mat else "", sym)

    blf.size(font, 13 * scale)
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.9)
    blf.shadow_offset(font, 1, -1)
    y = 20 * scale
    rows = CONTROLS if s.show_overlay else [("H", "Show controls")]
    for keys, action in reversed(rows):
        blf.color(font, 1.0, 0.85, 0.4, 1.0)
        blf.position(font, x, y, 0)
        blf.draw(font, keys)
        blf.color(font, 1.0, 1.0, 1.0, 0.9)
        blf.position(font, x + 130 * scale, y, 0)
        blf.draw(font, action)
        y += line
    blf.color(font, 0.6, 0.9, 1.0, 1.0)
    blf.position(font, x, y + 4 * scale, 0)
    blf.draw(font, "Bambu Paint: " + state)
    blf.disable(font, blf.SHADOW)


def _draw_brush(op):
    _draw_controls(op)
    if op.mouse is None:
        return
    from . import material_linear_color
    x, y = op.mouse
    s = op.settings
    obj = op.session.obj
    mat = obj.active_material
    rgb = material_linear_color(mat) if mat else (1.0, 1.0, 1.0)

    radius = s.radius if s.tool == "BRUSH" else 8
    segments = 48
    circle = [(x + radius * math.cos(2 * math.pi * i / segments),
               y + radius * math.sin(2 * math.pi * i / segments)) for i in range(segments + 1)]
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.line_width_set(3.0)
    shader.bind()
    shader.uniform_float("color", (0.0, 0.0, 0.0, 0.6))
    batch_for_shader(shader, "LINE_STRIP", {"pos": circle}).draw(shader)
    gpu.state.line_width_set(1.5)
    shader.uniform_float("color", (*rgb, 1.0))
    batch_for_shader(shader, "LINE_STRIP", {"pos": circle}).draw(shader)
    if s.tool == "FILL":
        cross = [(x - 14, y), (x + 14, y), (x, y - 14), (x, y + 14)]
        batch_for_shader(shader, "LINES", {"pos": cross}).draw(shader)
    gpu.state.line_width_set(1.0)
    gpu.state.blend_set("NONE")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class VIEW3D_PT_bambu_paint(bpy.types.Panel):
    bl_label = "Bambu Paint"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bambu"

    def draw(self, context):
        from . import material_color_source
        layout = self.layout
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            layout.label(text="Select a mesh object to paint", icon="INFO")
            return
        s = context.scene.bambu_paint

        layout.label(text="Colours of %s" % obj.name)
        col = layout.column(align=True)
        for i, slot in enumerate(obj.material_slots):
            row = col.row(align=True)
            swatch = row.row(align=True)
            swatch.ui_units_x = 2.5
            mat = slot.material
            if mat:
                owner, prop = material_color_source(mat)
                swatch.prop(owner, prop, text="")
            else:
                swatch.label(text="")
            name = mat.name if mat else "(empty)"
            op = row.operator(BAMBU_OT_paint_set_color.bl_idname,
                              text="%d  %s" % (i + 1, name) if i < 9 else name,
                              depress=(i == obj.active_material_index))
            op.index = i
        col.operator(BAMBU_OT_paint_add_color.bl_idname, icon="ADD")

        layout.row().prop(s, "tool", expand=True)
        if s.tool == "BRUSH":
            layout.prop(s, "radius")
        row = layout.row(align=True)
        row.label(text="Symmetry")
        row.prop(s, "sym_x", toggle=True)
        row.prop(s, "sym_y", toggle=True)
        row.prop(s, "sym_z", toggle=True)

        if _running is not None:
            layout.label(text="Painting… Esc/Enter to finish", icon="BRUSH_DATA")
        else:
            layout.operator(BAMBU_OT_paint.bl_idname, text="Start Painting", icon="BRUSH_DATA")
        row = layout.row()
        row.prop(s, "show_controls", emboss=False,
                 icon="DISCLOSURE_TRI_DOWN" if s.show_controls else "DISCLOSURE_TRI_RIGHT")
        if s.show_controls:
            box = layout.box().column(align=True)
            for keys, action in CONTROLS:
                split = box.split(factor=0.42)
                split.label(text=keys)
                split.label(text=action)
            box.separator()
            box.prop(s, "show_overlay")

        box = layout.box().column(align=True)
        box.label(text="Colour 1 is the base colour.")
        box.label(text="Paint works per face: add detail")
        box.label(text="(subdivide) for finer edges.")
        box.label(text="Symmetry mirrors around the origin.")


classes = (
    BambuPaintSettings,
    BAMBU_OT_paint_add_color,
    BAMBU_OT_paint_set_color,
    BAMBU_OT_paint,
    VIEW3D_PT_bambu_paint,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.bambu_paint = PointerProperty(type=BambuPaintSettings)


def unregister():
    global _running
    if _sync_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_sync_handler)
    _running = None
    del bpy.types.Scene.bambu_paint
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
