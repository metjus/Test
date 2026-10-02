// Výber riešenia a „schéma zákazky“ s ističom na domovskej stránke.
import { validName, validPhone, sendInquiry } from './send.js';

const circ = document.querySelector('[data-circ]');

if (circ) {
  const stageBtns = [...document.querySelectorAll('[data-stage]')];
  const subjectBtns = [...document.querySelectorAll('[data-subject]')];
  const nodes = [...circ.querySelectorAll('[data-node]')];
  const title = circ.querySelector('[data-circ-title]');
  const loadsBox = circ.querySelector('[data-loads]');
  const nameIn = circ.querySelector('[data-f-name]');
  const phoneIn = circ.querySelector('[data-f-phone]');
  const hp = circ.querySelector('[data-f-hp]');
  const wrap = circ.querySelector('[data-brk-wrap]');
  const brk = circ.querySelector('[data-brk]');
  const txt = circ.querySelector('[data-brk-txt]');
  const endpoint = wrap.dataset.endpoint || '';

  const st = { stages: ['kluc'], subjects: ['fve'], sent: false, busy: false, error: false };
  const nouns = { proj: 'projekt', mont: 'montáž', rev: 'revíziu' };
  const STAGE_LABEL = { proj: 'Navrhnúť (projekt)', mont: 'Namontovať', rev: 'Zrevidovať', kluc: 'Všetko na kľúč' };
  const list = (a) => (a.length > 1 ? a.slice(0, -1).join(', ') + ' a ' + a[a.length - 1] : a[0]);
  const setBtn = (b, on) => {
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  };

  function render() {
    const isKluc = st.stages.includes('kluc');
    const active = isKluc ? ['proj', 'mont', 'rev'] : st.stages;
    stageBtns.forEach((b) => setBtn(b, b.dataset.stage === 'kluc' ? isKluc : !isKluc && st.stages.includes(b.dataset.stage)));
    subjectBtns.forEach((b) => setBtn(b, st.subjects.includes(b.dataset.subject)));
    nodes.forEach((n) => {
      const on = active.includes(n.dataset.node);
      n.classList.toggle('on', on);
      n.classList.toggle('off', !on);
      n.querySelector('small').textContent = on ? 'zapojené' : 'tentoraz nie';
    });
    title.textContent = isKluc
      ? 'Celý obvod ide cez nás. Vy už len zapnete svetlo.'
      : 'Zapájame ' + list(['proj', 'mont', 'rev'].filter((id) => active.includes(id)).map((id) => nouns[id])) + '. Ostatné pripojíme, keď budete chcieť.';

    loadsBox.replaceChildren();
    const picked = subjectBtns.filter((b) => st.subjects.includes(b.dataset.subject));
    if (!picked.length) {
      const e = document.createElement('span');
      e.className = 'load empty';
      e.textContent = 'zatiaľ nič, pridajte vyššie v kroku 2';
      loadsBox.append(e);
    }
    for (const b of picked) {
      const e = document.createElement('span');
      e.className = 'load';
      e.innerHTML = `<svg class="ico" aria-hidden="true" focusable="false"><use href="${b.dataset.href}"></use></svg>`;
      e.append(b.dataset.label);
      loadsBox.append(e);
    }

    const ok = validName(nameIn.value) && validPhone(phoneIn.value);
    circ.classList.toggle('live', st.sent);
    wrap.classList.toggle('on', st.sent);
    wrap.classList.toggle('ready', !st.sent && ok);
    brk.disabled = st.sent || st.busy || !ok;
    brk.setAttribute('aria-pressed', st.sent ? 'true' : 'false');
    txt.textContent = st.sent
      ? `Prúd tečie. Dopyt je u nás, ozveme sa vám na ${phoneIn.value.trim()}.${endpoint ? '' : ' (Ukážkový režim: nič sa neodoslalo.)'}`
      : st.error
        ? 'Dopyt sa nepodarilo odoslať. Skúste to znova alebo zavolajte na 0910 635 595.'
        : ok
          ? 'Všetko zapojené. Zapnite istič.'
          : 'Doplňte meno a číslo. Potom zapnete istič a dopyt je na ceste.';
  }

  stageBtns.forEach((b) =>
    b.addEventListener('click', () => {
      const id = b.dataset.stage;
      let cur = st.stages.filter((x) => x !== 'kluc');
      if (id === 'kluc') cur = ['kluc'];
      else {
        cur = cur.includes(id) ? cur.filter((x) => x !== id) : cur.concat(id);
        if (cur.length === 0 || cur.length === 3) cur = ['kluc'];
      }
      st.stages = cur;
      st.sent = false;
      render();
    }),
  );
  subjectBtns.forEach((b) =>
    b.addEventListener('click', () => {
      const id = b.dataset.subject;
      st.subjects = st.subjects.includes(id) ? st.subjects.filter((x) => x !== id) : st.subjects.concat(id);
      st.sent = false;
      render();
    }),
  );
  [nameIn, phoneIn].forEach((i) =>
    i.addEventListener('input', () => {
      st.sent = false;
      st.error = false;
      render();
    }),
  );

  brk.addEventListener('click', async () => {
    if (brk.disabled) return;
    st.busy = true;
    st.error = false;
    render();
    try {
      await sendInquiry(
        endpoint,
        {
          name: nameIn.value.trim(),
          phone: phoneIn.value.trim(),
          services: st.stages.map((id) => STAGE_LABEL[id]),
          purposes: subjectBtns.filter((b) => st.subjects.includes(b.dataset.subject)).map((b) => b.dataset.label),
          town: '',
          contactMethod: 'Zavolať mi',
          contactTime: 'Kedykoľvek',
          note: '',
        },
        hp && hp.value,
      );
      st.sent = true;
    } catch {
      st.error = true;
    }
    st.busy = false;
    render();
  });

  render();
}
