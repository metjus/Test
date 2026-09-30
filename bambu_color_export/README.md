# Bambu Color Export (Blender add-on)

Exports your Blender model with its material colours so **Bambu Studio opens it
already painted**, one filament per colour.

## Install
1. Zip the `bambu_color_export` folder (the zip must contain the folder).
2. Blender → *Edit → Preferences → Get Extensions → ⌄ → Install from Disk…* → pick the zip.
   (Or drag the zip into the Blender window.) Requires Blender 4.2+.

## Use
1. Colour parts as you already do: a material with a **Principled BSDF** whose
   *Base Color* is set directly or through a **Color (RGB)** node. Diffuse/Emission
   shaders also work; anything else falls back to the material's *Viewport Display* colour.
2. Open the **Bambu** tab in the 3D Viewport sidebar (`N`). There is one row per
   object (named as in the Outliner; objects with several materials get one row per material):
   - **Colour**: click the swatch for Blender's colour picker (wheel, RGB/HSV, **Hex**).
     It edits the material's own colour (its Color node or Base Color), so viewport,
     render and export stay in sync. Rows with a chain icon share one material, so
     changing one changes them all;
   - **Filament**: the filament/AMS slot the part gets in Bambu Studio. Parts with the
     same colour share a slot automatically. Type a number to choose it yourself, 0 to go back to automatic;
   - objects without a material show a **+** button that gives them one.
3. Click **Export 3MF** (or *File → Export → Bambu Studio 3MF*).
4. Open the 3MF in Bambu Studio. It says *"The 3mf is not from Bambu Lab, load geometry
   data and color data only"*. That is expected for any file not saved by Bambu Studio;
   click OK. Bambu then opens its colour dialog: check the colour → filament matching
   (it can add missing filaments) and confirm. The model appears painted.

### Options
- **Scale**: 1 Blender unit = 1 mm by default. Enable *Use Scene Units* if you model in
  real metres.
- **Merge Same Colours / Colour Tolerance**: combine near-identical colours into one filament.
- **Export OBJ + MTL**: fallback. Bambu Studio shows its colour-mapping dialog for coloured OBJ files.

## Paint a single model
For one whole mesh that needs several colours, use the **Bambu Paint** panel (Bambu tab):
1. Select the mesh. Click **Add Colour** for each colour you need. Colour 1 is the base
   colour (unpainted areas); click a swatch to change a colour.
2. Pick a colour (click its name), choose **Brush** or **Fill**, set **Symmetry** X / Y / Z
   if the model is symmetric, then click **Start Painting**.
3. In the viewport:
   | Input | Action |
   |---|---|
   | LMB drag | paint with the active colour |
   | Shift + LMB | paint with the base colour (erase) |
   | 1 – 9 | pick colour |
   | `[` / `]` | brush radius |
   | F | switch Brush / Fill |
   | S | Fill: stop at sharp edges on/off |
   | X / Y / Z | toggle symmetry |
   | Ctrl+Z | undo last stroke |
   | H | show / hide the controls overlay |
   | MMB / wheel | navigate the view as usual |
   | Esc / Enter / RMB | finish |
   The controls are listed in the viewport while painting (H hides them) and in the
   panel's collapsible **Controls** section.
   **Fill options**: *Stop at Colour Change* fills only the clicked colour's area;
   *Stop at Sharp Edges* stops at creases bending more than *Sharp Angle* (default 30°)
   and at edges marked Sharp. Click a raised detail with it on to colour just that detail.
4. Export as usual. Painted areas become separate filaments.

Notes: painting colours whole faces, so edges follow the mesh. Subdivide (or remesh) low-poly
models for finer detail. Symmetry mirrors across the object's origin, so keep the origin
on the model's centre line.

## How it works
All selected objects are merged (modifiers applied) into one mesh. Each triangle gets:
- a colour from a standard 3MF colour group (`m:colorgroup`). Bambu Studio reads this and
  shows its colour-to-filament dialog;
- Bambu's per-triangle `paint_color` filament code (the panel's Filament number), used
  if you cancel that dialog.
