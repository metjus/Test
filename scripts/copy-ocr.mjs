// Skopíruje OCR engine a slovenské/anglické jazykové dáta do public/ocr,
// aby appka nezávisela od žiadnej cudzej CDN a fungovala offline.
import { cpSync, mkdirSync, readdirSync, rmSync } from 'node:fs'

const out = 'public/ocr'
rmSync(out, { recursive: true, force: true })
mkdirSync(`${out}/core`, { recursive: true })
mkdirSync(`${out}/lang`, { recursive: true })

cpSync('node_modules/tesseract.js/dist/worker.min.js', `${out}/worker.min.js`)
for (const f of readdirSync('node_modules/tesseract.js-core')) {
  if (f.includes('lstm')) cpSync(`node_modules/tesseract.js-core/${f}`, `${out}/core/${f}`)
}
for (const l of ['slk', 'eng']) {
  cpSync(`node_modules/@tesseract.js-data/${l}/4.0.0_best_int/${l}.traineddata.gz`, `${out}/lang/${l}.traineddata.gz`)
}
console.log('OCR súbory skopírované do', out)
