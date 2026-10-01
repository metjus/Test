import { useRef, useState } from 'react'
import { BackupError, exportBackup, importBackup, markBackup, MIN_PASSWORD } from './backup'

// Testovacia verzia v claude.ai Artifact: prehliadač tam blokuje ukladanie súborov zo stránky
const NO_DOWNLOAD = import.meta.env.VITE_ARTIFACT === '1'

const stamp = () => new Date().toISOString().slice(0, 10)

async function saveFile(blob: Blob, name: string) {
  const file = new File([blob], name, { type: 'application/octet-stream' })
  // iPhone: ponúkne "Uložiť do Súborov" / AirDrop; inde klasické sťahovanie
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: 'Záloha dokumentov' })
      return true
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return false
    }
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
  return true
}

export function BackupDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const pick = useRef<HTMLInputElement>(null)

  const run = async (label: string, job: () => Promise<string | null>) => {
    setMsg(null)
    setBusy(label)
    try {
      const text = await job()
      if (text) setMsg({ ok: true, text })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof BackupError ? e.message : `Zlyhalo: ${e instanceof Error ? e.message : e}` })
    } finally {
      setBusy(null)
    }
  }

  const doExport = () =>
    run('Šifrujem a pripravujem zálohu…', async () => {
      if (pw !== pw2) throw new BackupError('Heslá sa nezhodujú.')
      const blob = await exportBackup(pw)
      const saved = await saveFile(blob, `dokumenty-${stamp()}.dokbackup`)
      if (!saved) return null
      markBackup()
      onDone()
      return `Záloha uložená (${blob.size < 1048576 ? `${Math.ceil(blob.size / 1024)} kB` : `${(blob.size / 1048576).toFixed(1)} MB`}). Heslo si zapamätaj, bez neho sa nedá obnoviť.`
    })

  const doImport = (f: File | undefined) =>
    f &&
    run('Dešifrujem a obnovujem…', async () => {
      const r = await importBackup(f, pw)
      onDone()
      return `Hotovo: nových dokumentov ${r.docsAdded}, aktualizovaných ${r.docsUpdated}, pridaných verzií ${r.versionsAdded}.`
    })

  const weak = pw.length > 0 && pw.length < MIN_PASSWORD

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>Zálohy</h2>
          <button className="ghost" onClick={onClose}>Zavrieť</button>
        </header>
        <p className="muted">
          Záloha je jeden šifrovaný súbor so všetkými dokumentmi a verziami. Bez hesla ho nikto neprečíta, ani ja. Heslo sa nedá
          obnoviť, tak si ho bezpečne uschovaj.
        </p>

        {NO_DOWNLOAD && (
          <p className="error">
            Testovacia verzia: ukladanie súborov je tu zablokované, takže záloha sa vytvoriť nedá. Obnova zo súboru funguje. Export
            bude fungovať v nasadenej appke.
          </p>
        )}
        <div className="form">
          <label>
            Heslo zálohy
            <input type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} />
          </label>
          {weak && <span className="error">Aspoň {MIN_PASSWORD} znakov.</span>}
          <label>
            Heslo znova (len pri vytváraní)
            <input type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
          </label>
        </div>

        <div className="actions">
          <button disabled={!!busy || !pw} onClick={() => pick.current?.click()}>⬆ Obnoviť zo zálohy</button>
          <button className="primary" disabled={NO_DOWNLOAD || !!busy || pw.length < MIN_PASSWORD} onClick={doExport}>⬇ Vytvoriť zálohu</button>
          <input ref={pick} hidden type="file" onChange={(e) => { doImport(e.target.files?.[0]); e.target.value = '' }} />
        </div>

        {busy && <p className="muted">{busy}</p>}
        {msg && <p className={msg.ok ? '' : 'error'}>{msg.text}</p>}
        <p className="muted">Obnova nič nemaže: pridá chýbajúce dokumenty a verzie, a pri rovnakom dokumente nechá novšiu úpravu.</p>
      </div>
    </div>
  )
}
