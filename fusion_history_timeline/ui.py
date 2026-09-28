# SPDX-License-Identifier: GPL-3.0-or-later
"""Fusion-style timeline strip, sidebar panel and preferences."""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, StringProperty)

from . import core, operators


# ------------------------------------------------------------ preferences
class FH_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = core.ADDON_ID

    auto_capture: BoolProperty(
        name="Record History", default=True,
        description="Snapshot the file after every change")
    debounce: FloatProperty(
        name="Idle Delay", default=0.6, min=0.1, max=10.0, subtype='TIME_ABSOLUTE', unit='TIME_ABSOLUTE',
        description="Wait this long after the last change before writing a snapshot")
    max_steps: IntProperty(
        name="Max Steps", default=200, min=0, soft_max=2000,
        description="Oldest unpinned steps are deleted beyond this count (0 = unlimited)")
    max_disk_mb: IntProperty(
        name="Disk Quota (MB)", default=2048, min=0, soft_max=100000,
        description="Oldest unpinned steps are deleted while a file's history uses more "
                    "disk space than this (0 = unlimited)")
    history_root: StringProperty(
        name="History Folder", subtype='DIR_PATH', default="",
        description="Keep all histories in this folder instead of next to each .blend")
    capture_on_open: BoolProperty(
        name="Capture on Open", default=True,
        description="Add a step when a file is opened whose state is not in its timeline yet")
    ignore_operators: StringProperty(
        name="Also Ignore", default="",
        description="Comma separated operator patterns that never create a step "
                    "(e.g. 'object.shade_*, mesh.select_mode')")
    strip_location: EnumProperty(
        name="Timeline Strip", default='STATUSBAR',
        items=(
            ('STATUSBAR', "Status Bar", "Bottom of the window, like Fusion's timeline"),
            ('VIEW3D_HEADER', "3D View Header", "Header of every 3D Viewport"),
            ('NONE', "Sidebar Only", "Only in the 3D View sidebar (N panel) History tab"),
        ),
        update=lambda self, ctx: core.tag_redraw())
    strip_count: IntProperty(
        name="Visible Steps", default=24, min=5, max=200,
        description="How many steps the timeline strip shows at once")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        col = layout.column(heading="Recording")
        col.prop(self, "auto_capture")
        col.prop(self, "capture_on_open")
        col.prop(self, "debounce")
        col.prop(self, "ignore_operators")
        col = layout.column(heading="Storage")
        col.prop(self, "max_steps")
        col.prop(self, "max_disk_mb")
        col.prop(self, "history_root")
        col = layout.column(heading="Timeline")
        col.prop(self, "strip_location")
        col.prop(self, "strip_count")


# ------------------------------------------------------------------ strip
def draw_strip(layout, show_count=True):
    """Row of step icons: rolled-back steps greyed, current step pressed."""
    store = core.get_store()
    steps = store.steps
    count = core.prefs().strip_count
    offset = core._State.strip_offset
    end = max(0, len(steps) - offset)
    start = max(0, end - count)

    row = layout.row(align=True)
    nav = row.row(align=True)
    nav.enabled = bool(steps)
    nav.operator("fh.step", text="", icon='REW').direction = 'FIRST'
    nav.operator("fh.step", text="", icon='PLAY_REVERSE').direction = 'PREV'

    if start > 0:
        row.operator("fh.scroll", text="", icon='TRIA_LEFT', emboss=False).delta = count // 2

    strip = row.row(align=True)
    if not steps:
        strip.label(text="History: no steps yet", icon='TIME')
    prev = steps[start - 1] if start > 0 else None
    for step in steps[start:end]:
        if prev is not None and step.get("parent") not in (0, prev["id"]):
            strip.separator(factor=0.6)  # new branch after a rollback
        cell = strip.row(align=True)
        cell.active = not store.is_rolled_back(step)
        op = cell.operator("fh.restore", text="", icon=core.category_icon(step.get("category")),
                           depress=step["id"] == store.current)
        op.step_id = step["id"]
        prev = step

    if end < len(steps):
        row.operator("fh.scroll", text="", icon='TRIA_RIGHT', emboss=False).delta = -(count // 2)

    nav = row.row(align=True)
    nav.enabled = bool(steps)
    nav.operator("fh.step", text="", icon='PLAY').direction = 'NEXT'
    nav.operator("fh.step", text="", icon='FF').direction = 'LAST'

    if show_count and steps:
        idx = store.current_index()
        row.label(text="%d/%d" % (idx + 1, len(steps)))


def draw_statusbar(self, context):
    if core.prefs().strip_location == 'STATUSBAR':
        self.layout.separator(factor=2.0)
        draw_strip(self.layout)


def draw_view3d_header(self, context):
    if core.prefs().strip_location == 'VIEW3D_HEADER':
        self.layout.separator(factor=2.0)
        draw_strip(self.layout, show_count=False)


# ------------------------------------------------------------------- list
class FH_StepItem(bpy.types.PropertyGroup):
    step_id: IntProperty()
    label: StringProperty()
    category: StringProperty()
    detail: StringProperty()
    stamp: StringProperty()
    pinned: BoolProperty()
    is_current: BoolProperty()
    rolled_back: BoolProperty()
    is_saved: BoolProperty()


class FH_UL_steps(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.active = not item.rolled_back
        text = "#%d  %s" % (item.step_id, item.label)
        if item.detail:
            text += "  (%s)" % item.detail
        row.label(text=text, icon=core.category_icon(item.category))
        if item.is_saved:
            row.label(text="", icon='FILE_TICK')
        if item.pinned:
            row.label(text="", icon='PINNED')
        if item.is_current:
            row.label(text="", icon='TRIA_LEFT')

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flags = [self.bitflag_filter_item] * len(items)
        if self.filter_name:
            needle = self.filter_name.lower()
            flags = [self.bitflag_filter_item if needle in (i.label + " " + i.detail).lower() else 0
                     for i in items]
        return flags, []


class FH_PT_history(bpy.types.Panel):
    bl_label = "History Timeline"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "History"

    def draw_header(self, context):
        prefs = core.prefs()
        if isinstance(prefs, bpy.types.AddonPreferences):
            self.layout.prop(prefs, "auto_capture", text="")

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        store = core.get_store()

        box = layout.box()
        draw_strip(box.column())

        row = layout.row(align=True)
        row.operator("fh.capture", text="Checkpoint", icon='BOOKMARKS')
        row.operator("fh.open_folder", text="", icon='FILE_FOLDER')
        row.operator("fh.clear", text="", icon='TRASH')

        layout.template_list("FH_UL_steps", "", wm, "fh_steps", wm, "fh_index", rows=8)

        if 0 <= wm.fh_index < len(wm.fh_steps):
            item = wm.fh_steps[wm.fh_index]
            col = layout.column(align=True)
            col.label(text=item.stamp, icon='TIME')
            row = col.row(align=True)
            op = row.operator("fh.restore", text="Restore", icon='RECOVER_LAST')
            op.step_id = item.step_id
            row.operator("fh.rename_step", text="", icon='GREASEPENCIL').step_id = item.step_id
            row.operator("fh.pin_step", text="",
                         icon='PINNED' if item.pinned else 'UNPINNED').step_id = item.step_id
            row.operator("fh.delete_step", text="", icon='X').step_id = item.step_id

        col = layout.column(align=True)
        col.scale_y = 0.8
        if not bpy.data.filepath:
            col.label(text="Unsaved file: save to enable restoring", icon='INFO')
        col.label(text="%d steps, %s on disk" % (len(store.steps), operators._fmt_size(store.disk_bytes)))


class TOPBAR_MT_fh_history(bpy.types.Menu):
    bl_label = "History Timeline"

    def draw(self, context):
        layout = self.layout
        layout.operator("fh.step", text="Roll Back", icon='PLAY_REVERSE').direction = 'PREV'
        layout.operator("fh.step", text="Roll Forward", icon='PLAY').direction = 'NEXT'
        layout.separator()
        layout.operator("fh.capture", icon='BOOKMARKS')
        layout.operator("fh.open_folder", icon='FILE_FOLDER')
        layout.operator("fh.clear", icon='TRASH')


def draw_edit_menu(self, context):
    self.layout.separator()
    self.layout.menu("TOPBAR_MT_fh_history", icon='TIME')


classes = (
    FH_AddonPreferences,
    FH_StepItem,
    FH_UL_steps,
    FH_PT_history,
    TOPBAR_MT_fh_history,
)

_addon_keymaps = []


def register():
    wm = bpy.types.WindowManager
    wm.fh_steps = CollectionProperty(type=FH_StepItem)
    wm.fh_index = IntProperty(name="Active Step")
    bpy.types.STATUSBAR_HT_header.append(draw_statusbar)
    bpy.types.VIEW3D_HT_header.append(draw_view3d_header)
    bpy.types.TOPBAR_MT_edit.append(draw_edit_menu)

    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Window", space_type='EMPTY')
        kmi = km.keymap_items.new("fh.step", 'Z', 'PRESS', ctrl=True, alt=True)
        kmi.properties.direction = 'PREV'
        _addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new("fh.step", 'Z', 'PRESS', ctrl=True, alt=True, shift=True)
        kmi.properties.direction = 'NEXT'
        _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()
    bpy.types.TOPBAR_MT_edit.remove(draw_edit_menu)
    bpy.types.VIEW3D_HT_header.remove(draw_view3d_header)
    bpy.types.STATUSBAR_HT_header.remove(draw_statusbar)
    del bpy.types.WindowManager.fh_index
    del bpy.types.WindowManager.fh_steps
