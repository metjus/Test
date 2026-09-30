"""Studio renders for History Timeline promo images.

Usage: python studio.py <mode> <out.png> <width> <height> <samples>
  mode = row          five modeling stages on pedestals
  mode = stage<N>     a single stage (1-5) close up
"""
import math
import os
import sys

import bpy
import bmesh  # must follow bpy when bpy runs as a module
from mathutils import Vector

mode, out, W, H, SAMPLES = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


# ---------------------------------------------------------------- materials
def principled(name, color, rough=0.5, coat=0.0, metallic=0.0, emission=None, strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Coat Weight"].default_value = coat
    bsdf.inputs["Coat Roughness"].default_value = 0.05
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = strength
    return mat


backdrop_mat = principled("Backdrop", (0.018, 0.02, 0.025), rough=0.6)
pedestal_mat = principled("Pedestal", (0.035, 0.037, 0.043), rough=0.22)
clay_mat = principled("Clay", (0.42, 0.42, 0.44), rough=0.6)
matte_mat = principled("Matte", (0.9, 0.2, 0.02), rough=0.75)
final_mat = principled("Paint", (1.0, 0.2, 0.01), rough=0.18, coat=1.0)
ring_mat = principled("Ring", (0.0, 0.0, 0.0), rough=1.0, emission=(1.0, 0.45, 0.1), strength=6.0)


# ---------------------------------------------------------------- backdrop
def sweep():
    """Seamless studio sweep: floor curving up into a back wall."""
    mesh = bpy.data.meshes.new("Sweep")
    bm = bmesh.new()
    profile = [(y, 0.0) for y in (-40, -10, 0)]
    r = 8.0
    for i in range(1, 17):
        a = math.radians(90 * i / 16)
        profile.append((math.sin(a) * r, r - math.cos(a) * r))
    profile += [(r, 30.0)]
    half = 60
    rows = []
    for x in (-half, half):
        rows.append([bm.verts.new((x, y + 4, z)) for y, z in profile])
    for i in range(len(profile) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    bm.to_mesh(mesh)
    obj = bpy.data.objects.new("Sweep", mesh)
    scene.collection.objects.link(obj)
    for p in mesh.polygons:
        p.use_smooth = True
    mesh.materials.append(backdrop_mat)
    return obj


def add_modifier(obj, kind, **props):
    mod = obj.modifiers.new(kind.title(), kind)
    for k, v in props.items():
        setattr(mod, k, v)
    return mod


def pedestal(x):
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=1.05, depth=0.5, location=(x, 0, 0.25))
    ped = bpy.context.object
    add_modifier(ped, 'BEVEL', width=0.04, segments=4)
    ped.data.materials.append(pedestal_mat)
    bpy.ops.object.shade_smooth()
    # thin glowing ring on the top edge, echoing the timeline accent
    bpy.ops.mesh.primitive_torus_add(major_radius=1.02, minor_radius=0.012, location=(x, 0, 0.5),
                                     major_segments=128, minor_segments=8)
    bpy.context.object.data.materials.append(ring_mat)
    return ped


def stage(n, x):
    """Model at history step n (1..5)."""
    z = 0.5
    if n == 1:
        bpy.ops.mesh.primitive_cube_add(size=1.25, location=(x, 0, z + 0.625))
        obj = bpy.context.object
        obj.rotation_euler.z = math.radians(-20)
        obj.data.materials.append(clay_mat)
        return obj
    bpy.ops.mesh.primitive_monkey_add(size=1.55, location=(x, 0, z + 0.78))
    obj = bpy.context.object
    obj.rotation_euler = (math.radians(-12), 0, math.radians(-14))
    if n == 2:
        obj.data.materials.append(clay_mat)
        return obj
    add_modifier(obj, 'SUBSURF', levels=1 if n == 3 else 2, render_levels=1 if n == 3 else 3)
    bpy.ops.object.shade_smooth()
    obj.data.materials.append(clay_mat if n == 3 else matte_mat if n == 4 else final_mat)
    if n == 5:
        obj.rotation_euler = (math.radians(-8), 0, math.radians(-18))
    return obj


def sit_on(obj, top=0.5):
    """Drop an object so its lowest evaluated point rests on the pedestal."""
    bpy.context.view_layer.update()
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    low = min((ev.matrix_world @ v.co).z for v in ev.to_mesh().vertices)
    ev.to_mesh_clear()
    obj.location.z += top - low


def area(name, loc, target, size, energy, color=(1, 1, 1), spread=180):
    data = bpy.data.lights.new(name, 'AREA')
    data.size = size
    data.spread = math.radians(spread)
    data.energy = energy
    data.color = color
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    direction = Vector(target) - Vector(loc)
    obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.collection.objects.link(obj)
    return obj


def camera(loc, target, lens):
    data = bpy.data.cameras.new("Cam")
    data.lens = lens
    obj = bpy.data.objects.new("Cam", data)
    obj.location = loc
    obj.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    scene.collection.objects.link(obj)
    scene.camera = obj
    return obj


# ------------------------------------------------------------------ layout
sweep()
if mode == "row":
    xs = [-7.2, -3.6, 0.0, 3.6, 7.2]
    for i, x in enumerate(xs, start=1):
        pedestal(x)
        sit_on(stage(i, x))
    camera((0, -26, 3.0), (0, 0, 1.05), 50)
    area("Key", (-6, -11, 12), (0, 0, 1), 10, 3800, spread=55)
    area("Fill", (12, -14, 4), (0, 0, 1), 10, 500, (0.85, 0.92, 1.0), spread=70)
    area("Rim", (9, 6, 6), (2, 0, 1), 5, 2400, (1.0, 0.55, 0.25), spread=60)
    area("RimL", (-9, 6, 6), (-2, 0, 1), 5, 1500, (0.45, 0.7, 1.0), spread=60)
else:
    n = int(mode[len("stage"):])
    pedestal(0)
    sit_on(stage(n, 0))
    camera((0.6, -7.6, 2.4), (0, 0, 1.05), 58)
    area("Key", (-4, -5, 6.5), (0, 0, 1), 5, 1300, spread=60)
    area("Fill", (5, -5, 2.5), (0, 0, 1), 5, 180, (0.85, 0.92, 1.0), spread=70)
    area("Rim", (3.5, 3.5, 3.5), (0, 0, 1), 2.5, 800, (1.0, 0.55, 0.25), spread=60)
    area("RimL", (-3.5, 3.5, 3.5), (0, 0, 1), 2.5, 500, (0.45, 0.7, 1.0), spread=60)

world = bpy.data.worlds.new("World")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.012, 0.013, 0.016, 1)
scene.world = world

# ------------------------------------------------------------------ render
r = scene.render
r.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.max_bounces = 6
r.resolution_x, r.resolution_y = W, H
r.resolution_percentage = 100
r.film_transparent = False
scene.view_settings.view_transform = 'Standard'
scene.view_settings.look = 'None'
scene.view_settings.exposure = -1.6
r.image_settings.file_format = 'PNG'
r.filepath = out

# Where each pedestal (base and top centre) lands in the image, 0..1 from top-left,
# so HTML overlays can line up with the render.
import json
from bpy_extras.object_utils import world_to_camera_view
bpy.context.view_layer.update()
points = {}
for obj in scene.objects:
    if obj.name.startswith("Cylinder"):
        for key, z in (("top", 0.5), ("base", 0.0)):
            v = world_to_camera_view(scene, scene.camera, Vector((obj.location.x, -1.05 if key == "base" else 0, z)))
            points.setdefault(obj.name, {})[key] = (round(v.x, 4), round(1 - v.y, 4))
with open(out + ".json", "w") as fh:
    json.dump(dict(sorted(points.items())), fh, indent=1)
if os.environ.get("NO_RENDER"):
    raise SystemExit
bpy.ops.render.render(write_still=True)
