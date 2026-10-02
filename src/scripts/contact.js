// Formulár „Nezáväzný dopyt“ na stránke Kontakt.
import { validName, validPhone, sendInquiry } from './send.js';

const form = document.querySelector('[data-k-form]');

if (form) {
  const ok = document.querySelector('[data-k-ok]');
  const $ = (s) => form.querySelector(s);
  const nameIn = $('[data-f-name]');
  const phoneIn = $('[data-f-phone]');
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

  const refresh = () => {
    sendBtn.disabled = !(validName(nameIn.value) && validPhone(phoneIn.value));
  };
  [nameIn, phoneIn].forEach((i) => i.addEventListener('input', refresh));

  sendBtn.addEventListener('click', async () => {
    if (sendBtn.disabled) return;
    ferr.hidden = true;
    sendBtn.disabled = true;
    const services = picked('services');
    const payload = {
      name: nameIn.value.trim(),
      phone: phoneIn.value.trim(),
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
    set('phone', payload.phone);
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
    [nameIn, phoneIn, townIn, noteIn].forEach((i) => (i.value = ''));
    refresh();
    ok.hidden = true;
    form.hidden = false;
    nameIn.focus();
  });
}
