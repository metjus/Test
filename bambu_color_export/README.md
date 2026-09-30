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
2. Open the **Bambu** tab in the 3D Viewport sidebar (`N`). It lists every material
   with its hex colour and filament slot (F1, F2, …). Set *Filament* on a material to
   force a slot; 0 = automatic. Materials with the same colour share a slot.
3. Click **Export 3MF** (or *File → Export → Bambu Studio 3MF*).
4. In Bambu Studio open the 3MF, add as many filaments as the export reported, and set
   their colours to the hex values shown in Blender. The model appears painted, with each
   part assigned to its filament.

### Options
- **Scale**: 1 Blender unit = 1 mm by default. Enable *Use Scene Units* if you model in
  real metres.
- **Merge Same Colours / Colour Tolerance**: combine near-identical colours into one filament.
- **Export OBJ + MTL**: fallback. Bambu Studio shows its colour-mapping dialog for coloured OBJ files.

## How it works
All selected objects are merged (modifiers applied) into one mesh. Each triangle
gets Bambu's per-triangle `paint_color` filament code, plus a standard 3MF base
material so other viewers also show the colours.
