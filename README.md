# Dokumenty

Súkromný archív zmlúv a dokumentov. Všetko ostáva **len v zariadení** (IndexedDB), bez servera, bez účtu
a bez platených API. Beží ako PWA: na iPhone „Pridať na plochu", na Windows/Macu „Inštalovať appku".

## Čo vie (MVP)
- Pridať PDF alebo fotku (aj priamo z fotoaparátu), OCR v zariadení (slovenčina + angličtina)
- Pravidlový návrh údajov: typ, kategória, protistrana, dátum podpisu, platnosť do, výpovedná lehota
- Dashboard s pásom **Pozor** (končiace viazanosti / výpovedné lehoty) a farebným zvýraznením
- Vyhľadávanie v prirodzenej vete („nájdi mi zmluvu k telekomu"), bez diakritiky, s toleranciou skloňovania
- **Aktualizovať**: nová verzia dokumentu, stará ostáva v histórii

- **Zálohy**: jeden šifrovaný súbor `.dokbackup` (AES-256-GCM, kľúč z hesla), export aj obnova; obnova dáta len zlučuje, nič nemaže
- Pripomienka v dashboarde, ak je posledná záloha staršia ako 30 dní

## Spustenie
```
npm install
npm run dev        # vývoj
npm run build      # produkčný build do dist/
npm run preview    # vyskúšanie buildu
npm test           # testy extrakcie a vyhľadávania
```
OCR engine a jazykové dáta sa pri `dev`/`build` skopírujú do `public/ocr` (nie sú v gite) a servíruje ich appka sama.

## Súkromie
Do repozitára nikdy nepatria skutočné dokumenty (`.gitignore` blokuje `*.pdf`, `zalohy/`). Na testovanie používaj vymyslené dáta.

## Plán
Synchronizácia telefón ↔ PC (WebRTC, párovanie cez QR).
