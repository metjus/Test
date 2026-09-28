"""Turns a part's feature history into Blender data.

Design: every feature after the base becomes one modifier on the part object,
named ``Fox:<uid>``, kept in history order at the top of the modifier stack.
Sketch features (extrude, revolve, hole) get a hidden "tool" object with the
generated solid, used by a Boolean modifier. The result is plain Blender data:
a .blend opens fine without the add-on, it just can't be edited parametrically.
"""

import contextlib

import bpy
from bpy.app.handlers import persistent

from . import geometry
from .props import SKETCH_TYPES, TYPE_NAMES

MOD_PREFIX = "Fox:"
SMOOTH_MOD = MOD_PREFIX + "Smooth"
NORMALS_MOD = MOD_PREFIX + "Normals"
SMOOTH_GROUP = ".Fox Smooth by Angle"
TOOL_COLLECTION = "Fox Tools"

_busy = False       # a rebuild is running (ignore our own property writes)
_suspended = 0      # batch edits in progress: rebuild once at the end
_signatures = {}    # object pointer -> hash of its parameters (for animation/drivers)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_part(obj):
    return obj is not None and obj.type == "MESH" and obj.fox_part.is_part


@contextlib.contextmanager
def batch():
    """Change many properties, rebuild only once."""
    global _suspended
    _suspended += 1
    try:
        yield
    finally:
        _suspended -= 1


def request_rebuild(obj):
    if _busy or _suspended or not is_part(obj):
        return
    rebuild(obj)


def rebuild(obj):
    global _busy
    if _busy or not is_part(obj):
        return
    _busy = True
    try:
        _rebuild(obj)
    finally:
        _busy = False
    _signatures[obj.as_pointer()] = signature(obj)


def feature_active(part, index):
    f = part.features[index]
    return not f.suppressed and (part.rollback < 0 or index <= part.rollback)


def new_uid(part):
    uid = str(part.next_uid)
    part.next_uid += 1
    return uid


def unique_feature_name(part, ftype):
    base = TYPE_NAMES[ftype]
    names = {f.name for f in part.features}
    i = 1
    while "%s %d" % (base, i) in names:
        i += 1
    return "%s %d" % (base, i)


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

def _tool_collection(scene):
    coll = bpy.data.collections.get(TOOL_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(TOOL_COLLECTION)
        coll.hide_render = True
    if scene is not None and coll.name not in scene.collection.children:
        # Boolean operands must be in the scene to be evaluated.
        scene.collection.children.link(coll)
    return coll


def _scene_of(obj):
    scene = bpy.context.scene
    if scene is not None and obj.name in scene.objects:
        return scene
    return obj.users_scene[0] if obj.users_scene else scene


def _through_depth(obj):
    co = [abs(c) for corner in obj.bound_box for c in corner]
    return max(co + [0.1]) * 4.0 + 0.1


def _write_bmesh(bm, mesh):
    bm.to_mesh(mesh)
    mesh.update()
    bm.free()


def _ensure_tool(obj, f, coll):
    tool = f.tool
    if (tool is None or tool.name not in bpy.data.objects or tool.parent != obj
            or tool.get("fox_uid") != f.uid):
        # Missing, deleted, or belongs to another part (e.g. after Shift+D).
        name = "FoxTool.%s.%s" % (obj.name, f.uid)
        tool = bpy.data.objects.new(name, bpy.data.meshes.new(name))
        coll.objects.link(tool)
        tool.parent = obj
        tool["fox_uid"] = f.uid
        f.tool = tool
    elif tool.name not in coll.objects:
        coll.objects.link(tool)
    tool.display_type = "WIRE"
    tool.hide_render = True
    tool.hide_select = True
    tool.hide_viewport = not f.show_tool
    return tool


def _ensure_modifier(obj, name, mtype):
    mod = obj.modifiers.get(name)
    if mod is not None and mod.type != mtype:
        obj.modifiers.remove(mod)
        mod = None
    if mod is None:
        mod = obj.modifiers.new(name, mtype)
    return mod


def _move_modifier(obj, name, index):
    if obj.modifiers.find(name) == index:
        return
    try:
        with bpy.context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.modifier_move_to_index(modifier=name, index=index)
    except Exception:
        pass  # order is cosmetic for the first rebuild; fixed on the next one


def _smooth_group():
    """Node group: faces smooth, edges sharper than an angle stay sharp."""
    ng = bpy.data.node_groups.get(SMOOTH_GROUP)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(SMOOTH_GROUP, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    angle = ng.interface.new_socket("Angle", in_out="INPUT", socket_type="NodeSocketFloat")
    angle.subtype = "ANGLE"
    angle.default_value = 0.5236
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = ng.nodes
    gin, gout = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    faces = n.new("GeometryNodeSetShadeSmooth")
    faces.domain = "FACE"
    edges = n.new("GeometryNodeSetShadeSmooth")
    edges.domain = "EDGE"
    edge_angle = n.new("GeometryNodeInputMeshEdgeAngle")
    compare = n.new("FunctionNodeCompare")
    compare.data_type, compare.operation = "FLOAT", "LESS_EQUAL"
    link = ng.links.new
    link(gin.outputs[0], faces.inputs["Geometry"])
    link(faces.outputs[0], edges.inputs["Geometry"])
    link(edge_angle.outputs["Unsigned Angle"], compare.inputs[0])
    link(gin.outputs[1], compare.inputs[1])
    link(compare.outputs[0], edges.inputs["Shade Smooth"])
    link(edges.outputs[0], gout.inputs[0])
    for i, node in enumerate((gin, faces, edge_angle, compare, edges, gout)):
        node.location = (i * 200, 0)
    return ng


def _update_smooth(obj):
    """Smooth-by-angle + weighted normals, so big flat faces stay flat next to
    fillets. Returns the modifier names in stack order."""
    part = obj.fox_part
    if not part.smooth:
        for name in (SMOOTH_MOD, NORMALS_MOD):
            if name in obj.modifiers:
                obj.modifiers.remove(obj.modifiers[name])
        return []
    mod = _ensure_modifier(obj, SMOOTH_MOD, "NODES")
    ng = _smooth_group()
    if mod.node_group != ng:
        mod.node_group = ng
    ident = next(i.identifier for i in ng.interface.items_tree
                 if getattr(i, "in_out", None) == "INPUT" and i.name == "Angle")
    mod[ident] = part.smooth_angle
    mod.show_expanded = False
    wn = _ensure_modifier(obj, NORMALS_MOD, "WEIGHTED_NORMAL")
    wn.mode = "FACE_AREA"
    wn.keep_sharp = True
    wn.weight = 50
    wn.show_expanded = False
    return [SMOOTH_MOD, NORMALS_MOD]


def _remove_tool(tool):
    me = tool.data
    bpy.data.objects.remove(tool, do_unlink=True)
    if me is not None and me.users == 0:
        bpy.data.meshes.remove(me)


def _rebuild(obj):
    part = obj.fox_part
    feats = part.features
    if not len(feats):
        return
    scene = _scene_of(obj)

    # 1) Base body -> the object's own mesh (unless it is a hand-made mesh).
    base = feats[0]
    if base.type in ("EXTRUDE", "REVOLVE") and obj.mode != "EDIT":
        bm = geometry.build_feature_bmesh(base, pattern=False)
        _write_bmesh(bm, obj.data)

    through = _through_depth(obj)
    coll = None
    wanted = []

    # 2) Every later feature -> one modifier, in order.
    for i in range(1, len(feats)):
        f = feats[i]
        if f.type == "BASE_MESH":
            continue  # only meaningful as the first feature
        if not f.uid:
            f.uid = new_uid(part)
        name = MOD_PREFIX + f.uid
        wanted.append(name)

        if f.type in SKETCH_TYPES:
            coll = coll or _tool_collection(scene)
            tool = _ensure_tool(obj, f, coll)
            _write_bmesh(geometry.build_feature_bmesh(f, through_depth=through), tool.data)
            mod = _ensure_modifier(obj, name, "BOOLEAN")
            mod.object = tool
            mod.solver = "EXACT"
            mod.operation = "DIFFERENCE" if f.type == "HOLE" else {
                "JOIN": "UNION", "CUT": "DIFFERENCE", "INTERSECT": "INTERSECT"}[f.operation]
            mod.use_self = f.pattern != "NONE"  # patterned copies may overlap
        else:
            if f.tool is not None and f.tool.name in bpy.data.objects and f.tool.parent == obj:
                _remove_tool(f.tool)
                f.tool = None
            if f.type in ("FILLET", "CHAMFER"):
                mod = _ensure_modifier(obj, name, "BEVEL")
                mod.offset_type = "OFFSET"
                mod.width = f.size
                mod.segments = f.fillet_segments if f.type == "FILLET" else 1
                mod.profile = 0.5
                mod.limit_method = "ANGLE" if f.edges == "ANGLE" else "NONE"
                mod.angle_limit = f.edge_angle
                mod.use_clamp_overlap = True
            elif f.type == "MIRROR":
                mod = _ensure_modifier(obj, name, "MIRROR")
                mod.use_axis = (f.mirror_x, f.mirror_y, f.mirror_z)
                mod.use_bisect_axis = (f.mirror_bisect and f.mirror_x, f.mirror_bisect and f.mirror_y,
                                       f.mirror_bisect and f.mirror_z)
                mod.use_mirror_merge = True
        active = feature_active(part, i)
        mod.show_viewport = active
        mod.show_render = active
        mod.show_expanded = False

    # Smooth shading goes after all features.
    wanted += _update_smooth(obj)

    # 3) Drop modifiers and tools of deleted features.
    for mod in [m for m in obj.modifiers if m.name.startswith(MOD_PREFIX) and m.name not in wanted]:
        obj.modifiers.remove(mod)
    uids = {f.uid for f in feats if f.type in SKETCH_TYPES}
    for child in [c for c in obj.children if "fox_uid" in c and c["fox_uid"] not in uids]:
        _remove_tool(child)

    # 4) Our modifiers first, in history order; the user's own ones stay after.
    for index, name in enumerate(wanted):
        _move_modifier(obj, name, index)


# ---------------------------------------------------------------------------
# Parameters driven by animation or drivers
# ---------------------------------------------------------------------------

def signature(obj):
    vals = [obj.fox_part.rollback, obj.fox_part.smooth, obj.fox_part.smooth_angle]
    for f in obj.fox_part.features:
        for p in f.bl_rna.properties:
            if p.identifier in ("rna_type", "tool", "name"):
                continue
            v = getattr(f, p.identifier)
            vals.append(tuple(v) if isinstance(v, (bpy.types.bpy_prop_array,)) else v)
    return hash(tuple(vals))


@persistent
def _on_change(scene, depsgraph=None):
    """Rebuild parts whose parameters changed through keyframes or drivers."""
    if _busy or _suspended:
        return
    for obj in scene.objects:
        if obj.animation_data is None or not is_part(obj):
            continue
        if _signatures.get(obj.as_pointer()) != signature(obj):
            rebuild(obj)


@persistent
def _on_load(_dummy=None):
    _signatures.clear()
    for obj in bpy.data.objects:
        if is_part(obj):
            _signatures[obj.as_pointer()] = signature(obj)


def register():
    bpy.app.handlers.frame_change_post.append(_on_change)
    bpy.app.handlers.depsgraph_update_post.append(_on_change)
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    for lst, fn in ((bpy.app.handlers.frame_change_post, _on_change),
                    (bpy.app.handlers.depsgraph_update_post, _on_change),
                    (bpy.app.handlers.load_post, _on_load)):
        if fn in lst:
            lst.remove(fn)
