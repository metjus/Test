"""Sidebar (N panel) interface, tab "Fox"."""

import bpy

from . import core, geometry
from .props import FEATURE_TYPES, SKETCH_TYPES, TYPE_ICONS


class FOX_UL_features(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        part = data
        row = layout.row(align=True)
        row.active = core.feature_active(part, index)
        row.label(text="", icon=TYPE_ICONS.get(item.type, "DOT"))
        row.prop(item, "name", text="", emboss=False)
        if part.rollback == index:
            row.label(text="", icon="TRIA_LEFT_BAR")
        if index > 0:
            row.prop(item, "suppressed", text="", emboss=False,
                     icon="HIDE_ON" if item.suppressed else "HIDE_OFF")


class FOX_MT_add_feature(bpy.types.Menu):
    bl_label = "Add Feature"
    bl_idname = "FOX_MT_add_feature"

    def draw(self, context):
        layout = self.layout
        for ident, name, desc, icon, _ in FEATURE_TYPES:
            if ident == "BASE_MESH":
                continue
            layout.operator("fox.add_feature", text=name, icon=icon).type = ident


class FOX_MT_new_part(bpy.types.Menu):
    bl_label = "Fox Part"
    bl_idname = "FOX_MT_new_part"

    def draw(self, context):
        layout = self.layout
        layout.operator("fox.new_part", text="Box", icon="MESH_CUBE").kind = "BOX"
        layout.operator("fox.new_part", text="Cylinder", icon="MESH_CYLINDER").kind = "CYLINDER"
        layout.operator("fox.new_part", text="Revolved Profile", icon="MOD_SCREW").kind = "REVOLVE"


class FOX_PT_main(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Fox"
    bl_label = "Fox Parametric"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        if not core.is_part(obj):
            layout.label(text="New parametric part:")
            col = layout.column(align=True)
            col.scale_y = 1.2
            col.operator("fox.new_part", text="Box", icon="MESH_CUBE").kind = "BOX"
            col.operator("fox.new_part", text="Cylinder", icon="MESH_CYLINDER").kind = "CYLINDER"
            col.operator("fox.new_part", text="Revolved Profile", icon="MOD_SCREW").kind = "REVOLVE"
            layout.separator()
            layout.label(text="Or start from your own model:")
            layout.operator("fox.make_part", icon="MESH_DATA")
            return

        part = obj.fox_part
        layout.label(text="History", icon="SORTTIME")
        row = layout.row()
        row.template_list("FOX_UL_features", "", part, "features", part, "active_index", rows=6)
        side = row.column(align=True)
        side.menu("FOX_MT_add_feature", text="", icon="ADD")
        side.operator("fox.remove_feature", text="", icon="REMOVE")
        side.separator()
        side.operator("fox.duplicate_feature", text="", icon="DUPLICATE")
        side.separator()
        side.operator("fox.move_feature", text="", icon="TRIA_UP").direction = "UP"
        side.operator("fox.move_feature", text="", icon="TRIA_DOWN").direction = "DOWN"
        side.separator()
        side.operator("fox.rollback", text="", icon="LOOP_BACK").index = part.active_index
        side.operator("fox.rollback", text="", icon="LOOP_FORWARDS").index = -1

        if part.rollback >= 0:
            box = layout.box()
            box.label(text="Rolled back to '%s'" % part.features[part.rollback].name, icon="INFO")
            box.operator("fox.rollback", text="Show All Features", icon="LOOP_FORWARDS").index = -1

        if context.mode == "EDIT_MESH" and part.features[0].type != "BASE_MESH":
            box = layout.box()
            box.alert = True
            box.label(text="The base is generated from parameters.", icon="ERROR")
            box.label(text="Hand edits get replaced on the next change.")
            box.label(text="Leave Edit Mode and use 'Edit Base By Hand'.")

        row = layout.row(heading="Smooth Shading")
        row.prop(part, "smooth", text="")
        sub = row.row()
        sub.active = part.smooth
        sub.prop(part, "smooth_angle")

        row = layout.row(align=True)
        row.operator("fox.rebuild", icon="FILE_REFRESH")
        row.operator("fox.apply_part", text="To Mesh", icon="CHECKMARK")


class FOX_PT_feature(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Fox"
    bl_label = "Feature"
    bl_parent_id = "FOX_PT_main"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (core.is_part(obj) and len(obj.fox_part.features)
                and 0 <= obj.fox_part.active_index < len(obj.fox_part.features))

    def draw_header(self, context):
        f = self._feature(context)
        self.layout.label(text=f.name, icon=TYPE_ICONS.get(f.type, "DOT"))

    @staticmethod
    def _feature(context):
        part = context.active_object.fox_part
        return part.features[part.active_index]

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = True  # keyframe dots: every value can be animated
        part = context.active_object.fox_part
        index = part.active_index
        f = part.features[index]
        is_base = index == 0

        if f.type == "BASE_MESH":
            layout.label(text="Your own mesh is the base.", icon="MESH_DATA")
            layout.label(text="Press Tab to model it by hand.")
            layout.label(text="Features below it stay parametric.")
            return

        if f.type in SKETCH_TYPES:
            if not is_base and f.type != "HOLE":
                layout.row().prop(f, "operation", expand=True)
            if not is_base:
                layout.prop(f, "show_tool")
            self._sketch(layout, f)
            if f.type == "EXTRUDE":
                col = layout.column(heading="Extent")
                col.prop(f, "distance")
                col.row().prop(f, "direction", expand=True)
            elif f.type == "REVOLVE":
                col = layout.column(heading="Revolve")
                col.row().prop(f, "revolve_axis", expand=True)
                col.prop(f, "revolve_angle")
                if geometry.revolve_crosses_axis(
                        geometry.place_2d(geometry.profile_points(f), f.pos_u, f.pos_v, f.rotation),
                        f.revolve_axis):
                    warn = col.box()
                    warn.alert = True
                    warn.label(text="Profile crosses the axis - move it to one side", icon="ERROR")
            elif f.type == "HOLE":
                col = layout.column(heading="Hole")
                col.prop(f, "hole_diameter")
                col.prop(f, "through_all")
                sub = col.column()
                sub.active = not f.through_all
                sub.prop(f, "hole_depth")
                col.prop(f, "flip")
            if not is_base:
                self._pattern(layout, f)
            if is_base:
                layout.separator()
                layout.operator("fox.base_to_mesh", icon="EDITMODE_HLT")

        elif f.type in ("FILLET", "CHAMFER"):
            layout.prop(f, "size")
            if f.type == "FILLET":
                layout.prop(f, "fillet_segments")
            layout.prop(f, "edges")
            if f.edges == "ANGLE":
                layout.prop(f, "edge_angle")

        elif f.type == "MIRROR":
            row = layout.row(heading="Axis", align=True)
            row.prop(f, "mirror_x", toggle=True)
            row.prop(f, "mirror_y", toggle=True)
            row.prop(f, "mirror_z", toggle=True)
            layout.prop(f, "mirror_bisect")

    @staticmethod
    def _sketch(layout, f):
        box = layout.box()
        box.label(text="Sketch", icon="GREASEPENCIL")
        box.prop(f, "plane")
        box.prop(f, "offset")
        if f.type != "HOLE":
            box.prop(f, "profile")
            if f.profile == "RECT":
                box.prop(f, "width")
                box.prop(f, "height")
            elif f.profile == "SLOT":
                box.prop(f, "width", text="Length")
                box.prop(f, "height", text="Width")
            else:
                box.prop(f, "radius")
                if f.profile == "POLYGON":
                    box.prop(f, "sides")
        col = box.column(align=True)
        col.prop(f, "pos_u", text="Position U")
        col.prop(f, "pos_v", text="V")
        if f.type != "HOLE":
            box.prop(f, "rotation")
        if f.type == "HOLE" or f.profile in ("CIRCLE", "SLOT") or f.type == "REVOLVE":
            box.prop(f, "segments")

    @staticmethod
    def _pattern(layout, f):
        box = layout.box()
        box.label(text="Pattern", icon="MOD_ARRAY")
        box.row().prop(f, "pattern", expand=True)
        if f.pattern == "LINEAR":
            col = box.column(align=True)
            col.prop(f, "count_u")
            col.prop(f, "spacing_u")
            col = box.column(align=True)
            col.prop(f, "count_v")
            col.prop(f, "spacing_v")
        elif f.pattern == "CIRCULAR":
            box.prop(f, "circ_count")
            box.prop(f, "circ_angle")


def _add_menu(self, context):
    self.layout.menu("FOX_MT_new_part", icon="MOD_SOLIDIFY")


classes = (FOX_UL_features, FOX_MT_add_feature, FOX_MT_new_part, FOX_PT_main, FOX_PT_feature)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_mesh_add.append(_add_menu)


def unregister():
    bpy.types.VIEW3D_MT_mesh_add.remove(_add_menu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
