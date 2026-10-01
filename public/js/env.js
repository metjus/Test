// Spúšťa sa pred vykreslením. Pridá triedu `io` len tam, kde nie sú CSS scroll-driven animácie
// (a používateľ nevypol pohyb); vtedy ich nahradí záložné odhaľovanie v scripts/reveal.js.
(function () {
  var root = document.documentElement;
  var supported = window.CSS && CSS.supports && CSS.supports('animation-timeline: view()');
  var reduced = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!supported && !reduced) root.classList.add('io');
})();
