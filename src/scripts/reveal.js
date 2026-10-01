// Záložné riešenie pre prehliadače bez `animation-timeline: view()`:
// pri vstupe do obrazovky pridá prvku triedu `.in`, ktorá spustí rovnaký efekt časovo (pozri base.css).
const root = document.documentElement;

if (root.classList.contains('io')) {
  const targets = document.querySelectorAll('.rv, .sw');
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('in');
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.12 },
    );
    targets.forEach((el) => observer.observe(el));
  } else {
    root.classList.remove('io');
  }
}

// Hlavička a ukazovateľ pokroku bez scroll-driven animácií (pozri base.css).
if (root.classList.contains('io')) {
  const nav = document.querySelector('.nav');
  const bar = document.querySelector('.progress i');
  let ticking = false;

  const update = () => {
    ticking = false;
    const y = window.scrollY;
    if (nav) nav.classList.toggle('scrolled', y > 60);
    if (bar) {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.transform = `scaleX(${max > 0 ? Math.min(1, y / max) : 0})`;
    }
  };

  window.addEventListener(
    'scroll',
    () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(update);
      }
    },
    { passive: true },
  );
  update();
}
