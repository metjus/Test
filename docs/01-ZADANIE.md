# 01 · Zadanie

## Čo staviame
Prezentačný web GridFlow s.r.o.: predstaviť službu (revízne správy, projektová dokumentácia, kompletné riešenie), vzbudiť dôveru a priviesť človeka k hovoru alebo k odoslaniu dopytu.

**Čisto prezentačný** znamená:
- žiadny e-shop, platby, prihlásenie, účty, blog ani redakčný systém,
- obsah sa mení zriedka (nasadzuje sa cez nový build),
- jediná „dynamická“ vec je kontaktný formulár, ktorý odošle dopyt e-mailom (pozri `05-FORMULAR-A-ZASADY.md`).

## Stránky
| Súbor | Adresa | Obsah |
| --- | --- | --- |
| `index.html` | `/` | Jedna dlhá stránka so sekciami: hero, služby, kedy, postup, kompletné riešenie, kto vás bude revidovať, časté otázky, záverečný pruh, päta |
| `kontakt.html` | `/kontakt/` | Samostatná stránka: údaje, formulár (smart default), „Čo bude nasledovať“ |
| `zasady.html` | `/zasady-ochrany-osobnych-udajov/` | Zásady ochrany osobných údajov (návrh textu) |
| 404 | | Jednoduchá stránka v rovnakom štýle (logo, veta, odkaz domov a telefón) |

Menu v hlavičke: Služby, Kedy ju potrebujete, Postup, Časté otázky (kotvy na hlavnej stránke), telefón a tlačidlo **Kontakt** (samostatná stránka). Na podstránkach logo vedie späť na hlavnú stránku (tlačidlo „Späť na web“ nie je).

## Mimo rozsahu
Viac jazykov, blog, CMS, e-shop, rezervačný systém, chat, CRM, vlastný backend s databázou.

## Odporúčané technológie
- **Astro (statický výstup)**, čistý CSS (premenné z `02-DIZAJN.md`), minimálny vanilla JS. Alternatíva: ručne písané statické HTML/CSS/JS. Dôvod: web je malý, rýchly a SEO-priateľský bez frameworku.
- Odosielanie formulára: serverless funkcia alebo formulárová služba (Formspree, Netlify Forms, Cloudflare Pages Function + e-mail). Rozhodnutie podľa hostingu.
- Hosting: Cloudflare Pages, Netlify alebo bežný webhosting s HTTPS. Doménu zaobstará klient.
- Nasadenie cez git (priebežná verzia, jednoduché vrátenie zmien).

## Odporúčaný postup
1. Založ projekt, nastav tokeny a lokálne písma (`assets/`).
2. Spoločné časti: hlavička, päta, tlačidlá, čipy, karty, ikony (`assets/icons/sprite.svg`).
3. Hlavná stránka sekciu po sekcii podľa `reference/static/index.html`.
4. Kontakt a zásady.
5. Animácie (`04-ANIMACIE.md`) vrátane záložného riešenia a `prefers-reduced-motion`.
6. Formulár (validácia, odoslanie, chybové stavy, ochrana pred spamom).
7. SEO a výkon (`06-SEO-A-VYKON.md`).
8. Kontrola kritérií prijatia, potom nasadenie.

## Kritériá prijatia
- Vzhľad zodpovedá referencii na šírkach 360, 390, 768, 1024, 1440 a 1920 px, bez horizontálneho posunu.
- Lighthouse (mobil): Výkon ≥ 90, Prístupnosť ≥ 95, SEO ≥ 95, Best Practices ≥ 95.
- Bez chýb v konzole, platné HTML, všetky odkazy fungujú (`tel:` odkazy otvoria vytáčanie).
- Plná ovládateľnosť klávesnicou, viditeľný focus, kontrast aspoň WCAG AA, `prefers-reduced-motion` vypne animácie a všetko je čitateľné.
- Formulár: povinné len meno a telefón, chybové hlášky po slovensky, úspešný stav, ochrana pred spamom, odkaz na zásady.
- Pri vypnutom JS je celý obsah čitateľný (animácie sú vylepšenie, nie podmienka).
- Zástupné polia „DOPLNIŤ“ sú viditeľné, kým klient nedodá údaje (zoznam v `07-DOPLNIT-OD-KLIENTA.md`).
