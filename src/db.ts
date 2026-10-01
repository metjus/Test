import Dexie, { type Table } from 'dexie'
import type { Doc, DocVersion } from './types'

class ArchiveDB extends Dexie {
  docs!: Table<Doc, number>
  versions!: Table<DocVersion, number>

  constructor() {
    super('dokumenty')
    this.version(1).stores({
      docs: '++id, category, type, validUntil, updatedAt',
      versions: '++id, docId, [docId+version]',
    })
  }
}

export const db = new ArchiveDB()

export type NewDoc = Omit<Doc, 'id' | 'currentVersion' | 'createdAt' | 'updatedAt' | 'text'>

export async function addDoc(meta: NewDoc, file: { name: string; mime: string; blob: Blob; text: string }) {
  const now = Date.now()
  return db.transaction('rw', db.docs, db.versions, async () => {
    const id = await db.docs.add({ ...meta, text: file.text, currentVersion: 1, createdAt: now, updatedAt: now })
    await db.versions.add({ docId: id, version: 1, fileName: file.name, mime: file.mime, blob: file.blob, note: 'Prvá verzia', addedAt: now })
    return id
  })
}

/** Tlačidlo "Aktualizovať": nová verzia dokumentu, stará ostáva v histórii. */
export async function addVersion(
  docId: number,
  file: { name: string; mime: string; blob: Blob; text: string },
  patch: Partial<Pick<Doc, 'validUntil' | 'signedAt' | 'noticeDays'>>,
  note: string,
) {
  const now = Date.now()
  await db.transaction('rw', db.docs, db.versions, async () => {
    const doc = await db.docs.get(docId)
    if (!doc) throw new Error('Dokument neexistuje')
    const version = doc.currentVersion + 1
    await db.versions.add({ docId, version, fileName: file.name, mime: file.mime, blob: file.blob, note, addedAt: now })
    await db.docs.update(docId, { ...patch, currentVersion: version, text: `${doc.text}\n${file.text}`, updatedAt: now })
  })
}

export async function deleteDoc(docId: number) {
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
