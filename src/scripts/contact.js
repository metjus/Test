// Formulár „Nezáväzný dopyt“ na stránke Kontakt.
import { validName, validPhone, validEmail, sendInquiry } from './send.js';

const form = document.querySelector('[data-k-form]');

if (form) {
  const ok = document.querySelector('[data-k-ok]');
  const $ = (s) => form.querySelector(s);
  const nameIn = $('[data-f-name]');
  const phoneIn = $('[data-f-phone]');
  const emailIn = $('[data-f-email]');
  const townIn = $('[data-f-town]');
  const noteIn = $('[data-f-note]');
  const hp = $('[data-f-hp]');
  const sendBtn = $('[data-send]');
  const ferr = $('[data-ferr]');
  const endpoint = form.dataset.endpoint || '';
  const groups = [...form.querySelectorAll('[data-group]')];
  const defaults = new Map();

  const setBtn = (b, on) => {
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  };
  const chipsOf = (g) => [...g.querySelectorAll('.chip')];
  const picked = (name) => chipsOf(form.querySelector(`[data-group="${name}"]`)).filter((c) => c.classList.contains('on')).map((c) => c.textContent.trim());

  for (const g of groups) {
    const chips = chipsOf(g);
    defaults.set(g, chips.map((c) => c.classList.contains('on')));
    const excl = g.dataset.exclusive;
    chips.forEach((c) =>
      c.addEventListener('click', () => {
        const on = c.classList.contains('on');
        if (g.dataset.mode === 'single') chips.forEach((x) => setBtn(x, x === c));
        else if (excl && c.dataset.id === excl) chips.forEach((x) => setBtn(x, x === c && !on));
        else {
          if (excl) chips.filter((x) => x.dataset.id === excl).forEach((x) => setBtn(x, false));
          setBtn(c, !on);
        }
      }),
    );
  }

  // Predvýber z domovskej stránky: ?vyber=id,id alebo výber uložený v prehliadači.
  const preselect = () => {
    let ids = [];
    const q = new URLSearchParams(location.search).get('vyber');
    if (q) ids = q.split(',');
    else {
      try {
        const saved = JSON.parse(sessionStorage.getItem('gf-vyber') || 'null');
        if (saved) ids = [...(saved.stages || []), ...(saved.subjects || [])];
      } catch {}
    }
    for (const name of ['services', 'purposes']) {
      const g = form.querySelector(`[data-group="${name}"]`);
      chipsOf(g).forEach((c) => {
        if (ids.includes(c.dataset.id)) setBtn(c, true);
      });
    }
  };
  preselect();

  const contactOk = () => validPhone(phoneIn.value) || validEmail(emailIn.value);
  const refresh = () => {
    sendBtn.disabled = !(validName(nameIn.value) && contactOk());
  };
  [nameIn, phoneIn, emailIn].forEach((i) => i.addEventListener('input', refresh));

  sendBtn.addEventListener('click', async () => {
    if (sendBtn.disabled) return;
    ferr.hidden = true;
    sendBtn.disabled = true;
    const services = picked('services');
    const payload = {
      name: nameIn.value.trim(),
      phone: phoneIn.value.trim(),
      email: emailIn.value.trim(),
      services: services.length ? services : ['Zatiaľ neviem, poraďte nám'],
      purposes: picked('purposes'),
      town: townIn.value.trim(),
      contactMethod: picked('pref')[0],
      contactTime: picked('when')[0],
      note: noteIn.value.trim(),
    };
    try {
      await sendInquiry(endpoint, payload, hp && hp.value);
    } catch {
      ferr.hidden = false;
      refresh();
      return;
    }
    const set = (k, v) => (ok.querySelector(`[data-sum="${k}"]`).textContent = v);
    const kam = [validPhone(payload.phone) ? `na číslo ${payload.phone}` : '', validEmail(payload.email) ? `na e-mail ${payload.email}` : ''].filter(Boolean).join(' alebo ');
    set('kam', kam);
    set('services', payload.services.join(', '));
    set('purposes', payload.purposes.length ? payload.purposes.join(', ') : '—');
    set('pref', `${payload.contactMethod}, ${payload.contactTime.toLowerCase()}`);
    ok.querySelector('[data-demo]').hidden = Boolean(endpoint);
    form.hidden = true;
    ok.hidden = false;
    ok.focus({ preventScroll: true });
  });

  ok.querySelector('[data-again]').addEventListener('click', () => {
    for (const g of groups) chipsOf(g).forEach((c, i) => setBtn(c, defaults.get(g)[i]));
    [nameIn, phoneIn, emailIn, townIn, noteIn].forEach((i) => (i.value = ''));
    refresh();
    ok.hidden = true;
    form.hidden = false;
    nameIn.focus();
  });
}
