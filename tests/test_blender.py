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
