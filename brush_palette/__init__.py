# SPDX-License-Identifier: GPL-3.0-or-later
"""Brush & Alpha Palette: a ZBrush-style popup palette for brushes and alphas."""

bl_info = {
    "name": "Brush & Alpha Palette",
    "author": "Matus Sturdik",
    "version": (1, 0, 0),
    "blender": (4, 3, 0),
    "location": "3D Viewport > Sculpt / Paint modes > Alt+B (brushes), Alt+A (alphas), Sidebar > Palette",
    "description": "ZBrush-style popup palette with big thumbnails for picking brushes and alphas",
    "category": "Paint",
}

if "bpy" in locals():
    import importlib
    for _mod in (prefs, thumbs, brushes, alphas, palette, ui, keymaps):  # noqa: F821
        importlib.reload(_mod)

import bpy  # noqa: E402

from . import prefs, thumbs, brushes, alphas, palette, ui, keymaps  # noqa: E402

_modules = (prefs, palette, ui, keymaps)


def register():
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
    thumbs.free_gpu()
