# SPDX-License-Identifier: GPL-3.0-or-later
"""Change detection, snapshot capture and restore."""

import fnmatch
import os
import time

import bpy
from bpy.app.handlers import persistent

from . import storage

ADDON_ID = __package__


class _State:
    store = None            # storage.HistoryStore for the open file
    last_op = None          # (pointer, idname) of every registered operator
    strong_change = False   # geometry / transform / shading changed
    tool_change = False     # ... while a built-in tool (grab, knife ...) was running
    quiet_until = 0.0       # ignore scene updates caused by undo/redo until then
    undo_log = []           # per Blender undo push: timeline step it created, or None
    redo_log = []           # entries undone with Ctrl+Z, most recent last
    any_change = False      # anything at all changed
    changed_ids = []        # names of changed datablocks (for labels)
    last_change = 0.0
    last_frame = None
    obj_count = None        # object count at the last snapshot (for labels)
    timer_running = False
    saving_copy = False     # True while we write a snapshot
    restoring = None        # dict while a restore is in flight
    strip_offset = 0        # scroll position of the timeline strip (0 = follow end)


# ------------------------------------------------------------------ prefs
class _DefaultPrefs:
    auto_capture = True
    debounce = 0.6
    max_steps = 200
    max_disk_mb = 2048
    history_root = ""
    capture_on_open = True
    continuous_undo = True
    ignore_operators = ""
    strip_location = "STATUSBAR"
    strip_count = 24


def prefs():
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    if addon is not None and addon.preferences is not None:
        return addon.preferences
    return _DefaultPrefs


# Operators that change selection, visibility, modes, the view or UI state but
# not the model. They are undoable (so Blender marks the file as changed), yet
# must never become timeline steps.
DEFAULT_IGNORE = (
    # selection: select_all, loop_multi_select, faces_select_linked_flat,
    # shortest_path_pick, de_select_first ...
    "*.select*", "*_select", "*_select_*", "*.de_select*", "*deselect*", "*_pick",
    "*selection_mode", "*selection_domain",
    # visibility
    "*.hide*", "*_hide*", "*.reveal*", "*_reveal*", "*.unhide*", "*_unhide*",
    # modes (Tab = object.editmode_toggle)
    "*.mode_set", "*mode_toggle", "*_paint_toggle", "particle.particle_edit_toggle",
    "nla.tweakmode_*", "*enter_editcurve_mode",
    # active item, 3D cursor, preview range
    "*set_active*", "*active_set", "*.layer_active", "*cursor_set", "*snap_cursor*",
    "view3d.cursor3d", "*previewrange*", "*transform_gizmo_set",
    # view and UI
    "view3d.view*", "view3d.zoom*", "view3d.navigate", "view3d.localview*",
    "view3d.toggle_*", "view2d.*", "image.view*", "node.view*", "*_view_all",
    "screen.*", "wm.*", "ed.*", "file.*", "ui.*", "anim.change_frame",
    "anim.channels_*", "outliner.item_activate",
    "ht.*",
)

# Real edits whose names look like the patterns above (checked first).
ALWAYS_CAPTURE = (
    "wm.append", "wm.link", "wm.*import*", "wm.*_import",
    "*copy*_to_selected", "*snap_selected*", "uv.select_split",
)

# (patterns, category) - first match wins.
CATEGORIES = (
    (("*.delete*", "*dissolve*", "*.remove*", "*.clear*"), "delete"),
    (("*.duplicate*", "*.join*", "*.separate*"), "duplicate"),
    (("import_*", "*import*", "wm.append", "wm.link"), "import"),
    (("object.modifier*", "object.*_modifier*"), "modifier"),
    (("*.primitive_*", "*_add", "*.add*"), "add"),
    (("transform.*", "*.origin_set", "*.transform_apply", "*.snap*"), "transform"),
    (("sculpt.*", "paint.*"), "sculpt"),
    (("material.*", "node.*", "shader.*", "texture.*"), "material"),
    (("mesh.*", "curve.*", "curves.*", "armature.*", "uv.*", "gpencil.*",
      "grease_pencil.*", "lattice.*", "font.*"), "edit"),
)

CATEGORY_ICONS = {
    "file": "FILE_BLEND",
    "restore": "RECOVER_LAST",
    "delete": "TRASH",
    "duplicate": "DUPLICATE",
    "import": "IMPORT",
    "add": "ADD",
    "transform": "EMPTY_ARROWS",
    "modifier": "MODIFIER",
    "sculpt": "SCULPTMODE_HLT",
    "material": "MATERIAL",
    "edit": "EDITMODE_HLT",
    "property": "PROPERTIES",
    "manual": "BOOKMARKS",
    "other": "DOT",
}


def category_icon(category):
    return CATEGORY_ICONS.get(category, "DOT")


def py_idname(bl_idname):
    """``OBJECT_OT_delete`` -> ``object.delete``."""
    if "_OT_" in bl_idname:
        mod, name = bl_idname.split("_OT_", 1)
        return mod.lower() + "." + name
    return bl_idname


def _match(idname, patterns):
    return any(fnmatch.fnmatchcase(idname, p) for p in patterns)


def categorize(idname):
    for patterns, category in CATEGORIES:
        if _match(idname, patterns):
            return category
    return "other"


def is_ignored(idname):
    """True for operators that never form a step on their own."""
    return not _match(idname, ALWAYS_CAPTURE) and _match(idname, _ignore_patterns())


def _ignore_patterns():
    extra = [p.strip() for p in prefs().ignore_operators.split(",") if p.strip()]
    return DEFAULT_IGNORE + tuple(extra)


# ------------------------------------------------------------------ store
worker = storage.Worker()


def _poll_worker():
    return 0.1 if worker.poll() else None


def _submit(fn, *args, on_done=None):
    worker.threaded = not bpy.app.background
    worker.submit(fn, *args, on_done=on_done)
    if worker.threaded and not bpy.app.timers.is_registered(_poll_worker):
        bpy.app.timers.register(_poll_worker, first_interval=0.1, persistent=True)


def get_store():
    """Store for the currently open file (created lazily)."""
    path = bpy.data.filepath
    root = bpy.path.abspath(prefs().history_root) if prefs().history_root else ""
    directory = storage.history_dir_for(path, root)
    st = _State.store
    if st is None or os.path.abspath(st.dir) != os.path.abspath(directory):
        worker.wait()  # pending jobs belong to the previous store
        _State.store = storage.HistoryStore.open(directory, path)
        _scan(_State.store)
        if _State.obj_count is None:
            _State.obj_count = len(bpy.data.objects)
    return _State.store


def _over_quota(store):
    quota = prefs().max_disk_mb * 1024 * 1024
    return quota and store.disk_bytes > quota


def release_removed(store):
    """Delete the files of removed steps in the background, then keep
    dropping the oldest steps while the history is over its disk quota."""
    def done(used, error):
        if error is not None:
            print("History Timeline: cleanup failed: %s" % error)
            return
        store.data["disk_bytes"] = used
        if not worker.outstanding and _over_quota(store) and store.drop_oldest():
            release_removed(store)
        store.save()
        tag_redraw()
    for path in store.take_released():
        _submit(store.chunks.release, path, on_done=done)


def _scan(store):
    """Once per opened history: exact disk use, orphan cleanup, ref counts."""
    def done(used, error):
        if error is None:
            store.data["disk_bytes"] = used
            if _over_quota(store) and store.drop_oldest():
                release_removed(store)
            tag_redraw()
    _submit(store.chunks.scan, on_done=done)


def steps_after(step_id):
    """Steps that come after ``step_id`` on the timeline (branches included)."""
    store = get_store()
    idx = store.index_of(step_id)
    return store.steps[idx + 1:] if idx >= 0 else []


def truncate_after(step_id):
    """Go back to ``step_id`` and permanently delete every later step.

    Returns the number of deleted steps.
    """
    store = get_store()
    if store.get(step_id) is None:
        raise RestoreError("Step %d no longer exists" % step_id)
    if _State.any_change:
        flush_pending()  # unrecorded work becomes a (later) step, deleted below
    worker.wait()
    later = steps_after(step_id)
    for step in list(later):
        store._remove(step)
    if store.get(store.data.get("saved_step", 0)) is None:
        store.data["saved_step"] = 0
    release_removed(store)
    # Blender's undo steps may point at deleted steps; the mirror starts over.
    _State.undo_log.clear()
    _State.redo_log.clear()
    for step in store.steps:
        step.pop("undone", None)
    if store.current != step_id or bpy.data.is_dirty:
        store.current = step_id
        store.save()
        restore(step_id)
    else:
        store.save()
    tag_redraw()
    return len(later)


def delete_step(step_id):
    worker.wait()
    store = get_store()
    if not store.delete(step_id):
        return False
    release_removed(store)
    return True


def clear_history():
    worker.wait()
    store = get_store()
    store.clear()
    release_removed(store)


def _registered_operators():
    return list(bpy.context.window_manager.operators)


def _operator_marker(ops=None):
    """Identity of the registered-operator list.

    Comparing only the newest operator's address is not enough: Blender can
    allocate the next operator at the address just freed, which made a new
    operator look like the old one.
    """
    ops = _registered_operators() if ops is None else ops
    return tuple((op.as_pointer(), op.bl_idname) for op in ops)


def _sync_operator_marker():
    _State.last_op = _operator_marker()


def _new_operators():
    """Operators registered since the last sync, oldest first.

    Blender appends to the list and drops the oldest entries, so the new ones
    are what follows the longest overlap with the previous list.
    """
    ops = _registered_operators()
    cur = _operator_marker(ops)
    prev = _State.last_op or ()
    for k in range(min(len(prev), len(cur)), 0, -1):
        if prev[-k:] == cur[:k]:
            return ops[k:]
    return ops if cur != prev else []


def _pushes_undo(op):
    return bool({'UNDO', 'UNDO_GROUPED'} & set(op.bl_options))


def _is_real_edit(op):
    return not is_ignored(py_idname(op.bl_idname)) and not _no_op_transform(op)


def _no_op_transform(op):
    """A move/rotate/scale that ended where it started (e.g. a click with a
    tiny drag). Blender still registers it, but nothing changed."""
    idname = py_idname(op.bl_idname)
    if not idname.startswith("transform."):
        return False
    value = getattr(op.properties, "value", None)
    if value is None:
        return False
    values = list(value) if hasattr(value, "__len__") else [value]
    scale = idname in ("transform.resize", "transform.skin_resize") or (
        idname == "transform.transform" and getattr(op.properties, "mode", "") == 'RESIZE')
    identity = 1.0 if scale else 0.0
    count = 3 if idname == "transform.transform" else len(values)
    return all(abs(v - identity) < 1e-6 for v in values[:count])


def _reset_pending():
    _State.strong_change = False
    _State.tool_change = False
    _State.any_change = False
    _State.changed_ids = []


def tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    _redraw_status_bars()


def _redraw_status_bars():
    """Repaint the status bar, where the timeline strip lives.

    It is a global area, not part of ``Screen.areas``, so tagging areas never
    reached it and new steps only appeared once something else (the mouse
    leaving the model) happened to refresh it. Clearing the (empty) status
    text is Blender's own way to request that repaint. Skipped while a tool
    runs, since tools show their hints there.
    """
    wm = bpy.context.window_manager
    if _modal_running():
        return
    for window in wm.windows:
        workspace = window.workspace
        if workspace is None:
            continue
        try:
            with bpy.context.temp_override(window=window):
                workspace.status_text_set_internal(None)
        except (RuntimeError, TypeError, AttributeError):
            pass


# ---------------------------------------------------------------- capture
def _active_object_name():
    try:
        obj = bpy.context.view_layer.objects.active
        return obj.name if obj else ""
    except AttributeError:
        return ""


def _call_with_window(op, **kwargs):
    """Run ``op`` with a window in context (timers run without one)."""
    wm = bpy.context.window_manager
    if bpy.context.window is None and wm is not None and wm.windows:
        with bpy.context.temp_override(window=wm.windows[0]):
            return op(**kwargs)
    return op(**kwargs)


def _write_snapshot(path):
    """Write a copy of the open file without changing its path or dirty state."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Uncompressed (chunks dedupe raw data) and without remapping relative
    # paths, so a snapshot is valid when rebuilt at the working file's path.
    kwargs = dict(filepath=path, copy=True, check_existing=False,
                  compress=False, relative_remap=False)
    _State.saving_copy = True
    try:
        _call_with_window(bpy.ops.wm.save_as_mainfile, **kwargs)
    finally:
        _State.saving_copy = False


def capture(label, idname="", category=None, detail=None):
    """Snapshot the current state as a new timeline step. Returns the step."""
    store = get_store()
    if category is None:
        category = categorize(idname) if idname else "other"
    if detail is None:
        detail = _active_object_name()
    step = store.new_step(label, idname, category, detail)
    src = store.ingest_path(step)
    try:
        _write_snapshot(store.snapshot_path())
        os.replace(store.snapshot_path(), src)
    except (RuntimeError, OSError) as ex:
        print("History Timeline: snapshot failed: %s" % ex)
        return None
    store.commit(step)
    _submit(_ingest, store.chunks, src, store.path(step),
            on_done=lambda result, error: _ingested(store, step["id"], result, error))
    _State.obj_count = len(bpy.data.objects)
    _State.strip_offset = 0
    _reset_pending()
    _sync_operator_marker()
    tag_redraw()
    return step


def _ingest(chunks, src, manifest):
    """Worker thread: dedupe + compress the written .blend, then drop it."""
    try:
        return chunks.ingest(src, manifest)
    finally:
        try:
            os.remove(src)
        except OSError:
            pass


def _ingested(store, step_id, result, error):
    step = store.get(step_id)
    if step is None:
        return
    if error is not None:
        print("History Timeline: storing step %d failed: %s" % (step_id, error))
        idx = store.index_of(step_id)
        store._remove(step)
        if store.current == step_id:
            store.current = store.steps[idx - 1]["id"] if idx > 0 and store.steps else 0
    else:
        step.pop("pending", None)
        step["raw_size"], step["added"] = result
        store.data["disk_bytes"] = store.chunks.used
    store.prune(prefs().max_steps)
    if _over_quota(store):
        store.drop_oldest()
    release_removed(store)
    store.save()
    tag_redraw()


def _modal_running():
    """Avoid snapshots in the middle of an interactive tool (grab, knife ...)."""
    wm = bpy.context.window_manager
    for window in wm.windows:
        if len(getattr(window, "modal_operators", ())):
            return True
    return False


# Operator modules of Blender's own interactive tools. Changes made while one
# of them runs only count once the tool finishes (it is then registered); a
# right-click cancel registers nothing. Add-on modals are not in this list, so
# an add-on that keeps a modal running cannot hide real edits.
BUILTIN_TOOL_MODULES = frozenset((
    "transform", "mesh", "object", "curve", "curves", "sculpt", "sculpt_curves", "paint",
    "gpencil", "grease_pencil", "armature", "pose", "uv", "node", "view3d", "image",
    "graph", "action", "nla", "sequencer", "clip", "mask", "font", "lattice", "particle",
    "marker", "anim",
))


def _tool_running():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for op in getattr(window, "modal_operators", ()):
            if op.bl_idname.split("_OT_")[0].lower() in BUILTIN_TOOL_MODULES:
                return True
    return False


def _is_playing():
    screen = getattr(bpy.context, "screen", None)
    if screen is not None and screen.is_animation_playing:
        return True
    wm = bpy.context.window_manager
    return any(w.screen.is_animation_playing for w in wm.windows)


def _describe_change():
    """Label for a change that was not made by a registered operator."""
    count = len(bpy.data.objects)
    prev = _State.obj_count
    active = _active_object_name()
    if prev is not None and count > prev:
        return ("Add " + active if active else "Add Object"), "add"
    if prev is not None and count < prev:
        removed = prev - count
        return ("Delete %d Object%s" % (removed, "s" if removed > 1 else "")), "delete"
    names = _State.changed_ids
    if active and active in names:
        return "Edit " + active, "property"
    if names:
        return "Edit " + names[0], "property"
    return "Property Change", "property"


def flush_pending():
    """Decide whether the recent changes form a new step and capture it.

    Returns the captured step or None.
    """
    new = _new_operators()
    # Selection, navigation, mode switches ... never form a step on their own;
    # whatever they touched is included in the next real step.
    real = [op for op in new if _is_real_edit(op)]
    label, idname, category = None, "", None
    property_edit = False

    if real:
        label, idname = real[-1].name, py_idname(real[-1].bl_idname)
    elif not new and _State.strong_change:
        # Changed without an operator: a value typed or dragged in the UI.
        # (Changes made only while a tool ran, then cancelled, are dropped.)
        property_edit = True
        label, category = _describe_change()

    step = None
    if label is not None and bpy.data.is_dirty:
        step = capture(label, idname, category)
    else:
        _reset_pending()
        _sync_operator_marker()

    # Mirror Blender's undo stack: one entry per undo push.
    entries = [step["id"] if step is not None and real and op is real[-1] else None
               for op in new if _pushes_undo(op)]
    if property_edit:
        entries.append(step["id"] if step is not None else None)
    _record_undo_pushes(entries)
    return step


def _tick():
    if _State.restoring or not prefs().auto_capture:
        _State.timer_running = False
        _reset_pending()
        return None
    if _is_playing():
        return TICK
    idle = time.monotonic() - _State.last_change
    tool = _modal_running()
    # A command that just finished (a confirmed rotate, an extrude ...) is
    # recorded right away. Only changes without a command (values typed or
    # dragged in the UI) wait for the idle delay, so a slider drag is one step.
    finished_command = not tool and _operator_marker() != _State.last_op
    if not finished_command:
        if idle < prefs().debounce:
            return TICK
        # Wait for interactive tools to finish, but not for add-ons that
        # keep a modal operator running all the time.
        if tool and idle < MODAL_WAIT_LIMIT:
            return TICK
    _State.timer_running = False
    try:
        flush_pending()
    except Exception as ex:  # never let a timer die silently mid-session
        print("History Timeline: capture error: %s" % ex)
    return None


MODAL_WAIT_LIMIT = 20.0  # seconds
TICK = 0.1  # seconds between checks while changes are pending


def _ensure_timer():
    # Checked via is_registered: a stale flag would stop recording for good.
    _State.timer_running = True
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=TICK, persistent=True)


# --------------------------------------------------------------- handlers
@persistent
def on_depsgraph_update(scene, depsgraph):
    if _State.saving_copy or _State.restoring or not prefs().auto_capture:
        return
    # Frame changes / playback re-evaluate animated objects: not an edit.
    frame = scene.frame_current
    if _State.last_frame is not None and frame != _State.last_frame:
        _State.last_frame = frame
        return
    _State.last_frame = frame
    if time.monotonic() < _State.quiet_until:
        return  # the scene update that follows an undo/redo is not an edit
    # In edit modes, (de)selecting elements is reported as a geometry/shading
    # update, indistinguishable from an edit. Every real edit there is an
    # operator, so only operators may create steps in these modes.
    strong = False
    watch_data = not getattr(bpy.context, "mode", "").startswith("EDIT")
    names = []
    for update in depsgraph.updates:
        if watch_data and (update.is_updated_geometry or update.is_updated_transform
                           or update.is_updated_shading):
            strong = True
        id_data = update.id
        if isinstance(id_data, bpy.types.Object):
            names.append(id_data.name)
    _State.any_change = True
    if strong and _tool_running():
        _State.tool_change = True
    else:
        _State.strong_change |= strong
    for name in names:
        if name not in _State.changed_ids:
            _State.changed_ids.append(name)
    _State.last_change = time.monotonic()
    _ensure_timer()


# ------------------------------------------------------------ undo / redo
UNDO_LOG_LIMIT = 1024
UNDO_QUIET = 0.3  # seconds


def _record_undo_pushes(entries):
    """Append undo pushes; a new push discards Blender's redo stack, so the
    steps undone with Ctrl+Z are discarded from the timeline too."""
    if not entries:
        return
    if _State.redo_log:
        _State.redo_log.clear()
        _discard_undone()
    _State.undo_log.extend(entries)
    del _State.undo_log[:-UNDO_LOG_LIMIT]


def _discard_undone():
    store = get_store()
    gone = [s for s in store.steps if s.get("undone")]
    for step in gone:
        store._remove(step)
    if gone:
        release_removed(store)
        store.save()
        tag_redraw()


def _forget_undo(store):
    """A file load resets Blender's undo stack: undone steps become ordinary
    rolled-back steps (kept, clickable)."""
    _State.undo_log.clear()
    _State.redo_log.clear()
    for step in store.steps:
        step.pop("undone", None)


def _after_undo_redo():
    _reset_pending()
    _sync_operator_marker()
    _State.quiet_until = time.monotonic() + UNDO_QUIET


@persistent
def on_undo_pre(*_args):
    if _State.restoring:
        return
    # Pushes still waiting for the idle delay are about to be undone; they
    # never became steps, but they must be counted to stay in sync.
    new = _new_operators()
    entries = [None for op in new if _pushes_undo(op)]
    if not new and _State.strong_change:
        entries.append(None)
    _record_undo_pushes(entries)
    _reset_pending()
    _sync_operator_marker()


@persistent
def on_undo_post(*_args):
    _after_undo_redo()
    if not _State.undo_log:
        return
    entry = _State.undo_log.pop()
    _State.redo_log.append(entry)
    store = get_store()
    step = store.get(entry) if entry is not None else None
    if step is None:
        return
    step["undone"] = True
    parent = store.get(step.get("parent"))
    if parent is None:
        idx = store.index_of(entry)
        parent = store.steps[idx - 1] if idx > 0 else None
    store.current = parent["id"] if parent else 0
    store.save()
    tag_redraw()


@persistent
def on_redo_post(*_args):
    _after_undo_redo()
    if not _State.redo_log:
        return
    entry = _State.redo_log.pop()
    _State.undo_log.append(entry)
    store = get_store()
    step = store.get(entry) if entry is not None else None
    if step is None:
        return
    step.pop("undone", None)
    store.current = entry
    store.save()
    tag_redraw()


@persistent
def on_save_post(*_args):
    if _State.saving_copy:
        return
    path = bpy.data.filepath
    store = _State.store
    root = bpy.path.abspath(prefs().history_root) if prefs().history_root else ""
    new_dir = storage.history_dir_for(path, root)
    if store is not None and os.path.abspath(store.dir) != os.path.abspath(new_dir):
        worker.wait()
        # First save of an untitled file moves the history, "Save As" copies it.
        store.relocate(new_dir, path, move=storage.is_temp_dir(store.dir))
        _scan(store)  # chunk store moved: rebuild its reference counts
    store = get_store()
    pending = _State.any_change and _State.timer_running
    store.data["saved_step"] = 0 if pending else store.current
    try:
        store.data["saved_mtime"] = os.path.getmtime(path)
    except OSError:
        store.data["saved_mtime"] = 0.0
    store.save()
    tag_redraw()


@persistent
def on_load_pre(*_args):
    worker.wait()


@persistent
def on_load_post(*_args):
    _reset_pending()
    _State.obj_count = len(bpy.data.objects)
    _State.strip_offset = 0
    _State.last_frame = None
    info = _State.restoring
    if info is not None:
        _finish_restore(info)
        return

    store = get_store()
    _forget_undo(store)
    _sync_operator_marker()

    path = bpy.data.filepath
    if path:
        saved = store.get(store.data.get("saved_step", 0))
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        unchanged = saved is not None and abs(mtime - store.data.get("saved_mtime", 0)) < 1.0
        if unchanged:
            # Steps captured after the last save stay available as "rolled back".
            store.current = saved["id"]
            store.save()
        elif prefs().capture_on_open and prefs().auto_capture:
            capture("Opened " + os.path.basename(path), category="file", detail="")
            store.data["saved_step"] = store.current
            store.data["saved_mtime"] = mtime
            store.save()
    elif store.steps and storage.is_temp_dir(store.dir):
        # New untitled file: history of the previous untitled session is stale.
        clear_history()
    tag_redraw()


# ---------------------------------------------------------------- restore
class RestoreError(Exception):
    pass


def restore_in_progress():
    return _State.restoring is not None


def restore(step_id, deferred=True):
    """Bring the file back to ``step_id``.

    The step is rebuilt in place of the working file (the previous file is
    kept as ``<name>.blend1``, like Blender's own save versions) and opened
    with the current UI kept. The state being left is captured first, so a
    restore can always be undone from the timeline itself.
    """
    store = get_store()
    step = store.get(step_id)
    if step is None:
        raise RestoreError("Step %d no longer exists" % step_id)
    target = bpy.data.filepath
    if not target:
        raise RestoreError("Save the file once before restoring history steps")

    if prefs().auto_capture and _State.any_change:
        # Changes still waiting for the idle delay become a step first.
        flush_pending()
        # capture() may have pruned the requested step.
        step = store.get(step_id)
        if step is None:
            raise RestoreError("Step %d no longer exists" % step_id)

    worker.wait()
    rebuilt = target + ".restoring"
    try:
        store.chunks.materialize(store.path(step), rebuilt)
    except (storage.CorruptHistory, OSError) as ex:
        raise RestoreError("Cannot rebuild step %d: %s" % (step_id, ex))

    info = {"target": target, "step": step_id,
            "compress": storage.is_compressed_blend(target)}

    def _do():
        try:
            if os.path.exists(target):
                os.replace(target, target + "1")
            os.replace(rebuilt, target)
        except OSError as ex:
            _State.restoring = None
            print("History Timeline: restore failed: %s" % ex)
            return None
        try:
            _call_with_window(bpy.ops.wm.open_mainfile, filepath=target, load_ui=False)
        except RuntimeError as ex:
            _State.restoring = None
            print("History Timeline: restore failed: %s" % ex)
        return None

    # Marked busy right away, so repeated clicks / a held Ctrl+Z don't queue
    # several loads before the first one has happened.
    _State.restoring = info
    if deferred and not bpy.app.background:
        # Loading a file from inside a button's operator is fragile; do it
        # from a timer once the UI event has been fully handled.
        bpy.app.timers.register(_do, first_interval=0.01)
    else:
        _do()


def _finish_restore(info):
    _State.restoring = None
    target = info["target"]
    if info["compress"]:
        # Snapshots are uncompressed; keep the file's compression setting.
        try:
            _State.saving_copy = True
            bpy.ops.wm.save_mainfile(compress=True)
        except RuntimeError as ex:
            print("History Timeline: could not re-compress %s: %s" % (target, ex))
        finally:
            _State.saving_copy = False

    store = get_store()
    _forget_undo(store)
    if store.get(info["step"]) is not None:
        store.current = info["step"]
    store.data["saved_step"] = store.current
    try:
        store.data["saved_mtime"] = os.path.getmtime(target)
    except OSError:
        pass
    store.save()
    _sync_operator_marker()
    tag_redraw()


HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, on_depsgraph_update),
    (bpy.app.handlers.undo_pre, on_undo_pre),
    (bpy.app.handlers.redo_pre, on_undo_pre),
    (bpy.app.handlers.undo_post, on_undo_post),
    (bpy.app.handlers.redo_post, on_redo_post),
    (bpy.app.handlers.save_post, on_save_post),
    (bpy.app.handlers.load_pre, on_load_pre),
    (bpy.app.handlers.load_post, on_load_post),
)


def register():
    for handler_list, fn in HANDLERS:
        if fn not in handler_list:
            handler_list.append(fn)


def unregister():
    for handler_list, fn in HANDLERS:
        if fn in handler_list:
            handler_list.remove(fn)
    worker.wait()
    for timer in (_tick, _poll_worker):
        if bpy.app.timers.is_registered(timer):
            bpy.app.timers.unregister(timer)
    _State.timer_running = False
    _State.store = None
