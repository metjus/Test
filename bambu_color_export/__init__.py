"""Export material colours from Blender so Bambu Studio can read them.

Every triangle is tagged with the filament slot of its material's colour, so
Bambu Studio opens the model already painted, one filament per colour.
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from . import paint, writers
from .writers import MAX_FILAMENTS, PaletteEntry

GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}
NO_MATERIAL = "(no material)"
DEFAULT_RGB = (0.8, 0.8, 0.8)


# ---------------------------------------------------------------------------
# Material colour resolution
# ---------------------------------------------------------------------------

def linear_to_srgb(c):
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


def _socket_source(socket, depth=0):
    """(owner, property) holding the colour on a colour socket, following simple links."""
    if depth > 16:
        return None
    if not socket.is_linked:
        return socket, "default_value"
    node = socket.links[0].from_node
    if node.type == "RGB":
        return node.outputs[0], "default_value"
    if node.type == "REROUTE":
        return _socket_source(node.inputs[0], depth + 1)
    return None


# Shader node type -> name of its colour input.
_SHADER_COLOR_INPUT = {
    "BSDF_PRINCIPLED": "Base Color",
    "BSDF_DIFFUSE": "Color",
    "EMISSION": "Color",
    "BSDF_GLOSSY": "Color",
    "SUBSURFACE_SCATTERING": "Color",
    "BSDF_TOON": "Color",
}


def _shader_source(node, depth=0):
    if node is None or depth > 16:
        return None
    if node.type == "REROUTE":
        inp = node.inputs[0]
        return _shader_source(inp.links[0].from_node, depth + 1) if inp.is_linked else None
    if node.type in ("MIX_SHADER", "ADD_SHADER"):
        for inp in node.inputs:
            if inp.type == "SHADER" and inp.is_linked:
                source = _shader_source(inp.links[0].from_node, depth + 1)
                if source is not None:
                    return source
        return None
    name = _SHADER_COLOR_INPUT.get(node.type)
    if name and name in node.inputs:
        return _socket_source(node.inputs[name])
    return None


def material_color_source(mat):
    """(owner, property) that defines a material's colour, for reading or editing.

    This is the Color (RGB) node or shader colour input feeding the active
    output; otherwise the material's viewport display colour.
    """
    if getattr(mat, "use_nodes", True) and mat.node_tree:
        outputs = [n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]
        active = [n for n in outputs if n.is_active_output] or outputs
        for out in active:
            surface = out.inputs.get("Surface")
            if surface and surface.is_linked:
                source = _shader_source(surface.links[0].from_node)
                if source is not None:
                    return source
    return mat, "diffuse_color"


def material_linear_color(mat):
    """Linear RGB colour of a material."""
    if mat is None:
        return DEFAULT_RGB
    owner, prop = material_color_source(mat)
    return tuple(getattr(owner, prop)[:3])


def material_srgb(mat):
    return tuple(linear_to_srgb(c) for c in material_linear_color(mat))


# ---------------------------------------------------------------------------
# Palette: colour -> filament slot
# ---------------------------------------------------------------------------

def _close(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def build_palette(materials, tolerance, merge_same_colors=True):
    """Return (palette, {material_name: palette_index}) for the given materials.

    Materials with ``bambu_filament`` > 0 keep that slot; the rest get the
    next free slot, sharing one when their colours match within tolerance.
    """
    palette = []
    index_of = {}

    def add(key, rgb, filament, mat_name):
        palette.append(PaletteEntry(name=mat_name, rgb=rgb, filament=filament, materials=[mat_name]))
        index_of[key] = len(palette) - 1

    # Explicit slots first, so automatic ones can avoid them.
    auto = []
    for mat in materials:
        key = mat.name if mat else NO_MATERIAL
        slot = getattr(mat, "bambu_filament", 0) if mat else 0
        if slot > 0:
            rgb = material_srgb(mat)
            same = next((i for i, e in enumerate(palette) if e.filament == slot), None)
            if same is not None:
                palette[same].materials.append(key)
                index_of[key] = same
            else:
                add(key, rgb, slot, key)
        else:
            auto.append(mat)

    used = {e.filament for e in palette}
    next_slot = 1
    for mat in auto:
        key = mat.name if mat else NO_MATERIAL
        rgb = material_srgb(mat)
        match = None
        if merge_same_colors:
            match = next((i for i, e in enumerate(palette) if _close(e.rgb, rgb, tolerance)), None)
        if match is not None:
            palette[match].materials.append(key)
            index_of[key] = match
            continue
        while next_slot in used:
            next_slot += 1
        add(key, rgb, next_slot, key)
        used.add(next_slot)
    return palette, index_of


# ---------------------------------------------------------------------------
# Geometry collection
# ---------------------------------------------------------------------------

def export_objects(context, selected_only):
    objs = context.selected_objects if selected_only else context.visible_objects
    return [o for o in objs if o.type in GEOMETRY_TYPES or o.instance_type != "NONE"]


def used_materials(objects):
    """Materials referenced by the objects' slots (for the UI list)."""
    seen = {}
    for obj in objects:
        if obj.type not in GEOMETRY_TYPES:
            continue
        slots = [s.material for s in obj.material_slots] or [None]
        for mat in slots:
            seen.setdefault(mat.name if mat else NO_MATERIAL, mat)
    return list(seen.values())


def panel_rows(objects):
    """(object, material, label) rows for the sidebar: one per object, or one
    per material when an object has several."""
    rows = []
    for obj in sorted(objects, key=lambda o: o.name):
        if obj.type not in GEOMETRY_TYPES:
            continue
        mats = list(dict.fromkeys(s.material for s in obj.material_slots if s.material)) or [None]
        for mat in mats:
            label = obj.name if len(mats) == 1 else "%s \u00b7 %s" % (obj.name, mat.name)
            rows.append((obj, mat, label))
    return rows


def _panel_palette(context):
    objects = export_objects(context, bool(context.selected_objects))
    materials = used_materials(objects)
    palette, index_of = build_palette(materials, 0.02) if materials else ([], {})
    return objects, palette, index_of


def _get_slot(mat):
    """Effective filament slot: the manual one, or the automatic one."""
    if mat.bambu_filament:
        return mat.bambu_filament
    _objects, palette, index_of = _panel_palette(bpy.context)
    i = index_of.get(mat.name)
    return palette[i].filament if i is not None else 0


def _set_slot(mat, value):
    mat.bambu_filament = value


def collect_geometry(context, objects, scale):
    """Evaluate objects (modifiers, instances) into one world-space triangle soup.

    Returns (vertices, triangles, tri_materials) where tri_materials holds the
    Material (or None) of each triangle.
    """
    depsgraph = context.evaluated_depsgraph_get()
    wanted = {o.original for o in objects}
    vertices, triangles, tri_materials = [], [], []

    for inst in depsgraph.object_instances:
        ob = inst.object
        owner = inst.parent.original if inst.is_instance and inst.parent else ob.original
        if owner not in wanted or ob.type not in GEOMETRY_TYPES:
            continue
        matrix = inst.matrix_world.copy()
        mesh = ob.to_mesh()
        if mesh is None:
            continue
        try:
            mesh.calc_loop_triangles()
            base = len(vertices)
            for v in mesh.vertices:
                co = matrix @ v.co
                vertices.append((co.x * scale, co.y * scale, co.z * scale))
            mats = [s.material for s in ob.material_slots] or list(mesh.materials)
            flip = matrix.determinant() < 0
            for tri in mesh.loop_triangles:
                a, b, c = tri.vertices
                if flip:
                    b, c = c, b
                triangles.append((a + base, b + base, c + base))
                mi = tri.material_index
                tri_materials.append(mats[mi] if mi < len(mats) else None)
        finally:
            ob.to_mesh_clear()
    return vertices, triangles, tri_materials


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class _BambuExportBase(ExportHelper):
    use_selection: BoolProperty(
        name="Selected Only", default=True,
        description="Export only selected objects (otherwise all visible objects)")
    global_scale: FloatProperty(
        name="Scale", default=1.0, min=1e-6, max=1e6, soft_min=0.001, soft_max=1000.0,
        description="Scale factor; 1 Blender unit = 1 mm at scale 1.0")
    use_scene_unit: BoolProperty(
        name="Use Scene Units", default=False,
        description="Convert using the scene's unit scale so 1 m in Blender becomes 1000 mm")
    merge_same_colors: BoolProperty(
        name="Merge Same Colours", default=True,
        description="Materials with the same colour share one filament")
    color_tolerance: FloatProperty(
        name="Colour Tolerance", default=0.02, min=0.0, max=1.0,
        description="Max per-channel difference for two colours to count as the same")

    def _scale(self, context):
        scale = self.global_scale
        if self.use_scene_unit:
            scale *= context.scene.unit_settings.scale_length * 1000.0
        return scale

    def execute(self, context):
        objects = export_objects(context, self.use_selection)
        if not objects:
            self.report({"ERROR"}, "Nothing to export (select mesh objects or untick Selected Only)")
            return {"CANCELLED"}

        vertices, triangles, tri_mats = collect_geometry(context, objects, self._scale(context))
        if not triangles:
            self.report({"ERROR"}, "Selected objects have no faces")
            return {"CANCELLED"}

        materials = list({(m.name if m else NO_MATERIAL): m for m in tri_mats}.values())
        palette, index_of = build_palette(materials, self.color_tolerance, self.merge_same_colors)
        tri_color = [index_of[m.name if m else NO_MATERIAL] for m in tri_mats]

        slots = {e.filament for e in palette}
        if max(slots) > MAX_FILAMENTS:
            self.report({"ERROR"}, "%d filaments needed; Bambu Studio supports up to %d. "
                        "Assign shared filament slots in the Bambu sidebar panel."
                        % (max(slots), MAX_FILAMENTS))
            return {"CANCELLED"}

        name = os.path.splitext(os.path.basename(self.filepath))[0]
        self.write(self.filepath, vertices, triangles, tri_color, palette, name)

        summary = ", ".join("F%d %s" % (e.filament, e.hex) for e in sorted(palette, key=lambda e: e.filament))
        self.report({"INFO"}, "Exported %d triangles, %d filament(s): %s"
                    % (len(triangles), len(slots), summary))
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "use_selection")
        layout.prop(self, "global_scale")
        layout.prop(self, "use_scene_unit")
        layout.prop(self, "merge_same_colors")
        row = layout.row()
        row.enabled = self.merge_same_colors
        row.prop(self, "color_tolerance")


class EXPORT_OT_bambu_3mf(bpy.types.Operator, _BambuExportBase):
    """Export as a colour-painted 3MF for Bambu Studio"""
    bl_idname = "export_mesh.bambu_3mf"
    bl_label = "Export Bambu 3MF"
    bl_options = {"PRESET"}

    filename_ext = ".3mf"
    filter_glob: StringProperty(default="*.3mf", options={"HIDDEN"})

    def write(self, *args):
        writers.write_3mf(*args)


class EXPORT_OT_bambu_obj(bpy.types.Operator, _BambuExportBase):
    """Export as OBJ + MTL with material colours (Bambu Studio colour-mapping import)"""
    bl_idname = "export_mesh.bambu_obj"
    bl_label = "Export Bambu OBJ"
    bl_options = {"PRESET"}

    filename_ext = ".obj"
    filter_glob: StringProperty(default="*.obj", options={"HIDDEN"})

    def write(self, *args):
        writers.write_obj(*args)


class BAMBU_OT_sync_viewport_colors(bpy.types.Operator):
    """Copy each material's resolved colour to its viewport display colour (Solid view)"""
    bl_idname = "bambu.sync_viewport_colors"
    bl_label = "Sync Viewport Colours"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mats = [m for m in used_materials(export_objects(context, False)) if m]
        for mat in mats:
            r, g, b = material_linear_color(mat)
            mat.diffuse_color = (r, g, b, 1.0)
        self.report({"INFO"}, "Updated %d material(s)" % len(mats))
        return {"FINISHED"}


class BAMBU_OT_add_material(bpy.types.Operator):
    """Give objects without a material a new one, so their colour can be edited"""
    bl_idname = "bambu.add_material"
    bl_label = "Add Material to Uncoloured Objects"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = export_objects(context, bool(context.selected_objects))
        targets = [o for o in objects if o.type in GEOMETRY_TYPES and o.data is not None
                   and not any(s.material for s in o.material_slots)]
        if not targets:
            self.report({"INFO"}, "Every object already has a material")
            return {"CANCELLED"}
        mat = bpy.data.materials.new("Bambu Colour")
        if hasattr(mat, "use_nodes"):
            mat.use_nodes = True
        for obj in targets:
            if obj.material_slots:
                for slot in obj.material_slots:
                    slot.material = mat
            else:
                obj.data.materials.append(mat)
        self.report({"INFO"}, "Added '%s' to %d object(s)" % (mat.name, len(targets)))
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

class VIEW3D_PT_bambu_colors(bpy.types.Panel):
    bl_label = "Bambu Colour Export"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Bambu"

    def draw(self, context):
        layout = self.layout
        paint.draw_error_box(layout)
        try:
            self._draw(context, layout)
        except Exception:
            paint.record_error("export panel")
            layout.label(text="Panel error, see Copy Error above", icon="ERROR")

    def _draw(self, context, layout):
        objects, palette, index_of = _panel_palette(context)
        layout.label(text="%s: %d object(s)" % ("Selected" if context.selected_objects else "Visible",
                                                 len(objects)))
        rows = panel_rows(objects)
        if not rows:
            layout.label(text="No mesh objects", icon="INFO")
        else:
            header = layout.row(align=True)
            header.label(text="Colour")
            header.label(text="Object")
            header.label(text="Filament")
            shared = {}
            for _obj, mat, _label in rows:
                shared[mat] = shared.get(mat, 0) + 1

            col = layout.column(align=True)
            for obj, mat, label in rows:
                row = col.row(align=True)
                swatch = row.row(align=True)
                swatch.ui_units_x = 2.5
                if mat:
                    # Clicking the swatch opens Blender's colour picker (wheel + Hex).
                    owner, prop = material_color_source(mat)
                    swatch.prop(owner, prop, text="")
                else:
                    swatch.operator(BAMBU_OT_add_material.bl_idname, text="", icon="ADD")
                icon = "LINKED" if mat and shared[mat] > 1 else "OBJECT_DATA"
                row.label(text=label, icon=icon)
                slot = row.row(align=True)
                slot.ui_units_x = 2.5
                if mat:
                    slot.prop(mat, "bambu_slot", text="")
                else:
                    entry = palette[index_of[NO_MATERIAL]]
                    slot.label(text=str(entry.filament))
            if any(n > 1 for m, n in shared.items() if m):
                layout.label(text="Linked parts share one colour", icon="LINKED")
            layout.label(text="Filament = Bambu slot, 0 = auto", icon="INFO")
            if palette and max(e.filament for e in palette) > MAX_FILAMENTS:
                layout.label(text="More than %d filaments!" % MAX_FILAMENTS, icon="ERROR")

        layout.separator()
        layout.operator(BAMBU_OT_sync_viewport_colors.bl_idname, icon="SHADING_SOLID")
        col = layout.column(align=True)
        col.operator(EXPORT_OT_bambu_3mf.bl_idname, text="Export 3MF", icon="EXPORT")
        col.operator(EXPORT_OT_bambu_obj.bl_idname, text="Export OBJ + MTL", icon="EXPORT")


def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_bambu_3mf.bl_idname, text="Bambu Studio 3MF, coloured (.3mf)")
    self.layout.operator(EXPORT_OT_bambu_obj.bl_idname, text="Bambu Studio OBJ, coloured (.obj)")


classes = (
    EXPORT_OT_bambu_3mf,
    EXPORT_OT_bambu_obj,
    BAMBU_OT_sync_viewport_colors,
    BAMBU_OT_add_material,
    VIEW3D_PT_bambu_colors,
)


def register():
    bpy.types.Material.bambu_filament = IntProperty(
        name="Filament", default=0, min=0, max=MAX_FILAMENTS,
        description="Bambu Studio filament slot for this material (0 = assign automatically)")
    bpy.types.Material.bambu_slot = IntProperty(
        name="Filament", min=0, max=MAX_FILAMENTS, get=_get_slot, set=_set_slot,
        description="Filament slot in Bambu Studio (AMS slot). Type 0 to go back to automatic")
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    paint.register()


def unregister():
    paint.unregister()
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Material.bambu_slot
    del bpy.types.Material.bambu_filament
