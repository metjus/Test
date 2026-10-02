# Gumroad: všetko na vyplnenie produktu

Texty sú po anglicky (pre zákazníkov), vysvetlivky po slovensky.
Postupuj zhora nadol, poradie zodpovedá formuláru na Gumroade.

---

## 1. Name (názov)

```
History Timeline for Blender
```

## 2. URL (vlastná adresa produktu)

```
history-timeline
```

Výsledok bude napr. `tvojemeno.gumroad.com/l/history-timeline`.

## 3. Description (hlavný popis)

Skopíruj celý text medzi čiarami. Gumroad nezoberie Markdown automaticky, takže
nadpisy (riadky so `###`) potom označ a nastav ako nadpis v jeho editore, a hviezdičky
`**...**` nahraď tučným písmom.

---

**Undo that survives closing Blender.**

Blender forgets your undo history the moment you close a file. History Timeline doesn't. Every change you make becomes a step on a visual timeline in the status bar, saved to disk next to your .blend. Click any step to go back to it, or forward again, whether that's five minutes later or next week.

### Go back to any point, any time

- Every edit (move, extrude, bevel, modifier, material change and so on) becomes a step on the timeline automatically
- Click a step to restore it. Later steps aren't deleted: they turn grey and stay one click away
- Changed your mind for good? Go back to a step and delete everything after it (with a confirmation)
- Closed without saving, or Blender crashed? When you reopen the file, your recent steps are still on the timeline
- Hover a step to see what it was, which object it touched and when

### Ctrl+Z that keeps going

- Ctrl+Z works exactly as always while you work, and the timeline follows it
- After reopening a file, Blender's own undo history is empty. With History Timeline, Ctrl+Z simply continues back through your saved steps, and Ctrl+Shift+Z goes forward again
- You can turn this off, and then Ctrl+Z is Blender's standard undo

### Checkpoints

- Save a named state ("Blockout done", "Before boolean") with one click
- Checkpoints are never cleaned up automatically

### Clean history, no noise

- Selecting, orbiting the view, switching modes and tools you cancel don't create steps. Only real changes do
- A searchable, paged list of all steps in the sidebar (N panel), with rename, pin and delete

### Small on disk

Steps are not full copies of your file. History Timeline stores only the parts of the file that actually changed, deduplicated and compressed.

- On a 317 MB scene, moving an object added 0.13 MB and editing one vertex added 0.19 MB
- 10,000 steps of a 10.6 MB scene took 305 MB. Full copies would have taken 106 GB
- You set the limits (max steps and disk space per file). Older steps are cleaned up automatically, and pinned steps and checkpoints are always kept

*Measured with Blender 4.2 on test scenes. Your numbers depend on how much each step changes. The first step stores the whole file once, compressed.*

### FAQ

**Does it replace Blender's undo?**
No. Ctrl+Z is Blender's normal undo while you work. The timeline only takes over when Blender has nothing left to undo, for example after reopening a file. You can switch that off.

**Will it work with my existing projects?**
Yes. Open any .blend file and the timeline starts recording from that moment.

**Does it slow Blender down?**
For typical scenes you won't notice it. Compression runs in the background. On very large scenes (hundreds of MB) there is a short pause when a step is recorded, because Blender writes the file once.

**Where is my history stored?**
In a folder next to your file (`yourfile_history`), or in a folder of your choice set in the preferences.

### Requirements

- Blender 4.2 or newer (installs as a Blender extension)
- No external dependencies

### Installation

1. Download the .zip file
2. In Blender: Edit > Preferences > Get Extensions > the ▾ menu at the top right > Install from Disk
3. Pick the .zip. The timeline appears in the status bar at the bottom of the window

### Good to know

- To restore a step, the file must have been saved at least once. Recording starts right away, even for unsaved files
- Restoring a step reloads the file. On very large scenes that takes a moment, like opening the file
- When you restore a step, your previous file is kept as `yourfile.blend1`, just like Blender's own backups

---

## 4. Cover (obrázky na stránke produktu)

Nahraj v tomto poradí (súbory sú v tomto priečinku):

1. `01-hero.png`
2. `02-interface.png`
3. `05-undo.png`
4. `03-rollback.png`
5. `04-storage.png`

Ak neskôr nahráš krátke video (napr. tých 20 sekúnd zatvoriť a znova otvoriť),
daj ho ako **prvé**, pred obrázky.

## 5. Thumbnail (štvorcový náhľad)

`thumbnail.png` (1200×1200). Zobrazuje sa v knižnici zákazníka a v Gumroad Discover.

## 6. Call to action (text tlačidla)

Vyber z ponuky: **"I want this!"** (pôsobí prirodzene) alebo **"Buy this"**.

## 7. Summary (riadok „You'll get…“)

```
History Timeline for Blender 4.2 and newer (Blender extension, .zip)
```

## 8. Additional details (dvojice kľúč / hodnota)

| Key | Value |
|---|---|
| Blender version | 4.2 or newer |
| Format | Blender extension (.zip) |
| Version | 1.6.0 |
| Install | Edit > Preferences > Get Extensions > Install from Disk |

## 9. Price (cena)

Nechávam na tebe. Pri doplnkoch tohto typu býva bežné 10 až 25 USD.
Môžeš zapnúť aj **"Allow customers to pay more"**, niektorí ľudia radi prispejú viac.

## 10. Tags (Discover)

```
blender, blender addon, blender extension, undo, history, 3d modeling, b3d, workflow
```

Kategória: **3D**, ak je ponuka podrobnejšia, tak **3D > Blender** alebo **3D Modeling**.

## 11. Content (čo kupujúci uvidí po nákupe)

Sem nahraj súbor `history_timeline-1.6.0.zip` a pod neho daj tento text:

---

**Thank you for getting History Timeline!**

**Install**

1. Download `history_timeline-1.6.0.zip` above (don't unzip it)
2. In Blender 4.2 or newer: Edit > Preferences > Get Extensions > the ▾ menu at the top right > Install from Disk
3. Pick the .zip. The timeline appears in the status bar at the bottom of the window

**Getting started**

- Save your file once, then just work. Every change appears as a step on the timeline
- Click a step to go back to it. Hover a step to see what it was
- Press N in the 3D Viewport and open the **History** tab for the full list, checkpoints and "Go Back Here, Delete Later Steps"
- After reopening a file, Ctrl+Z keeps going back through the timeline
- Settings: Edit > Preferences > Add-ons > History Timeline

**Updating to a new version**

Remove the old version in Edit > Preferences > Add-ons, then install the new .zip the same way. Your saved history stays where it is.

**Questions or problems?**

Write to me at [tvoj e-mail]. Please include your Blender version and what happened.

---

## 12. Receipt (poznámka v potvrdení e-mailom)

Pole „Custom receipt note“ (alebo podobne nazvané v nastaveniach produktu):

```
Thanks for supporting an independent Blender add-on! Install it via Edit > Preferences > Get Extensions > Install from Disk. If anything doesn't work, just reply to this email.
```

## 13. Refund policy (vrátenie peňazí)

Rozhodnutie je na tebe. Keďže ide o digitálny súbor, je bežné jedno z týchto:

- **„30-day money back guarantee“**: buduje dôveru, zneužíva sa málo.
- **„No refunds“**: bežné pri digitálnych produktoch, ale môže odradiť váhajúcich.

Pri prvom produkte by som odporučil 30 dní: znižuje strach z nákupu a pri doplnku,
ktorý funguje, sa vracia málo.

---

## Pred zverejnením skontroluj

- [ ] Doplnený e-mail v časti 11 (`[tvoj e-mail]`)
- [ ] Nahraný súbor `history_timeline-1.6.0.zip` v časti Content
- [ ] Nastavená cena
- [ ] Gumroad má funkciu **Preview**: pozri si stránku ako zákazník, než ju zverejníš
- [ ] Ideálne aspoň jeden skutočný screenshot z tvojho Blenderu medzi obrázkami
