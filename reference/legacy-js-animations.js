/* GridFlow – animácie a skrolovanie (čistý JS, bez knižníc) */
(() => {
  const root = document.documentElement;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  root.classList.add('js');
  if (reduce) root.classList.add('rm');

  const $ = (s, c = document) => c.querySelector(s);
  const $$ = (s, c = document) => [...c.querySelectorAll(s)];
  const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));

  /* ---------- rozdelenie textu na slová / znaky ---------- */
  function splitWords(el) {
    const text = el.textContent.trim().replace(/\s+/g, ' ');
    const raw = text.split(' ');
    const tokens = [];
    for (let i = 0; i < raw.length; i++) {
      let t = raw[i];
      // jednopísmenové predložky a „§“ sa viažu na ďalšie slovo (slovenská typografia)
      if ((t.length === 1 || t === '§') && i < raw.length - 1) t += '\u00A0' + raw[++i];
      tokens.push(t);
    }
    el.setAttribute('aria-label', text);
    el.innerHTML = tokens
      .map((t, i) => `<span class="w" aria-hidden="true"><span class="wi" style="--i:${i}">${t}</span></span>`)
      .join(' ');
  }
  function splitChars(el) {
    const text = el.textContent.trim();
    el.innerHTML = [...text]
      .map((c, i) => `<span class="ch" aria-hidden="true" style="--i:${i}">${c === ' ' ? '\u00A0' : c}</span>`)
      .join('');
  }

  $$('[data-split],[data-hero-split]').forEach(splitWords);
  $$('[data-chars]').forEach(splitChars);

  /* ---------- objavenie pri vstupe do obrazovky ---------- */
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    });
  }, { threshold: 0.28, rootMargin: '0px 0px -6% 0px' });
  $$('[data-split],[data-reveal],[data-chars]').forEach((el) => io.observe(el));

  /* stupňované oneskorenie pre riadky zoznamu */
  $$('.rows li').forEach((li, i) => li.style.setProperty('--d', `${(i % 8) * 70}ms`));

  /* ---------- hero: vstupná sekvencia po načítaní fontov ---------- */
  const hero = $('.hero');
  $$('.trace').forEach((p, i) => p.style.setProperty('--td', `${i * 0.45}s`));
  $$('.rings circle').forEach((c, i) => c.style.setProperty('--rd', `${0.2 + i * 0.45}s`));
  const startHero = () => {
    hero.classList.add('go');
    const h1 = $('[data-hero-split]');
    h1.style.setProperty('--base', '150ms');
    h1.classList.add('in');
    $$('[data-hero-fade]').forEach((el) => el.classList.add('in'));
  };
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(() => requestAnimationFrame(startHero));

  /* ---------- skrolom riadené prvky ---------- */
  const nav = $('#nav');
  const bar = $('.progress i');
  const heroArt = $('.hero-art');
  const heroCopy = $('.hero-copy');

  const pinProgress = (track) => {
    const r = track.getBoundingClientRect();
    const total = r.height - window.innerHeight;
    return total > 0 ? clamp(-r.top / total) : 0;
  };

  /* sekcia „Kedy“: aktívna položka sa posúva po koľajnici */
  const when = $('.when');
  const wTrack = $('.track', when);
  const wItems = $$('.when-list li', when);
  const wList = $('.when-list', when);
  const wNode = $('.rail-node', when);
  const wFill = $('.rail-fill', when);
  let centers = [];
  const measure = () => { centers = wItems.map((li) => li.offsetTop + li.offsetHeight / 2); };
  measure();
  window.addEventListener('resize', measure);
  window.addEventListener('load', measure);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(measure);

  function updateWhen() {
    const n = wItems.length;
    const p = reduce ? 1 : pinProgress(wTrack);
    const idx = reduce ? n - 1 : p * (n - 1);
    wItems.forEach((li, i) => {
      const d = Math.min(1, Math.abs(i - idx));
      const o = 1 - d * 0.84;
      li.style.opacity = reduce ? 1 : o.toFixed(3);
      li.style.transform = `translate3d(${((o - 0.16) / 0.84 * 14).toFixed(1)}px,0,0)`;
    });
    if (!centers.length) return;
    const lo = Math.floor(idx), hi = Math.min(n - 1, lo + 1), t = idx - lo;
    const y = centers[lo] + (centers[hi] - centers[lo]) * t;
    wNode.style.transform = `translate(-50%, ${(y - 13).toFixed(1)}px)`;
    wFill.style.transform = `scaleY(${clamp(y / wList.offsetHeight).toFixed(4)})`;
  }

  /* sekcia „Riešenie“: obvod sa kreslí podľa skrolu */
  const sol = $('.solution');
  const sTrack = $('.track', sol);
  const flow = $('.flow', sol);
  const steps = $$('.step', sol);
  const note = $('.flow-note', sol);

  function updateSolution() {
    const p = reduce ? 1 : pinProgress(sTrack);
    const fill = clamp(p / 0.82);
    flow.style.setProperty('--p', fill.toFixed(4));
    steps.forEach((s, i) => s.classList.toggle('on', fill >= i * 0.25));
    note.classList.toggle('on', p > 0.9);
  }

  /* hlavný slučkový update (rAF) */
  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      ticking = false;
      const y = window.scrollY;
      const vh = window.innerHeight;
      const doc = document.documentElement;
      bar.style.transform = `scaleX(${clamp(y / (doc.scrollHeight - vh)).toFixed(4)})`;
      nav.classList.toggle('scrolled', y > 24);
      if (!reduce && y < vh * 1.2) {
        const k = clamp(y / vh);
        heroArt.style.transform = `translate3d(0,${(y * 0.16).toFixed(1)}px,0)`;
        heroCopy.style.opacity = (1 - k * 1.15).toFixed(3);
        heroCopy.style.transform = `translate3d(0,${(y * -0.06).toFixed(1)}px,0)`;
      }
      updateWhen();
      updateSolution();
    });
  }
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  onScroll();
})();
