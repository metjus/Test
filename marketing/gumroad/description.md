# Gumroad listing: History Timeline for Blender

## Product name

History Timeline for Blender

## Description (paste into the main description box)

**Undo that survives closing Blender.**

Blender forgets your undo history the moment you close a file. History Timeline doesn't. Every change you make becomes a step on a visual timeline in the status bar, saved to disk next to your .blend. Click any step to go back to it, or forward again, whether that's five minutes later or next week.

### Go back to any point, any time

- Every edit (move, extrude, bevel, modifier, material change and so on) becomes a step on the timeline automatically
- Click a step to restore it. Later steps aren't deleted: they turn grey and stay one click away
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

### Requirements

- Blender 4.2 or newer (installs as a Blender extension)
- Windows, macOS and Linux
- No external dependencies

### Installation

1. Download the .zip file
2. In Blender: Edit > Preferences > Get Extensions > the ▾ menu at the top right > Install from Disk
3. Pick the .zip. The timeline appears in the status bar at the bottom of the window

### Good to know

- The history is stored in a folder next to your file (`yourfile_history`). You can choose another location in the preferences
- To restore a step, the file must have been saved at least once. Recording starts right away, even for unsaved files
- Restoring a step reloads the file. On very large scenes that takes a moment, like opening the file
- On very large scenes (hundreds of MB), recording a step causes a short pause, because Blender writes the file once in the background. You can adjust the idle delay in the preferences
- When you restore a step, your previous file is kept as `yourfile.blend1`, just like Blender's own backups

## Summary / "You'll get" line

You'll get: history_timeline-1.5.0.zip, a Blender extension for Blender 4.2 and newer.

## Additional details (key / value pairs)

| Key | Value |
|---|---|
| Blender version | 4.2 or newer |
| Platforms | Windows, macOS, Linux |
| Format | Blender extension (.zip) |
| Version | 1.5.0 |

## Images (upload order)

1. `01-hero.png`: cover (1920×1080)
2. `02-interface.png`: timeline and sidebar
3. `05-undo.png`: Ctrl+Z after reopening
4. `03-rollback.png`: roll back / roll forward
5. `04-storage.png`: disk usage
6. `thumbnail.png`: square product thumbnail (1200×1200)
