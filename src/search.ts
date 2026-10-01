import MiniSearch from 'minisearch'
import { fold } from './extract'
import type { Doc } from './types'

const STOPWORDS = new Set([
  'najdi', 'najst', 'mi', 'ma', 'mam', 'kde', 'je', 'som', 'ako', 'ktora', 'ktory', 'ktore', 'k', 'ku', 'na', 'v', 'vo', 'o', 'u', 'od', 'do', 'za',
  'a', 'aj', 'i', 'to', 'tu', 'pre', 'zo', 'so', 'si', 'sa', 'moj', 'moja', 'moje', 'ukaz', 'zobraz', 'kedy', 'konci', 'dokument',
])

/**
 * Normalizácia: bez diakritiky, malé písmená, odstránená jedna koncová samohláska
 * ("telekomu" aj "telekom" -> "telekom", "zmluvu" aj "zmluva" -> "zmluv").
 */
export function processTerm(term: string): string | null {
  const t = fold(term)
  if (t.length < 2 || STOPWORDS.has(t)) return null
  return t.length >= 5 ? t.replace(/[aeiouy]$/, '') : t
}

export function buildIndex(docs: Doc[]): MiniSearch<Doc> {
  const ms = new MiniSearch<Doc>({
    idField: 'id',
    fields: ['title', 'counterparty', 'category', 'type', 'description', 'text'],
    processTerm,
    searchOptions: { prefix: true, fuzzy: 0.2, combineWith: 'OR', boost: { title: 3, counterparty: 3, type: 2, category: 2, description: 1.5 } },
  })
  ms.addAll(docs)
  return ms
}

export function search(ms: MiniSearch<Doc>, docs: Doc[], query: string): Doc[] {
  if (!query.trim()) return docs
  const byId = new Map(docs.map((d) => [d.id, d]))
  return ms
    .search(query)
    .map((r) => byId.get(r.id as string))
    .filter((d): d is Doc => !!d)
}
