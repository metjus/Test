import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

# Import writers.py directly; the package __init__ needs bpy.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bambu_color_export"))
import writers  # noqa: E402
from writers import PaletteEntry, paint_color_code  # noqa: E402

NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
M = "{http://schemas.microsoft.com/3dmanufacturing/material/2015/02}"

# Two triangles forming a quad, each a different colour.
VERTS = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
TRIS = [(0, 1, 2), (0, 2, 3)]
PALETTE = [
    PaletteEntry("Body", (1.0, 1.0, 1.0), 1),
    PaletteEntry("Eyes", (0.0, 0.0, 0.0), 2),
    PaletteEntry("Ears", (1.0, 0.75, 0.8), 5),
]


class PaintCodeTest(unittest.TestCase):
    def test_known_codes(self):
        # Values Bambu Studio / PrusaSlicer write for filaments 1..6.
        self.assertEqual(
            [paint_color_code(i) for i in range(0, 7)],
            ["", "4", "8", "0C", "1C", "2C", "3C"])
        self.assertEqual(paint_color_code(16), "DC")

    def test_out_of_range(self):
        with self.assertRaises(ValueError):
            paint_color_code(19)


class ThreeMFTest(unittest.TestCase):
    def test_package(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cat.3mf")
            writers.write_3mf(path, VERTS, TRIS, [0, 2], PALETTE, "cat")
            with zipfile.ZipFile(path) as zf:
                self.assertEqual(
                    sorted(zf.namelist()),
                    ["3D/3dmodel.model", "[Content_Types].xml", "_rels/.rels"])
                root = ET.fromstring(zf.read("3D/3dmodel.model"))

        self.assertEqual(root.get("unit"), "millimeter")
        group = root.find(f"{NS}resources/{M}colorgroup")
        self.assertEqual(group.get("id"), "1")
        self.assertEqual([c.get("color") for c in group.findall(f"{M}color")],
                         ["#FFFFFF", "#000000", "#FFBFCC"])
        obj = root.find(f"{NS}resources/{NS}object")
        self.assertEqual((obj.get("pid"), obj.get("pindex")), ("1", "0"))
        tris = root.findall(f".//{NS}triangle")
        self.assertEqual([t.get("paint_color") for t in tris], ["4", "2C"])
        self.assertEqual([t.get("p1") for t in tris], ["0", "2"])
        self.assertEqual({t.get("pid") for t in tris}, {"1"})
        self.assertEqual(len(root.findall(f".//{NS}vertex")), 4)

    def test_literal_bambu_tag_names(self):
        model = writers.build_3mf_model(VERTS, TRIS, [0, 1], PALETTE)
        self.assertIn('<m:colorgroup id="1">', model)
        self.assertIn('<m:color color="#000000"/>', model)

    def test_default_slot_has_no_paint(self):
        palette = [PaletteEntry("none", (0.8, 0.8, 0.8), 0)]
        model = writers.build_3mf_model(VERTS, TRIS[:1], [0], palette)
        self.assertNotIn("paint_color", model)


class ObjTest(unittest.TestCase):
    def test_obj_mtl(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cat.obj")
            mtl = writers.write_obj(path, VERTS, TRIS, [1, 0], PALETTE[:2], "cat")
            with open(path) as f:
                obj_text = f.read()
            with open(mtl) as f:
                mtl_text = f.read()
        self.assertIn("mtllib cat.mtl", obj_text)
        self.assertIn("usemtl F1_Body\nf 1 3 4", obj_text)
        self.assertIn("usemtl F2_Eyes\nf 1 2 3", obj_text)
        self.assertIn("newmtl F2_Eyes\nKa 0 0 0\nKd 0 0 0", mtl_text)


if __name__ == "__main__":
    unittest.main()
