bl_info = {
    "name": "Split by Color",
    "author": "metjus",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Split Color",
    "description": "Split a colored mesh (e.g. from Tripo AI) into per-color parts for multi-color 3D printing",
    "category": "Mesh",
}

if "bpy" in locals():  # reload pri vývoji
    import importlib

    from . import core, mesh_colors, operators

    for m in (core, mesh_colors, operators):
        importlib.reload(m)

import bpy

from . import operators


def register():
    for c in operators.CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(operators.CLASSES):
        bpy.utils.unregister_class(c)
