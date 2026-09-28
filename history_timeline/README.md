# History Timeline for Blender

A **visual history timeline** for Blender. Every change you make
becomes an icon on a timeline strip, and any icon can be clicked to go back
(or forward) to that state, **even after Blender was closed and the file
reopened**.

Blender's own undo stack lives only in memory and is gone once you close the
file. This add-on keeps the history on disk, so it's permanent. It does
**not** keep a full `.blend` copy per step. Snapshots are deduplicated, so
each step only stores what changed (see *Disk usage* below).

## Install

Requires Blender 4.2 or newer.

1. Build the extension zip. With Blender on your PATH, run
   `blender --command extension build --source-dir history_timeline`,
   which gives you `history_timeline-<version>.zip`.
   You can also zip the *contents* of the folder yourself, with
   `blender_manifest.toml` at the top level of the zip.
2. In Blender, go to *Edit > Preferences > Get Extensions*, open the ▾ menu, and choose
   *Install from Disk…*. Pick the zip. You can also drag the zip onto Blender.
3. It appears under *Add-ons* as **History Timeline**, enabled.

## Using it

| Where | What |
|---|---|
| **Status bar** (bottom of the window) | The timeline strip. Each icon is one step, and hovering it shows the name, active object and time. Click an icon to restore that state. ⏮ ◀ ▶ ⏭ move the marker. |
| **3D View > Sidebar (N) > History** | The strip, a searchable list of all steps, and Restore / Rename / Pin / Delete for the selected step, plus *Checkpoint*, *Open Folder* and *Clear*. |
| **Edit > History Timeline** | Roll Back / Roll Forward / Checkpoint. |
| `Ctrl Alt Z` / `Ctrl Alt Shift Z` | Roll back / roll forward one step. |

Timeline icons show what kind of step it was: ➕ add, 🗑 delete, move/rotate/scale,
modifier, edit mode, sculpt, material/nodes, property edit, 🔖 manual checkpoint,
and file opened.

### Rolling back with the timeline marker

* Restoring an older step **doesn't delete anything**. The marker moves back
  and later steps turn grey ("rolled back"), and you can click one to roll forward.
* If you keep working after a rollback, the new steps are appended after a
  small gap (a branch). The rolled-back states are still there and still clickable.
* Any change that hasn't been recorded yet is captured before a restore, so
  a restore can always be undone from the timeline.

### After closing Blender

History is stored next to the file in `<name>_history/` (see *Disk usage*).
When you reopen the file:

* The marker sits on the step that matches the saved file.
* Steps made **after the last save** (work you closed without saving) show
  as rolled back. Click one to get that work back.
* If the file was changed outside the add-on, an *Opened* step is added
  first so the current state is never lost.

Unsaved (untitled) files are recorded in a temp folder. The history moves next to
the file on its first save. *Save As* copies the history to the new name.

## Preferences

*Edit > Preferences > Add-ons > History Timeline*

* **Record History**: turn automatic recording on or off. The checkbox is also in the panel header.
* **Idle Delay**: how long after the last change a snapshot is written.
* **Also Ignore**: extra operator patterns that should never create a step
  (selection, view navigation, mode switches etc. are ignored already).
* **Max Steps** and **Disk Quota (MB)**: the oldest unpinned steps are deleted beyond
  either limit (defaults: 200 steps, 2048 MB per file). Pinned steps, checkpoints
  and the current step are always kept.
* **History Folder**: store all histories in one place instead of next to each file.
* **Timeline Strip**: show it in the Status Bar, the 3D View header, or the sidebar only.
* **Visible Steps**: how many icons the strip shows before scrolling.

## Disk usage

Each step is stored as deduplicated, compressed chunks, not as a copy of the file:

* The saved `.blend` is cut at Blender's own data-block boundaries. Every
  piece is stored once (zlib-compressed, named by its SHA-1) in `chunks/`,
  and a step is only a small manifest in `manifests/` listing its pieces.
* Blender writes unchanged data blocks byte-for-byte the same, so a step
  only adds the blocks that changed. Big arrays (mesh data, images) are
  split into 256 KiB pieces, so a local edit rewrites only one piece.
* Deleting or pruning steps removes chunks that no step uses any more.

Measured on a 317 MB file with 6 high-poly meshes:

| Step | Added to disk |
|---|---|
| First step (whole file, compressed) | 108 MB |
| Reopen file + move an object | 0.13 MB |
| Edit one vertex | 0.19 MB |
| Add a cube | 0.03 MB |

Folder layout: `<name>_history/history.json`, `manifests/step_#####.step`,
`chunks/xx/<hash>`. A step's manifest is itself stored as deduplicated
pieces, so it's only a few hundred bytes, even for a 300 MB file.

### Long histories (10,000 steps)

Simulated with 10,000 real captures on a 10.6 MB file (three meshes of 130k
vertices, with moves, rotations, scales and vertex edits in rotation), with no limits:

| Steps | History on disk | Time per step (main thread) |
|---|---|---|
| 1 | 3.7 MB | ~35 ms |
| 1,000 | 33 MB | ~40 ms |
| 10,000 | 305 MB (≈30 KB per step) | ~80 ms |

* Every one of the 10,000 steps can be restored, and a step rebuilds in about 0.1 s.
  Reference counts were checked against a full rescan at every 1,000 steps and
  never drifted.
* Disk use grows linearly with how much each step changes, not with file size.
  Edits touching a large part of a big mesh (sculpting, applying a modifier,
  remeshing) cost more, up to the compressed size of the changed data.
* With a limit set (for example *Max Steps* 2,000), the oldest step is
  released as each new one arrives, so disk use levels off. It stayed at about 60 MB in
  the same test. Only chunks that no remaining step uses are deleted.
* The per-step cost that grows with history length is rewriting
  `history.json` (about 2 MB at 10,000 steps, about 30 ms). The sidebar list is
  paged and the strip shows only the visible steps, so the UI does not slow down.
* When a history is opened, the add-on scans it once in the background
  (about 3 s for 10,000 steps) to rebuild reference counts and remove leftovers
  from a crash.
* The defaults (200 steps, 2 GB) are conservative. For 10,000 steps, set *Max Steps*
  to 10000 (or 0 for unlimited) and pick a *Disk Quota* that suits your drive.

## How it works / limits

* To take a step, Blender writes the file once (uncompressed, to a temporary
  file in the history folder). A background thread then chunks, dedupes and
  compresses it, and deletes the temporary file, so only changed data stays on
  disk. The write happens after the scene has been idle for *Idle Delay*
  seconds, never mid-tool or during playback. For very large scenes the write
  is the part you notice (about 2 s for 300 MB), so raise *Idle Delay* if needed.
* A restore rebuilds the step's `.blend` from its chunks and checks each
  chunk's hash. It then puts the rebuilt file in place of the working file and
  opens it, keeping your current UI layout. The previous file is kept as
  `<name>.blend1`, like Blender's own save versions, and a compressed file stays
  compressed. Relative paths (textures, libraries) keep working, because
  snapshots are written with the paths as they are in the working file.
* If a snapshot is running into another add-on's always-on tool, recording
  waits at most 20 s for tools to finish.
* A restore needs the file to be saved at least once.
* Blender's normal `Ctrl Z` still works as usual. The timeline doesn't
  replace it; it adds a history that persists.
* Relative paths (textures, libraries) are remapped when snapshots are
  written and restored.
