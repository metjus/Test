"""Zabalí addon do ZIP súboru, ktorý sa dá nainštalovať v Blenderi (Edit > Preferences > Get Extensions > Install from Disk)."""
import re
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
src = root / "blender_addon" / "split_by_color"
version = re.search(r'^version = "([^"]+)"', (src / "blender_manifest.toml").read_text(), re.M).group(1)
out = root / "dist-addon" / f"split_by_color-{version}.zip"
out.parent.mkdir(exist_ok=True)

with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(src.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
            z.write(f, f.relative_to(src))  # manifest musí byť v koreni archívu
print(out)
