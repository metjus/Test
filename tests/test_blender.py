"""Testy v skutočnom Blenderi (balík bpy). Bez bpy sa preskočia."""
import sys
from pathlib import Path

import numpy as np
import pytest

bpy = pytest.importorskip("bpy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender_addon"))
import split_by_color  # noqa: E402

N = 20  # mriežka N×N plôch
RED, BLACK, SKIN = (0.8, 0.1, 0.1), (0.02, 0.02, 0.02), (0.9, 0.7, 0.55)


@pytest.fixture(autouse=True)
def addon():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    split_by_color.register()
    yield
    split_by_color.unregister()


def make_grid(name="Model"):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=N, y_subdivisions=N, size=2)
    obj = bpy.context.active_object
    obj.name = name
    assert len(obj.data.polygons) == N * N
    return obj


def texture(layout, size=100):
    """layout: funkcia (x,y)->farba pre pixel; vráti 8-bitový obrázok."""
    img = bpy.data.images.new("tex", size, size, alpha=False)
    px = np.zeros((size, size, 4), np.float32)
    px[..., 3] = 1
    for y in range(size):
        for x in range(size):
            px[y, x, :3] = layout(x / size, y / size)
    img.pixels.foreach_set(px.ravel())
    img.update()
    return img


def apply_texture(obj, img):
    mat = bpy.data.materials.new("m")
    if bpy.app.version < (5, 0, 0):
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    obj.data.materials.append(mat)


def faces_by_material(obj):
    idx = np.array([p.material_index for p in obj.data.polygons])
    return np.bincount(idx, minlength=len(obj.material_slots))


def run(obj, **kw):
    for o in bpy.context.scene.objects:
        o.select_set(o is obj)
    bpy.context.view_layer.objects.active = obj
    return bpy.ops.object.split_by_color(**kw)


# rozloženie: ľavá polovica červená, čierny štvorec (3x3 plochy) vpravo dole, zvyšok pleť
def layout(u, v):
    if u < 0.5:
        return RED
    if u > 0.6 and u < 0.75 and v < 0.15:
        return BLACK
    return SKIN


def test_texture_to_materials():
    obj = make_grid()
    apply_texture(obj, texture(layout))
    assert run(obj, mode="MATERIALS") == {"FINISHED"}
    assert len(obj.material_slots) == 3
    counts = sorted(faces_by_material(obj))
    assert sum(counts) == N * N
    assert counts[-1] == 200  # červená polovica = 10 stĺpcov
    assert counts[0] in range(6, 13)  # čierny štvorec ~ 3x3 plochy (hrany sú približné)
    # materiály majú správne farby
    cols = sorted(tuple(round(c, 2) for c in m.diffuse_color[:3]) for m in obj.data.materials)
    assert len(cols) == 3


def test_texture_to_objects_conserves_faces_and_removes_original():
    obj = make_grid("Head")
    apply_texture(obj, texture(layout))
    run(obj, mode="OBJECTS")
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert len(parts) == 3
    assert "Head" not in bpy.data.objects
    assert sum(len(p.data.polygons) for p in parts) == N * N
    for p in parts:
        assert len(p.material_slots) == 1
        # žiadne osamelé vrcholy
        used = {v for poly in p.data.polygons for v in poly.vertices}
        assert len(used) == len(p.data.vertices)


def test_split_disconnected_patches():
    # dve čierne škvrny, ktoré sa nedotýkajú (ako dve oči)
    def two_eyes(u, v):
        if (0.2 < u < 0.35 or 0.6 < u < 0.75) and 0.6 < v < 0.8:
            return BLACK
        return SKIN

    obj = make_grid()
    apply_texture(obj, texture(two_eyes))
    run(obj, mode="OBJECTS", split_islands=False)
    assert len([o for o in bpy.context.scene.objects if o.type == "MESH"]) == 2

    bpy.ops.wm.read_factory_settings(use_empty=True)  # triedy addonu ostávajú zaregistrované
    obj = make_grid()
    apply_texture(obj, texture(two_eyes))
    run(obj, mode="OBJECTS", split_islands=True)
    assert len([o for o in bpy.context.scene.objects if o.type == "MESH"]) == 3


def test_keep_original_hides_it():
    obj = make_grid("Keep")
    apply_texture(obj, texture(layout))
    run(obj, mode="OBJECTS", keep_original=True)
    assert "Keep" in bpy.data.objects and bpy.data.objects["Keep"].hide_get()


def test_vertex_colors_source():
    obj = make_grid()
    attr = obj.data.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    co = np.empty(len(obj.data.vertices) * 3, np.float32)
    obj.data.vertices.foreach_get("co", co)
    x = co.reshape(-1, 3)[:, 0]
    lin = lambda c: [c[0] ** 2.2, c[1] ** 2.2, c[2] ** 2.2, 1]  # približne do lineárneho
    cols = np.array([lin(RED) if xi < 0 else lin(SKIN) for xi in x], np.float32)
    attr.data.foreach_set("color", cols.ravel())
    run(obj, mode="MATERIALS", source="VERTEX")
    assert len(obj.material_slots) == 2
    assert sorted(faces_by_material(obj)) == [N * N // 2, N * N // 2]


def test_material_colors_source():
    obj = make_grid()
    for i, c in enumerate((RED, SKIN)):
        m = bpy.data.materials.new(f"c{i}")
        if bpy.app.version < (5, 0, 0):
            m.use_nodes = True
        bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = [c[0] ** 2.2, c[1] ** 2.2, c[2] ** 2.2, 1]
        obj.data.materials.append(m)
    obj.data.polygons.foreach_set("material_index", [0 if i % 2 else 1 for i in range(N * N)])
    run(obj, mode="MATERIALS", source="MATERIAL")
    assert len(obj.material_slots) == 2


def test_max_colors_limit():
    def many(u, v):
        return [RED, SKIN, BLACK, (0.1, 0.2, 0.9)][min(int(u * 4), 3)]

    obj = make_grid()
    apply_texture(obj, texture(many))
    run(obj, mode="MATERIALS", max_colors=2)
    assert len(obj.material_slots) == 2


def test_error_without_color_data():
    obj = make_grid()  # bez materiálu, textúry aj farieb
    for o in bpy.context.scene.objects:
        o.select_set(o is obj)
    # materiálová farba je vždy k dispozícii (predvolená sivá), takže delenie prebehne s jednou skupinou
    assert run(obj, mode="MATERIALS") == {"FINISHED"}
    assert len(obj.material_slots) == 1


def test_obj_mtl_roundtrip_like_tripo(tmp_path):
    """Export OBJ+MTL+PNG a znovu import, ako by to prišlo z Tripo."""
    obj = make_grid("Tripo")
    img = texture(layout)
    img.filepath_raw = str(tmp_path / "tex.png")
    img.file_format = "PNG"
    img.save()
    apply_texture(obj, img)
    path = tmp_path / "model.obj"
    bpy.ops.wm.obj_export(filepath=str(path), export_materials=True, path_mode="COPY")
    assert (tmp_path / "model.mtl").exists()

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=str(path))
    imported = bpy.context.selected_objects[0]
    assert len(imported.data.polygons) > 0
    run(imported, mode="OBJECTS")
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert len(parts) == 3
    assert sum(len(p.data.polygons) for p in parts) == N * N


def test_noisy_blurred_texture_on_sphere():
    """Guľa s UV švom a pólmi; textúra má šum a rozmazané hrany (ako reálny export)."""
    rng = np.random.default_rng(7)
    size = 256
    v, u = np.mgrid[0:size, 0:size] / size
    img_arr = np.zeros((size, size, 3))
    img_arr[:] = SKIN
    img_arr[(u > 0.1) & (u < 0.4) & (v > 0.3) & (v < 0.7)] = RED   # "vlasy"
    img_arr[(u > 0.55) & (u < 0.62) & (v > 0.45) & (v < 0.55)] = BLACK  # "oko"
    for _ in range(3):  # rozmazanie hrán
        img_arr = (img_arr + np.roll(img_arr, 1, 0) + np.roll(img_arr, -1, 0) + np.roll(img_arr, 1, 1) + np.roll(img_arr, -1, 1)) / 5
    img_arr += rng.normal(0, 0.012, img_arr.shape)
    px = np.ones((size, size, 4), np.float32)
    px[..., :3] = np.clip(img_arr, 0, 1)
    img = bpy.data.images.new("noisy", size, size, alpha=False)
    img.pixels.foreach_set(px.ravel())
    img.update()

    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32)
    obj = bpy.context.active_object
    apply_texture(obj, img)
    faces = len(obj.data.polygons)
    run(obj, mode="OBJECTS")
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert len(parts) == 3, [len(p.data.polygons) for p in parts]
    assert sum(len(p.data.polygons) for p in parts) == faces


# --------------------------------------------------------------------------- spresnenie a vyhladenie hraníc

import bmesh  # noqa: E402

from split_by_color import mesh_colors, refine  # noqa: E402


def border_vertices(obj, labels=None):
    """Súradnice vrcholov na farebnej hranici."""
    if labels is None:
        labels, _ = refine.groups_for(obj, "AUTO", 10.0, 0, 4, True)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    pts = {}
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) == 2 and labels[lf[0].index] != labels[lf[1].index]:
            for v in e.verts:
                pts[v.index] = np.array(v.co)
    bm.free()
    return np.array(list(pts.values()))


def edge_length_sum(pts_obj, labels):
    bm = bmesh.new()
    bm.from_mesh(pts_obj.data)
    bm.faces.ensure_lookup_table()
    total = 0.0
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) == 2 and labels[lf[0].index] != labels[lf[1].index]:
            total += e.calc_length()
    bm.free()
    return total


def open_edges(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    n = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    vol = bm.calc_volume(signed=True)
    bm.free()
    return n, vol


def diagonal(u, v):
    return RED if u + v < 1.0 else SKIN


def test_refine_makes_diagonal_border_follow_the_texture():
    obj = make_grid()
    apply_texture(obj, texture(diagonal, size=256))
    before = border_vertices(obj)
    err_before = np.abs(before[:, 0] + before[:, 1]).max() / np.sqrt(2)
    n0 = len(obj.data.polygons)
    assert bpy.ops.object.split_by_color_refine(levels=3, smooth=0.0) == {"FINISHED"}
    after = border_vertices(obj)
    err_after = np.abs(after[:, 0] + after[:, 1]).max() / np.sqrt(2)
    assert len(obj.data.polygons) > n0
    assert err_after < 0.4 * err_before, (err_before, err_after)


def test_smoothing_shortens_staircase_border_without_gaps():
    obj = make_grid()
    apply_texture(obj, texture(diagonal, size=256))
    labels, _ = refine.groups_for(obj, "AUTO", 10.0, 0, 4, True)
    before = edge_length_sum(obj, labels)
    faces = len(obj.data.polygons)
    assert bpy.ops.object.split_by_color_refine(levels=0, smooth=0.7, smooth_iterations=20) == {"FINISHED"}
    assert len(obj.data.polygons) == faces  # vyhladenie netvorí nové plochy
    labels, _ = refine.groups_for(obj, "AUTO", 10.0, 0, 4, True)
    assert edge_length_sum(obj, labels) < 0.95 * before


def test_closed_sphere_stays_closed_and_keeps_volume_and_split_still_works():
    def hemispheres(u, v):
        return RED if 0.2 < u < 0.6 and 0.25 < v < 0.75 else SKIN

    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24)
    obj = bpy.context.active_object
    apply_texture(obj, texture(hemispheres, size=512))
    open0, vol0 = open_edges(obj)
    assert open0 == 0
    assert bpy.ops.object.split_by_color_refine(levels=2, smooth=0.5, smooth_iterations=15) == {"FINISHED"}
    open1, vol1 = open_edges(obj)
    assert open1 == 0, "po spresnení nesmú vzniknúť diery ani T-spoje"
    assert abs(vol1 - vol0) / vol0 < 0.01, (vol0, vol1)
    faces = len(obj.data.polygons)
    run(obj, mode="OBJECTS")
    parts = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert len(parts) == 2
    assert sum(len(p.data.polygons) for p in parts) == faces


def test_small_closed_region_does_not_shrink_to_nothing():
    def eye(u, v):
        return BLACK if (u - 0.5) ** 2 + (v - 0.5) ** 2 < 0.04**2 else SKIN

    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32)
    obj = bpy.context.active_object
    apply_texture(obj, texture(eye, size=1024))
    bpy.ops.object.split_by_color_refine(levels=2, smooth=0.0)
    labels, _ = refine.groups_for(obj, "AUTO", 10.0, 0, 4, True)
    pts0 = border_vertices(obj, labels)
    extent0 = np.ptp(pts0, axis=0).max()
    bpy.ops.object.split_by_color_refine(levels=0, smooth=0.5, smooth_iterations=30)
    pts1 = border_vertices(obj, labels)
    extent1 = np.ptp(pts1, axis=0).max()
    assert extent1 > 0.85 * extent0, (extent0, extent1)


def test_refine_with_vertex_colors_only_smooths():
    obj = make_grid()
    attr = obj.data.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    co = np.empty(len(obj.data.vertices) * 3, np.float32)
    obj.data.vertices.foreach_get("co", co)
    pts = co.reshape(-1, 3)
    cols = np.array([[0.6, 0.0, 0.0, 1] if p[0] + p[1] < 0 else [0.8, 0.5, 0.3, 1] for p in pts], np.float32)
    attr.data.foreach_set("color", cols.ravel())
    faces = len(obj.data.polygons)
    assert bpy.ops.object.split_by_color_refine(levels=2, smooth=0.5, source="VERTEX") == {"FINISHED"}
    assert len(obj.data.polygons) == faces
