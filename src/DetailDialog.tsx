import { useLiveQuery } from 'dexie-react-hooks'
import { useEffect, useRef, useState } from 'react'
import { DocForm } from './DocForm'
import { addVersion, db, deleteDoc, type NewDoc } from './db'
import { suggest } from './extract'
import { processFile } from './ocr'

export function DetailDialog({ docId, onClose }: { docId: string; onClose: () => void }) {
  const doc = useLiveQuery(() => db.docs.get(docId), [docId])
  const versions = useLiveQuery(() => db.versions.where('docId').equals(docId).reverse().sortBy('version'), [docId])
  const [draft, setDraft] = useState<NewDoc | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [pick, setPick] = useState(0) // zobrazená verzia
  const [note, setNote] = useState('Dodatok / predĺženie')
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const upd = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (doc && !draft) {
      const { id: _i, text: _t, currentVersion: _c, createdAt: _a, updatedAt: _u, ...meta } = doc
      setDraft(meta)
    }
  }, [doc, draft])

  const shown = versions?.find((v) => v.version === (pick || doc?.currentVersion))
  useEffect(() => {
    if (!shown) return
    const u = URL.createObjectURL(shown.blob)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [shown?.id]) // eslint-disable-line

  if (!doc || !draft) return null

  const save = async () => {
    await db.docs.update(docId, { ...draft, updatedAt: Date.now() })
    onClose()
  }

  const update = async (f: File | undefined) => {
    if (!f) return
    try {
      setError(null)
      setBusy('Spracúvam…')
      const p = await processFile(f, setBusy)
      const s = suggest(p.text)
      const nextUntil = s.validUntil ?? null
      await addVersion(
        docId,
        { name: p.name, mime: p.mime, blob: p.blob, text: p.text },
        { ...(nextUntil ? { validUntil: nextUntil } : {}), ...(s.noticeDays ? { noticeDays: s.noticeDays } : {}) },
        note,
      )
      setDraft(null) // znova načíta nové údaje
      setPick(0)
    } catch (e) {
      setError(`Aktualizácia zlyhala: ${e instanceof Error ? e.message : e}`)
    } finally {
      setBusy(null)
    }
  }

  const remove = async () => {
    await deleteDoc(docId)
    onClose()
  }

  const download = () => {
    if (!shown || !url) return
    const a = document.createElement('a')
    a.href = url
    a.download = shown.fileName
    a.click()
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>{doc.title}</h2>
          <button className="ghost" onClick={onClose}>Zavrieť</button>
        </header>

        {url && shown && (
          <div className="preview">
            {shown.mime === 'application/pdf' ? <iframe src={url} title="Náhľad" /> : <img src={url} alt={shown.fileName} />}
          </div>
        )}
        <label className="note">
          Poznámka k novej verzii
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder='napr. „Predĺženie o 24 mesiacov"' />
        </label>
        <div className="actions">
          <button onClick={download}>⬇ Stiahnuť</button>
          <button onClick={() => upd.current?.click()} disabled={!!busy}>🔄 Aktualizovať</button>
          <input ref={upd} hidden type="file" accept="application/pdf,image/*" onChange={(e) => update(e.target.files?.[0])} />
        </div>
        {busy && <p className="muted">{busy}</p>}
        {error && <p className="error">{error}</p>}

        <DocForm value={draft} onChange={setDraft} />

        <h3>História verzií</h3>
        <ul className="versions">
          {versions?.map((v) => (
            <li key={v.id} className={v.version === (pick || doc.currentVersion) ? 'on' : ''}>
              <button className="link" onClick={() => setPick(v.version)}>
                v{v.version} · {new Date(v.addedAt).toLocaleDateString('sk-SK')} · {v.note || v.fileName}
              </button>
            </li>
          ))}
        </ul>

        <div className="actions">
          {confirmDelete ? (
            <>
              <span className="muted">Zmaže aj všetky verzie, nedá sa vrátiť.</span>
              <button className="ghost" onClick={() => setConfirmDelete(false)}>Nie</button>
              <button className="danger" onClick={remove}>Áno, zmazať</button>
            </>
          ) : (
            <button className="danger" onClick={() => setConfirmDelete(true)}>Zmazať</button>
          )}
          <button className="primary" onClick={save}>Uložiť zmeny</button>
        </div>
      </div>
    </div>
  )
}
