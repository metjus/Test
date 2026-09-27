#!/bin/bash
# Builds "Blender Fox Transfer.app" on a Mac.
# Run in Terminal:   bash build_mac.command
set -e
cd "$(dirname "$0")"

# Prefer the python.org Python (it has a modern Tk for the window).
PY=""
for p in /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c "import tkinter, sys; sys.exit(tkinter.TkVersion < 8.6)" 2>/dev/null; then
    PY="$p"; break
  fi
done
if [ -z "$PY" ]; then
  echo "No suitable Python found."
  echo "Install Python from https://www.python.org/downloads/macos/ and run this again."
  exit 1
fi
echo "Using $PY"

"$PY" -m pip install --user --upgrade pyinstaller
"$PY" -m PyInstaller --noconfirm --windowed \
  --name "Blender Fox Transfer" --icon assets/icon.icns \
  --osx-bundle-identifier io.github.blender-fox-transfer \
  blender_fox_transfer.py

cd dist
ditto -c -k --keepParent "Blender Fox Transfer.app" BlenderFoxTransfer-macOS.zip
echo
echo "Done:  $(pwd)/Blender Fox Transfer.app"
echo "       $(pwd)/BlenderFoxTransfer-macOS.zip  (send this one to others)"
open .
