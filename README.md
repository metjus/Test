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
| `/sitemap.xml`, `/robots.txt`, `/llms.txt` | `src/pages/sitemap.xml.ts`, `robots.txt.ts`, `llms.txt.ts` (generujú sa pri builde) |

Stránky vychádzajú z odsúhlaseného mockupu (Claude Design). Hlavička dokumentu (SEO údaje, písma, ikony) je v `src/layouts/Site.astro`, hlavička webu, päta a obsah sú priamo v stránkach. Odoslanie dopytu (domovská stránka aj Kontakt) rieši `src/scripts/send.js`. Časté otázky sú v `src/data/faq.js`, odtiaľ ide aj JSON-LD `FAQPage`.

## Štýly

Presné farby, písma a rozmery sú v `docs/02-DIZAJN.md`. Štýly každej stránky sú v `src/styles/` (`home.css`, `contact.css`, `policy.css`, 404 používa `policy.css`); každý súbor je samostatný. Písma (Sora, Michroma) sa hosťujú lokálne z `assets/fonts/` (`fonts.css`), nič sa nenačítava z Googlu. Ikony domovskej stránky sú SVG sprite vložený priamo v `src/pages/index.astro`.

## Animácie

Sekcie sa odhaľujú pri skrolovaní: `src/scripts/reveal.js` cez IntersectionObserver pridá prvku `data-in`, keď sa objaví na obrazovke, a CSS spustí časovanú animáciu. Ako záloha bez JS slúžia CSS scroll-driven animácie (`animation-timeline`) v `@supports`. Pri `prefers-reduced-motion` sa nič z toho nespúšťa a pri vypnutom JS je všetok obsah čitateľný.

Pozor: v `astro.config.mjs` je pre CSS nastavený `cssMinify: 'esbuild'`. Predvolený minifikátor prepíše `animation` spolu s `animation-timeline` do skráteného zápisu, ktorému súčasné prehliadače nerozumejú, a animácie viazané na skrol prestanú fungovať.

## Typografia

Jednopísmenové predložky (k, s, v, z, o, u, a, i), „§ 24“ a telefónne číslo sa viažu nezlomiteľnou medzerou. Rieši to integrácia `nonbreaking-spaces` v `astro.config.mjs` po builde, takže vo vývojovom serveri sa zalomenie môže mierne líšiť.

## Formulár

Formulár na `/kontakt/` aj „schéma zákazky“ na domovskej stránke odosielajú dopyt na `/dopyt.php`. Povinné je meno a telefón alebo e-mail, nič nie je predvolené, je tam honeypot a ochrana proti opakovanému odoslaniu. Do konzoly sa nič neloguje.

- **`public/dopyt.php`** prijme dopyt a pošle ho na **info@gridflow.sk** (pri zadanom e-maile je Reply-To na zákazníka). Vyžaduje hosting s PHP: obsah priečinka `dist/` sa nahrá na hosting tak, ako je (aj `.htaccess` pre Apache).
- **E-mail beží u iného poskytovateľa ako web**, preto sa má posielať cez **SMTP schránky info@gridflow.sk**: na hostingu sa vedľa `dopyt.php` vytvorí `dopyt-nastavenia.php` podľa vzoru `dopyt-nastavenia.example.php` (server, port, meno, heslo od poskytovateľa e-mailu). Správa potom prejde kontrolami SPF/DKIM/DMARC. Súbor s heslom nie je v gite (`.gitignore`) a `.htaccess` ho na webe nezobrazí.
- Bez `dopyt-nastavenia.php` (alebo keď SMTP zlyhá) sa použije `mail()` hostingu s odosielateľom `info@gridflow.sk`. Pri e-maile mimo hostingu to spoľahlivo funguje len vtedy, keď záznam SPF domény povoľuje aj servery hostingu; inak môžu správy skončiť v spame alebo sa nedoručiť. Chyby SMTP sa zapisujú do chybového logu PHP na hostingu (bez osobných údajov).
- **Na Cloudflare PHP nebeží**: `public/.assetsignore` zabráni nahratiu `dopyt.php` a `.htaccess`, takže na testovacej adrese na workers.dev formulár zobrazí chybu s telefónnym číslom. Iný cieľ (napríklad formulárovú službu) sa dá nastaviť premennou `PUBLIC_FORM_ENDPOINT` pri builde.
- Formulár odošle `POST` s `Content-Type: application/json`:

```json
{
  "name": "Ján Novák",
  "phone": "0910 000 000",
  "email": "",
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

## SEO

- Hlavička dokumentu (`src/layouts/Site.astro`): `title`, `description` do ~155 znakov, `robots`, kanonická adresa, Open Graph a Twitter karta s obrázkom `public/og-image.png` (1200 × 630), favicony (`favicon.ico` 16/32/48 px, `favicon.svg`, `favicon-96.png`, `favicon-192.png` a `apple-touch-icon.png`: logo „reversed“ na Grid Navy štvorci, aby bolo vidno vo výsledkoch Googlu na svetlom aj tmavom pozadí) a `site.webmanifest`. Stránka 404 má `noindex` a nemá kanonickú adresu.
- Štruktúrované údaje (JSON-LD): na domovskej stránke `Electrician` (firma, adresa, telefón, e-mail, IČO, DIČ, oblasť pôsobenia, služby), `WebSite` a `FAQPage`; na Kontakte a v zásadách `BreadcrumbList`. Hodnotenia ani recenzie sa nepridávajú, kým neexistujú skutočné.
- `sitemap.xml` (dátum poslednej zmeny = dátum buildu), `robots.txt` (odkaz na sitemap, `dopyt.php` vylúčený) a `llms.txt` (stručný opis firmy, služieb, kontaktu a častých otázok pre AI vyhľadávače, len fakty z webu).
- Po nasadení: overiť doménu v Google Search Console, odoslať `https://gridflow.sk/sitemap.xml` a založiť Google Business Profile.

## Nasadenie (Websupport)

1. `npm run build`. Doména je nastavená na `https://gridflow.sk` (bez www); inú sa dá zadať premennou `SITE_URL` pri builde.
2. Celý obsah priečinka `dist/` (aj skryté súbory `.htaccess` a `.assetsignore`) nahrať cez FTP do koreňového priečinka webu domény gridflow.sk.
3. Vo Webadmine skontrolovať, že je pri doméne aktívny SSL certifikát (Websupport ho zapína automaticky). `.htaccess` sám presmeruje `www` na `gridflow.sk`, `http` na `https` (pozná aj hlavičku `X-Forwarded-Proto` z proxy Websupportu) a `/kontakt` na `/kontakt/`; zapína kompresiu, cache a bezpečnostné hlavičky a pri neexistujúcej adrese zobrazí `404.html`.
4. Odoslať skúšobný dopyt z webu a skontrolovať doručenú poštu aj spam na info@gridflow.sk.

`.htaccess` bol overený na Apache 2.4 (presmerovania, 404, hlavičky). `public/_headers` a `.assetsignore` sú len pre Cloudflare (testovacia adresa na workers.dev); na Apache ich `.htaccess` nezobrazí.

## Prenos výberu na Kontakt

Výber služieb na domovskej stránke (len id volieb, bez osobných údajov) sa ukladá do `sessionStorage` pod kľúčom `gf-vyber` a formulár na `/kontakt/` ho po načítaní predvyplní. Tlačidlo „Potrebujem poradiť“ otvára `/kontakt/?vyber=poradit`. Formulár sa dá odoslať s menom a telefónom alebo e-mailom.

## Logá partnerov

Logá a fotka v sekciách Smart domácnosť a Partneri sú v `public/partners/`:

- `solax.png`: logo SolaX Power z repozitára značiek Home Assistant (home-assistant/brands). Pred ostrým nasadením overte s klientom, či ide o aktuálnu verziu loga.
- `homemaster.png` a `homemaster-miniplc.webp`: logo a fotka produktu z oficiálnych podkladov výrobcu HomeMaster (datasheet a partner kit pre predajcov). Podľa pravidiel výrobcu sa nesmie používať spojenie „Works with Home Assistant“ (povolené je „integruje sa s Home Assistant cez ESPHome“) a fotky sa nesmú prefarbovať.
- `deye.png`: logo Deye (latinská časť firemného loga Ningbo Deye) z repozitára značiek Home Assistant. Ak klient dodá oficiálny súbor loga pre meniče, stačí ho nahradiť pod rovnakým názvom.

## Čo ešte treba doplniť

Pôvodný zoznam údajov od klienta je v `docs/07-DOPLNIT-OD-KLIENTA.md`. Ďalej:

- schválenie loga (v `public/logo/` je kópia bez neviditeľných metadát, originály sú v `assets/logo/`),
- právna kontrola zásad ochrany osobných údajov,
- po nasadení Google Search Console a Google Business Profile.

## Kontrola kvality

Pri vývoji sa overovalo: bez chýb v konzole a bez vodorovného posunu na šírkach 360, 390, 768, 1024, 1440 a 1920 px, Lighthouse (mobil) výkon 99 až 100, prístupnosť 100, Best Practices 100, SEO 100 (stránka 404 má zámerne stavový kód 404 a `noindex`, preto jej SEO skóre nie je 100), a funkčnosť formulára (validácia, voľby, odoslanie, chybové stavy).
