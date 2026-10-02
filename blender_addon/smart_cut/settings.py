"""Nastavenia kolíkov uložené v scéne, aby sa dali zadať vopred v paneli a ostali zapamätané."""
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty

class SmartCutSettings(bpy.types.PropertyGroup):
    shape: EnumProperty(
        name="Shape",
        description="Peg cross-section",
        items=[
            ("SQUARE", "Square", "Square peg, common for multi-part figurines"),
            ("ROUND", "Round", "Round peg"),
        ],
        default="SQUARE",
    )
    size: FloatProperty(
        name="Peg size",
        description="Width of the peg: side of the square, or diameter. In mm if 1 unit = 1 mm. 0 = automatic from the cut",
        default=0.0, min=0.0, max=100.0, step=10, precision=2, unit="LENGTH",
    )
    length: FloatProperty(
        name="Peg length",
        description="How far the peg sticks out of the cut face. 0 = automatic (about 2.2x the size)",
        default=0.0, min=0.0, max=200.0, step=10, precision=2, unit="LENGTH",
    )
    taper: FloatProperty(
        name="Taper",
        description="Width of the tip relative to the base (1 = straight). Just enough taper to guide the peg in",
        default=0.96, min=0.5, max=1.0,
    )
    count: IntProperty(
        name="Pegs", description="How many pegs on this cut. 0 = automatic from the size of the cut", default=0, min=0, max=8
    )
    alternate: BoolProperty(
        name="Alternate sides", description="Put pegs on both parts alternately instead of all on the active one", default=False
    )
    clearance: FloatProperty(
        name="Hole clearance",
        description="Gap on EACH side between peg and hole. In mm if 1 unit = 1 mm. "
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
