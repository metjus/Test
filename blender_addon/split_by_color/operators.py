import bmesh
import bpy
import numpy as np
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

from . import core, mesh_colors, refine


def _hex(srgb) -> str:
    r, g, b = (int(round(float(c) * 255)) for c in srgb)
    return f"{r:02X}{g:02X}{b:02X}"


def _make_material(name: str, srgb) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    linear = list(core.srgb_to_linear(np.asarray(srgb))) + [1.0]
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True  # od Blenderu 5 sú uzly vždy zapnuté
    node = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.node_tree else None
    if node is not None:
        node.inputs["Base Color"].default_value = linear
    mat.diffuse_color = linear  # farba vo viewporte (Solid režim)
    return mat


def _part_object(src: bpy.types.Object, face_mask: np.ndarray, name: str, mat) -> bpy.types.Object:
    bm = bmesh.new()
    bm.from_mesh(src.data)
    bm.faces.ensure_lookup_table()
    drop = [f for f in bm.faces if not face_mask[f.index]]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    obj.matrix_world = src.matrix_world
    obj.parent = src.parent
    for coll in src.users_collection:
        coll.objects.link(obj)
    return obj


def color_props() -> dict:
    """Nastavenia zisťovania a zoskupenia farieb, spoločné pre všetky operátory."""
    return {
        "source": EnumProperty(
            name="Color from",
            items=[
                ("AUTO", "Auto", "Texture if there is one, else vertex colors, else material"),
                ("TEXTURE", "Texture", "Sample the image texture through the UV map"),
                ("VERTEX", "Vertex colors", "Use the color attribute"),
                ("MATERIAL", "Material colors", "Use each material's base color"),
            ],
            default="AUTO",
        ),
        "tolerance": FloatProperty(
            name="Color tolerance",
            description="How different two colors may be to still count as the same (CIELAB distance). "
            "Raise it if one color is split into several, lower it if different colors are merged",
            default=10.0, min=1.0, max=60.0,
        ),
        "max_colors": IntProperty(
            name="Max colors",
            description="Merge the smallest groups until at most this many remain (0 = as many as found)",
            default=0, min=0, max=64,
        ),
        "min_island_faces": IntProperty(
            name="Min patch size",
            description="Patches of fewer faces are merged into the neighboring color (removes speckles). "
            "Separate floating parts are kept",
            default=4, min=1, max=1000,
        ),
        "merge_blends": BoolProperty(
            name="Merge blended edges",
            description="Treat colors that only appear between two other colors (soft transitions) as part of them",
            default=True,
        ),
    }


def with_color_props(cls):
    cls.__annotations__ = {**color_props(), **getattr(cls, "__annotations__", {})}
    return cls


def _target_objects(context):
    return [o for o in context.selected_objects if o.type == "MESH"] or (
        [context.active_object] if context.active_object and context.active_object.type == "MESH" else []
    )


@with_color_props
class OBJECT_OT_split_by_color(bpy.types.Operator):
    bl_idname = "object.split_by_color"
    bl_label = "Split by Color"
    bl_description = "Group faces by color and either assign one material per color or split into separate objects"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Result",
        items=[
            ("MATERIALS", "Materials (preview)", "Keep one object, assign one material per color"),
            ("OBJECTS", "Separate objects", "Create one object per color (ready for multi-color printing)"),
        ],
        default="MATERIALS",
    )
    split_islands: BoolProperty(
        name="Split disconnected patches",
        description="Make same-colored patches that do not touch (e.g. both eyes) separate objects",
        default=False,
    )
    keep_original: BoolProperty(
        name="Keep original",
        description="Keep the source object (hidden) when creating separate objects",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return bool(_target_objects(context))

    def draw(self, context):
        col = self.layout.column()
        for p in ("mode", "source", "tolerance", "max_colors", "min_island_faces", "merge_blends"):
            col.prop(self, p)
        if self.mode == "OBJECTS":
            col.prop(self, "split_islands")
            col.prop(self, "keep_original")

    def execute(self, context):
        objs = _target_objects(context)
        total_parts = 0
        for obj in objs:
            try:
                total_parts += self._process(context, obj)
            except mesh_colors.NoColorData as e:
                self.report({"ERROR"}, f"{obj.name}: {e}")
                return {"CANCELLED"}
        self.report({"INFO"}, f"Done: {total_parts} color part(s) from {len(objs)} object(s)")
        return {"FINISHED"}

    def _process(self, context, obj) -> int:
        if obj.modifiers:
            self.report({"WARNING"}, f"{obj.name} has modifiers, they are ignored. Apply them first if you need them.")
        mesh = obj.data
        rgb, used, notes = mesh_colors.face_colors(obj, self.source)
        for n in notes:
            self.report({"WARNING"}, f"{obj.name}: {n}")
        adj = mesh_colors.mesh_adjacency(mesh)
        res = core.analyze(rgb, adj, self.tolerance, self.max_colors, self.min_island_faces, self.merge_blends)

        base = obj.name
        mats = [
            _make_material(f"{base}_color{i + 1}_{_hex(c)}", c) for i, c in enumerate(res.palette)
        ]
        if self.mode == "MATERIALS":
            mesh.materials.clear()
            for m in mats:
                mesh.materials.append(m)
            mesh.polygons.foreach_set("material_index", res.labels.astype(np.int32))
            mesh.update()
            return len(mats)

        groups = res.labels
        if self.split_islands:
            ids = core.island_ids(res.labels, adj)
            # číslo kusu je unikátne pre celý mesh, takže stačí ísť cez ne
            keys = [(int(res.labels[np.nonzero(ids == i)[0][0]]), i) for i in range(int(ids.max()) + 1)]
            keys.sort()
            parts = [(lab, ids == i, f"{base}_color{lab + 1}_{j + 1}") for j, (lab, i) in enumerate(keys)]
        else:
            parts = [(lab, groups == lab, f"{base}_color{lab + 1}") for lab in range(len(mats))]

        created = []
        for lab, mask, name in parts:
            if mask.any():
                created.append(_part_object(obj, mask, name, mats[lab]))
        if self.keep_original:
            obj.hide_set(True)
        else:
            bpy.data.objects.remove(obj, do_unlink=True)
        for o in context.selected_objects:
            o.select_set(False)
        for o in created:
            o.select_set(True)
        if created:
            context.view_layer.objects.active = created[0]
        return len(created)


@with_color_props
class OBJECT_OT_split_by_color_refine(bpy.types.Operator):
    bl_idname = "object.split_by_color_refine"
    bl_label = "Refine & Smooth Color Edges"
    bl_description = (
        "Reduce jagged color borders: subdivide faces along color borders (using the texture) and smooth the "
        "border lines. Changes the mesh, undo with Ctrl+Z"
    )
    bl_options = {"REGISTER", "UNDO"}

    levels: IntProperty(
        name="Refine levels",
        description="How many times faces on a color border are subdivided (0 = off). Each level roughly halves the jaggedness",
        default=2, min=0, max=4,
    )
    smooth: FloatProperty(
        name="Smooth strength",
        description="How strongly border lines are straightened (0 = off). The surface shape is preserved",
        default=0.5, min=0.0, max=1.0,
    )
    smooth_iterations: IntProperty(name="Smooth passes", default=10, min=1, max=100)

    @classmethod
    def poll(cls, context):
        return bool(_target_objects(context))

    def draw(self, context):
        col = self.layout.column()
        for p in ("levels", "smooth", "smooth_iterations", "source", "tolerance", "max_colors", "min_island_faces", "merge_blends"):
            col.prop(self, p)

    def execute(self, context):
        if self.levels == 0 and self.smooth == 0:
            self.report({"INFO"}, "Nothing to do: refine levels and smooth strength are both 0")
            return {"CANCELLED"}
        for obj in _target_objects(context):
            if obj.modifiers:
                self.report({"WARNING"}, f"{obj.name} has modifiers, they are ignored.")

            def groups():
                return refine.groups_for(
                    obj, self.source, self.tolerance, self.max_colors, self.min_island_faces, self.merge_blends
                )

            try:
                added = 0
                if self.levels:
                    _, used, _ = mesh_colors.face_colors(obj, self.source)
                    if used == "TEXTURE":
                        added = refine.refine_boundaries(obj, self.levels, groups)
                    else:
                        self.report({"WARNING"}, f"{obj.name}: refining needs a texture, only smoothing is applied.")
                moved = 0
                if self.smooth > 0:
                    labels, _ = groups()
                    moved = refine.smooth_boundaries(obj, labels, self.smooth, self.smooth_iterations)
            except mesh_colors.NoColorData as e:
                self.report({"ERROR"}, f"{obj.name}: {e}")
                return {"CANCELLED"}
            self.report({"INFO"}, f"{obj.name}: +{added} faces, {moved} border vertices smoothed")
        return {"FINISHED"}


class VIEW3D_PT_split_by_color(bpy.types.Panel):
    bl_label = "Split by Color"
    bl_idname = "VIEW3D_PT_split_by_color"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Split Color"

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="1. Preview the color groups")
        op = col.operator("object.split_by_color", text="Preview (materials)", icon="MATERIAL")
        op.mode = "MATERIALS"
        col.separator()
        col.label(text="2. Optional: fix jagged borders")
        col.operator("object.split_by_color_refine", text="Refine & Smooth Edges", icon="MOD_SMOOTH")
        col.separator()
        col.label(text="3. Create one object per color")
        op = col.operator("object.split_by_color", text="Split into objects", icon="MOD_BUILD")
        op.mode = "OBJECTS"
        col.separator()
        col.label(text="Tweak values in the panel after running", icon="INFO")


CLASSES = (OBJECT_OT_split_by_color, OBJECT_OT_split_by_color_refine, VIEW3D_PT_split_by_color)
