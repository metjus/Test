# SPDX-License-Identifier: GPL-3.0-or-later
import os
import time

import bpy
from bpy.props import IntProperty, StringProperty, EnumProperty

from . import core


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
    if step["id"] == store.current:
        lines.append("Current state (timeline marker)")
    elif store.is_rolled_back(step):
        lines.append("Rolled back - click to roll forward")
    if step["id"] == store.data.get("saved_step"):
        lines.append("Matches the saved file")
    lines.append("Click to restore this state")
    return "\n".join(lines)


class FH_OT_restore(bpy.types.Operator):
    """Restore the file to this history step"""
    bl_idname = "fh.restore"
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


class FH_OT_step(bpy.types.Operator):
    """Move the timeline marker and restore that state"""
    bl_idname = "fh.step"
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


class FH_OT_capture(bpy.types.Operator):
    """Add a named snapshot of the current state to the timeline"""
    bl_idname = "fh.capture"
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
        core.sync_ui()
        return {'FINISHED'}


class _StepOp:
    step_id: IntProperty()

    def _step(self):
        return core.get_store().get(self.step_id)


class FH_OT_delete_step(_StepOp, bpy.types.Operator):
    """Delete this snapshot from disk"""
    bl_idname = "fh.delete_step"
    bl_label = "Delete History Step"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not core.get_store().delete(self.step_id):
            return {'CANCELLED'}
        core.sync_ui()
        core.tag_redraw()
        return {'FINISHED'}


class FH_OT_pin_step(_StepOp, bpy.types.Operator):
    """Pin this step so it is never pruned by the step limit"""
    bl_idname = "fh.pin_step"
    bl_label = "Pin History Step"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        step = self._step()
        if step is None:
            return {'CANCELLED'}
        step["pinned"] = not step.get("pinned", False)
        core.get_store().save()
        core.sync_ui()
        return {'FINISHED'}


class FH_OT_rename_step(_StepOp, bpy.types.Operator):
    """Rename this history step"""
    bl_idname = "fh.rename_step"
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
        core.sync_ui()
        core.tag_redraw()
        return {'FINISHED'}


class FH_OT_clear(bpy.types.Operator):
    """Delete every snapshot of this file's history"""
    bl_idname = "fh.clear"
    bl_label = "Clear History"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        core.get_store().clear()
        core.sync_ui()
        core.tag_redraw()
        return {'FINISHED'}


class FH_OT_open_folder(bpy.types.Operator):
    """Open the folder containing the history snapshots"""
    bl_idname = "fh.open_folder"
    bl_label = "Open History Folder"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        directory = core.get_store().dir
        os.makedirs(directory, exist_ok=True)
        bpy.ops.wm.path_open(filepath=directory)
        return {'FINISHED'}


class FH_OT_scroll(bpy.types.Operator):
    """Scroll the timeline strip"""
    bl_idname = "fh.scroll"
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


classes = (
    FH_OT_restore,
    FH_OT_step,
    FH_OT_capture,
    FH_OT_delete_step,
    FH_OT_pin_step,
    FH_OT_rename_step,
    FH_OT_clear,
    FH_OT_open_folder,
    FH_OT_scroll,
)
