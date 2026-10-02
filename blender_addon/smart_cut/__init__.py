bl_info = {
    "name": "Smart Cut",
    "author": "metjus",
    "version": (0, 3, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Smart Cut",
    "description": "Cut a model along a smooth hand-drawn loop into printable parts",
    "category": "Mesh",
}

if "bpy" in locals():  # reload pri vývoji
    import importlib

    from . import caps, connectors, cutter, geom, operators, stroke, surface

    for m in (geom, surface, caps, stroke, cutter, connectors, operators):
        importlib.reload(m)

import bpy

from . import operators


def register():
    for c in operators.CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(operators.CLASSES):
        bpy.utils.unregister_class(c)
