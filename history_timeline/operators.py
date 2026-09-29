# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

import bpy
from bpy.props import IntProperty, StringProperty, EnumProperty

from . import core


def _fmt_size(num):
    for unit in ("B", "KB", "MB"):
        if num < 1024:
            return "%.0f %s" % (num, unit) if unit == "B" else "%.1f %s" % (num, unit)
        num /= 1024.0
    return "%.2f GB" % num


def _step_tooltip(step, store):
    lines = ["#%d  %s" % (step["id"], step["label"])]
    if step.get("detail"):
        lines.append("Active: %s" % step["detail"])
    lines.append(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(step["time"])))
    if step.get("idname"):
        lines.append("Operator: %s" % step["idname"])
    idx = store.index_of(step["id"])
    if idx > 0 and step.get("parent") and step["parent"] != store.steps[idx - 1]["id"]:
        lines.append("Branched from #%d" % step["parent"])
    if step.get("undone"):
        lines.append("Undone with Ctrl+Z: Ctrl+Shift+Z brings it back,\n"
                     "your next change discards it (like Blender's redo)")
    elif step["id"] == store.current:
        lines.append("Current state (timeline marker)")
    elif store.is_rolled_back(step):
        lines.append("Rolled back - click to roll forward")
    if step["id"] == store.data.get("saved_step"):
        lines.append("Matches the saved file")
    if step.get("pending"):
        lines.append("Storing...")
    elif step.get("raw_size"):
        lines.append("Took %s on disk (file is %s)" % (
            _fmt_size(step.get("added", 0)), _fmt_size(step["raw_size"])))
    lines.append("Click to restore this state")
    return "\n".join(lines)


class HT_OT_restore(bpy.types.Operator):
    """Restore the file to this history step"""
    bl_idname = "ht.restore"
    bl_label = "Restore History Step"
    bl_options = {'INTERNAL'}

    step_id: IntProperty()

    @classmethod
    def description(cls, context, properties):
        store = core.get_store()
        step = store.get(properties.step_id)
        return _step_tooltip(step, store) if step else cls.__doc__

    def execute(self, context):
        store = core.get_store()
        if self.step_id == store.current and not bpy.data.is_dirty:
            return {'CANCELLED'}
        try:
            core.restore(self.step_id)
        except core.RestoreError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class HT_OT_step(bpy.types.Operator):
    """Move the timeline marker and restore that state"""
    bl_idname = "ht.step"
    bl_label = "Step Through History"
    bl_options = {'INTERNAL'}

    direction: EnumProperty(items=(
        ('FIRST', "First", "Go to the first step"),
        ('PREV', "Previous", "Roll back one step"),
        ('NEXT', "Next", "Roll forward one step"),
        ('LAST', "Last", "Go to the latest step"),
    ))

    @classmethod
    def description(cls, context, properties):
        return {
            'FIRST': "Roll back to the beginning of the history",
            'PREV': "Roll back one step (works across sessions, unlike Undo)",
            'NEXT': "Roll forward one step",
            'LAST': "Roll forward to the latest step",
        }[properties.direction]

    def execute(self, context):
        store = core.get_store()
        if not store.steps:
            return {'CANCELLED'}
        if self.direction == 'FIRST':
            step = store.steps[0]
        elif self.direction == 'LAST':
            step = store.steps[-1]
        else:
            step = store.neighbour(-1 if self.direction == 'PREV' else 1)
        if step is None or (step["id"] == store.current and not bpy.data.is_dirty):
            return {'CANCELLED'}
        try:
            core.restore(step["id"])
        except core.RestoreError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        return {'FINISHED'}


class _ContinuousUndo:
    """Blender's undo/redo first; once Blender has nothing left (e.g. right
    after reopening the file), keep going through the History Timeline."""
    bl_options = {'INTERNAL'}  # no UNDO/REGISTER: this must never push an undo step itself

    # (Blender operator, timeline direction, wording)
    blender_op = None
    offset = 0
    word = ""

    def execute(self, context):
        if core.restore_in_progress():
            return {'CANCELLED'}  # a held key must not queue several file loads
        op = self.blender_op()
        try:
            available = op.poll()
        except RuntimeError:  # undo system not initialised (background mode)
            available = False
        if available:
            return op()
        if not core.prefs().continuous_undo:
            return {'CANCELLED'}
        store = core.get_store()
        step = store.neighbour(self.offset)
        if step is None:
            self.report({'INFO'}, "Nothing more to %s in the History Timeline" % self.word)
            return {'CANCELLED'}
        try:
            core.restore(step["id"])
        except core.RestoreError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        self.report({'INFO'}, "History Timeline: %s to #%d %s" % (
            "back" if self.offset < 0 else "forward", step["id"], step["label"]))
        return {'FINISHED'}


class HT_OT_undo(_ContinuousUndo, bpy.types.Operator):
    """Undo. When Blender's own undo history is used up (for example after
    reopening the file), go back one step in the History Timeline"""
    bl_idname = "ht.undo"
    bl_label = "Undo (continues in History Timeline)"
    blender_op = staticmethod(lambda: bpy.ops.ed.undo)
    offset = -1
    word = "undo"


class HT_OT_redo(_ContinuousUndo, bpy.types.Operator):
    """Redo. When Blender has nothing left to redo, go forward one step in
    the History Timeline"""
    bl_idname = "ht.redo"
    bl_label = "Redo (continues in History Timeline)"
    blender_op = staticmethod(lambda: bpy.ops.ed.redo)
    offset = 1
    word = "redo"


class HT_OT_capture(bpy.types.Operator):
    """Add a named snapshot of the current state to the timeline"""
    bl_idname = "ht.capture"
    bl_label = "Capture History Step"
    bl_options = {'REGISTER'}

    label: StringProperty(name="Name", default="Checkpoint")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        step = core.capture(self.label, category="manual")
        if step is None:
            self.report({'ERROR'}, "Could not write the snapshot (see console)")
            return {'CANCELLED'}
        step["pinned"] = True
        core.get_store().save()
        core.tag_redraw()
        return {'FINISHED'}


class _StepOp:
    step_id: IntProperty()

    def _step(self):
        return core.get_store().get(self.step_id)


class HT_OT_delete_step(_StepOp, bpy.types.Operator):
    """Delete this snapshot from disk"""
    bl_idname = "ht.delete_step"
    bl_label = "Delete History Step"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not core.delete_step(self.step_id):
            return {'CANCELLED'}
        core.tag_redraw()
        return {'FINISHED'}


class HT_OT_pin_step(_StepOp, bpy.types.Operator):
    """Pin this step so it is never pruned by the step limit"""
    bl_idname = "ht.pin_step"
    bl_label = "Pin History Step"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        step = self._step()
        if step is None:
            return {'CANCELLED'}
        step["pinned"] = not step.get("pinned", False)
        core.get_store().save()
        core.tag_redraw()
        return {'FINISHED'}


class HT_OT_rename_step(_StepOp, bpy.types.Operator):
    """Rename this history step"""
    bl_idname = "ht.rename_step"
    bl_label = "Rename History Step"
    bl_options = {'INTERNAL'}

    label: StringProperty(name="Name")

    def invoke(self, context, event):
        step = self._step()
        if step is None:
            return {'CANCELLED'}
        self.label = step["label"]
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        step = self._step()
        if step is None:
            return {'CANCELLED'}
        step["label"] = self.label
        core.get_store().save()
        core.tag_redraw()
        return {'FINISHED'}


class HT_OT_clear(bpy.types.Operator):
    """Delete every snapshot of this file's history"""
    bl_idname = "ht.clear"
    bl_label = "Clear History"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        core.clear_history()
        core.tag_redraw()
        return {'FINISHED'}


class HT_OT_open_folder(bpy.types.Operator):
    """Open the folder containing the history snapshots"""
    bl_idname = "ht.open_folder"
    bl_label = "Open History Folder"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        directory = core.get_store().dir
        os.makedirs(directory, exist_ok=True)
        bpy.ops.wm.path_open(filepath=directory)
        return {'FINISHED'}


class HT_OT_scroll(bpy.types.Operator):
    """Scroll the timeline strip"""
    bl_idname = "ht.scroll"
    bl_label = "Scroll Timeline"
    bl_options = {'INTERNAL'}

    delta: IntProperty()

    def execute(self, context):
        total = len(core.get_store().steps)
        count = core.prefs().strip_count
        limit = max(0, total - count)
        core._State.strip_offset = min(max(core._State.strip_offset + self.delta, 0), limit)
        core.tag_redraw()
        return {'FINISHED'}


class HT_OT_select_step(bpy.types.Operator):
    """Select this step (double-check it, then Restore)"""
    bl_idname = "ht.select_step"
    bl_label = "Select History Step"
    bl_options = {'INTERNAL'}

    step_id: IntProperty()

    @classmethod
    def description(cls, context, properties):
        store = core.get_store()
        step = store.get(properties.step_id)
        return _step_tooltip(step, store).replace("Click to restore", "Select") if step else ""

    def execute(self, context):
        context.window_manager.ht_selected = self.step_id
        return {'FINISHED'}


class HT_OT_page(bpy.types.Operator):
    """Show the previous / next page of steps"""
    bl_idname = "ht.page"
    bl_label = "Change History Page"
    bl_options = {'INTERNAL'}

    delta: IntProperty()
    pages: IntProperty(default=1)

    def execute(self, context):
        wm = context.window_manager
        wm.ht_page = min(max(0, wm.ht_page + self.delta), max(0, self.pages - 1))
        return {'FINISHED'}


classes = (
    HT_OT_undo,
    HT_OT_redo,
    HT_OT_select_step,
    HT_OT_page,
    HT_OT_restore,
    HT_OT_step,
    HT_OT_capture,
    HT_OT_delete_step,
    HT_OT_pin_step,
    HT_OT_rename_step,
    HT_OT_clear,
    HT_OT_open_folder,
    HT_OT_scroll,
)
