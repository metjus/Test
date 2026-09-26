/* TABEG – interactions & scroll motion (vanilla, no dependencies) */
(() => {
  'use strict';

  const body = document.body;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => [...c.querySelectorAll(s)];
  const clamp = (v, min = 0, max = 1) => Math.min(max, Math.max(min, v));

  /* ---------- Loader ---------- */
  const reveal = () => body.classList.add('is-loaded');
  if (reduceMotion.matches) reveal();
  else {
    let done = false;
    const go = () => { if (!done) { done = true; setTimeout(reveal, 900); } };
    if (document.readyState === 'complete') go(); else window.addEventListener('load', go);
    setTimeout(() => { done = true; reveal(); }, 2500); // never block the page
  }

  const year = $('[data-year]');
  if (year) year.textContent = new Date().getFullYear();

  /* ---------- Mobile menu ---------- */
  const burger = $('.burger');
  const menu = $('#mobile-menu');
  const setMenu = (open) => {
    burger.setAttribute('aria-expanded', String(open));
    burger.setAttribute('aria-label', open ? 'Zavrieť menu' : 'Otvoriť menu');
    body.classList.toggle('is-locked', open);
    if (open) {
      menu.hidden = false;
      requestAnimationFrame(() => menu.classList.add('is-open'));
      $('a', menu).focus({ preventScroll: true });
    } else {
      menu.classList.remove('is-open');
      setTimeout(() => { if (!menu.classList.contains('is-open')) menu.hidden = true; }, reduceMotion.matches ? 0 : 700);
    }
  };
  burger.addEventListener('click', () => setMenu(burger.getAttribute('aria-expanded') !== 'true'));
  $$('a', menu).forEach((a) => a.addEventListener('click', () => setMenu(false)));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && burger.getAttribute('aria-expanded') === 'true') { setMenu(false); burger.focus(); }
  });

  /* ---------- Reveal on scroll ---------- */
  // Stagger siblings that reveal together
  $$('[data-reveal]').forEach((el) => {
    const group = [...el.parentElement.children].filter((c) => c.hasAttribute('data-reveal'));
    const i = group.indexOf(el);
    if (i > 0) el.style.setProperty('--d', `${Math.min(i, 5) * 90}ms`);
  });

  const io = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) { entry.target.classList.add('is-in'); io.unobserve(entry.target); }
    });
  }, { rootMargin: '0px 0px -10% 0px', threshold: 0.1 });
  $$('[data-reveal], .cta .line').forEach((el) => io.observe(el));

  /* ---------- Manifest: words light up with scroll ---------- */
  const manifest = $('[data-words]');
  let words = [];
  if (manifest && !reduceMotion.matches) {
    const text = manifest.textContent.replace(/\s+/g, ' ').trim();
    manifest.setAttribute('aria-label', text);
    manifest.innerHTML = text.split(' ').map((w) => `<span class="w" aria-hidden="true">${w}</span>`).join(' ');
    words = $$('.w', manifest);
  }

  /* ---------- Active nav link ---------- */
  const navLinks = $$('.nav__list a');
  const sections = navLinks.map((a) => $(a.getAttribute('href'))).filter(Boolean);
  const navIO = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      navLinks.forEach((a) => {
        const on = a.getAttribute('href') === `#${entry.target.id}`;
        a.classList.toggle('is-active', on);
        if (on) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
      });
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  sections.forEach((s) => navIO.observe(s));

  /* ---------- Services: pinned horizontal scroll (desktop) ---------- */
  const services = $('.services');
  const track = $('.services__track');
  const serviceIndex = $('[data-service-index]');
  const serviceBar = $('.services__bar');
  const cards = $$('.card', track);
  let pinDistance = 0;

  const setupPin = () => {
    const enable = window.innerWidth >= 1000 && !reduceMotion.matches;
    services.classList.toggle('is-pinned', enable);
    if (!enable) { services.style.height = ''; track.style.transform = ''; pinDistance = 0; return; }
    pinDistance = Math.max(0, track.scrollWidth - window.innerWidth);
    services.style.height = `${window.innerHeight + pinDistance}px`;
  };

  /* ---------- Process line ---------- */
  const steps = $('.steps');
  const stepItems = $$('.step');

  /* ---------- Parallax ---------- */
  const parallax = $$('[data-parallax]');
  const tiles = $$('[data-parallax-inner]');

  /* ---------- Header & progress ---------- */
  const header = $('.header');
  const progress = $('.progress span');
  let lastY = window.scrollY;

  const onScroll = () => {
    const y = window.scrollY;
    const vh = window.innerHeight;
    const docH = document.documentElement.scrollHeight - vh;

    progress.style.setProperty('--p', docH > 0 ? (y / docH).toFixed(4) : 0);
    header.classList.toggle('is-scrolled', y > 40);
    const menuOpen = burger.getAttribute('aria-expanded') === 'true';
    header.classList.toggle('is-hidden', !menuOpen && y > lastY && y > vh * 0.8);
    lastY = y;

    if (reduceMotion.matches) return;

    // Hero drawing parallax
    parallax.forEach((el) => {
      if (y < vh * 1.2) el.style.transform = `translate3d(0, ${y * parseFloat(el.dataset.parallax)}px, 0)`;
    });

    // Manifest words
    if (words.length) {
      const r = manifest.getBoundingClientRect();
      const p = clamp((vh * 0.85 - r.top) / (r.height + vh * 0.35));
      const lit = Math.round(p * words.length);
      words.forEach((w, i) => w.classList.toggle('is-lit', i < lit));
    }

    // Services horizontal
    if (pinDistance > 0) {
      const r = services.getBoundingClientRect();
      const p = clamp(-r.top / pinDistance);
      track.style.transform = `translate3d(${-p * pinDistance}px, 0, 0)`;
      const idx = Math.min(cards.length, 1 + Math.floor(p * cards.length * 0.999));
      serviceIndex.textContent = String(idx).padStart(2, '0');
      serviceBar.style.setProperty('--sp', (0.2 + p * 0.8).toFixed(3));
    }

    // Process line
    if (steps) {
      const r = steps.getBoundingClientRect();
      const p = clamp((vh * 0.6 - r.top) / r.height);
      steps.style.setProperty('--lp', p.toFixed(3));
      stepItems.forEach((s) => {
        s.classList.toggle('is-active', s.getBoundingClientRect().top < vh * 0.6);
      });
    }

    // Tile parallax
    tiles.forEach((t) => {
      const r = t.getBoundingClientRect();
      if (r.bottom < 0 || r.top > vh) return;
      const p = (r.top + r.height / 2 - vh / 2) / vh; // -1..1
      t.style.setProperty('--py', `${(p * -24).toFixed(1)}px`);
    });
  };

  let ticking = false;
  const requestTick = () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { onScroll(); ticking = false; });
  };
  window.addEventListener('scroll', requestTick, { passive: true });
  window.addEventListener('resize', () => { setupPin(); requestTick(); });
  reduceMotion.addEventListener?.('change', () => { setupPin(); requestTick(); });
  document.fonts?.ready.then(() => { setupPin(); requestTick(); });
  setupPin();
  onScroll();

  /* ---------- Magnetic buttons (fine pointer only) ---------- */
  if (finePointer.matches && !reduceMotion.matches) {
    $$('[data-magnetic]').forEach((el) => {
      el.style.transition = `${getComputedStyle(el).transition}, transform 500ms cubic-bezier(.16,1,.3,1)`;
      el.addEventListener('mousemove', (e) => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left - r.width / 2) * 0.18;
        const yy = (e.clientY - r.top - r.height / 2) * 0.3;
        el.style.transform = `translate(${x}px, ${yy}px)`;
      });
      el.addEventListener('mouseleave', () => { el.style.transform = ''; });
    });
  }

  /* ---------- Contact form → prefilled e-mail ---------- */
  const form = $('#contact-form');
  const note = $('#form-note');
  const fields = {
    name: { el: $('#f-name'), msg: 'Zadajte, prosím, vaše meno.' },
    email: { el: $('#f-email'), msg: 'Zadajte platnú e-mailovú adresu.' },
    message: { el: $('#f-msg'), msg: 'Napíšte nám pár slov o vašom projekte.' },
  };
  const validate = (key) => {
    const { el, msg } = fields[key];
    const ok = el.value.trim() !== '' && el.checkValidity();
    const err = $(`#${el.id}-err`);
    el.closest('.field').classList.toggle('has-error', !ok);
    el.setAttribute('aria-invalid', String(!ok));
    if (ok) el.removeAttribute('aria-describedby'); else el.setAttribute('aria-describedby', err.id);
    err.textContent = ok ? '' : msg;
    return ok;
  };
  Object.keys(fields).forEach((k) => fields[k].el.addEventListener('blur', () => { if (fields[k].el.value) validate(k); }));

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const results = Object.keys(fields).map(validate);
    if (results.includes(false)) {
      fields[Object.keys(fields)[results.indexOf(false)]].el.focus();
      return;
    }
    const data = new FormData(form);
    const services = data.getAll('service');
    const lines = [
      `Meno: ${data.get('name')}`,
      `E-mail: ${data.get('email')}`,
      data.get('phone') ? `Telefón: ${data.get('phone')}` : '',
      services.length ? `Záujem o: ${services.join(', ')}` : '',
      '',
      data.get('message'),
    ].filter((l, i) => l !== '' || i === 4);
    const subject = `Dopyt z webu – ${data.get('name')}`;
    window.location.href = `mailto:info@tabeg.sk?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join('\n'))}`;
    note.textContent = 'Ďakujeme! Otvorili sme váš e-mailový klient, stačí správu odoslať.';
    note.classList.add('is-success');
  });
})();
