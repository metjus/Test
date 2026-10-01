import { useLiveQuery } from 'dexie-react-hooks'
import { useEffect, useMemo, useState } from 'react'
import { AddDialog } from './AddDialog'
import { DetailDialog } from './DetailDialog'
import { db, requestPersistentStorage } from './db'
import { statusOf, type Urgency } from './extract'
import { buildIndex, search } from './search'
import { CATEGORIES, type Doc } from './types'

const ORDER: Record<Urgency, number> = { expired: 0, urgent: 1, soon: 2, ok: 3, none: 4 }
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('sk-SK') : '—')

function Card({ doc, onOpen }: { doc: Doc; onOpen: () => void }) {
  const st = statusOf(doc.validUntil, doc.noticeDays)
  return (
    <button className={`card ${st.urgency}`} onClick={onOpen}>
      <div className="card-top">
        <strong>{doc.title}</strong>
        <span className={`badge ${st.urgency}`}>{st.urgency === 'none' ? 'bez dátumu' : st.label}</span>
      </div>
      <div className="meta">
        {doc.category} · {doc.type}
        {doc.counterparty && ` · ${doc.counterparty}`}
      </div>
      {doc.description && <div className="desc">{doc.description}</div>}
      <div className="meta">Platné do: {fmt(doc.validUntil)}{st.noticeBy && ` · výpoveď najneskôr ${fmt(st.noticeBy)}`}</div>
    </button>
  )
}

export default function App() {
  const docs = useLiveQuery(() => db.docs.toArray(), [])
  const [q, setQ] = useState('')
  const [cat, setCat] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const [persisted, setPersisted] = useState<boolean | null>(null)

  useEffect(() => {
    requestPersistentStorage().then(setPersisted)
  }, [])

  const index = useMemo(() => buildIndex(docs ?? []), [docs])
  const warn = useMemo(
    () =>
      (docs ?? [])
        .map((d) => ({ d, st: statusOf(d.validUntil, d.noticeDays) }))
        .filter((x) => ['expired', 'urgent', 'soon'].includes(x.st.urgency))
        .sort((a, b) => ORDER[a.st.urgency] - ORDER[b.st.urgency] || (a.st.daysLeft ?? 0) - (b.st.daysLeft ?? 0)),
    [docs],
  )

  const list = useMemo(() => {
    const found = search(index, docs ?? [], q)
    const filtered = cat ? found.filter((d) => d.category === cat) : found
    if (q.trim()) return filtered // zachová poradie podľa relevancie
    return [...filtered].sort(
      (a, b) => ORDER[statusOf(a.validUntil, a.noticeDays).urgency] - ORDER[statusOf(b.validUntil, b.noticeDays).urgency] || b.updatedAt - a.updatedAt,
    )
  }, [index, docs, q, cat])

  return (
    <div className="app">
      <header className="top">
        <h1>Dokumenty</h1>
        <button className="primary" onClick={() => setAdding(true)}>+ Pridať</button>
      </header>

      {warn.length > 0 && (
        <section className="alert">
          <h2>⚠ Pozor</h2>
          <ul>
            {warn.map(({ d, st }) => (
              <li key={d.id}>
                <button className={`link ${st.urgency}`} onClick={() => setOpen(d.id!)}>
                  <span className={`dot ${st.urgency}`} /> {d.title} <em>{st.label}</em>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <input className="search" type="search" placeholder='Hľadaj, napr. „zmluva k telekomu"' value={q} onChange={(e) => setQ(e.target.value)} />

      <div className="chips">
        <button className={!cat ? 'chip on' : 'chip'} onClick={() => setCat(null)}>Všetko</button>
        {CATEGORIES.map((c) => (
          <button key={c} className={cat === c ? 'chip on' : 'chip'} onClick={() => setCat(cat === c ? null : c)}>{c}</button>
        ))}
      </div>

      {docs && docs.length === 0 ? (
        <div className="empty">
          <p>Zatiaľ tu nič nie je.</p>
          <p className="muted">Klikni na „+ Pridať" a naskenuj alebo nahraj prvú zmluvu. Všetko ostáva len v tomto zariadení.</p>
        </div>
      ) : (
        <div className="list">
          {list.map((d) => (
            <Card key={d.id} doc={d} onOpen={() => setOpen(d.id!)} />
          ))}
          {list.length === 0 && <p className="muted">Nič sa nenašlo.</p>}
        </div>
      )}

      {persisted === false && (
        <p className="foot muted">Prehliadač zatiaľ nezaručuje trvalé úložisko. Rob si zálohy a appku si pridaj na plochu.</p>
      )}

      {adding && <AddDialog onClose={() => setAdding(false)} />}
      {open !== null && <DetailDialog docId={open} onClose={() => setOpen(null)} />}
    </div>
  )
}
