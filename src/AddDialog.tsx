import { useRef, useState } from 'react'
import { DocForm, emptyDoc } from './DocForm'
import { addDoc, type NewDoc } from './db'
import { suggest } from './extract'
import { processFile, type Processed } from './ocr'

export function AddDialog({ onClose }: { onClose: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [file, setFile] = useState<Processed | null>(null)
  const [meta, setMeta] = useState<NewDoc>(emptyDoc())
  const pick = useRef<HTMLInputElement>(null)
  const cam = useRef<HTMLInputElement>(null)

  const onFile = async (f: File | undefined) => {
    if (!f) return
    setError(null)
    try {
      setBusy('Spracúvam…')
      const p = await processFile(f, setBusy)
      const s = suggest(p.text)
      setFile(p)
      setMeta({
        ...emptyDoc(),
        title: s.counterparty ? `${s.type ?? 'Dokument'} – ${s.counterparty}` : f.name.replace(/\.\w+$/, ''),
        type: s.type ?? 'Iné',
        category: s.category ?? 'Iné',
        counterparty: s.counterparty ?? '',
        signedAt: s.signedAt ?? null,
        validUntil: s.validUntil ?? null,
        noticeDays: s.noticeDays ?? null,
      })
    } catch (e) {
      setError(`Spracovanie zlyhalo: ${e instanceof Error ? e.message : e}. Dokument môžeš pridať aj bez rozpoznaného textu.`)
    } finally {
      setBusy(null)
    }
  }

  const save = async () => {
    if (!file) return
    await addDoc({ ...meta, title: meta.title.trim() || file.name }, { name: file.name, mime: file.mime, blob: file.blob, text: file.text })
    onClose()
  }

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>Pridať dokument</h2>
          <button className="ghost" onClick={onClose}>Zavrieť</button>
        </header>

        {!file && (
          <div className="pick">
            <button className="primary" disabled={!!busy} onClick={() => cam.current?.click()}>📷 Odfotiť / naskenovať</button>
            <button disabled={!!busy} onClick={() => pick.current?.click()}>📄 Vybrať PDF alebo obrázok</button>
            <input ref={cam} hidden type="file" accept="image/*" capture="environment" onChange={(e) => onFile(e.target.files?.[0])} />
            <input ref={pick} hidden type="file" accept="application/pdf,image/*" onChange={(e) => onFile(e.target.files?.[0])} />
            {busy && <p className="muted">{busy}</p>}
            {error && <p className="error">{error}</p>}
          </div>
        )}

        {file && (
          <>
            <p className="muted">Údaje sú len návrh z rozpoznaného textu. Skontroluj ich pred uložením.</p>
            <DocForm value={meta} onChange={setMeta} />
            <details>
              <summary>Rozpoznaný text ({file.text.trim().length} znakov)</summary>
              <pre className="ocr">{file.text.trim() || '(nič sa nerozpoznalo)'}</pre>
            </details>
            <div className="actions">
              <button className="ghost" onClick={() => setFile(null)}>Zrušiť</button>
              <button className="primary" onClick={save}>Uložiť</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
