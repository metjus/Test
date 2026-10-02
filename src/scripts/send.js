// Odoslanie dopytu JSON-om na PUBLIC_FORM_ENDPOINT. Bez endpointu ukážkový režim (nič sa neodosiela).
// Do konzoly sa nič neloguje. Pozri README (Formulár).
const COOLDOWN_MS = 30000;
let lastSent = 0;

export const validName = (v) => v.trim().length >= 2;
export const validPhone = (v) => /^\+?[\d\s\-()/]+$/.test(v.trim()) && v.replace(/\D/g, '').length >= 9;

export async function sendInquiry(endpoint, payload, honeypot) {
  if (honeypot) return; // robot: tvárime sa, že sa odoslalo
  if (Date.now() - lastSent < COOLDOWN_MS) return; // opakované kliknutie
  if (!endpoint) {
    await new Promise((r) => setTimeout(r, 400));
    lastSent = Date.now();
    return;
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ ...payload, page: location.pathname, ts: new Date().toISOString() }),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error('send failed');
    lastSent = Date.now();
  } finally {
    clearTimeout(timer);
  }
}
