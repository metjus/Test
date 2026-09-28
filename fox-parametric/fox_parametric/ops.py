"""Operators: creating parts and editing the feature history."""

import bpy
from bpy.props import EnumProperty, IntProperty
from mathutils import Vector

from . import core
from .props import BASE_TYPES, FEATURE_TYPES, SKETCH_TYPES


def _part(context):
    obj = context.active_object
    return obj if core.is_part(obj) else None


class _PartOp:
    @classmethod
    def poll(cls, context):
        return _part(context) is not None and context.mode == "OBJECT"


def _local_bounds(obj):
    pts = [Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def _init_feature(obj, f, ftype):
    """Sensible starting values, scaled to the size of the part."""
    part = obj.fox_part
    f.uid = core.new_uid(part)
    f.type = ftype
    f.name = core.unique_feature_name(part, ftype)
    lo, hi = _local_bounds(obj)
    size = max((hi - lo).length, 0.01) if len(part.features) > 1 else 1.0
    s = size / 1.7  # roughly the largest side
    f.width, f.height = s * 0.3, s * 0.2
    f.radius = s * 0.1
    f.distance = s * 0.2
    f.hole_diameter, f.hole_depth = s * 0.08, s * 0.2
    f.size = s * 0.02
    f.spacing_u = f.spacing_v = s * 0.2
    if ftype in SKETCH_TYPES and len(part.features) > 1:
        # Sketch on the top face of the current body.
        f.plane, f.offset = "XY", hi.z
        f.pos_u, f.pos_v = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
        if ftype == "EXTRUDE":
            f.operation = "JOIN"
        if ftype == "REVOLVE":
            # Ring on top of the body, around the part's Z axis.
            f.plane, f.offset, f.pos_v = "XZ", 0.0, hi.z + f.height / 2
            f.pos_u = max(hi.x * 0.5, f.width)


# ---------------------------------------------------------------------------
# Creating parts
# ---------------------------------------------------------------------------

class FOX_OT_new_part(bpy.types.Operator):
    """Create a new parametric part"""
    bl_idname = "fox.new_part"
    bl_label = "New Fox Part"
    bl_options = {"REGISTER", "UNDO"}

    kind: EnumProperty(name="Start From", items=[
        ("BOX", "Box", "Start from an extruded rectangle", "MESH_CUBE", 0),
        ("CYLINDER", "Cylinder", "Start from an extruded circle", "MESH_CYLINDER", 1),
        ("REVOLVE", "Revolved Profile", "Start from a revolved rectangle (a ring or disc)", "MOD_SCREW", 2),
    ])

    def execute(self, context):
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        me = bpy.data.meshes.new("Fox Part")
        obj = bpy.data.objects.new("Fox Part", me)
        context.collection.objects.link(obj)
        obj.location = context.scene.cursor.location
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        part = obj.fox_part
        with core.batch():
            part.is_part = True
            f = part.features.add()
            ftype = "REVOLVE" if self.kind == "REVOLVE" else "EXTRUDE"
            _init_feature(obj, f, ftype)
            f.name = {"BOX": "Base Box", "CYLINDER": "Base Cylinder", "REVOLVE": "Base Revolve"}[self.kind]
            if self.kind == "BOX":
                f.profile, f.width, f.height, f.distance = "RECT", 1.0, 0.6, 0.3
            elif self.kind == "CYLINDER":
                f.profile, f.radius, f.distance, f.segments = "CIRCLE", 0.4, 0.5, 48
            else:
                f.plane, f.profile = "XZ", "RECT"
                f.width, f.height, f.pos_u, f.pos_v = 0.2, 0.3, 0.4, 0.15
                f.segments = 48
        core.rebuild(obj)
        return {"FINISHED"}


class FOX_OT_make_part(bpy.types.Operator):
    """Turn the selected mesh into a parametric part. Your mesh stays the base and stays editable; add holes, cuts, fillets on top"""
    bl_idname = "fox.make_part"
    bl_label = "Make Part From Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and not obj.fox_part.is_part and context.mode == "OBJECT"

    def execute(self, context):
        obj = context.active_object
        part = obj.fox_part
        with core.batch():
            part.is_part = True
            f = part.features.add()
            _init_feature(obj, f, "BASE_MESH")
            f.name = "Base Mesh"
        core.rebuild(obj)
        return {"FINISHED"}


# ---------------------------------------------------------------------------
# Editing the history
# ---------------------------------------------------------------------------

class FOX_OT_add_feature(_PartOp, bpy.types.Operator):
    """Add a feature after the selected one"""
    bl_idname = "fox.add_feature"
    bl_label = "Add Feature"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(items=[t for t in FEATURE_TYPES if t[0] != "BASE_MESH"])

    def execute(self, context):
        obj = _part(context)
        part = obj.fox_part
        with core.batch():
            f = part.features.add()
            _init_feature(obj, f, self.type)
            new = len(part.features) - 1
            target = min(part.active_index + 1, new)
            part.features.move(new, max(target, 1))
            part.active_index = max(target, 1)
            if part.rollback >= 0 and part.active_index > part.rollback:
                part.rollback = part.active_index
        core.rebuild(obj)
        return {"FINISHED"}


class FOX_OT_remove_feature(_PartOp, bpy.types.Operator):
    """Delete the selected feature"""
    bl_idname = "fox.remove_feature"
    bl_label = "Delete Feature"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = _part(context)
        return obj is not None and context.mode == "OBJECT" and obj.fox_part.active_index > 0

    def execute(self, context):
        obj = _part(context)
        part = obj.fox_part
        with core.batch():
            part.features.remove(part.active_index)
            part.active_index = min(part.active_index, len(part.features) - 1)
            if part.rollback >= len(part.features):
                part.rollback = -1
        core.rebuild(obj)
        return {"FINISHED"}


class FOX_OT_move_feature(_PartOp, bpy.types.Operator):
    """Move the selected feature earlier or later in the history"""
    bl_idname = "fox.move_feature"
    bl_label = "Move Feature"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(items=[("UP", "Up", ""), ("DOWN", "Down", "")])

    @classmethod
    def poll(cls, context):
        obj = _part(context)
        return obj is not None and context.mode == "OBJECT" and obj.fox_part.active_index > 0

    def execute(self, context):
        obj = _part(context)
        part = obj.fox_part
        i = part.active_index
        j = i - 1 if self.direction == "UP" else i + 1
        if j < 1 or j >= len(part.features):
            return {"CANCELLED"}  # the base always stays first
        with core.batch():
            part.features.move(i, j)
            part.active_index = j
        core.rebuild(obj)
        return {"FINISHED"}


class FOX_OT_duplicate_feature(_PartOp, bpy.types.Operator):
    """Copy the selected feature"""
    bl_idname = "fox.duplicate_feature"
    bl_label = "Duplicate Feature"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = _part(context)
        return obj is not None and context.mode == "OBJECT" and obj.fox_part.active_index > 0

    def execute(self, context):
        obj = _part(context)
        part = obj.fox_part
        src = part.features[part.active_index]
        # Copy the values first: adding to the collection invalidates `src`.
        values = {p.identifier: getattr(src, p.identifier) for p in src.bl_rna.properties
                  if not p.is_readonly and p.identifier not in ("uid", "tool", "name")}
        with core.batch():
            f = part.features.add()
            for key, value in values.items():
                setattr(f, key, value)
            f.uid = core.new_uid(part)
            f.name = core.unique_feature_name(part, f.type)
            new = len(part.features) - 1
            part.features.move(new, part.active_index + 1)
            part.active_index += 1
        core.rebuild(obj)
        return {"FINISHED"}


class FOX_OT_rollback(_PartOp, bpy.types.Operator):
    """Roll the history back to a feature: later features are temporarily switched off"""
    bl_idname = "fox.rollback"
    bl_label = "Roll Back"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty(default=-1, description="-1 = roll forward to the end")

    def execute(self, context):
        obj = _part(context)
        part = obj.fox_part
        part.rollback = -1 if self.index >= len(part.features) - 1 else self.index
        return {"FINISHED"}


class FOX_OT_base_to_mesh(_PartOp, bpy.types.Operator):
    """Keep the current base shape as a normal mesh you can model by hand. Later features stay parametric"""
    bl_idname = "fox.base_to_mesh"
    bl_label = "Edit Base By Hand"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = _part(context)
        return obj is not None and obj.fox_part.features[0].type != "BASE_MESH"

    def execute(self, context):
        obj = _part(context)
        base = obj.fox_part.features[0]
        with core.batch():
            base.type = "BASE_MESH"
            base.name = "Base Mesh"
        core.rebuild(obj)
        self.report({"INFO"}, "Base is now a regular mesh - Tab into Edit Mode to shape it")
        return {"FINISHED"}


class FOX_OT_apply_part(_PartOp, bpy.types.Operator):
    """Bake the whole history into a regular mesh. The parameters are removed"""
    bl_idname = "fox.apply_part"
    bl_label = "Convert to Regular Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = _part(context)
        part = obj.fox_part
        names = [m.name for m in obj.modifiers if m.name.startswith(core.MOD_PREFIX)]
        with context.temp_override(object=obj, active_object=obj):
            for name in names:
                mod = obj.modifiers[name]
                if mod.show_viewport:
                    bpy.ops.object.modifier_apply(modifier=name)
                else:
                    obj.modifiers.remove(mod)
        for child in [c for c in obj.children if "fox_uid" in c]:
            me = child.data
            bpy.data.objects.remove(child, do_unlink=True)
            if me.users == 0:
                bpy.data.meshes.remove(me)
        with core.batch():
            part.features.clear()
            part.rollback = -1
            part.is_part = False
        return {"FINISHED"}


class FOX_OT_rebuild(_PartOp, bpy.types.Operator):
    """Rebuild the part from its history"""
    bl_idname = "fox.rebuild"
    bl_label = "Rebuild"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        core.rebuild(_part(context))
        return {"FINISHED"}


classes = (FOX_OT_new_part, FOX_OT_make_part, FOX_OT_add_feature, FOX_OT_remove_feature,
           FOX_OT_move_feature, FOX_OT_duplicate_feature, FOX_OT_rollback, FOX_OT_base_to_mesh,
           FOX_OT_apply_part, FOX_OT_rebuild)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
