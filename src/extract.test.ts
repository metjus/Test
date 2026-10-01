import { describe, expect, it } from 'vitest'
import { findDates, statusOf, suggest } from './extract'

describe('findDates', () => {
  it('rozpozná slovenské formáty', () => {
    const d = findDates('Dňa 1.2.2025 a 15. marca 2026, tiež 2027-01-31 a 31.2.2025')
    expect(d.map((x) => x.iso)).toEqual(['2025-02-01', '2026-03-15', '2027-01-31'])
  })
})

describe('suggest', () => {
  const text = `Zmluva o poskytovaní služieb Slovak Telekom, a.s.
    Zmluva bola uzatvorená dňa 1.3.2024 na dobu určitú 24 mesiacov.
    Výpovedná lehota je 30 dní.`
  it('vyberie typ, protistranu a kategóriu', () => {
    const s = suggest(text)
    expect(s.type).toBe('Zmluva')
    expect(s.counterparty).toBe('Slovak Telekom')
    expect(s.category).toBe('Telekomunikácie')
  })
  it('dopočíta koniec viazanosti z dĺžky', () => {
    const s = suggest(text)
    expect(s.signedAt).toBe('2024-03-01')
    expect(s.validUntil).toBe('2026-03-01')
    expect(s.noticeDays).toBe(30)
  })
  it('použije výslovné "platnosť do"', () => {
    const s = suggest('Poistná zmluva Allianz. Platnosť do 31. decembra 2027')
    expect(s.validUntil).toBe('2027-12-31')
    expect(s.signedAt).toBeNull()
  })
})

describe('statusOf', () => {
  const today = new Date(2026, 9, 1)
  it('bez dátumu', () => expect(statusOf(null, null, today).urgency).toBe('none'))
  it('skončilo', () => expect(statusOf('2026-09-01', null, today).urgency).toBe('expired'))
  it('urgentné do 30 dní', () => expect(statusOf('2026-10-20', null, today).urgency).toBe('urgent'))
  it('čoskoro do 60 dní', () => expect(statusOf('2026-11-20', null, today).urgency).toBe('soon'))
  it('ok', () => expect(statusOf('2027-06-01', null, today).urgency).toBe('ok'))
  it('berie do úvahy výpovednú lehotu', () => {
    const s = statusOf('2026-12-01', 60, today)
    expect(s.noticeBy).toBe('2026-10-02')
    expect(s.urgency).toBe('urgent')
    expect(s.label).toMatch(/Výpoveď/)
  })
})
