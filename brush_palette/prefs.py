"""Add-on preferences, persistent favorites / recents and user data paths."""

import json
import os

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import AddonPreferences, PropertyGroup, UIList

ADDON_ID = __package__

MAP_MODES = (
    ('VIEW_PLANE', "View Plane", "Alpha is projected from the view"),
    ('AREA_PLANE', "Area Plane", "Alpha follows the surface under the brush (best for sculpting)"),
    ('TILED', "Tiled", "Alpha repeats across the surface"),
    ('RANDOM', "Random", "Alpha is placed with a random offset/rotation per dab"),
    ('STENCIL', "Stencil", "Alpha is used as a screen-space stencil"),
)

STROKE_MODES = (
    ('KEEP', "Keep", "Do not change the brush stroke method"),
    ('DRAG_DOT', "Drag Dot", "Place a single dab that can be dragged into place"),
    ('ANCHORED', "Anchored", "ZBrush 'DragRect': click and drag to size the alpha"),
    ('SPACE', "Space", "Regular spaced stroke"),
)

MAX_RECENTS = 24


def user_data_dir():
    """Writable per-user directory for this add-on (thumbnail cache, starter alphas)."""
    try:
        return bpy.utils.extension_path_user(ADDON_ID, create=True)
    except (ValueError, AttributeError):
        path = os.path.join(bpy.utils.user_resource('CONFIG'), "brush_palette")
        os.makedirs(path, exist_ok=True)
        return path


def default_alpha_dir():
    return os.path.join(user_data_dir(), "alphas")


class _Defaults:
    """Stand-in used when the preferences are not registered (e.g. scripted use)."""
    thumb_size = 72
    columns = 12
    show_labels = True
    close_on_pick = True
    scan_user_libraries = True
    include_current_file = True
    alpha_map_mode = 'AREA_PLANE'
    alpha_stroke = 'KEEP'
    alpha_non_color = True
    alpha_folders = ()
    favorites = "[]"
    recents = "[]"


def get_prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    if addon is None:
        return _Defaults
    return addon.preferences


def _load_list(prefs, attr):
    try:
        value = json.loads(getattr(prefs, attr) or "[]")
        return [v for v in value if isinstance(v, str)]
    except (ValueError, TypeError):
        return []


def _store_list(prefs, attr, values):
    if prefs is _Defaults:
        setattr(_Defaults, attr, json.dumps(values))
        return
    setattr(prefs, attr, json.dumps(values))


def favorites(prefs):
    return _load_list(prefs, "favorites")


def recents(prefs):
    return _load_list(prefs, "recents")


def toggle_favorite(prefs, key):
    favs = favorites(prefs)
    if key in favs:
        favs.remove(key)
    else:
        favs.append(key)
    _store_list(prefs, "favorites", favs)


def push_recent(prefs, key):
    items = [k for k in recents(prefs) if k != key]
    items.insert(0, key)
    _store_list(prefs, "recents", items[:MAX_RECENTS])


class BPAL_AlphaFolder(PropertyGroup):
    path: StringProperty(name="Folder", subtype='DIR_PATH')
    recursive: BoolProperty(name="Include Subfolders", default=True)


class BPAL_UL_alpha_folders(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "path", text="", emboss=False, icon='FILE_FOLDER')
        row.prop(item, "recursive", text="", icon='OUTLINER', emboss=False)


class BPAL_Preferences(AddonPreferences):
    bl_idname = ADDON_ID

    thumb_size: IntProperty(
        name="Thumbnail Size", default=72, min=32, max=192, subtype='PIXEL',
        description="Size of the palette thumbnails (Ctrl+Wheel inside the palette also changes it)",
    )
    columns: IntProperty(
        name="Columns", default=12, min=4, max=30,
        description="Maximum number of thumbnails per row",
    )
    show_labels: BoolProperty(name="Show Names", default=True)
    close_on_pick: BoolProperty(
        name="Close After Picking", default=True,
        description="Close the palette after a pick (hold Shift while clicking to keep it open)",
    )
    scan_user_libraries: BoolProperty(
        name="Include User Asset Libraries", default=True,
        description="List brushes stored in the asset libraries configured under File Paths",
    )
    include_current_file: BoolProperty(
        name="Include Current File Brushes", default=True,
        description="List brush assets stored in the open .blend file",
    )

    alpha_folders: CollectionProperty(type=BPAL_AlphaFolder)
    alpha_folder_index: IntProperty()
    alpha_map_mode: EnumProperty(
        name="Alpha Mapping", items=MAP_MODES, default='AREA_PLANE',
        description="Texture mapping used when an alpha is applied to a brush",
    )
    alpha_stroke: EnumProperty(
        name="Stroke on Alpha", items=STROKE_MODES, default='KEEP',
        description="Optionally switch the brush stroke method when an alpha is applied",
    )
    alpha_non_color: BoolProperty(
        name="Load Alphas as Non-Color", default=True,
        description="Treat alpha images as data so the grey values are not gamma corrected",
    )

    favorites: StringProperty(default="[]", options={'HIDDEN'})
    recents: StringProperty(default="[]", options={'HIDDEN'})

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(heading="Palette")
        col.prop(self, "thumb_size")
        col.prop(self, "columns")
        col.prop(self, "show_labels")
        col.prop(self, "close_on_pick")

        col = layout.column(heading="Brushes")
        col.prop(self, "scan_user_libraries")
        col.prop(self, "include_current_file")

        col = layout.column(heading="Alphas")
        col.prop(self, "alpha_map_mode")
        col.prop(self, "alpha_stroke")
        col.prop(self, "alpha_non_color")

        box = layout.box()
        box.use_property_split = False
        box.label(text="Alpha Folders", icon='IMAGE_ALPHA')
        box.label(text="Built-in: " + default_alpha_dir(), icon='FILE_FOLDER')
        row = box.row()
        row.template_list("BPAL_UL_alpha_folders", "", self, "alpha_folders", self, "alpha_folder_index", rows=3)
        side = row.column(align=True)
        side.operator("brush_palette.add_alpha_folder", text="", icon='ADD')
        side.operator("brush_palette.remove_alpha_folder", text="", icon='REMOVE')
        row = box.row()
        row.operator("brush_palette.generate_starter_alphas", icon='IMAGE_ALPHA')
        row.operator("brush_palette.refresh", icon='FILE_REFRESH')

        from . import keymaps
        keymaps.draw_keymap_prefs(layout, context)


classes = (
    BPAL_AlphaFolder,
    BPAL_UL_alpha_folders,
    BPAL_Preferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
