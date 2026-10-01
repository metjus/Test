import type { NewDoc } from './db'

export const emptyDocMeta = (): NewDoc => ({
  title: 'Test', type: 'Zmluva', category: 'Iné', counterparty: '', description: '', signedAt: null, validUntil: null, noticeDays: null,
})
