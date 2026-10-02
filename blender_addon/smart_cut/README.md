# Smart Cut (Blender addon)

Rozreže model podľa plynulej slučky, ktorú nakreslíš priamo na povrch. Hodí sa na delenie figúrok na tlačiteľné
diely tam, kde rez rovinou nestačí (ohyby rúk, krk). Rez ide po krivke, ktorú vidíš, a oba diely sa uzavrú.

## Inštalácia
`python scripts/build_addon.py smart_cut` vytvorí `dist-addon/smart_cut-0.4.0.zip`.
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

5. **Kolíky na lepenie** (vyber jeden z dvoch dielov):
   - Predvolený tvar je **štvorcový kolík, ktorý sa smerom k špičke mierne zužuje** (**Taper**, predvolene 0,96 — len na zavedenie, aby kolík dosadal po celej dĺžke),
     ako sa používa pri figúrkach tlačených po častiach. Štvorec sa natočí podľa dlhšej strany plochy rezu, takže
     nemôže byť zasunutý otočený. Voľba **Shape** prepne na okrúhly kolík.
   - **Add Connectors** umiestni kolíky na plochu rezu ako **drôtové obrysy viditeľné cez model**, ktoré vidíš a môžeš posunúť (`G`)
     alebo zmeniť ich veľkosť (`S`) ešte pred aplikovaním. Počet, priemer a dĺžka sa dajú nastaviť v paneli
     „Adjust Last Operation" (0 = automaticky podľa veľkosti rezu). **Alternate sides** dá kolíky striedavo na oba diely.
   - **Apply Connectors** pripojí každý kolík k jeho dielu a do druhého dielu vyreže otvor s vôľou **Clearance**
     **na každej strane** (predvolene 0,05; mm, ak 1 jednotka = 1 mm). Pri 4 mm kolíku má otvor 4,10 mm, čiže spoj je
     tesný a ostane v ňom len film na CA lepidlo. Ak diely po tlači nejdú spolu, zvýš vôľu po 0,02.
     Otvor je na dne o niečo hlbší, aby kolík nedosadol skôr, než sa stretnú plochy rezu.
   - Kolíky smerujú v smere osi rezu a sú rovnobežné, takže sa diely zasunú jedným pohybom.

## Zatiaľ nie je
- Voliteľná medzera medzi dielmi (ako pri rezaní rovinou s hrúbkou).
- Rez cez viac slučiek naraz.
- Interaktívne kreslenie nemá automatický test (potrebuje okno Blenderu). Všetko ostatné je pokryté testami.

## Testy
```
pip install bpy pytest numpy
python -m pytest tests -q
```
