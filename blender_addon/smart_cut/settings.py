"""Nastavenia kolíka uložené v scéne: zadávajú sa v paneli a ostanú zapamätané."""
import bpy
from bpy.props import FloatProperty


class SmartCutSettings(bpy.types.PropertyGroup):
    size: FloatProperty(
        name="Peg size",
        description="Width of the square peg, in mm if 1 unit = 1 mm. "
        "Use Fit to Cut to fill in a size that suits the current cut",
        default=4.0, min=0.05, max=200.0, step=10, precision=2, unit="LENGTH",
    )
    taper: FloatProperty(
        name="Taper",
        description="Width of the peg tip relative to its base. 1.00 is a straight peg; "
        "a little taper guides it in without making the fit loose",
        default=0.96, min=0.5, max=1.0,
    )
    clearance: FloatProperty(
        name="Hole clearance",
        description="Gap on EACH side between peg and hole, in mm if 1 unit = 1 mm. "
        "0.05 is a snug fit that still leaves a film for CA glue; raise it if the printed parts do not go together",
        default=0.05, min=0.0, max=1.0, step=1, precision=3, unit="LENGTH",
    )


def get(context) -> SmartCutSettings:
    return context.scene.smartcut


CLASSES = (SmartCutSettings,)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.smartcut = bpy.props.PointerProperty(type=SmartCutSettings)


def unregister():
    del bpy.types.Scene.smartcut
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
