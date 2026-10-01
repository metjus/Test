# GridFlow – prezentačný web (zadanie pre Claude Code)

Slovenský, **čisto prezentačný** web pre GridFlow s.r.o. (revízny technik podľa § 24, rozsah E1A a E1B, pôsobnosť celé Slovensko). Cieľom webu je, aby návštevník **zavolal alebo poslal dopyt**. Nie je to e-shop, portál ani aplikácia.

## Začni tu
1. Prečítaj `docs/01-ZADANIE.md` (rozsah, technológie, postup, kritériá prijatia).
2. Otvor `reference/static/index.html` v prehliadači (Chromium) a prejdi `kontakt.html` aj `zasady.html`. **Toto je vizuálny zdroj pravdy.** Snímky sú v `reference/screens/`.
3. Presné hodnoty (farby, písma, rozmery) sú v `docs/02-DIZAJN.md` a v CSS referenčných stránok.
4. Texty sú v `docs/03-OBSAH-SK.md`. Nič si nevymýšľaj.
5. Animácie: `docs/04-ANIMACIE.md`. Formulár a zásady: `docs/05-FORMULAR-A-ZASADY.md`. SEO: `docs/06-SEO-A-VYKON.md`.
6. Čo musí doplniť klient: `docs/07-DOPLNIT-OD-KLIENTA.md`.

## Pravidlá
- Jazyk webu: **iba slovenčina** (`lang="sk"`). Slová typu „k elektrickému“ a „§ 24“ sa nesmú zalomiť osamote (nezlomiteľná medzera).
- **Neprepisuj texty od klienta** a nepridávaj nepravdivé tvrdenia (recenzie, počty zákazníkov, odpočítavanie, „posledné voľné termíny“). Čiarkované zástupné polia „DOPLNIŤ: …“ nechaj viditeľné, kým klient nedodá údaje.
- Dodrž brand guide: farby Grid Navy `#022253` a Flow Cyan `#02ACC1`, bez glow, tieňov a 3D na logu, bez zámeny farieb Grid / Flow, bez „s.r.o.“ v marketingovom logu. Logo zostáva presne podľa `assets/logo/`.
- Písma (Sora, Michroma) **hosťuj lokálne** (`assets/fonts/`), nenačítavaj z Googlu.
- Dostupnosť: kontrast, klávesnica, viditeľný focus, `prefers-reduced-motion`.
- Nepoužívaj cookies ani analytiku bez rozhodnutia klienta. Ak sa pridajú, doplň ich do zásad ochrany údajov.
- Pred každou väčšou zmenou štruktúry sa krátko spýtaj, ak niečo v zadaní chýba.

## Stav projektu
Web je postavený v Astro (statický výstup). Príkazy, štruktúra, formulár a nasadenie sú v `README.md`. `reference/` slúži už len ako vizuálna referencia, zdroj pravdy pre kód je `src/`.
