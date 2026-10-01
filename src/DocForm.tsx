import { CATEGORIES, DOC_TYPES } from './types'
import type { NewDoc } from './db'

export function DocForm({ value, onChange }: { value: NewDoc; onChange: (v: NewDoc) => void }) {
  const set = <K extends keyof NewDoc>(k: K, v: NewDoc[K]) => onChange({ ...value, [k]: v })
  return (
    <div className="form">
      <label>
        Názov
        <input value={value.title} onChange={(e) => set('title', e.target.value)} placeholder="napr. Mobilný paušál" />
      </label>
      <div className="row">
        <label>
          Typ
          <select value={value.type} onChange={(e) => set('type', e.target.value)}>
            {DOC_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label>
          Kategória
          <select value={value.category} onChange={(e) => set('category', e.target.value)}>
            {CATEGORIES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Protistrana
        <input value={value.counterparty} onChange={(e) => set('counterparty', e.target.value)} placeholder="napr. Slovak Telekom" />
      </label>
      <label>
        Popis
        <textarea rows={3} value={value.description} onChange={(e) => set('description', e.target.value)} />
      </label>
      <div className="row">
        <label>
          Podpísané
          <input type="date" value={value.signedAt ?? ''} onChange={(e) => set('signedAt', e.target.value || null)} />
        </label>
        <label>
          Platné / viazané do
          <input type="date" value={value.validUntil ?? ''} onChange={(e) => set('validUntil', e.target.value || null)} />
        </label>
      </div>
      <label>
        Výpovedná lehota (dni)
        <input
          type="number"
          min={0}
          inputMode="numeric"
          value={value.noticeDays ?? ''}
          onChange={(e) => set('noticeDays', e.target.value === '' ? null : Math.max(0, +e.target.value))}
        />
      </label>
    </div>
  )
}

export const emptyDoc = (): NewDoc => ({
  title: '', type: 'Zmluva', category: 'Iné', counterparty: '', description: '', signedAt: null, validUntil: null, noticeDays: null,
})
