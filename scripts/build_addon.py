"""Zabalí addon do ZIP súboru, ktorý sa dá nainštalovať v Blenderi
(Edit > Preferences > Get Extensions > šípka vpravo hore > Install from Disk).

Použitie: python scripts/build_addon.py [smart_cut]
"""
import re
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
name = sys.argv[1] if len(sys.argv) > 1 else "smart_cut"
src = root / "blender_addon" / name
version = re.search(r'^version = "([^"]+)"', (src / "blender_manifest.toml").read_text(), re.M).group(1)
out = root / "dist-addon" / f"{name}-{version}.zip"
out.parent.mkdir(exist_ok=True)

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(src.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
            z.write(f, f.relative_to(src))  # manifest musí byť v koreni archívu
print(out)
