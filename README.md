# GridFlow – prezentačný web

Statický web GridFlow s.r.o. (revízny technik podľa § 24, rozsah E1A, E1B, celé Slovensko) postavený na [Astro](https://astro.build) s čistým CSS a minimálnym vanilla JS. Zadanie, dizajn a obsah sú v `docs/`, vizuálna referencia v `reference/` (spustiteľná v `reference/static/`, snímky v `reference/screens/`).

## Príkazy

| Príkaz | Čo robí |
| --- | --- |
| `npm install` | nainštaluje závislosti |
| `npm run dev` | vývojový server (formulár beží v ukážkovom režime, nič sa neodosiela) |
| `npm run build` | statický výstup do `dist/` |
| `npm run preview` | lokálne zobrazí `dist/` |

Premenné prostredia (pozri `.env.example`): `SITE_URL` (kanonické odkazy, sitemap, Open Graph) a `PUBLIC_FORM_ENDPOINT` (kam formulár odošle dopyt).

## Stránky

| Adresa | Súbor |
| --- | --- |
| `/` | `src/pages/index.astro` (výber riešenia a vypínač: `src/scripts/home.js`) |
| `/kontakt/` | `src/pages/kontakt.astro` (formulár: `src/scripts/contact.js`) |
| `/zasady-ochrany-osobnych-udajov/` | `src/pages/zasady-ochrany-osobnych-udajov.astro` |
| 404 | `src/pages/404.astro` |

Stránky vychádzajú z odsúhlaseného mockupu (Claude Design). Hlavička dokumentu (SEO údaje, písma, ikony) je v `src/layouts/Site.astro`, hlavička webu, päta a obsah sú priamo v stránkach. Odoslanie dopytu (domovská stránka aj Kontakt) rieši `src/scripts/send.js`. Časté otázky sú v `src/data/faq.js`, odtiaľ ide aj JSON-LD `FAQPage`.

## Štýly

Presné farby, písma a rozmery sú v `docs/02-DIZAJN.md`. Štýly každej stránky sú v `src/styles/` (`home.css`, `contact.css`, `policy.css`, 404 používa `policy.css`); každý súbor je samostatný. Písma (Sora, Michroma) sa hosťujú lokálne z `assets/fonts/` (`fonts.css`), nič sa nenačítava z Googlu. Ikony domovskej stránky sú SVG sprite vložený priamo v `src/pages/index.astro`.

## Animácie

Sekcie sa odhaľujú pri skrolovaní: `src/scripts/reveal.js` cez IntersectionObserver pridá prvku `data-in`, keď sa objaví na obrazovke, a CSS spustí časovanú animáciu. Ako záloha bez JS slúžia CSS scroll-driven animácie (`animation-timeline`) v `@supports`. Pri `prefers-reduced-motion` sa nič z toho nespúšťa a pri vypnutom JS je všetok obsah čitateľný.

Pozor: v `astro.config.mjs` je pre CSS nastavený `cssMinify: 'esbuild'`. Predvolený minifikátor prepíše `animation` spolu s `animation-timeline` do skráteného zápisu, ktorému súčasné prehliadače nerozumejú, a animácie viazané na skrol prestanú fungovať.

## Typografia

Jednopísmenové predložky (k, s, v, z, o, u, a, i), „§ 24“ a telefónne číslo sa viažu nezlomiteľnou medzerou. Rieši to integrácia `nonbreaking-spaces` v `astro.config.mjs` po builde, takže vo vývojovom serveri sa zalomenie môže mierne líšiť.

## Formulár

`/kontakt/` obsahuje formulár podľa `docs/05-FORMULAR-A-ZASADY.md`: povinné je len meno a telefón, najčastejšie voľby sú predvolené, chyby sú po slovensky, je tam honeypot a krátka ochrana proti opakovanému odoslaniu (30 s). Do konzoly sa nič neloguje.

- **Kým nie je nastavené `PUBLIC_FORM_ENDPOINT`**, formulár beží v ukážkovom režime: validácia, voľby aj poďakovanie fungujú, ale nič sa neodosiela (poďakovanie to uvedie). Pred ostrým nasadením endpoint nastavte, inak dopyty zaniknú.
- **Po nastavení** formulár odošle `POST` s `Content-Type: application/json`:

```json
{
  "name": "Ján Novák",
  "phone": "0910 000 000",
  "services": ["Revízia elektroinštalácie"],
  "purposes": ["Kolaudácia"],
  "town": "Nitra",
  "contactMethod": "Zavolať mi",
  "contactTime": "Kedykoľvek",
  "note": "",
  "page": "/kontakt/",
  "ts": "2026-10-01T12:00:00.000Z"
}
```

  Odpoveď 2xx znamená úspech. Funguje to napríklad s formulárovou službou (Formspree a podobne) alebo s vlastnou serverless funkciou, ktorá pošle e-mail s predmetom „Nový dopyt: {služby} ({obec})“. Obmedzenie počtu žiadostí a prípadnú CAPTCHA treba doplniť na strane servera. Ak sa CAPTCHA alebo služba tretej strany pridá, doplňte ju do zásad ochrany údajov a do CSP v `public/_headers`.

## Nasadenie

`npm run build`, výstup je `dist/`. Funguje Cloudflare Pages, Netlify aj bežný hosting s HTTPS. `public/_headers` obsahuje bezpečnostné hlavičky (CSP, `X-Content-Type-Options`, `Referrer-Policy`…) a cache pre súbory v `_astro/`; Cloudflare Pages a Netlify ho čítajú samy, pri inom hostingu ich nastavte na serveri. Pred ostrým nasadením nastavte `SITE_URL` na skutočnú doménu.

## Logá partnerov

Logá a fotka v sekciách Smart domácnosť a Partneri sú v `public/partners/`:

- `solax.png`: logo SolaX Power z repozitára značiek Home Assistant (home-assistant/brands). Pred ostrým nasadením overte s klientom, či ide o aktuálnu verziu loga.
- `homemaster.png` a `homemaster-miniplc.webp`: logo a fotka produktu z oficiálnych podkladov výrobcu HomeMaster (datasheet a partner kit pre predajcov). Podľa pravidiel výrobcu sa nesmie používať spojenie „Works with Home Assistant“ (povolené je „integruje sa s Home Assistant cez ESPHome“) a fotky sa nesmú prefarbovať.
- `deye.png`: logo Deye (latinská časť firemného loga Ningbo Deye) z repozitára značiek Home Assistant. Ak klient dodá oficiálny súbor loga pre meniče, stačí ho nahradiť pod rovnakým názvom.

## Čo ešte treba doplniť

Zoznam údajov od klienta je v `docs/07-DOPLNIT-OD-KLIENTA.md`. Do tej doby zostávajú na stránkach viditeľné čiarkované polia „DOPLNIŤ: …“. Ďalej:

- schválenie loga (v `public/logo/` je kópia bez neviditeľných metadát, originály sú v `assets/logo/`),
- obrázok pre sociálne siete 1200 × 630 (dočasne `icon-512.png`),
- právna kontrola a doplnenie zásad ochrany osobných údajov,
- doména, e-mail a rozhodnutie o formulárovej službe,
- po nasadení Google Search Console a Google Business Profile.

## Kontrola kvality

Pri vývoji sa overovalo: bez chýb v konzole a bez vodorovného posunu na šírkach 360, 390, 768, 1024, 1440 a 1920 px, Lighthouse (mobil) výkon 99 až 100, prístupnosť 100, Best Practices 100, SEO 100 (stránka 404 má zámerne stavový kód 404 a `noindex`, preto jej SEO skóre nie je 100), a funkčnosť formulára (validácia, voľby, odoslanie, chybové stavy).
