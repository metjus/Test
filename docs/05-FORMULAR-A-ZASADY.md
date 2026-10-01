# 05 · Formulár a zásady ochrany údajov

## Kontaktný formulár („smart default“)
Cieľ: čo najmenej písania a čo najmenej rozhodovania. Predvolené sú najpravdepodobnejšie voľby, človek len doplní **meno a telefón**.

Poradie polí na jednej obrazovke (číslované kruhy 1 až 7):
1. **Kam sa vám môžem ozvať?** Meno (povinné, aspoň 2 znaky), Telefón (povinný, aspoň 9 číslic, povolené `+`, medzery, pomlčky; `type="tel"`, `inputmode="tel"`, `autocomplete="tel"`)
2. **Čo potrebujete zrevidovať?** (viac možností) Revízia elektroinštalácie *(predvolene vybrané)*, Bleskozvod, Fotovoltika / NN prípojka / EV nabíjačka, Projekt alebo kompletné riešenie, Neviem, poraďte mi *(vylučuje ostatné)*
3. **Na aký účel?** (nepovinné, viac možností) Kolaudácia, Poistná udalosť, Pripojenie do siete, Rekonštrukcia, Kontrola bezpečnosti
4. **Obec alebo mesto** (nepovinné, `autocomplete="address-level2"`)
5. **Ako sa vám ozvať?** Zavolať mi *(predvolene)*, Napísať SMS
6. **Kedy sa vám ozvať?** Kedykoľvek *(predvolene)*, Dopoludnia, Popoludní
7. **Poznámka** (nepovinné) so zástupným textom „Napríklad rozsah, termín alebo čo už máte hotové“

Správanie:
- Tlačidlo **Odoslať dopyt** je neaktívne, kým nie je meno aj telefón platný. Vedľa je vysvetlenie („Odoslať sa dá po vyplnení mena a telefónu“).
- Ak nie je vybraná žiadna služba, ber to ako „Neviem, poraďte mi“.
- Čipy sú tlačidlá s `aria-pressed`; skupiny majú čitateľné nadpisy.
- Po odoslaní: poďakovanie („Ďakujem, dopyt je odoslaný“), zhrnutie voľby, `[DOPLNIŤ: do koľkých hodín sa ozvete]` a tlačidlo „Poslať ďalší dopyt“.
- Chyba: zrozumiteľná slovenská hláška pri poli a pri zlyhaní odoslania aj náhradná cesta (zavolajte na 0910 635 595).
- Pod tlačidlom: „Dopyt vás k ničomu nezaväzuje. Údaje použijem len na vybavenie dopytu. Viac v Zásadách ochrany osobných údajov.“ (odkaz).

Odoslanie (návrh):
- `POST` na serverless funkciu alebo formulárovú službu, telo JSON: `{ name, phone, services[], purposes[], town, contactMethod, contactTime, note, page, ts }`.
- Ochrana pred spamom: skryté pole (honeypot), obmedzenie počtu žiadostí, voliteľne neviditeľná CAPTCHA (rozhodne klient, doplniť do zásad ochrany údajov).
- E-mail klientovi: predmet „Nový dopyt: {služby} ({obec})“, v tele všetky polia, telefón ako odkaz `tel:`.
- Nelogovať osobné údaje do konzoly ani do verejných nástrojov.
- Kým klient nedodá e-mail (`[DOPLNIŤ: e-mail]`), formulár nespúšťaj ostro: zobraz len telefón a tlačidlo „Zavolať“.

## Zásady ochrany osobných údajov
Hotový **návrh textu** je v `docs/03-OBSAH-SK.md` a v `reference/static/zasady.html` (9 bodov: prevádzkovateľ, údaje, účel a právny základ, príjemcovia, doba uchovávania, práva, povinnosť poskytnúť údaje, cookies, zmeny). Dozorný orgán: Úrad na ochranu osobných údajov Slovenskej republiky, Hraničná 12, 820 07 Bratislava 27.

**Text nie je právna rada.** Pred zverejnením ho musí skontrolovať právnik a klient doplní: e-mail, zápis v obchodnom registri, dobu uchovávania, zoznam sprostredkovateľov (hosting, e-mail, formulárová služba), cookies a analytiku, dátum platnosti. Ak sa pridá analytika, mapa alebo iný skript tretej strany, treba doplniť zásady a podľa potreby súhlas s cookies.
