"""Pure geometry builders: sketch profiles, sketch planes, extrude, revolve.

Everything here works in the part's local space and returns bmesh data, so it
can be tested without any UI.
"""

import math

import bmesh
from mathutils import Matrix, Vector

# Sketch planes: (u axis, v axis). The normal is u x v, so profiles drawn
# counter-clockwise in (u, v) always face along the normal.
PLANES = {
    "XY": (Vector((1, 0, 0)), Vector((0, 1, 0))),
    "XZ": (Vector((1, 0, 0)), Vector((0, 0, 1))),
    "YZ": (Vector((0, 1, 0)), Vector((0, 0, 1))),
}


def plane_matrix(plane, offset=0.0):
    """Matrix mapping sketch coordinates (u, v, w) to part-local space.
    ``w`` runs along the plane normal; ``offset`` moves the plane along it."""
    u, v = PLANES[plane]
    n = u.cross(v)
    m = Matrix.Identity(4)
    for row in range(3):
        m[row][0], m[row][1], m[row][2] = u[row], v[row], n[row]
    m.translation = n * offset
    return m


# ---------------------------------------------------------------------------
# 2D profiles (lists of (u, v) points, counter-clockwise, centred on origin)
# ---------------------------------------------------------------------------

def _circle_points(radius, segments, start=0.0):
    return [(radius * math.cos(start + 2 * math.pi * i / segments),
             radius * math.sin(start + 2 * math.pi * i / segments)) for i in range(segments)]


def profile_points(f):
    """Profile of a feature as a CCW list of (u, v) points around (0, 0)."""
    kind = f.profile
    if kind == "RECT":
        w, h = f.width / 2.0, f.height / 2.0
        pts = [(-w, -h), (w, -h), (w, h), (-w, h)]
    elif kind == "CIRCLE":
        pts = _circle_points(f.radius, f.segments)
    elif kind == "POLYGON":
        pts = _circle_points(f.radius, f.sides, start=math.pi / 2)
    elif kind == "SLOT":
        # Stadium: straight length plus two half circles of the slot width.
        r, half = f.height / 2.0, max(f.width - f.height, 0.0) / 2.0
        n = max(f.segments // 2, 2)
        pts = [(half + r * math.cos(-math.pi / 2 + math.pi * i / n),
                r * math.sin(-math.pi / 2 + math.pi * i / n)) for i in range(n + 1)]
        pts += [(-half + r * math.cos(math.pi / 2 + math.pi * i / n),
                 r * math.sin(math.pi / 2 + math.pi * i / n)) for i in range(n + 1)]
    else:
        raise ValueError("Unknown profile: %s" % kind)
    return _ccw(pts)


def hole_points(f):
    return _circle_points(f.hole_diameter / 2.0, f.segments)


def _ccw(pts):
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))
    return pts if area >= 0 else pts[::-1]


def place_2d(pts, du, dv, rotation):
    """Rotate a profile around its centre, then move it to (du, dv)."""
    c, s = math.cos(rotation), math.sin(rotation)
    return [(du + x * c - y * s, dv + x * s + y * c) for x, y in pts]


# ---------------------------------------------------------------------------
# Solids
# ---------------------------------------------------------------------------

def add_prism(bm, pts, z0, z1, matrix):
    """Closed prism from a CCW profile between w=z0 and w=z1 (z0 < z1)."""
    bottom = [bm.verts.new(matrix @ Vector((x, y, z0))) for x, y in pts]
    top = [bm.verts.new(matrix @ Vector((x, y, z1))) for x, y in pts]
    n = len(pts)
    bm.faces.new(bottom[::-1])
    bm.faces.new(top)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((bottom[i], bottom[j], top[j], top[i]))


def extrude_range(f):
    d = f.distance
    if f.direction == "SYMMETRIC":
        return -d / 2.0, d / 2.0
    if f.direction == "REVERSE":
        return -d, 0.0
    return 0.0, d


def add_revolve(bm, pts, f, matrix):
    """Revolve a profile around the sketch's U or V axis (through the plane origin)."""
    axis2d = Vector((0, 1, 0)) if f.revolve_axis == "V" else Vector((1, 0, 0))
    verts = [bm.verts.new(Vector((x, y, 0.0))) for x, y in pts]
    edges = [bm.edges.new((verts[i], verts[(i + 1) % len(verts)])) for i in range(len(verts))]
    full = f.revolve_angle >= math.radians(359.999)
    res = bmesh.ops.spin(bm, geom=verts + edges, cent=(0, 0, 0), axis=axis2d,
                         angle=math.radians(360) if full else f.revolve_angle,
                         steps=max(f.segments, 3), use_merge=full, use_duplicate=False)
    if not full:
        last = [e for e in res["geom_last"] if isinstance(e, bmesh.types.BMEdge)]
        bmesh.ops.contextual_create(bm, geom=edges)
        bmesh.ops.contextual_create(bm, geom=last)
    # A profile edge lying on the axis spins into duplicate points; weld them.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
    bmesh.ops.transform(bm, matrix=matrix, verts=list(bm.verts))


def revolve_crosses_axis(pts, axis):
    """True if the profile lies on both sides of the revolve axis (invalid solid).
    Touching the axis is fine - that gives a solid without a hole."""
    idx = 0 if axis == "V" else 1
    vals = [p[idx] for p in pts]
    return min(vals) < -1e-9 and max(vals) > 1e-9


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

def pattern_matrices(f, plane):
    """Copies of a feature, as matrices in part-local space."""
    u, v = PLANES[plane]
    if f.pattern == "LINEAR":
        out = []
        for i in range(max(f.count_u, 1)):
            for j in range(max(f.count_v, 1)):
                out.append(Matrix.Translation(u * (i * f.spacing_u) + v * (j * f.spacing_v)))
        return out
    if f.pattern == "CIRCULAR":
        n = max(f.circ_count, 1)
        full = f.circ_angle >= math.radians(359.999)
        step = f.circ_angle / (n if full else max(n - 1, 1))
        axis = u.cross(v)
        return [Matrix.Rotation(step * i, 4, axis) for i in range(n)]
    return [Matrix.Identity(4)]


# ---------------------------------------------------------------------------
# Feature -> mesh
# ---------------------------------------------------------------------------

def build_feature_bmesh(f, through_depth=10.0, pattern=True):
    """Solid for a sketch-based feature (EXTRUDE, REVOLVE, HOLE), patterns included."""
    bm = bmesh.new()
    base = plane_matrix(f.plane, f.offset)
    copies = pattern_matrices(f, f.plane) if pattern else [Matrix.Identity(4)]
    for pm in copies:
        m = pm @ base
        if f.type == "EXTRUDE":
            pts = place_2d(profile_points(f), f.pos_u, f.pos_v, f.rotation)
            z0, z1 = extrude_range(f)
            add_prism(bm, pts, z0, z1, m)
        elif f.type == "HOLE":
            pts = place_2d(hole_points(f), f.pos_u, f.pos_v, 0.0)
            depth = through_depth if f.through_all else f.hole_depth
            # Drill into the material (against the normal) and start slightly
            # above the sketch plane so the top face is cut cleanly.
            eps = max(depth * 1e-3, 1e-5)
            if f.flip:
                add_prism(bm, pts, -eps, depth, m)
            else:
                add_prism(bm, pts, -depth, eps, m)
        elif f.type == "REVOLVE":
            pts = place_2d(profile_points(f), f.pos_u, f.pos_v, f.rotation)
            sub = bmesh.new()
            add_revolve(sub, pts, f, m)
            tmp_mesh = _bm_to_temp_mesh(sub)
            sub.free()
            bm.from_mesh(tmp_mesh)
            _free_temp_mesh(tmp_mesh)
        else:
            raise ValueError("Not a sketch feature: %s" % f.type)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def _bm_to_temp_mesh(bm):
    import bpy
    me = bpy.data.meshes.new(".fox_tmp")
    bm.to_mesh(me)
    return me


def _free_temp_mesh(me):
    import bpy
    bpy.data.meshes.remove(me)
