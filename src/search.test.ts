import { describe, expect, it } from 'vitest'
import { buildIndex, search } from './search'
import type { Doc } from './types'

const mk = (id: number, o: Partial<Doc>): Doc => ({
  id, title: '', type: 'Zmluva', category: 'Iné', counterparty: '', description: '', signedAt: null,
  validUntil: null, noticeDays: null, text: '', currentVersion: 1, createdAt: 0, updatedAt: 0, ...o,
})

const docs = [
  mk(1, { title: 'Mobilný paušál', counterparty: 'Slovak Telekom', category: 'Telekomunikácie' }),
  mk(2, { title: 'Poistka na auto', counterparty: 'Allianz', category: 'Poistenie' }),
  mk(3, { title: 'Kúpna zmluva k bytu', type: 'Kúpna zmluva', category: 'Bývanie' }),
]

describe('search', () => {
  const ms = buildIndex(docs)
  it('nájde zmluvu k telekomu v prirodzenej vete', () => {
    expect(search(ms, docs, 'nájdi mi zmluvu k telekomu')[0].id).toBe(1)
  })
  it('ignoruje diakritiku', () => {
    expect(search(ms, docs, 'kupna zmluva')[0].id).toBe(3)
  })
  it('prázdny dotaz vráti všetko', () => {
    expect(search(ms, docs, '')).toHaveLength(3)
  })
  it('poistenie auta', () => {
    expect(search(ms, docs, 'poistka auto')[0].id).toBe(2)
  })
})
