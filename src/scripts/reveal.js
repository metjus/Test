// Odhaľovanie sekcií pri skrolovaní: prvok dostane `data-in`, keď sa objaví na obrazovke,
// a CSS spustí časovanú animáciu. Bez JS alebo pri `prefers-reduced-motion` je obsah hneď viditeľný
// (CSS má ako zálohu animácie viazané na skrol).
const root = document.querySelector('.gf');
const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

if (root && 'IntersectionObserver' in window && !reduced) {
  root.setAttribute('data-io', '');
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.setAttribute('data-in', '');
          io.unobserve(e.target);
        }
      }
    },
    { threshold: 0.18, rootMargin: '0px 0px -6% 0px' },
  );
  root.querySelectorAll('.rv, .sa, .sa-r, .sw, .circ, .az-list').forEach((el) => io.observe(el));
}

// Pruh pokroku v hlavičke (ak ho prehliadač nerieši cez CSS animation-timeline)
const bar = document.querySelector('.progress i');
if (bar && !(window.CSS && CSS.supports && CSS.supports('animation-timeline: scroll()'))) {
  const update = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? scrollY / max : 0})`;
  };
  addEventListener('scroll', update, { passive: true });
  update();
}
