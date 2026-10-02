# Smart Cut (Blender addon)

Rozreže model podľa plynulej slučky, ktorú nakreslíš priamo na povrch. Hodí sa na delenie figúrok na tlačiteľné
diely tam, kde rez rovinou nestačí (ohyby rúk, krk). Rez ide po krivke, ktorú vidíš, a oba diely sa uzavrú.

## Inštalácia
`python scripts/build_addon.py smart_cut` vytvorí `dist-addon/smart_cut-0.1.0.zip`.
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
4. **Cut**: model sa rozreže na dva uzavreté diely. **Edge precision** určuje, ako presne hrana rezu sleduje krivku
   (viac = presnejšie, ale viac plôch pri rezu). Pôvodný model sa skryje (nezmaže).

## Zatiaľ nie je
- Kolíky a otvory na spájanie dielov.
- Rez cez viac slučiek naraz.
- Interaktívne kreslenie nemá automatický test (potrebuje okno Blenderu). Všetko ostatné je pokryté testami.

## Testy
```
pip install bpy pytest numpy
python -m pytest tests -q
```
