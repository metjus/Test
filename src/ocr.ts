import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { createWorker, type Worker } from 'tesseract.js'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

export interface Processed {
  name: string
  mime: string
  blob: Blob
  text: string
}

export type Progress = (msg: string) => void

let worker: Promise<Worker> | null = null
// Cesta od umiestnenia skriptu (nie od adresy stránky), aby fungovala aj pod podadresárom
const ROOT = new URL('..', /* @vite-ignore */ import.meta.url).href
const asset = (p: string) => `${ROOT}ocr/${p}`
const IN_ARTIFACT = import.meta.env.VITE_ARTIFACT === '1'

/**
 * Testovacia verzia na claude.ai nesmie servírovať .gz súbory, preto sú jazykové dáta publikované
 * ako base64 text. Malý obalový worker presmeruje ich sťahovanie, zvyšok je rovnaký ako v normálnej appke.
 */
function artifactWorkerUrl() {
  const src = `
    const origFetch = self.fetch.bind(self);
    self.fetch = async (input, init) => {
      const m = String(input).match(/\\/lang\\/(\\w+)\\.traineddata\\.gz$/);
      if (!m) return origFetch(input, init);
      const txt = await (await origFetch(${JSON.stringify(asset('lang/'))} + m[1] + '.b64.txt')).text();
      const bin = atob(txt.trim());
      const data = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) data[i] = bin.charCodeAt(i);
      return new Response(data);
    };
    importScripts(${JSON.stringify(asset('worker.min.js'))});
  `
  return URL.createObjectURL(new Blob([src], { type: 'text/javascript' }))
}

const getWorker = () =>
  (worker ??= createWorker(['slk', 'eng'], 1, {
    workerPath: IN_ARTIFACT ? artifactWorkerUrl() : asset('worker.min.js'),
    workerBlobURL: !IN_ARTIFACT,
    corePath: asset('core'),
    langPath: asset('lang'),
    gzip: true,
  }))

async function ocrCanvas(canvas: HTMLCanvasElement): Promise<string> {
  const w = await getWorker()
  const { data } = await w.recognize(canvas)
  return data.text
}

/** Zmenší fotku (zmluva je čitateľná aj pri 2000 px) a vráti canvas + komprimovaný JPEG. */
async function downscale(file: Blob, maxSide = 2000): Promise<{ canvas: HTMLCanvasElement; blob: Blob }> {
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' })
  const k = Math.min(1, maxSide / Math.max(bmp.width, bmp.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bmp.width * k)
  canvas.height = Math.round(bmp.height * k)
  canvas.getContext('2d')!.drawImage(bmp, 0, 0, canvas.width, canvas.height)
  bmp.close()
  const blob = await new Promise<Blob>((res, rej) => canvas.toBlob((b) => (b ? res(b) : rej(new Error('Kompresia zlyhala'))), 'image/jpeg', 0.85))
  return { canvas, blob }
}

async function readPdfText(file: File, progress: Progress): Promise<string> {
  const pdf = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise
  let all = ''
  for (let i = 1; i <= pdf.numPages; i++) {
    progress(`PDF: strana ${i}/${pdf.numPages}`)
    const page = await pdf.getPage(i)
    const content = await page.getTextContent()
    let text = content.items.map((it) => ('str' in it ? it.str : '')).join(' ')
    // naskenované PDF nemá textovú vrstvu, vtedy ideme cez OCR
    if (text.replace(/\s/g, '').length < 40) {
      progress(`OCR: strana ${i}/${pdf.numPages}`)
      const viewport = page.getViewport({ scale: 2 })
      const canvas = document.createElement('canvas')
      canvas.width = viewport.width
      canvas.height = viewport.height
      await page.render({ canvas, viewport }).promise
      text = await ocrCanvas(canvas)
    }
    all += `${text}\n`
  }
  return all
}

export async function processFile(file: File, progress: Progress): Promise<Processed> {
  if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
    const text = await readPdfText(file, progress)
    return { name: file.name, mime: 'application/pdf', blob: file, text }
  }
  progress('Spracúvam obrázok…')
  const { canvas, blob } = await downscale(file)
  progress('OCR: rozpoznávam text (prvýkrát to chvíľu trvá)…')
  const text = await ocrCanvas(canvas)
  return { name: file.name.replace(/\.\w+$/, '') + '.jpg', mime: 'image/jpeg', blob, text }
}
