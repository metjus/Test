# 04 · Animácie

Princíp: **jemné, ale viditeľné**, riadené skrolom. Obsah musí byť čitateľný aj bez animácií (vypnuté JS, `prefers-reduced-motion`, staršie prehliadače).

Referenčná implementácia v `reference/static/` používa **CSS scroll-driven animácie** (`animation-timeline: view()` a `scroll()`). Podporu overuj (Chrome a Edge áno, Safari od verzie 26, Firefox podľa verzie). Odporúčaný postup pre ostrý web: vstavaj to ako vylepšenie v `@supports (animation-timeline: view())` a pre ostatné prehliadače dodaj **záložné riešenie cez IntersectionObserver** (pri vstupe do obrazovky pridaj triedu `.in`, ktorá spustí rovnaký efekt časovo). Starší príklad v JS je v `reference/legacy-js-animations.js` (staršia štruktúra, použi len ako inšpiráciu).

## Vstup stránky
- **Opona**: dve vrstvy cez celú obrazovku (cyan a navy), zakrývajú stránku a odsunú sa nahor, `1.15 s`, `cubic-bezier(.76, 0, .24, 1)`, oneskorenie navy 0 s, cyan 0.2 s. Spúšťa sa pri načítaní každej stránky vrátane hlavnej. Pri `prefers-reduced-motion` sa nezobrazuje.
- Hero sa spustí až po opone: slová nadpisu `+900 ms`, ostatné prvky `+750 ms`, obvodové čiary `+0.85 s`.

## Hero
- Nadpis: slová sa vynárajú z masky (`translateY(125 %) rotate(6°)` na nulu), `1.25 s`, stupňovanie `80 ms` na slovo.
- Obvodové čiary (4 SVG cesty, `pathLength = 1`, `stroke-dasharray: 1 1`): vykreslenie **~5.2 s**, `cubic-bezier(.5, 0, .15, 1)`, stupňovanie `0.45 s`. Kruhové uzly sa objavia (scale .4 → 1) s oneskorením `0.2 s + 0.45 s × i`.
- Odstavec, tlačidlá, poznámka, karta a pruh faktov: fade-up `1.5 s` so stupňovaným oneskorením (700, 900, 1050, 1250 ms).
- Pri skrolovaní: obsah hera sa vytráca a posúva (`heroout`, rozsah 0 – 520 px), pozadie s čiarami sa posúva pomalšie (paralaxa), bodkovaná mriežka v pozadí sa pomaly posúva.

## Hlavička a pokrok
- Pozadie hlavičky prechádza z priehľadného na navy v prvých ~140 px skrolu.
- Tenký cyan pruh hore ukazuje pokrok skrolovania (`scaleX` podľa `scroll(root)`).

## Skrolovacie efekty po sekciách
| Prvok | Efekt | Poznámka |
| --- | --- | --- |
| Nadpisy sekcií | slová sa vynárajú z masky po jednom | rozsah od vstupu po približne stred obrazovky |
| Bento karty | zdola, zväčšenie z 0.82, stupňovanie podľa stĺpca | ikona v dlaždici sa roztočí z nuly |
| Kedy: koľajnica | aktívna položka v strede je plne viditeľná a posunutá o ~38 px, ostatné na 10 % | uzol pri položke sa zafarbí na cyan |
| Postup | čiara nad krokom sa dokreslí, ikony a čísla „naskočia“, kroky postupne | tlačidlo naposledy |
| Kompletné riešenie | čiara sa kreslí zľava (na mobile zhora), uzly sa postupne rozsvecujú, ikony v nich naskočia | poznámka sa objaví na konci |
| Kto vás bude revidovať | fotka sa odhaľuje zhora (`clip-path`), riadky po jednom | |
| FAQ | položky sa objavujú zdola | otvorenie: otočenie plus, plynulé rozbalenie |
| Záver | nadpis, veta a tlačidlá sa objavia, kruhy radaru sa zväčšujú | |
| Päta | stĺpce sa objavia | |
| Kontakt | panel a formulár sa pri načítaní vynárajú, „Čo bude nasledovať“ cez skrol | pri zmene stavu formulára jemný prechod |

**Dôležité pravidlo**: prvky na úplnom konci stránky (päta, posledné kroky) sa musia animovať len počas vstupu do obrazovky (`entry`), inak sa animácia nikdy nedokončí a ostanú rozostrené alebo posunuté.

## Nepretržité pohyby
- Radar v záverečnom pruhu: tri kruhy, `14 s`, nekonečne, posunuté o 4.7 s, pomalé a nenápadné.
- Plávajúci štítok v hero karte: `7 s` ease-in-out.

## Interakcie
- Tlačidlá: hover posun o −2 px, stlačenie `scale(.96)`.
- Karty služieb: hover mení pozadie na navy, kruh vzadu sa zväčší, šípka sa zafarbí na cyan.
- Odkazy v menu: cyan podčiarknutie sa dokreslí zľava.
- Kotvy (`#sluzby`…): `scroll-behavior: smooth` a `scroll-padding-top: 84px`.

## Prístupnosť
- `prefers-reduced-motion: reduce`: žiadne animácie, žiadna opona, všetko vo finálnom stave.
- Animácia nesmie meniť poradie obsahu ani skrývať text pred čítačkami obrazovky (neskrývaj cez `display: none`).
- Mobil: žiadne efekty, ktoré spomaľujú posúvanie (`will-change` len tam, kde treba).
