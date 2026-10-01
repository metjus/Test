"""Default hotkeys: Alt+B opens the brush palette, Alt+A the alpha palette.

They are added to each paint mode's keymap so they only act in those modes,
and can be changed from the add-on preferences.
"""

import bpy

KEYMAP_NAMES = (
    "Sculpt",
    "Vertex Paint",
    "Weight Paint",
    "Image Paint",
    "Sculpt Curves",
    "Grease Pencil Paint Mode",
    "Grease Pencil Sculpt Mode",
    "Grease Pencil Weight Paint",
    "Grease Pencil Vertex Paint",
)

ALPHA_KEYMAP_NAMES = ("Sculpt", "Image Paint")

_addon_keymaps = []


def register():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # background mode
        return
    for name in KEYMAP_NAMES:
        km = kc.keymaps.new(name=name, space_type='EMPTY')
        kmi = km.keymap_items.new("brush_palette.open", 'B', 'PRESS', alt=True)
        kmi.properties.tab = 'BRUSHES'
        _addon_keymaps.append((km, kmi))
        if name in ALPHA_KEYMAP_NAMES:
            kmi = km.keymap_items.new("brush_palette.open", 'A', 'PRESS', alt=True)
            kmi.properties.tab = 'ALPHAS'
            _addon_keymaps.append((km, kmi))


def unregister():
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    _addon_keymaps.clear()


def draw_keymap_prefs(layout, context):
    import rna_keymap_ui

    box = layout.box()
    box.label(text="Hotkeys", icon='KEYINGSET')
    kc = context.window_manager.keyconfigs.user
    if kc is None:
        return
    for name in KEYMAP_NAMES:
        km = kc.keymaps.get(name)
        if km is None:
            continue
        items = [kmi for kmi in km.keymap_items if kmi.idname == "brush_palette.open"]
        if not items:
            continue
        box.label(text=name)
        for kmi in items:
            rna_keymap_ui.draw_kmi([], kc, km, kmi, box, 0)
