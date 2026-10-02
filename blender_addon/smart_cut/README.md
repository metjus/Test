# Smart Cut (Blender addon)

Rozreže model podľa plynulej slučky, ktorú nakreslíš priamo na povrch. Hodí sa na delenie figúrok na tlačiteľné
diely tam, kde rez rovinou nestačí (ohyby rúk, krk). Rez ide po krivke, ktorú vidíš, a oba diely sa uzavrú.

## Inštalácia
`python scripts/build_addon.py smart_cut` vytvorí `dist-addon/smart_cut-0.6.0.zip`.
Blender: **Edit > Preferences > Get Extensions > (šípka vpravo hore) Install from Disk**.
V 3D okne stlač `N`, záložka **Smart Cut**.

## Postup
1. **Draw Cut Line**: vyber model, klikni na tlačidlo a ťahaj myšou po povrchu (oranžová čiara, biely bod = koniec).
   Čiara sa **nekončí pustením tlačidla**: stredným tlačidlom otoč pohľad a ťahaj ďalej, medzera medzi ťahmi sa
   premostí po povrchu. `Enter` čiaru dokončí, `Backspace` (alebo `Ctrl+Z`) zruší posledný ťah, `Esc` všetko zruší.
   **Continue Line** pokračuje v už hotovej otvorenej čiare od jej konca.
   V paneli „Adjust Last Operation" (vľavo dole) nastavíš **Smoothing** a **Control points**
   (menej bodov = plynulejšia, ľahšie upraviteľná krivka). Krivka je obyčajná Bezierova krivka.
2. **Complete Loop**: z nakresleného oblúka urobí uzavretú slučku okolo modelu, po povrchu cez druhú stranu.
   Ak zvolí zlú stranu, zapni **Other way round**.
3. **Úprava (nepovinné)**: pri vybranej krivke stlač `Tab`, presuň body (`G`) a vráť sa do Object Mode.
   **Snap Curve to Surface** vráti body späť na povrch modelu.
4. **Cut**: model sa rozreže na dva uzavreté diely. Hrana rezu sa prichytí presne na krivku. Plocha rezu je mriežka
   štvoruholníkov s hustotou ako okolitá sieť a je na oboch dieloch identická, takže do seba presne lícujú.
   **Edge precision** (predvolene 1) určuje, koľkokrát sa plochy pri reze delia pred prichytením hrany; vyššie
   hodnoty zlepšenie nepridajú, len pribudnú drobné trojuholníky. Pôvodný model sa skryje (nezmaže).

5. **Kolík na lepenie** (vyber jeden z dvoch dielov). Panel má tri hodnoty a tri tlačidlá:
   - **Peg size** — šírka štvorcového kolíka v mm (ak 1 jednotka = 1 mm). Predvolene 4,00. Ikonka vedľa poľa
     (**Fit to Cut**) ti doplní veľkosť vypočítanú z aktuálneho rezu, aby si mal od čoho začať.
   - **Taper** — šírka špičky voči základni (predvolene 0,96). Len na zavedenie, kolík dosadá po celej dĺžke.
   - **Hole clearance** — vôľa **na každej strane** medzi kolíkom a otvorom (predvolene 0,05). Riadok pod poľami
     rovno ukazuje výsledok, napríklad `Hole 4.10 (peg 4.00)`. Ak diely po tlači nejdú spolu, zvýš ju po 0,02.
   - **Add / Update Peg** umiestni jeden kolík ako drôtový obrys viditeľný cez model. Po zmene hodnoty klikni znova
     a kolík sa prekreslí (nehromadí sa).
   - **Flip Side** prehodí strany: kolík prejde na druhý diel a diera na ten, kde bol. Poloha ostáva.
   - Kolík posunieš klávesom **G**, prípadne zmeníš veľkosť cez **S**.
   - **Apply Peg** pripojí kolík k jeho dielu a do druhého vyreže otvor s nastavenou vôľou. Otvor je na dne
     o niečo hlbší, aby kolík nedosadol skôr, než sa stretnú plochy rezu.

## Zatiaľ nie je
- Voliteľná medzera medzi dielmi (ako pri rezaní rovinou s hrúbkou).
- Rez cez viac slučiek naraz.
- Interaktívne kreslenie nemá automatický test (potrebuje okno Blenderu). Všetko ostatné je pokryté testami.

## Testy
```
pip install bpy pytest numpy
python -m pytest tests -q
```
