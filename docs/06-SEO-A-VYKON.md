# 06 · SEO a výkon

## Meta údaje
| Stránka | `<title>` | Popis (do ~155 znakov) |
| --- | --- | --- |
| `/` | Revízne správy a projektová dokumentácia elektrických zariadení \| GridFlow | Revízne správy a projektová dokumentácia elektrických zariadení. OPaOS E1A, E1B pre domy, byty, rozvádzače, bleskozvody, fotovoltiku, NN prípojky a EV nabíjačky. Celé Slovensko. |
| `/kontakt/` | Kontakt a nezáväzný dopyt na revíziu \| GridFlow | Zavolajte alebo pošlite krátky dopyt na revíziu elektrického zariadenia. Pôsobnosť: celé Slovensko. |
| `/zasady-ochrany-osobnych-udajov/` | Zásady ochrany osobných údajov \| GridFlow | Informácie o spracúvaní osobných údajov GridFlow s.r.o. |

Jeden `<h1>` na stránku, logická hierarchia nadpisov, `lang="sk"`, kanonická adresa, `meta viewport`, `theme-color #022253`, Open Graph a Twitter karta (obrázok 1200 × 630 doplniť; dočasne `assets/logo/icon-512.png`), favicony (`assets/logo/`).

## Štruktúrované údaje (JSON-LD)
`ProfessionalService` (alebo `Electrician`) s údajmi: názov GridFlow s.r.o., telefón `+421910635595`, adresa Buková ulica 1309/23, 951 12 Ivanka pri Nitre, `areaServed`: Slovensko, popis služieb. Pridaj `FAQPage` pre sekciu Časté otázky (len odpovede, ktoré sú aj na stránke). **Nepridávaj hodnotenia ani recenzie, kým neexistujú skutočné.**

## Technické SEO
- `sitemap.xml` a `robots.txt` (odkaz na sitemap), HTTPS, presmerovanie `www` na jednu verziu, vlastná 404.
- Čisté adresy bez diakritiky, interné odkazy medzi stránkami, popisné `alt` pri obrázkoch (dekoratívne SVG `aria-hidden`).
- Telefón vždy ako `tel:+421910635595`.
- **Google Search Console** (overenie domény, odoslanie sitemap) a **Google Business Profile** pre lokálne vyhľadávanie (názov, adresa, oblasť pôsobnosti, kategórie), po nasadení ich nastaví klient alebo ty.
- Kľúčové témy: revízna správa, revízia elektroinštalácie, OPaOS, revízia bleskozvodu, revízia fotovoltiky, revízia NN prípojky, revízia EV nabíjacej stanice, projektová dokumentácia elektro. Do budúcna samostatné podstránky pre fotovoltiku, NN prípojky a EV nabíjačky.

## Výkon
- Cieľ: LCP < 2.5 s, CLS < 0.1, INP < 200 ms na mobile.
- Písma: len použité rezy a subsety (latin + latin-ext), `font-display: swap`, preload najdôležitejších. Logo a ikony ako SVG, žiadne rastrové obrázky v hero.
- CSS bez nepoužitých pravidiel, minimálny JS, žiadne knižnice na animácie.
- Hlavička používa `backdrop-filter`. Na slabých zariadeniach skontroluj plynulosť a v prípade potreby efekt zjednoduš.

## Zabezpečenie
- Bezpečnostné hlavičky (CSP, `X-Content-Type-Options`, `Referrer-Policy`), žiadne tajné kľúče v kóde, formulár cez server, nie priamo z prehliadača do e-mailu.
