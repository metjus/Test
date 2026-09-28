"""Fox Parametric - CAD-style feature history for Blender objects."""

bl_info = {
    "name": "Fox Parametric",
    "author": "Blender Fox",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Fox,  Add > Mesh > Fox Part",
    "description": "CAD-style parametric modelling with an editable feature history",
    "category": "Mesh",
}

from . import core, ops, props, ui  # noqa: E402

_modules = (props, core, ops, ui)


def register():
    for m in _modules:
        m.register()


def unregister():
    for m in reversed(_modules):
        m.unregister()
