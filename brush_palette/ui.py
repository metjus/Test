"""Sidebar panel, tool header buttons and small helper operators."""

import os

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel

from . import alphas, brushes, thumbs
from . import prefs as _prefs


class BPAL_OT_add_alpha_folder(Operator):
    """Add a folder of alpha images to the palette"""
    bl_idname = "brush_palette.add_alpha_folder"
    bl_label = "Add Alpha Folder"
    bl_options = {'REGISTER'}

    directory: StringProperty(subtype='DIR_PATH')
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        prefs = _prefs.get_prefs(context)
        path = bpy.path.abspath(self.directory)
        if not path or not os.path.isdir(path):
            self.report({'WARNING'}, "Not a folder: %s" % self.directory)
            return {'CANCELLED'}
        if prefs is _prefs._Defaults:
            self.report({'WARNING'}, "Enable the add-on to store alpha folders")
            return {'CANCELLED'}
        norm = brushes.norm(path)
        if any(brushes.norm(bpy.path.abspath(f.path)) == norm for f in prefs.alpha_folders if f.path):
            self.report({'INFO'}, "Folder already added")
            return {'FINISHED'}
        folder = prefs.alpha_folders.add()
        folder.path = path
        prefs.alpha_folder_index = len(prefs.alpha_folders) - 1
        count = sum(1 for _ in alphas.iter_images(path, True))
        self.report({'INFO'}, "Added %d alpha(s) from %s" % (count, path))
        return {'FINISHED'}


class BPAL_OT_remove_alpha_folder(Operator):
    """Remove the selected alpha folder from the palette (files are not deleted)"""
    bl_idname = "brush_palette.remove_alpha_folder"
    bl_label = "Remove Alpha Folder"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        prefs = _prefs.get_prefs(context)
        return prefs is not _prefs._Defaults and len(prefs.alpha_folders) > 0

    def execute(self, context):
        prefs = _prefs.get_prefs(context)
        index = min(prefs.alpha_folder_index, len(prefs.alpha_folders) - 1)
        prefs.alpha_folders.remove(index)
        prefs.alpha_folder_index = max(0, index - 1)
        return {'FINISHED'}


class BPAL_OT_generate_starter_alphas(Operator):
    """(Re)create the built-in procedural alphas in the add-on's alpha folder"""
    bl_idname = "brush_palette.generate_starter_alphas"
    bl_label = "Generate Starter Alphas"
    bl_options = {'REGISTER'}

    def execute(self, context):
        folder = alphas.ensure_starter_alphas(force=True)
        self.report({'INFO'}, "Starter alphas written to %s" % folder)
        return {'FINISHED'}


class BPAL_OT_refresh(Operator):
    """Rebuild the thumbnail cache and rescan brush libraries and alpha folders"""
    bl_idname = "brush_palette.refresh"
    bl_label = "Refresh Thumbnails"
    bl_options = {'REGISTER'}

    def execute(self, context):
        thumbs.clear(memory=True, disk=True)
        brushes.refresh()
        self.report({'INFO'}, "Brush Palette cache cleared")
        return {'FINISHED'}


class BPAL_OT_apply_alpha(Operator):
    """Apply an alpha image file to the active brush"""
    bl_idname = "brush_palette.apply_alpha"
    bl_label = "Apply Alpha"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH', description="Alpha image; empty removes the alpha")

    @classmethod
    def poll(cls, context):
        return alphas.supported(context)

    def execute(self, context):
        if self.filepath:
            path = bpy.path.abspath(self.filepath)
            name = os.path.splitext(os.path.basename(path))[0]
            item = alphas.AlphaItem(alphas.item_key(path), name, path, os.path.dirname(path), alphas.item_key(path))
        else:
            item = alphas.NONE_ITEM
        try:
            message = alphas.apply(context, item)
        except RuntimeError as ex:
            self.report({'WARNING'}, str(ex))
            return {'CANCELLED'}
        self.report({'INFO'}, message)
        return {'FINISHED'}


STROKES = (
    ('SPACE', "Space", "Normal continuous stroke"),
    ('DRAG_DOT', "Drag Dot", "One stamp you can slide into place before releasing"),
    ('ANCHORED', "DragRect", "Click and drag one stamp: distance sets size (and depth), direction sets rotation"),
)


class BPAL_OT_set_stroke(Operator):
    """Set the stroke method of the active brush"""
    bl_idname = "brush_palette.set_stroke"
    bl_label = "Set Stroke"
    bl_options = {'REGISTER'}

    method: bpy.props.EnumProperty(items=STROKES)

    @classmethod
    def description(cls, context, properties):
        return next((desc for ident, _name, desc in STROKES if ident == properties.method), "")

    @classmethod
    def poll(cls, context):
        return brushes.active_brush(context) is not None

    def execute(self, context):
        if not brushes.set_stroke(context, self.method):
            self.report({'WARNING'}, "This brush does not support that stroke")
            return {'CANCELLED'}
        return {'FINISHED'}


class BPAL_PT_palette(Panel):
    bl_label = "Brush Palette"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Palette"

    @classmethod
    def poll(cls, context):
        return brushes.supported(context)

    def draw(self, context):
        layout = self.layout
        brush = brushes.active_brush(context)

        box = layout.box()
        box.label(text="Current Brush", icon='BRUSHES_ALL')
        if brush is not None:
            # The brush preview; layout.icon() can give a tiny generic icon for brush copies.
            preview = brush.preview
            icon = preview.icon_id if preview is not None and preview.image_size[0] else layout.icon(brush)
            if icon:
                box.template_icon(icon_value=icon, scale=5.0)
            box.label(text=brush.name)
        row = box.row()
        row.scale_y = 1.6
        op = row.operator("brush_palette.open", text="Brushes", icon='BRUSHES_ALL')
        op.tab = 'BRUSHES'
        if brush is not None:
            row = box.row(align=True)
            current = brush.stroke_method
            for method, label, _desc in STROKES:
                row.operator("brush_palette.set_stroke", text=label, depress=current == method).method = method
            box.operator("brush.asset_save_as", text="Save as New Brush…", icon='ASSET_MANAGER')

        if not alphas.supported(context):
            return
        box = layout.box()
        box.label(text="Alpha", icon='IMAGE_ALPHA')
        tex = alphas.current_texture(context)
        image = getattr(tex, "image", None) if tex else None
        if image is not None:
            icon = layout.icon(image)
            if icon:
                box.template_icon(icon_value=icon, scale=5.0)
            box.label(text=os.path.splitext(image.name)[0])
            target = alphas.TARGETS[context.mode]
            box.prop(getattr(brush, target[1]), target[2], text="")
        else:
            box.label(text="No alpha")
        row = box.row(align=True)
        row.scale_y = 1.6
        op = row.operator("brush_palette.open", text="Alphas", icon='IMAGE_ALPHA')
        op.tab = 'ALPHAS'
        sub = row.row(align=True)
        sub.enabled = tex is not None
        sub.operator("brush_palette.apply_alpha", text="", icon='X').filepath = ""
        box.operator("brush_palette.add_alpha_folder", icon='FILE_FOLDER')


def draw_tool_header(self, context):
    if not brushes.supported(context):
        return
    layout = self.layout
    row = layout.row(align=True)
    row.operator("brush_palette.open", text="", icon='BRUSHES_ALL').tab = 'BRUSHES'
    if alphas.supported(context):
        row.operator("brush_palette.open", text="", icon='IMAGE_ALPHA').tab = 'ALPHAS'


classes = (
    BPAL_OT_add_alpha_folder,
    BPAL_OT_remove_alpha_folder,
    BPAL_OT_generate_starter_alphas,
    BPAL_OT_refresh,
    BPAL_OT_apply_alpha,
    BPAL_OT_set_stroke,
    BPAL_PT_palette,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_HT_tool_header.append(draw_tool_header)


def unregister():
    bpy.types.VIEW3D_HT_tool_header.remove(draw_tool_header)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
