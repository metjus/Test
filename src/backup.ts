import { db, normalizeVersions } from './db'
import type { Doc, DocVersion } from './types'

/**
 * Formát zálohy .dokbackup (všetko šifrované AES-GCM, kľúč z hesla cez PBKDF2):
 *   hlavička: "DOKB" | verzia(1) | iterácie(u32) | soľ(16)
 *   záznamy:  [dĺžka u32][iv 12 B][šifrovaný obsah]  ...
 * Záznam 0 je manifest (JSON), potom bloky súborov po CHUNK bajtov a na konci záznam "koniec".
 * Hlavička, poradie aj druh záznamu sú autentifikované (AAD), takže orezanie alebo prehodenie
 * častí súboru sa pri importe odhalí.
 */
const MAGIC = [0x44, 0x4f, 0x4b, 0x42] // "DOKB"
const FORMAT = 1
const HEADER_LEN = 4 + 1 + 4 + 16
const CHUNK = 4 * 1024 * 1024
export const DEFAULT_ITERATIONS = 600_000
export const MIN_PASSWORD = 8

const enum Kind {
  Manifest = 0,
  Data = 1,
  End = 2,
}

type VersionMeta = Omit<DocVersion, 'blob'> & { size: number }
interface Manifest {
  format: number
  exportedAt: number
  docs: Doc[]
  versions: VersionMeta[]
}

export class BackupError extends Error {}

const u32 = (n: number) => {
  const b = new Uint8Array(4)
  new DataView(b.buffer).setUint32(0, n)
  return b
}

async function deriveKey(password: string, salt: Uint8Array<ArrayBuffer>, iterations: number) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey'])
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
}

const aad = (header: Uint8Array, seq: number, kind: Kind) => {
  const out = new Uint8Array(header.length + 5)
  out.set(header)
  out.set(u32(seq), header.length)
  out[header.length + 4] = kind
  return out
}

async function seal(key: CryptoKey, header: Uint8Array, seq: number, kind: Kind, data: Uint8Array<ArrayBuffer>) {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: aad(header, seq, kind) }, key, data))
  return [u32(12 + ct.length), iv, ct]
}

export interface ExportOptions {
  iterations?: number
  onProgress?: (done: number, total: number) => void
}

export async function exportBackup(password: string, opts: ExportOptions = {}): Promise<Blob> {
  if (password.length < MIN_PASSWORD) throw new BackupError(`Heslo musí mať aspoň ${MIN_PASSWORD} znakov.`)
  const iterations = opts.iterations ?? DEFAULT_ITERATIONS
  const [docs, versions] = await Promise.all([db.docs.toArray(), db.versions.toArray()])
  versions.sort((a, b) => a.docId.localeCompare(b.docId) || a.version - b.version)

  const salt = crypto.getRandomValues(new Uint8Array(16))
  const header = new Uint8Array(HEADER_LEN)
  header.set(MAGIC)
  header[4] = FORMAT
  header.set(u32(iterations), 5)
  header.set(salt, 9)
  const key = await deriveKey(password, salt, iterations)

  const manifest: Manifest = {
    format: FORMAT,
    exportedAt: Date.now(),
    docs,
    versions: versions.map(({ blob, ...rest }) => ({ ...rest, size: blob.size })),
  }
  const parts: BlobPart[] = [header]
  let seq = 0
  parts.push(...(await seal(key, header, seq++, Kind.Manifest, new TextEncoder().encode(JSON.stringify(manifest)))))

  for (const [i, v] of versions.entries()) {
    for (let off = 0; off < v.blob.size; off += CHUNK) {
      const chunk = new Uint8Array(await v.blob.slice(off, off + CHUNK).arrayBuffer())
      parts.push(...(await seal(key, header, seq++, Kind.Data, chunk)))
    }
    opts.onProgress?.(i + 1, versions.length)
  }
  parts.push(...(await seal(key, header, seq, Kind.End, new Uint8Array(0))))
  return new Blob(parts, { type: 'application/octet-stream' })
}

export interface ImportResult {
  docsAdded: number
  docsUpdated: number
  versionsAdded: number
  exportedAt: number
}

export async function importBackup(file: Blob, password: string): Promise<ImportResult> {
  const bad = new BackupError('Nesprávne heslo alebo poškodený súbor zálohy.')
  if (file.size < HEADER_LEN) throw new BackupError('Toto nie je súbor zálohy.')
  const header = new Uint8Array(await file.slice(0, HEADER_LEN).arrayBuffer())
  if (!MAGIC.every((b, i) => header[i] === b)) throw new BackupError('Toto nie je súbor zálohy.')
  if (header[4] !== FORMAT) throw new BackupError('Záloha je z novšej verzie appky. Aktualizuj appku.')
  const iterations = new DataView(header.buffer).getUint32(5)
  if (iterations < 1 || iterations > 10_000_000) throw bad
  const key = await deriveKey(password, header.slice(9, 25), iterations)

  let offset = HEADER_LEN
  let seq = 0
  const open = async (expected: Kind): Promise<Uint8Array> => {
    if (offset + 4 > file.size) throw bad
    const len = new DataView(await file.slice(offset, offset + 4).arrayBuffer()).getUint32(0)
    if (len < 12 + 16 || offset + 4 + len > file.size) throw bad
    const rec = new Uint8Array(await file.slice(offset + 4, offset + 4 + len).arrayBuffer())
    offset += 4 + len
    try {
      return new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv: rec.slice(0, 12), additionalData: aad(header, seq++, expected) }, key, rec.slice(12)))
    } catch {
      throw bad
    }
  }

  const manifest = JSON.parse(new TextDecoder().decode(await open(Kind.Manifest))) as Manifest
  if (manifest.format !== FORMAT || !Array.isArray(manifest.docs) || !Array.isArray(manifest.versions)) throw bad

  const blobs = new Map<string, Blob>()
  for (const v of manifest.versions) {
    const parts: BlobPart[] = []
    let got = 0
    while (got < v.size) {
      const chunk = await open(Kind.Data)
      got += chunk.length
      parts.push(chunk as Uint8Array<ArrayBuffer>)
    }
    if (got !== v.size) throw bad
    blobs.set(v.id, new Blob(parts, { type: v.mime }))
  }
  await open(Kind.End) // overí, že súbor nebol orezaný

  const result: ImportResult = { docsAdded: 0, docsUpdated: 0, versionsAdded: 0, exportedAt: manifest.exportedAt }
  await db.transaction('rw', db.docs, db.versions, async () => {
    const touched = new Set<string>()
    for (const d of manifest.docs) {
      const cur = await db.docs.get(d.id)
      if (!cur) {
        await db.docs.put(d)
        result.docsAdded++
        touched.add(d.id)
      } else if (d.updatedAt > cur.updatedAt) {
        await db.docs.put(d) // novšia úprava vyhráva
        result.docsUpdated++
        touched.add(d.id)
      }
    }
    for (const { size: _size, ...v } of manifest.versions) {
      if (await db.versions.get(v.id)) continue
      if (!(await db.docs.get(v.docId))) continue
      await db.versions.add({ ...v, blob: blobs.get(v.id)! })
      result.versionsAdded++
      touched.add(v.docId)
    }
    for (const id of touched) await normalizeVersions(id)
  })
  return result
}

const KEY = 'dokumenty.lastBackup'
export const lastBackupAt = (): number | null => {
  try {
    return Number(localStorage.getItem(KEY)) || null
  } catch {
    return null
  }
}
export const markBackup = () => {
  try {
    localStorage.setItem(KEY, String(Date.now()))
  } catch {
    /* súkromný režim: bez pripomienky */
  }
}
