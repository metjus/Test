# Split by Color (Blender addon)

Rozdelí zafarbený model (napr. z Tripo AI, export OBJ + MTL + textúra) na samostatné diely podľa farby.
Určené na viacfarebnú 3D tlač: každý diel je samostatný objekt s vlastným materiálom.

## Inštalácia
1. `python scripts/build_addon.py` vytvorí `dist-addon/split_by_color-0.1.0.zip`
2. Blender: **Edit > Preferences > Get Extensions > (šípka vpravo hore) Install from Disk** a vyber ZIP.
3. V 3D okne stlač `N`, záložka **Split Color**.

## Použitie
1. Importuj OBJ (File > Import > Wavefront). Textúra musí ležať vedľa `.mtl`.
2. Vyber model, klikni **Preview (materials)**. Model dostane jeden materiál na farbu.
3. V paneli „Adjust last operation" (vľavo dole) dolaď:
   - **Color tolerance**: vyššia, ak sa jedna farba rozpadla na viac, nižšia, ak sa rôzne farby zliali
   - **Max colors**: horný limit počtu farieb (0 = koľko sa nájde)
   - **Min patch size**: drobné škvrny menšie ako toto sa pripoja k susedovi
   - **Merge blended edges**: rozmazané prechody medzi dvoma farbami nebudú samostatnou farbou
4. Keď to sedí, klikni **Split into objects**. „Split disconnected patches" oddelí aj nesúvislé miesta
   rovnakej farby (napr. obe oči zvlášť).

## Tipy pre Tripo
Exportuj s plochými farbami bez tieňov a odleskov. Čím čistejšie plochy, tým presnejšie delenie.

## Testy
```
pip install bpy pytest        # bpy = Blender ako Python modul (Python 3.11)
python -m pytest tests -q
```
