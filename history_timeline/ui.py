# SPDX-License-Identifier: GPL-3.0-or-later
"""Timeline strip, sidebar panel and preferences."""

import sys
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from . import core, operators


# ------------------------------------------------------------ preferences
class HT_AddonPreferences(bpy.types.AddonPreferences):
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
    continuous_undo: BoolProperty(
        name="Continuous Ctrl+Z", default=True,
        description="When Blender's own undo history runs out (for example after reopening "
                    "the file), Ctrl+Z / Ctrl+Shift+Z keep stepping through the History Timeline. "
                    "Off: Ctrl+Z is Blender's standard undo",
        update=lambda self, ctx: _update_undo_keys())
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
            ('STATUSBAR', "Status Bar", "Bottom of the window, always visible"),
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
        col.prop(self, "continuous_undo")
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
    nav.operator("ht.step", text="", icon='REW').direction = 'FIRST'
    nav.operator("ht.step", text="", icon='PLAY_REVERSE').direction = 'PREV'

    if start > 0:
        row.operator("ht.scroll", text="", icon='TRIA_LEFT', emboss=False).delta = count // 2

    strip = row.row(align=True)
    if not steps:
        strip.label(text="History: no steps yet", icon='TIME')
    prev = steps[start - 1] if start > 0 else None
    for step in steps[start:end]:
        if prev is not None and step.get("parent") not in (0, prev["id"]):
            strip.separator(factor=0.6)  # new branch after a rollback
        cell = strip.row(align=True)
        cell.active = not store.is_rolled_back(step)
        op = cell.operator("ht.restore", text="", icon=core.category_icon(step.get("category")),
                           depress=step["id"] == store.current)
        op.step_id = step["id"]
        prev = step

    if end < len(steps):
        row.operator("ht.scroll", text="", icon='TRIA_RIGHT', emboss=False).delta = -(count // 2)

    nav = row.row(align=True)
    nav.enabled = bool(steps)
    nav.operator("ht.step", text="", icon='PLAY').direction = 'NEXT'
    nav.operator("ht.step", text="", icon='FF').direction = 'LAST'

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
PAGE_SIZE = 12


def _filtered_steps(context):
    """Steps newest first, narrowed by the search field."""
    steps = core.get_store().steps
    needle = context.window_manager.ht_filter.lower()
    if needle:
        return [s for s in reversed(steps)
                if needle in ("%s %s" % (s["label"], s.get("detail", ""))).lower()]
    return steps[::-1]


class HT_PT_history(bpy.types.Panel):
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
        row.operator("ht.capture", text="Checkpoint", icon='BOOKMARKS')
        row.operator("ht.open_folder", text="", icon='FILE_FOLDER')
        row.operator("ht.clear", text="", icon='TRASH')

        # Paged list: drawing cost does not grow with the number of steps.
        layout.prop(wm, "ht_filter", text="", icon='VIEWZOOM')
        steps = _filtered_steps(context)
        pages = max(1, (len(steps) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(wm.ht_page, pages - 1)
        col = layout.column(align=True)
        saved = store.data.get("saved_step")
        for step in steps[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
            row = col.row(align=True)
            row.active = not store.is_rolled_back(step)
            text = "#%d  %s" % (step["id"], step["label"])
            if step.get("detail"):
                text += "  (%s)" % step["detail"]
            op = row.operator("ht.select_step", text=text, emboss=step["id"] == wm.ht_selected,
                              icon=core.category_icon(step.get("category")))
            op.step_id = step["id"]
            if step["id"] == saved:
                row.label(text="", icon='FILE_TICK')
            if step.get("pinned"):
                row.label(text="", icon='PINNED')
            if step["id"] == store.current:
                row.label(text="", icon='TRIA_LEFT')
        if pages > 1:
            row = layout.row(align=True)
            for delta, icon in ((-1, 'TRIA_LEFT'), (1, 'TRIA_RIGHT')):
                if delta > 0:
                    row.label(text="Page %d / %d" % (page + 1, pages))
                op = row.operator("ht.page", text="", icon=icon)
                op.delta, op.pages = delta, pages

        step = store.get(wm.ht_selected)
        if step is not None:
            col = layout.column(align=True)
            col.label(text=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(step["time"])),
                      icon='TIME')
            row = col.row(align=True)
            row.operator("ht.restore", text="Restore", icon='RECOVER_LAST').step_id = step["id"]
            row.operator("ht.rename_step", text="", icon='GREASEPENCIL').step_id = step["id"]
            row.operator("ht.pin_step", text="",
                         icon='PINNED' if step.get("pinned") else 'UNPINNED').step_id = step["id"]
            row.operator("ht.delete_step", text="", icon='X').step_id = step["id"]
            later = core.steps_after(step["id"])
            if later:
                row = col.row(align=True)
                row.alert = True
                row.operator("ht.truncate", icon='TRASH',
                             text="Go Back Here, Delete %d Later Step%s" % (
                                 len(later), "s" if len(later) > 1 else "")).step_id = step["id"]

        col = layout.column(align=True)
        col.scale_y = 0.8
        if not bpy.data.filepath:
            col.label(text="Unsaved file: save to enable restoring", icon='INFO')
        col.label(text="%d steps, %s on disk" % (len(store.steps), operators._fmt_size(store.disk_bytes)))


class TOPBAR_MT_ht_history(bpy.types.Menu):
    bl_label = "History Timeline"

    def draw(self, context):
        layout = self.layout
        layout.operator("ht.step", text="Roll Back", icon='PLAY_REVERSE').direction = 'PREV'
        layout.operator("ht.step", text="Roll Forward", icon='PLAY').direction = 'NEXT'
        layout.separator()
        layout.operator("ht.truncate", text="Delete Later Steps", icon='TRASH').step_id = 0
        layout.separator()
        layout.operator("ht.capture", icon='BOOKMARKS')
        layout.operator("ht.open_folder", icon='FILE_FOLDER')
        layout.operator("ht.clear", icon='TRASH')


def draw_edit_menu(self, context):
    self.layout.separator()
    self.layout.menu("TOPBAR_MT_ht_history", icon='TIME')


classes = (
    HT_AddonPreferences,
    HT_PT_history,
    TOPBAR_MT_ht_history,
)

_addon_keymaps = []
_undo_keymaps = []   # Ctrl+Z / Ctrl+Shift+Z, active only with "Continuous Ctrl+Z"


def _update_undo_keys():
    active = bool(getattr(core.prefs(), "continuous_undo", True))
    for _km, kmi in _undo_keymaps:
        kmi.active = active


def register():
    wm = bpy.types.WindowManager
    wm.ht_filter = StringProperty(name="Search", description="Filter steps by name or object",
                                  update=lambda self, ctx: setattr(self, "ht_page", 0))
    wm.ht_page = IntProperty(min=0)
    wm.ht_selected = IntProperty(name="Selected Step")
    bpy.types.STATUSBAR_HT_header.append(draw_statusbar)
    bpy.types.VIEW3D_HT_header.append(draw_view3d_header)
    bpy.types.TOPBAR_MT_edit.append(draw_edit_menu)

    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="Window", space_type='EMPTY')
        kmi = km.keymap_items.new("ht.step", 'Z', 'PRESS', ctrl=True, alt=True)
        kmi.properties.direction = 'PREV'
        _addon_keymaps.append((km, kmi))
        kmi = km.keymap_items.new("ht.step", 'Z', 'PRESS', ctrl=True, alt=True, shift=True)
        kmi.properties.direction = 'NEXT'
        _addon_keymaps.append((km, kmi))

        # Take over Ctrl+Z / Ctrl+Shift+Z where Blender binds its own undo
        # (the "Screen" keymap). Add-on key items are checked before the
        # default ones; the operators call Blender's undo/redo first.
        km = kc.keymaps.new(name="Screen", space_type='EMPTY')
        mods = [dict(ctrl=True)]
        if sys.platform == "darwin":
            mods.append(dict(oskey=True))
        for mod in mods:
            for idname, shift in (("ht.undo", False), ("ht.redo", True)):
                kmi = km.keymap_items.new(idname, 'Z', 'PRESS', shift=shift, repeat=True, **mod)
                _undo_keymaps.append((km, kmi))
        _update_undo_keys()


def unregister():
    for km, kmi in _addon_keymaps + _undo_keymaps:
        km.keymap_items.remove(kmi)
    _addon_keymaps.clear()
    _undo_keymaps.clear()
    bpy.types.TOPBAR_MT_edit.remove(draw_edit_menu)
    bpy.types.VIEW3D_HT_header.remove(draw_view3d_header)
    bpy.types.STATUSBAR_HT_header.remove(draw_statusbar)
    del bpy.types.WindowManager.ht_selected
    del bpy.types.WindowManager.ht_page
    del bpy.types.WindowManager.ht_filter
