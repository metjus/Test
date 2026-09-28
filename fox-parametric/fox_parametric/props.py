"""Data stored on objects: the part and its feature history."""

import math

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)

FEATURE_TYPES = [
    ("BASE_MESH", "Your Mesh", "Use the object's own mesh as the base. Model it by hand in Edit Mode", "MESH_DATA", 0),
    ("EXTRUDE", "Extrude", "Extrude a sketch profile", "MOD_SOLIDIFY", 1),
    ("REVOLVE", "Revolve", "Revolve a sketch profile around an axis", "MOD_SCREW", 2),
    ("HOLE", "Hole", "Drill a round hole", "MESH_CYLINDER", 3),
    ("FILLET", "Fillet", "Round sharp edges", "MOD_BEVEL", 4),
    ("CHAMFER", "Chamfer", "Cut sharp edges at an angle", "MOD_BEVEL", 5),
    ("MIRROR", "Mirror", "Mirror the whole body", "MOD_MIRROR", 6),
]
TYPE_ICONS = {k: icon for k, _, _, icon, _ in FEATURE_TYPES}
TYPE_NAMES = {k: name for k, name, _, _, _ in FEATURE_TYPES}
SKETCH_TYPES = {"EXTRUDE", "REVOLVE", "HOLE"}
BASE_TYPES = {"BASE_MESH", "EXTRUDE", "REVOLVE"}


def _changed(self, context):
    from . import core
    core.request_rebuild(self.id_data)


def _dist(name, default, desc="", min_=0.0):
    return FloatProperty(name=name, description=desc, default=default, min=min_, subtype="DISTANCE",
                         unit="LENGTH", precision=4, step=1, update=_changed)


class FoxFeature(bpy.types.PropertyGroup):
    uid: StringProperty()
    name: StringProperty(name="Name", update=_changed)
    type: EnumProperty(name="Type", items=FEATURE_TYPES, update=_changed)
    suppressed: BoolProperty(name="Suppress", description="Temporarily switch this feature off",
                             update=_changed)
    show_tool: BoolProperty(name="Show Tool", description="Show this feature's tool shape as a wireframe",
                            update=_changed)
    tool: PointerProperty(type=bpy.types.Object)

    operation: EnumProperty(name="Operation", default="JOIN", update=_changed, items=[
        ("JOIN", "Join", "Add material", "ADD", 0),
        ("CUT", "Cut", "Remove material", "REMOVE", 1),
        ("INTERSECT", "Intersect", "Keep only the overlap", "SELECT_INTERSECT", 2),
    ])

    # --- sketch -----------------------------------------------------------
    plane: EnumProperty(name="Plane", default="XY", update=_changed, items=[
        ("XY", "Top (XY)", "Sketch on the XY plane, extrude along Z"),
        ("XZ", "Front (XZ)", "Sketch on the XZ plane, extrude along -Y"),
        ("YZ", "Side (YZ)", "Sketch on the YZ plane, extrude along X"),
    ])
    offset: _dist("Plane Offset", 0.0, "Move the sketch plane along its normal", min_=-1e6)
    pos_u: _dist("Position U", 0.0, "Position along the plane's first axis", min_=-1e6)
    pos_v: _dist("Position V", 0.0, "Position along the plane's second axis", min_=-1e6)
    rotation: FloatProperty(name="Rotation", subtype="ANGLE", default=0.0, update=_changed)
    profile: EnumProperty(name="Profile", default="RECT", update=_changed, items=[
        ("RECT", "Rectangle", "", "MESH_PLANE", 0),
        ("CIRCLE", "Circle", "", "MESH_CIRCLE", 1),
        ("POLYGON", "Polygon", "", "SEQ_CHROMA_SCOPE", 2),
        ("SLOT", "Slot", "", "MESH_CAPSULE", 3),
    ])
    width: _dist("Width", 0.2, "Rectangle width / slot length")
    height: _dist("Height", 0.1, "Rectangle height / slot width")
    radius: _dist("Radius", 0.05)
    sides: IntProperty(name="Sides", default=6, min=3, max=256, update=_changed)
    segments: IntProperty(name="Segments", default=32, min=3, max=512, update=_changed,
                          description="Smoothness of round shapes")

    # --- extrude ----------------------------------------------------------
    distance: _dist("Distance", 0.05)
    direction: EnumProperty(name="Direction", default="ONE_SIDE", update=_changed, items=[
        ("ONE_SIDE", "One Side", "Along the plane normal"),
        ("REVERSE", "Reverse", "Against the plane normal"),
        ("SYMMETRIC", "Symmetric", "Half each way"),
    ])

    # --- revolve ----------------------------------------------------------
    revolve_axis: EnumProperty(name="Axis", default="V", update=_changed, items=[
        ("U", "U axis", "Revolve around the plane's first axis"),
        ("V", "V axis", "Revolve around the plane's second axis"),
    ])
    revolve_angle: FloatProperty(name="Angle", subtype="ANGLE", default=math.radians(360),
                                 min=math.radians(1), max=math.radians(360), update=_changed)

    # --- hole -------------------------------------------------------------
    hole_diameter: _dist("Diameter", 0.01)
    hole_depth: _dist("Depth", 0.02)
    through_all: BoolProperty(name="Through All", default=False, update=_changed)
    flip: BoolProperty(name="Flip Direction", default=False, update=_changed,
                       description="Drill along the plane normal instead of into it")

    # --- pattern ----------------------------------------------------------
    pattern: EnumProperty(name="Pattern", default="NONE", update=_changed, items=[
        ("NONE", "None", ""),
        ("LINEAR", "Linear", "Repeat in a grid along the plane axes"),
        ("CIRCULAR", "Circular", "Repeat around the plane origin"),
    ])
    count_u: IntProperty(name="Count U", default=3, min=1, max=1000, update=_changed)
    spacing_u: _dist("Spacing U", 0.05, min_=-1e6)
    count_v: IntProperty(name="Count V", default=1, min=1, max=1000, update=_changed)
    spacing_v: _dist("Spacing V", 0.05, min_=-1e6)
    circ_count: IntProperty(name="Count", default=6, min=1, max=1000, update=_changed)
    circ_angle: FloatProperty(name="Total Angle", subtype="ANGLE", default=math.radians(360),
                              min=0.0, max=math.radians(360), update=_changed)

    # --- fillet / chamfer -------------------------------------------------
    size: _dist("Size", 0.005, "Fillet radius / chamfer distance")
    fillet_segments: IntProperty(name="Segments", default=4, min=1, max=64, update=_changed)
    edges: EnumProperty(name="Edges", default="ANGLE", update=_changed, items=[
        ("ANGLE", "Sharp Edges", "Edges sharper than the angle below"),
        ("ALL", "All Edges", "Every edge"),
    ])
    edge_angle: FloatProperty(name="Angle", subtype="ANGLE", default=math.radians(30),
                              min=0.0, max=math.radians(180), update=_changed)

    # --- mirror -----------------------------------------------------------
    mirror_x: BoolProperty(name="X", default=True, update=_changed)
    mirror_y: BoolProperty(name="Y", default=False, update=_changed)
    mirror_z: BoolProperty(name="Z", default=False, update=_changed)
    mirror_bisect: BoolProperty(name="Cut Other Half", default=False, update=_changed,
                                description="Cut away the geometry on the mirrored side first")


class FoxPart(bpy.types.PropertyGroup):
    is_part: BoolProperty(default=False)
    features: CollectionProperty(type=FoxFeature)
    active_index: IntProperty(name="Active Feature", default=0)
    rollback: IntProperty(name="Rollback", default=-1, min=-1, update=_changed,
                          description="Only features up to this one are applied (-1 = all)")
    smooth: BoolProperty(name="Smooth Shading", default=True, update=_changed,
                         description="Shade curved surfaces smooth and keep sharp edges crisp")
    smooth_angle: FloatProperty(name="Angle", subtype="ANGLE", default=math.radians(30),
                                min=0.0, max=math.radians(180), update=_changed,
                                description="Edges sharper than this stay sharp")
    next_uid: IntProperty(default=1)


classes = (FoxFeature, FoxPart)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.fox_part = PointerProperty(type=FoxPart)


def unregister():
    del bpy.types.Object.fox_part
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
