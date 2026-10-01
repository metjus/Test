#!/usr/bin/env bash
# Pripraví adresár pre publikovanie testovacej verzie na claude.ai: ./scripts/stage-artifact.sh <cieľový adresár>
set -euo pipefail
OUT="$1"
node scripts/copy-ocr.mjs
VITE_ARTIFACT=1 npx vite build --outDir dist-artifact --emptyOutDir >/dev/null
rm -rf "$OUT" && mkdir -p "$OUT/assets" "$OUT/ocr/core" "$OUT/ocr/lang"
cp dist-artifact/assets/* "$OUT/assets/"
cp dist-artifact/icon.svg dist-artifact/apple-touch-icon.png "$OUT/"
cp dist-artifact/ocr/worker.min.js "$OUT/ocr/"
cp dist-artifact/ocr/core/*.wasm.js "$OUT/ocr/core/"
for l in slk eng; do base64 -w0 "dist-artifact/ocr/lang/$l.traineddata.gz" > "$OUT/ocr/lang/$l.b64.txt"; done
# artifact nepovolí surový ESC bajt v textových súboroch
python3 - "$OUT" <<'PY'
import glob, sys
for f in glob.glob(sys.argv[1] + '/assets/*.mjs'):
    s = open(f, 'rb').read().replace(b'\x1b', b'\\x1b')
    open(f, 'wb').write(s)
PY
JS=$(basename "$(ls "$OUT"/assets/index-*.js)"); CSS=$(basename "$(ls "$OUT"/assets/index-*.css)")
cat > "$OUT/index.html" <<HTML
<title>Dokumenty</title>
<meta name="description" content="Súkromný lokálny archív dokumentov a zmlúv">
<link rel="stylesheet" href="assets/$CSS">
<div id="root"></div>
<script type="module" src="assets/$JS"></script>
HTML
find "$OUT" -type f | sed "s#$OUT/##" | sort
