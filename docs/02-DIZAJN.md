# 02 · Dizajn

Smer: moderný, luxusný, profesionálny, „Apple-like“. Veľká ľahká typografia, veľa priestoru, tmavé a svetlé sekcie striedavo, jemné ale výrazné animácie. Technický charakter značky (obvodové čiary a uzly) sa opakuje ako motív.

## Farby
| Token | Hodnota | Použitie |
| --- | --- | --- |
| `--navy` | `#022253` | Grid Navy, hlavná farba, text na svetlom |
| `--deep` | `#011638` | tmavé pozadia (päta, sekcia „Kedy“) |
| `--cyan` | `#02ACC1` | Flow Cyan, akcenty a primárne tlačidlá |
| `--cyan-soft` | `#7fd6e2` | akcentový text na tmavom |
| `--ice` | `#eef3f8` | svetlé plochy a karty |
| `--line` | `#d6e0ec` | tenké čiary |
| `--muted-d` | `#9db3d4` | vedľajší text na tmavom |
| `--ink-soft` | `#3e5379` | vedľajší text na svetlom |
Biela `#fff` a čierna `#000` len podľa brand guide. Cyan nepoužívaj ako farbu malého textu na bielom (nízky kontrast); na tmavom je v poriadku.

## Písma (hosťovať lokálne, `font-display: swap`)
- **Sora** 200, 300, 400, 600 (nadpisy a text; subsety latin + latin-ext pre slovenčinu).
- **Michroma** 400 (čísla, telefón, „technické“ prvky, ladí so širokým wordmarkom).
- Nadpisy: Sora 300, záporný rozstup (`letter-spacing` −.035 až −.045 em), `text-wrap: balance`.
- Veľkosti nadpisov cez `clamp()`: hero `clamp(34px, 4.3vw, 66px)`, sekcie `clamp(30px, 3.8vw, 58px)`. Základný text 17–18 px, riadkovanie 1.65.

## Rozloženie
- Kontajner `.wrap`: max-šírka 1240 px, vodorovný padding `clamp(22px, 5vw, 64px)`.
- Zvislé odstupy sekcií `clamp(96px, 14vw, 200px)`.
- Zaoblenia: tlačidlá a čipy pilulka (`999px`), karty 26–30 px.
- Breakpointy: `1080` (skryje menu, ostane telefón a Kontakt), `960` (jednostĺpcové rozloženie, hero karta preč), `720` (mobil: spodná lišta, 1-stĺpcové zoznamy a postup), `400` (menšie logo).
- Easing: `--ease: cubic-bezier(.16, 1, .3, 1)`.

## Komponenty
- **Hlavička**: fixná/sticky 68 px, logo (verzia „reversed“, výška 34 px), odkazy, biela pilulka s telefónom (Michroma 12 px) a cyan tlačidlo Kontakt. Na vrchu priehľadná, po odskrolovaní navy `rgba(1,22,56,.92)` s rozostrením pozadia.
- **Tlačidlá**: výška min 56 px, pilulka. Primárne: cyan pozadie, navy text, 600. Obrysové: priehľadné, biely okraj. Navy: pre svetlé sekcie. Hover: mierny posun nahor.
- **Ikony**: SVG sprite `assets/icons/sprite.svg` (23 ikon), čiarové, farby cez CSS premenné `--ic1` (hlavná) a `--ic2` (akcent, cyan), hrúbka `--sw`. Ikony sú v zaoblených dlaždiciach (`.tile`).
- **Čipy** (formulár): pilulka 46 px, vybraný = navy pozadie, biely text, `aria-pressed`.
- **Uzly**: krúžok s dutým stredom (cyan okraj) ako koncové body obvodov v logu. Používajú sa v zoznamoch a pri postupe.
- **Zástupné polia**: čiarkovaný cyan obrys, text „DOPLNIŤ: …“ (len dočasne).

## Sekcie hlavnej stránky
1. **Hero** (navy, min výška ~100 vh): vľavo nadpis, odstavec, dve tlačidlá, poznámka. Vpravo sklenená „ilustračná“ karta (Revízna správa, 4 položky so začiarknutím) a plávajúci štítok „Revízny technik § 24“ (skrytá pod 960 px). V pozadí štyri rovnobežné obvodové čiary (SVG) s uzlami na ľavom konci, ktoré sa pomaly kreslia. Dole pruh troch faktov (E1A, E1B / podľa § 24 / celé Slovensko) v Michrome.
2. **Služby** (biela): vľavo/hore nadpis, pod ním **bento mriežka** 4 stĺpce, 8 kariet (Domy, Byty, Elektroinštalácie ×2 stĺpce, Rozvádzače ×2, Bleskozvody, Fotovoltiku, NN prípojky ×2, EV nabíjacie stanice ×2). Karta má ikonu v dlaždici, názov a pri hoveri sa zafarbí na navy.
3. **Kedy ju potrebujete** (deep navy): vľavo nadpis a veta, vpravo zvislá „koľajnica“ s piatimi položkami veľkým písmom. Aktívna (stredná) položka je plne viditeľná a posunutá, ostatné zhasnuté.
4. **Ako to prebieha** (biela): tri stĺpce s čiarou nad každým, ikona v dlaždici a číslo v Michrome, nadpis, krátky text, tlačidlo Nezáväzný dopyt.
5. **Kompletné riešenie** (ice): štyri uzly na vodorovnej čiare (Projektová dokumentácia, Montáž / rekonštrukcia, Oprava, Následná revízia), poznámka s cyan ľavým okrajom. Na mobile zvisle.
6. **Kto vás bude revidovať** (biela): fotka technika (zástupný rám), riadky s ikonami (oprávnenie, rozsah, meno, číslo osvedčenia, prax).
7. **Časté otázky** (ice): akordeón (`<details>`), plus v kruhu sa pri otvorení otočí a zafarbí na cyan.
8. **Záverečný pruh** (navy): „Ozvite sa“, veta, dve tlačidlá, v pozadí tri pomaly pulzujúce kruhy (radar).
9. **Päta** (deep): logo, firemné údaje, odkaz na Zásady ochrany osobných údajov.
- **Mobil**: spodná lišta s dvoma tlačidlami (Zavolať, Nezáväzný dopyt) vždy viditeľná.

## Podstránky
- **Kontakt**: navy hlavička s nadpisom, dole sa prekrýva karta s formulárom (biela, tieň) a vedľa navy panel s údajmi (telefón veľký v Michrome, oprávnenie, fakturačné údaje, e-mail). Pod tým sekcia „Čo bude nasledovať“ (3 kroky).
- **Zásady**: navy hlavička, vľavo lepivý obsah (9 bodov), vpravo odseky s číslovaním.

## Logo
Súbory v `assets/logo/` (SVG a PNG: horizontálne, stacked, symbol, wordmark, štvorcová ikona; farebné, na tmavom, navy, čierne, biele). Minimum: 180 px (horizontálne) a 48 px (symbol). Ochranná zóna: výška koncového bodu symbolu. Logo je presná vektorová rekonštrukcia z rastrovej referencie, nie pôvodný zdroj; **pred spustením ho musí schváliť klient**.
