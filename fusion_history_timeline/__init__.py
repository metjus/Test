# SPDX-License-Identifier: GPL-3.0-or-later
"""History Timeline - a Fusion 360 style, persistent history for Blender.

Every change is written as a .blend snapshot next to your file, shown as a
clickable icon strip, and can be restored even after Blender was closed.
"""

bl_info = {
    "name": "History Timeline",
    "author": "History Timeline contributors",
    "version": (1, 2, 0),
    "blender": (4, 2, 0),
    "location": "Status Bar / 3D View > Sidebar > History / Edit > History Timeline",
    "description": "Fusion-style visual history timeline with undo that survives closing Blender",
    "category": "System",
}

import bpy

from . import core, operators, ui

_classes = ui.classes + operators.classes


def _startup():
    # Pick up the file that was open when the add-on got enabled.
    if bpy.context.window_manager is None:
        return 0.2
    core.get_store()
    core._sync_operator_marker()
    core.tag_redraw()
    return None


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    ui.register()
    core.register()
    bpy.app.timers.register(_startup, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(_startup):
        bpy.app.timers.unregister(_startup)
    core.unregister()
    ui.unregister()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
