export const DOC_TYPES = ['Zmluva', 'Kúpna zmluva', 'Nájomná zmluva', 'Poistná zmluva', 'Faktúra', 'Záruka', 'Doklad', 'Iné'] as const
export const CATEGORIES = ['Bývanie', 'Auto', 'Telekomunikácie', 'Poistenie', 'Financie', 'Zdravie', 'Práca', 'Iné'] as const

export interface Doc {
  id: string // UUID, aby sa záznamy zo zariadení dali bezpečne zlučovať
  title: string
  type: string
  category: string
  counterparty: string
  description: string
  signedAt: string | null // ISO yyyy-mm-dd
  validUntil: string | null // ISO yyyy-mm-dd
  noticeDays: number | null // výpovedná lehota v dňoch
  text: string // OCR / text zo všetkých verzií (len na vyhľadávanie)
  currentVersion: number
  createdAt: number
  updatedAt: number
}

export interface DocVersion {
  id: string
  docId: string
  version: number
  fileName: string
  mime: string
  blob: Blob
  text: string // OCR / text tejto verzie
  note: string
  addedAt: number
}

export interface Suggestion {
  type?: string
  category?: string
  counterparty?: string
  signedAt?: string | null
  validUntil?: string | null
  noticeDays?: number | null
}
