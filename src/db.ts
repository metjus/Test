import Dexie, { type Table } from 'dexie'
import type { Doc, DocVersion } from './types'

class ArchiveDB extends Dexie {
  docs!: Table<Doc, string>
  versions!: Table<DocVersion, string>

  constructor() {
    super('dokumenty')
    this.version(1).stores({
      docs: 'id, category, type, validUntil, updatedAt',
      versions: 'id, docId, [docId+version]',
    })
  }
}

export const db = new ArchiveDB()

export type NewDoc = Omit<Doc, 'id' | 'currentVersion' | 'createdAt' | 'updatedAt' | 'text'>
export interface FileInput {
  name: string
  mime: string
  blob: Blob
  text: string
}

/**
 * Prečísluje verzie podľa času pridania (1..n) a z textov verzií zloží vyhľadávací text dokumentu.
 * Potrebné po zlúčení záloh, keď dve zariadenia pridali "v2" nezávisle od seba.
 */
export async function normalizeVersions(docId: string) {
  const vs = (await db.versions.where('docId').equals(docId).toArray()).sort((a, b) => a.addedAt - b.addedAt || a.version - b.version)
  await Promise.all(vs.map((v, i) => (v.version === i + 1 ? undefined : db.versions.update(v.id, { version: i + 1 }))))
  await db.docs.update(docId, { currentVersion: vs.length, text: vs.map((v) => v.text).join('\n') })
}

export async function addDoc(meta: NewDoc, file: FileInput) {
  const now = Date.now()
  const id = crypto.randomUUID()
  await db.transaction('rw', db.docs, db.versions, async () => {
    await db.docs.add({ ...meta, id, text: file.text, currentVersion: 1, createdAt: now, updatedAt: now })
    await db.versions.add({ id: crypto.randomUUID(), docId: id, version: 1, fileName: file.name, mime: file.mime, blob: file.blob, text: file.text, note: 'Prvá verzia', addedAt: now })
  })
  return id
}

/** Tlačidlo "Aktualizovať": nová verzia dokumentu, stará ostáva v histórii. */
export async function addVersion(
  docId: string,
  file: FileInput,
  patch: Partial<Pick<Doc, 'validUntil' | 'signedAt' | 'noticeDays'>>,
  note: string,
) {
  const now = Date.now()
  await db.transaction('rw', db.docs, db.versions, async () => {
    const doc = await db.docs.get(docId)
    if (!doc) throw new Error('Dokument neexistuje')
    await db.versions.add({ id: crypto.randomUUID(), docId, version: doc.currentVersion + 1, fileName: file.name, mime: file.mime, blob: file.blob, text: file.text, note, addedAt: now })
    await db.docs.update(docId, { ...patch, updatedAt: now })
    await normalizeVersions(docId)
  })
}

export async function deleteDoc(docId: string) {
  await db.transaction('rw', db.docs, db.versions, async () => {
    await db.versions.where('docId').equals(docId).delete()
    await db.docs.delete(docId)
  })
}

export async function requestPersistentStorage(): Promise<boolean> {
  try {
    return (await navigator.storage?.persist?.()) ?? false
  } catch {
    return false
  }
}
