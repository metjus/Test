// Kontaktný formulár: smart default, validácia po slovensky, odoslanie JSON-om.
// Žiadne osobné údaje sa nelogujú do konzoly. Pozri docs/05-FORMULAR-A-ZASADY.md.

const form = document.getElementById('inquiry');

if (form) {
  const endpoint = form.dataset.endpoint || '';
  const $ = (selector) => form.querySelector(selector);

  const nameInput = $('#f-name');
  const phoneInput = $('#f-phone');
  const townInput = $('#f-town');
  const noteInput = $('#f-note');
  const honeypot = $('#f-website');
  const submit = $('#f-submit');
  const formError = $('#form-error');
  const panel = $('#inq-panel');
  const sent = $('#inq-sent');
  const COOLDOWN_MS = 30000;

  const touched = { name: false, phone: false };

  // ---- Čipy ----
  const groups = [...form.querySelectorAll('[data-group]')];

  function setChip(chip, on) {
    chip.classList.toggle('on', on);
    chip.setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  for (const group of groups) {
    const chips = [...group.querySelectorAll('.chip')];
    const single = group.dataset.single === 'true';
    for (const chip of chips) {
      chip.addEventListener('click', () => {
        const wasOn = chip.classList.contains('on');
        if (single) {
          chips.forEach((c) => setChip(c, c === chip));
          return;
        }
        if (chip.dataset.exclusive === 'true') {
          chips.forEach((c) => setChip(c, c === chip && !wasOn));
          return;
        }
        setChip(chip, !wasOn);
        // „Neviem, poraďte mi“ vylučuje ostatné voľby
        chips.filter((c) => c.dataset.exclusive === 'true').forEach((c) => setChip(c, false));
      });
    }
  }

  const selected = (name) =>
    [...form.querySelectorAll(`[data-group="${name}"] .chip.on`)].map((c) => c.textContent.trim());

  // ---- Validácia ----
  const validName = (value) => value.trim().length >= 2;
  const validPhone = (value) => {
    const v = value.trim();
    return /^\+?[\d\s\-()]+$/.test(v) && v.replace(/\D/g, '').length >= 9;
  };

  function showError(input, id, message) {
    const el = document.getElementById(id);
    el.textContent = message;
    el.hidden = !message;
    if (message) input.setAttribute('aria-invalid', 'true');
    else input.removeAttribute('aria-invalid');
  }

  function refresh() {
    const nameOk = validName(nameInput.value);
    const phoneOk = validPhone(phoneInput.value);
    showError(
      nameInput,
      'err-name',
      touched.name && !nameOk ? 'Napíšte, prosím, meno (aspoň 2 znaky).' : '',
    );
    let phoneMessage = '';
    if (touched.phone && !phoneOk) {
      phoneMessage = phoneInput.value.trim()
        ? 'Zadajte telefón aspoň z 9 číslic, napríklad 0900 000 000.'
        : 'Napíšte, prosím, telefónne číslo.';
    }
    showError(phoneInput, 'err-phone', phoneMessage);
    submit.disabled = !(nameOk && phoneOk);
    return nameOk && phoneOk;
  }

  nameInput.addEventListener('input', refresh);
  phoneInput.addEventListener('input', refresh);
  nameInput.addEventListener('blur', () => { touched.name = true; refresh(); });
  phoneInput.addEventListener('blur', () => { touched.phone = true; refresh(); });

  // ---- Odoslanie ----
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function send(payload) {
    if (!endpoint) {
      await wait(500); // ukážkový režim (vývoj): nič sa neodosiela
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error('send failed');
    } finally {
      clearTimeout(timer);
    }
  }

  function showSent(payload) {
    $('#sent-phone').textContent = payload.phone;
    $('#sum-service').textContent = payload.services.join(', ');
    $('#sum-purpose').textContent = payload.purposes.length ? payload.purposes.join(', ') : '—';
    $('#sum-contact').textContent = `${payload.contactMethod}, ${payload.contactTime.toLowerCase()}`;
    panel.hidden = true;
    sent.hidden = false;
    $('#sent-title').focus({ preventScroll: true });
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    touched.name = true;
    touched.phone = true;
    formError.hidden = true;
    if (!refresh()) return;

    const payload = {
      name: nameInput.value.trim(),
      phone: phoneInput.value.trim(),
      services: selected('services').length ? selected('services') : ['Neviem, poraďte mi'],
      purposes: selected('purposes'),
      town: townInput.value.trim(),
      contactMethod: selected('method')[0],
      contactTime: selected('time')[0],
      note: noteInput.value.trim(),
      page: location.pathname,
      ts: new Date().toISOString(),
    };

    if (honeypot.value) {
      showSent(payload); // bot: tvárime sa, že sa odoslalo, nič neposielame
      return;
    }

    let last = 0;
    try { last = Number(sessionStorage.getItem('gf-inquiry-ts')) || 0; } catch { /* úložisko nemusí byť dostupné */ }
    if (Date.now() - last < COOLDOWN_MS) {
      formError.innerHTML = 'Dopyt ste práve odoslali. Počkajte chvíľu a skúste to znova alebo zavolajte na <a href="tel:+421910635595">0910 635 595</a>.';
      formError.hidden = false;
      return;
    }

    submit.disabled = true;
    submit.textContent = 'Odosielam…';
    try {
      await send(payload);
      try { sessionStorage.setItem('gf-inquiry-ts', String(Date.now())); } catch { /* ignoruj */ }
      showSent(payload);
    } catch {
      formError.innerHTML = 'Dopyt sa nepodarilo odoslať. Skúste to znova alebo zavolajte na <a href="tel:+421910635595">0910 635 595</a>.';
      formError.hidden = false;
    } finally {
      submit.textContent = 'Odoslať dopyt';
      refresh();
    }
  });

  $('#f-again').addEventListener('click', () => {
    form.reset();
    for (const group of groups) {
      const chips = [...group.querySelectorAll('.chip')];
      const defaults = group.dataset.group === 'services' ? ['inst'] : group.dataset.group === 'method' ? ['call'] : group.dataset.group === 'time' ? ['any'] : [];
      chips.forEach((c) => setChip(c, defaults.includes(c.dataset.value)));
    }
    touched.name = false;
    touched.phone = false;
    sent.hidden = true;
    panel.hidden = false;
    refresh();
    nameInput.focus();
  });

  refresh();
}
