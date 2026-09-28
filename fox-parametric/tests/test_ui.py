"""Runs every panel's draw() against a fake layout that checks each property
and operator the UI refers to really exists."""
import os
import sys

import bpy  # noqa: F401  (must be first with the PyPI bpy module)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fox_parametric  # noqa: E402
from fox_parametric import core, ui  # noqa: E402

errors = []


class FakeLayout:
    def __init__(self):
        self.use_property_split = self.use_property_decorate = False
        self.active = self.alert = True
        self.scale_y = 1.0

    def _child(self, *a, **k):
        return FakeLayout()
    row = column = box = split = _child

    def label(self, **k): pass
    def separator(self, **k): pass

    def prop(self, data, name, **k):
        if name not in data.bl_rna.properties:
            errors.append("missing property %s.%s" % (type(data).__name__, name))
        ptype = data.bl_rna.properties.get(name)
        if k.get("expand") and ptype is not None and ptype.type != "ENUM":
            errors.append("expand on non-enum %s" % name)

    def operator(self, idname, **k):
        mod, op = idname.split(".")
        if not hasattr(getattr(bpy.ops, mod), op):
            errors.append("missing operator " + idname)
        class Props:  # accept any attribute assignment, but check it exists
            def __setattr__(s, key, value):
                rna = getattr(getattr(bpy.ops, mod), op).get_rna_type()
                if key not in rna.properties:
                    errors.append("operator %s has no property %s" % (idname, key))
        return Props()

    def menu(self, idname, **k):
        if not hasattr(bpy.types, idname):
            errors.append("missing menu " + idname)

    def template_list(self, listtype, _id, data, prop, active_data, active_prop, **k):
        if not hasattr(bpy.types, listtype):
            errors.append("missing UIList " + listtype)
        for d, p in ((data, prop), (active_data, active_prop)):
            if p not in d.bl_rna.properties:
                errors.append("template_list: missing %s" % p)


class Ctx:
    def __init__(self, obj, mode="OBJECT"):
        self.active_object, self.mode = obj, mode


class FakeSelf:
    """Stands in for a Panel/Menu/UIList instance (those can't be created directly)."""
    def __init__(self, cls):
        self.layout, self.cls = FakeLayout(), cls

    def __getattr__(self, name):
        return getattr(self.cls, name)


def draw(panel_cls, ctx):
    if hasattr(panel_cls, "poll") and not panel_cls.poll(ctx):
        return
    me = FakeSelf(panel_cls)
    if hasattr(panel_cls, "draw_header"):
        panel_cls.draw_header(me, ctx)
    panel_cls.draw(me, ctx)


bpy.ops.wm.read_factory_settings(use_empty=True)
fox_parametric.register()

draw(ui.FOX_PT_main, Ctx(None))
bpy.ops.fox.new_part(kind="BOX")
obj = bpy.context.active_object
for t in ("EXTRUDE", "REVOLVE", "HOLE", "FILLET", "CHAMFER", "MIRROR"):
    bpy.ops.fox.add_feature(type=t)
part = obj.fox_part
for i in range(len(part.features)):
    part.active_index = i
    f = part.features[i]
    for profile in ("RECT", "CIRCLE", "POLYGON", "SLOT"):
        for pattern in ("NONE", "LINEAR", "CIRCULAR"):
            with core.batch():
                f.profile, f.pattern = profile, pattern
            for mode in ("OBJECT", "EDIT_MESH"):
                draw(ui.FOX_PT_main, Ctx(obj, mode))
                draw(ui.FOX_PT_feature, Ctx(obj, mode))
part.rollback = 2
draw(ui.FOX_PT_main, Ctx(obj))
bpy.ops.fox.base_to_mesh()
part.active_index = 0
draw(ui.FOX_PT_feature, Ctx(obj))
# list rows
for i, f in enumerate(part.features):
    ui.FOX_UL_features.draw_item(FakeSelf(ui.FOX_UL_features), None, FakeLayout(), part, f, 0, part,
                                 "active_index", i)
# menus
for m in (ui.FOX_MT_add_feature, ui.FOX_MT_new_part):
    m.draw(FakeSelf(m), None)

errors = sorted(set(errors))
print("\n".join(errors) if errors else "UI OK: every property, operator, menu and list exists")
fox_parametric.unregister()
sys.exit(1 if errors else 0)
