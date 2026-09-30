"""Paint-tool tests; need the `bpy` module (pip install bpy), skipped otherwise."""
import os
import sys
import unittest

try:
    import bpy
except ImportError:
    bpy = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@unittest.skipIf(bpy is None, "bpy not installed")
class PaintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import bambu_color_export
        cls.addon = bambu_color_export
        from bambu_color_export import paint
        cls.paint = paint
        bambu_color_export.register()

    @classmethod
    def tearDownClass(cls):
        cls.addon.unregister()

    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16)
        self.obj = bpy.context.object
        for _ in range(3):
            self.paint.add_color(self.obj)
        self.session = self.paint.PaintSession(self.obj)
        self.polys = self.obj.data.polygons

    def painted(self, index):
        return [p for p in self.polys if p.material_index == index]

    def test_add_color_first_is_base(self):
        names = [s.material.name for s in self.obj.material_slots]
        self.assertEqual(names[0], "Base")
        self.assertEqual(self.obj.active_material_index, 2)

    def test_brush_symmetry_and_undo(self):
        face = max(self.polys, key=lambda p: p.center.x + 0.1 * p.center.y)
        signs = self.paint.symmetry_signs(True, False, False)
        self.session.begin_stroke()
        self.session.brush(face.center, face.normal, face.index, 0.25, 1, signs)
        self.session.end_stroke()
        pos = sorted(round(p.center.y, 3) for p in self.painted(1) if p.center.x > 0)
        neg = sorted(round(p.center.y, 3) for p in self.painted(1) if p.center.x < 0)
        self.assertTrue(pos)
        self.assertEqual(pos, neg)
        self.assertTrue(self.session.undo())
        self.assertEqual(self.painted(1), [])

    def test_fill_stops_at_other_colour(self):
        for p in self.polys:
            p.material_index = 1 if abs(p.center.z) < 0.1 else 0
        top = max(self.polys, key=lambda p: p.center.z)
        self.session.fill(top.center, top.normal, top.index, 2, self.paint.symmetry_signs(False, False, False))
        self.assertTrue(all((p.material_index == 2) == (p.center.z > 0.1) for p in self.polys))

    def test_fill_stops_at_sharp_edges(self):
        import math
        # Raise a dome on a grid; its rim meets the flat base at a crease.
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=40, y_subdivisions=40, size=4)
        obj = bpy.context.object
        for v in obj.data.vertices:
            r = math.hypot(v.co.x, v.co.y)
            if r < 0.8:
                v.co.z = 0.4 + 0.3 * math.cos(r / 0.8 * math.pi / 2)
        obj.data.update()
        self.paint.add_color(obj)
        self.paint.add_color(obj)
        session = self.paint.PaintSession(obj)
        polys = obj.data.polygons
        top = max(polys, key=lambda p: p.center.z)
        none = self.paint.symmetry_signs(False, False, False)

        session.fill(top.center, top.normal, top.index, 1, none, True, math.radians(30))
        painted = {p.index for p in polys if p.material_index == 1}
        dome = {p.index for p in polys if math.hypot(p.center.x, p.center.y) < 0.75 and p.center.z > 0.39}
        self.assertEqual(painted, dome)

        session.fill(top.center, top.normal, top.index, 1, none, False, None)
        self.assertTrue(all(p.material_index == 1 for p in polys))

    def test_symmetry_signs(self):
        self.assertEqual(len(self.paint.symmetry_signs(False, False, False)), 1)
        self.assertEqual(len(self.paint.symmetry_signs(True, True, True)), 8)


if __name__ == "__main__":
    unittest.main()
