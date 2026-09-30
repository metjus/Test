"""Pure-Python file writers (no bpy), so they can be tested outside Blender.

Geometry is passed as one merged triangle mesh:
    vertices:  list of (x, y, z) floats, already in millimetres
    triangles: list of (i0, i1, i2) vertex indices
    tri_color: list of palette indices, one per triangle
    palette:   list of PaletteEntry
"""

import os
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

MAX_FILAMENTS = 16


@dataclass
class PaletteEntry:
    name: str
    rgb: tuple  # sRGB, 0..1
    filament: int  # 1-based filament/extruder slot, 0 = object default
    materials: list = field(default_factory=list)

    @property
    def hex(self):
        return "#" + "".join("%02X" % round(max(0.0, min(1.0, c)) * 255) for c in self.rgb)


def paint_color_code(filament):
    """Encode a filament slot as a Bambu/Prusa per-triangle paint string.

    This is the serialized TriangleSelector state of an unsplit triangle:
    states 1-2 fit in a single nibble (state << 2), higher states use the
    escape nibble 0xC followed by (state - 3); the nibbles are written in
    reverse order as hex. 1 -> "4", 2 -> "8", 3 -> "0C", 4 -> "1C", ...
    """
    if filament <= 0:
        return ""
    if filament < 3:
        return "%X" % (filament << 2)
    if filament - 3 > 0xF:
        raise ValueError("filament slot %d is out of range" % filament)
    return "%XC" % (filament - 3)


def _fmt(v):
    s = "%.6f" % v
    s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""

_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def build_3mf_model(vertices, triangles, tri_color, palette, object_name="Model"):
    """Return the 3D/3dmodel.model XML as a string.

    Colours are stored twice:
    - a standard 3MF colour group (``m:colorgroup``) with a colour per
      triangle. Bambu Studio reads this for 3MFs from other programs and
      opens its colour-mapping dialog, adding filaments as needed;
    - Bambu's per-triangle ``paint_color`` filament codes, used if that
      dialog is cancelled or unavailable.
    """
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>\n',
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">\n',
        ' <metadata name="Application">Blender Bambu Color Export</metadata>\n',
        " <resources>\n",
        # Bambu matches the literal tag names "m:colorgroup" / "m:color".
        '  <m:colorgroup id="1">\n',
    ]
    for entry in palette:
        out.append('   <m:color color="%s"/>\n' % entry.hex)
    out.append("  </m:colorgroup>\n")
    out.append('  <object id="2" type="model" name=%s pid="1" pindex="0">\n' % quoteattr(object_name))
    out.append("   <mesh>\n    <vertices>\n")
    for x, y, z in vertices:
        out.append('     <vertex x="%s" y="%s" z="%s"/>\n' % (_fmt(x), _fmt(y), _fmt(z)))
    out.append("    </vertices>\n    <triangles>\n")
    codes = [paint_color_code(e.filament) for e in palette]
    for (a, b, c), ci in zip(triangles, tri_color):
        paint = ' paint_color="%s"' % codes[ci] if codes[ci] else ""
        out.append('     <triangle v1="%d" v2="%d" v3="%d" pid="1" p1="%d"%s/>\n' % (a, b, c, ci, paint))
    out.append("    </triangles>\n   </mesh>\n  </object>\n")
    out.append(' </resources>\n <build>\n  <item objectid="2"/>\n </build>\n</model>\n')
    return "".join(out)


def write_3mf(path, vertices, triangles, tri_color, palette, object_name="Model"):
    model = build_3mf_model(vertices, triangles, tri_color, palette, object_name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", model)


def _mtl_name(entry, index):
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in entry.name)
    return "F%d_%s" % (entry.filament or 0, safe or "color%d" % index)


def write_obj(path, vertices, triangles, tri_color, palette, object_name="Model"):
    """Write an OBJ + MTL pair; Bambu Studio's colour-mapping dialog reads the Kd colours."""
    mtl_path = os.path.splitext(path)[0] + ".mtl"
    names = [_mtl_name(e, i) for i, e in enumerate(palette)]

    with open(mtl_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Blender Bambu Color Export\n")
        for entry, name in zip(palette, names):
            r, g, b = entry.rgb
            f.write("\nnewmtl %s\nKa 0 0 0\nKd %s %s %s\nKs 0 0 0\nd 1\nillum 1\n"
                    % (name, _fmt(r), _fmt(g), _fmt(b)))

    order = sorted(range(len(triangles)), key=lambda t: tri_color[t])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Blender Bambu Color Export\n")
        f.write("mtllib %s\n" % os.path.basename(mtl_path))
        f.write("o %s\n" % escape(object_name).replace(" ", "_"))
        for x, y, z in vertices:
            f.write("v %s %s %s\n" % (_fmt(x), _fmt(y), _fmt(z)))
        current = None
        for t in order:
            ci = tri_color[t]
            if ci != current:
                f.write("usemtl %s\n" % names[ci])
                current = ci
            a, b, c = triangles[t]
            f.write("f %d %d %d\n" % (a + 1, b + 1, c + 1))
    return mtl_path
