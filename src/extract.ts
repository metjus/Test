import type { Suggestion } from './types'
import { CATEGORIES, DOC_TYPES } from './types'

const MONTHS: Record<string, number> = {
  januara: 1, januar: 1, februara: 2, februar: 2, marca: 3, marec: 3, aprila: 4, april: 4,
  maja: 5, maj: 5, juna: 6, jun: 6, jula: 7, jul: 7, augusta: 8, august: 8,
  septembra: 9, september: 9, oktobra: 10, oktober: 10, novembra: 11, november: 11, decembra: 12, december: 12,
}

export const fold = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

const iso = (y: number, m: number, d: number): string | null => {
  if (y < 1990 || y > 2100 || m < 1 || m > 12 || d < 1) return null
  const dt = new Date(Date.UTC(y, m - 1, d))
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null
  return dt.toISOString().slice(0, 10)
}

export interface FoundDate {
  iso: string
  index: number
}

/** Nájde dátumy vo formátoch 1.2.2025, 01.02.2025, 1. februára 2025 a 2025-02-01. */
export function findDates(text: string): FoundDate[] {
  const out: FoundDate[] = []
  const push = (value: string | null, index: number) => value && out.push({ iso: value, index })

  for (const m of text.matchAll(/(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})/g)) push(iso(+m[3], +m[2], +m[1]), m.index!)
  for (const m of text.matchAll(/(\d{4})-(\d{2})-(\d{2})/g)) push(iso(+m[1], +m[2], +m[3]), m.index!)
  for (const m of text.matchAll(/(\d{1,2})\s*\.\s*([A-Za-zÀ-ž]+)\s+(\d{4})/g)) {
    const month = MONTHS[fold(m[2])]
    if (month) push(iso(+m[3], month, +m[1]), m.index!)
  }
  return out.sort((a, b) => a.index - b.index)
}

const addMonths = (isoDate: string, months: number): string => {
  const [y, m, d] = isoDate.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1 + months, d))
  // zmluva uzavretá 31.1. na 1 mesiac nekončí 3.3.
  if (dt.getUTCDate() !== d) dt.setUTCDate(0)
  return dt.toISOString().slice(0, 10)
}

const nearestDate = (text: string, dates: FoundDate[], keyword: RegExp): string | null => {
  const f = fold(text)
  let best: { iso: string; dist: number } | null = null
  for (const k of f.matchAll(keyword)) {
    for (const d of dates) {
      const dist = d.index - (k.index! + k[0].length)
      if (dist >= -5 && dist <= 60 && (!best || dist < best.dist)) best = { iso: d.iso, dist }
    }
  }
  return best?.iso ?? null
}

const COUNTERPARTIES = [
  'Slovak Telekom', 'Telekom', 'Orange', 'O2', 'Swan', 'Nay', 'Allianz', 'Kooperativa', 'Generali', 'Union', 'Uniqa',
  'Slovenská sporiteľňa', 'Tatra banka', 'VÚB', 'ČSOB', 'Prima banka', 'ZSE', 'SSE', 'VSE', 'SPP', 'Slovnaft',
  'Ikea', 'Datart', 'Alza', 'Okay', 'Dôvera', 'Union zdravotná', 'Všeobecná zdravotná poisťovňa',
]

const TYPE_RULES: [RegExp, (typeof DOC_TYPES)[number]][] = [
  [/kupna zmluva/, 'Kúpna zmluva'],
  [/najomn[au] zmluv|zmluva o najme/, 'Nájomná zmluva'],
  [/poistn[au] zmluv|poistka|poistenie/, 'Poistná zmluva'],
  [/faktur/, 'Faktúra'],
  [/zaruc/, 'Záruka'],
  [/zmluv/, 'Zmluva'],
]

const CATEGORY_RULES: [RegExp, (typeof CATEGORIES)[number]][] = [
  [/telekom|orange|\bo2\b|swan|mobil|internet|pausal|operator/, 'Telekomunikácie'],
  [/poist|poistn/, 'Poistenie'],
  [/byt|nehnutel|najom|energi|elektr|plyn|voda|zse|spp|vse|sse/, 'Bývanie'],
  [/vozidl|auto|spz|leasing|stk|ek\b/, 'Auto'],
  [/uver|banka|sporen|hypotek|ucet|financ/, 'Financie'],
  [/zdravot|lekar|nemocn|poliklinik/, 'Zdravie'],
  [/pracovn|zamestn|mzda|zamestnavatel/, 'Práca'],
]

/** Pravidlová extrakcia z textu dokumentu. Výsledok je len návrh, používateľ ho vždy skontroluje. */
export function suggest(text: string): Suggestion {
  const f = fold(text)
  const dates = findDates(text)
  const s: Suggestion = {}

  s.type = TYPE_RULES.find(([re]) => re.test(f))?.[1]
  s.category = CATEGORY_RULES.find(([re]) => re.test(f))?.[1]

  const party = COUNTERPARTIES.filter((c) => f.includes(fold(c))).sort((a, b) => b.length - a.length)[0]
  if (party) s.counterparty = party

  s.signedAt =
    nearestDate(text, dates, /(dna|datum podpisu|dnom podpisu|podpisana|uzatvorena|v [a-z]+ dna)/g) ?? dates[0]?.iso ?? null

  s.validUntil = nearestDate(
    text,
    dates,
    /(platnost do|platna do|viazanost do|viazanosti do|uzatvorena do|na dobu urcitu do|ucinna do|do dna|trvanie do)/g,
  )

  // jediný dátum v texte nemôže byť zároveň podpis aj koniec platnosti
  if (s.signedAt && s.signedAt === s.validUntil) s.signedAt = null

  const dur = f.match(/(?:na\s+)?dobu\s+(?:urcitu\s+)?(?:v\s+dlzke\s+)?(\d{1,3})\s*(mesiac\w*|rok\w*|roky|rokov)/)
  if (!s.validUntil && dur && s.signedAt) {
    const n = +dur[1]
    s.validUntil = addMonths(s.signedAt, dur[2].startsWith('mesiac') ? n : n * 12)
  }

  const notice = f.match(/vypovedn\w*\s+(?:lehot\w*|dob\w*)[^.\d]{0,40}(\d{1,3})\s*(dni|dny|dn|mesiac\w*)/)
  if (notice) s.noticeDays = notice[2].startsWith('mesiac') ? +notice[1] * 30 : +notice[1]

  return s
}

export type Urgency = 'expired' | 'urgent' | 'soon' | 'ok' | 'none'

export interface Status {
  urgency: Urgency
  daysLeft: number | null
  /** posledný deň na výpoveď, ak je známa výpovedná lehota */
  noticeBy: string | null
  noticeDaysLeft: number | null
  label: string
}

const dayDiff = (isoDate: string, today: Date) => {
  const [y, m, d] = isoDate.split('-').map(Number)
  const t = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((Date.UTC(y, m - 1, d) - t) / 86_400_000)
}

export function statusOf(validUntil: string | null, noticeDays: number | null, today = new Date()): Status {
  if (!validUntil) return { urgency: 'none', daysLeft: null, noticeBy: null, noticeDaysLeft: null, label: 'Bez dátumu platnosti' }
  const daysLeft = dayDiff(validUntil, today)
  let noticeBy: string | null = null
  let noticeDaysLeft: number | null = null
  if (noticeDays) {
    const [y, m, d] = validUntil.split('-').map(Number)
    noticeBy = new Date(Date.UTC(y, m - 1, d - noticeDays)).toISOString().slice(0, 10)
    noticeDaysLeft = dayDiff(noticeBy, today)
  }
  // rozhodujúci je skorší z termínov: koniec platnosti alebo posledný deň na výpoveď
  const effective = noticeDaysLeft !== null && noticeDaysLeft >= 0 ? Math.min(daysLeft, noticeDaysLeft) : daysLeft
  if (daysLeft < 0) return { urgency: 'expired', daysLeft, noticeBy, noticeDaysLeft, label: `Skončilo pred ${-daysLeft} d` }
  const urgency: Urgency = effective <= 30 ? 'urgent' : effective <= 60 ? 'soon' : 'ok'
  const label =
    noticeDaysLeft !== null && noticeDaysLeft >= 0 && noticeDaysLeft < daysLeft
      ? `Výpoveď do ${noticeDaysLeft} d`
      : daysLeft === 0
        ? 'Končí dnes'
        : `Končí o ${daysLeft} d`
  return { urgency, daysLeft, noticeBy, noticeDaysLeft, label }
}
