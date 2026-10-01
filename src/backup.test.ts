import 'fake-indexeddb/auto'
import { beforeEach, describe, expect, it } from 'vitest'
import { BackupError, exportBackup, importBackup } from './backup'
import { addDoc, addVersion, db } from './db'
import { emptyDocMeta } from './testutil'

const IT = 1000 // málo iterácií, aby testy bežali rýchlo
const PW = 'tajne-heslo-123'

const bytes = (n: number, seed = 1) => Uint8Array.from({ length: n }, (_, i) => (i * 31 + seed) % 256)
const file = (name: string, data: Uint8Array<ArrayBuffer>, text = 'text') => ({ name, mime: 'application/pdf', blob: new Blob([data]), text })
const read = async (b: Blob) => new Uint8Array(await b.arrayBuffer())
// toEqual na miliónoch prvkov je veľmi pomalé, porovnáme jednoduchým cyklom
const same = (a: Uint8Array, b: Uint8Array) => {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false
  return true
}

beforeEach(async () => {
  await db.docs.clear()
  await db.versions.clear()
})

describe('záloha', () => {
  it('export a import vrátia identické dáta aj veľké súbory (viac blokov)', async () => {
    const big = bytes(9 * 1024 * 1024) // 3 bloky po 4 MiB
    const id = await addDoc({ ...emptyDocMeta(), title: 'Telekom' }, file('a.pdf', big, 'prvý text'))
    await addVersion(id, file('b.pdf', bytes(100, 7), 'druhý text'), { validUntil: '2028-01-01' }, 'Dodatok')

    const backup = await exportBackup(PW, { iterations: IT })
    await db.docs.clear()
    await db.versions.clear()

    const res = await importBackup(backup, PW)
    expect(res).toMatchObject({ docsAdded: 1, versionsAdded: 2 })
    const doc = (await db.docs.get(id))!
    expect(doc.title).toBe('Telekom')
    expect(doc.validUntil).toBe('2028-01-01')
    expect(doc.currentVersion).toBe(2)
    expect(doc.text).toBe('prvý text\ndruhý text')
    const vs = await db.versions.where('docId').equals(id).sortBy('version')
    expect(same(await read(vs[0].blob), big)).toBe(true)
    expect(same(await read(vs[1].blob), bytes(100, 7))).toBe(true)
  })

  it('zlé heslo je odmietnuté', async () => {
    await addDoc(emptyDocMeta(), file('a.pdf', bytes(10)))
    const backup = await exportBackup(PW, { iterations: IT })
    await expect(importBackup(backup, 'iné-heslo-999')).rejects.toBeInstanceOf(BackupError)
  })

  it('krátke heslo je odmietnuté pri exporte', async () => {
    await expect(exportBackup('krátke', { iterations: IT })).rejects.toBeInstanceOf(BackupError)
  })

  it('upravený alebo orezaný súbor je odhalený', async () => {
    await addDoc(emptyDocMeta(), file('a.pdf', bytes(5000)))
    const raw = await read(await exportBackup(PW, { iterations: IT }))

    const flipped = raw.slice()
    flipped[flipped.length - 40] ^= 1
    await expect(importBackup(new Blob([flipped]), PW)).rejects.toBeInstanceOf(BackupError)

    const cut = raw.slice(0, raw.length - 60) // chýba záverečný záznam
    await expect(importBackup(new Blob([cut]), PW)).rejects.toBeInstanceOf(BackupError)

    const hdr = raw.slice()
    hdr[6] ^= 1 // iné iterácie v hlavičke
    await expect(importBackup(new Blob([hdr]), PW)).rejects.toBeInstanceOf(BackupError)
  })

  it('cudzí súbor nie je záloha', async () => {
    await expect(importBackup(new Blob([bytes(200)]), PW)).rejects.toBeInstanceOf(BackupError)
  })

  it('zlúčenie: novšia úprava vyhrá, verzie z oboch zariadení ostanú', async () => {
    const id = await addDoc({ ...emptyDocMeta(), title: 'Pôvodný' }, file('a.pdf', bytes(10), 'A'))
    const backup = await exportBackup(PW, { iterations: IT }) // "telefón"

    // "počítač" medzitým upravil názov a pridal vlastnú verziu
    await db.docs.update(id, { title: 'Novší názov', updatedAt: Date.now() + 5000 })
    await addVersion(id, file('pc.pdf', bytes(20, 3), 'PC'), {}, 'z počítača')

    const res = await importBackup(backup, PW)
    expect(res.docsUpdated).toBe(0) // záloha je staršia, nič neprepíše
    expect((await db.docs.get(id))!.title).toBe('Novší názov')
    expect((await db.docs.get(id))!.currentVersion).toBe(2)
  })

  it('zlúčenie: dve nezávislé "v2" sa prečíslujú a nestratia', async () => {
    const id = await addDoc(emptyDocMeta(), file('a.pdf', bytes(10), 'A'))
    const base = await exportBackup(PW, { iterations: IT })
    await addVersion(id, file('pc.pdf', bytes(20), 'PC'), {}, 'PC')
    const pc = await exportBackup(PW, { iterations: IT })

    // druhé zariadenie: vyjde zo základu a pridá vlastnú v2
    await db.docs.clear()
    await db.versions.clear()
    await importBackup(base, PW)
    await addVersion(id, file('tel.pdf', bytes(30), 'TEL'), {}, 'telefón')
    await importBackup(pc, PW)

    const vs = await db.versions.where('docId').equals(id).sortBy('version')
    expect(vs.map((v) => v.version)).toEqual([1, 2, 3])
    expect((await db.docs.get(id))!.currentVersion).toBe(3)
    expect((await db.docs.get(id))!.text.split('\n').sort()).toEqual(['A', 'PC', 'TEL'])
  })
})
