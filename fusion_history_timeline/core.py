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
    last_op = None          # (pointer, idname) of newest registered operator
    strong_change = False   # geometry / transform / shading changed
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
    max_steps = 100
    compress = False
    history_root = ""
    capture_on_open = True
    ignore_operators = ""
    strip_location = "STATUSBAR"
    strip_count = 24


def prefs():
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    if addon is not None and addon.preferences is not None:
        return addon.preferences
    return _DefaultPrefs


DEFAULT_IGNORE = (
    "*.select*", "*select_all", "*.hide_view_*", "view3d.view*", "view3d.zoom*",
    "view3d.navigate", "view3d.localview*", "view3d.cursor3d", "view3d.toggle_*",
    "screen.*", "wm.*", "ed.*", "file.*", "anim.change_frame", "outliner.item_activate",
    "outliner.*select*", "object.mode_set", "sculpt.sculptmode_toggle",
    "view2d.*", "image.view*", "node.view*", "node.select*", "ui.*",
    "fh.*",
)

# Matched before DEFAULT_IGNORE (``wm.*`` would otherwise swallow them).
ALWAYS_CAPTURE = ("wm.append", "wm.link", "wm.*import*", "wm.*_import")

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


def _ignore_patterns():
    extra = [p.strip() for p in prefs().ignore_operators.split(",") if p.strip()]
    return DEFAULT_IGNORE + tuple(extra)


# ------------------------------------------------------------------ store
def get_store():
    """Store for the currently open file (created lazily)."""
    path = bpy.data.filepath
    root = bpy.path.abspath(prefs().history_root) if prefs().history_root else ""
    directory = storage.history_dir_for(path, root)
    st = _State.store
    if st is None or os.path.abspath(st.dir) != os.path.abspath(directory):
        _State.store = storage.HistoryStore.open(directory, path)
    return _State.store


def _newest_operator():
    ops = bpy.context.window_manager.operators
    if not len(ops):
        return None
    op = ops[-1]
    return op.as_pointer(), op.bl_idname, op.name


def _sync_operator_marker():
    op = _newest_operator()
    _State.last_op = op[:2] if op else None


def _reset_pending():
    _State.strong_change = False
    _State.any_change = False
    _State.changed_ids = []


def tag_redraw():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


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
    kwargs = dict(filepath=path, copy=True, check_existing=False,
                  compress=prefs().compress, relative_remap=True)
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
    try:
        _write_snapshot(store.path(step))
    except (RuntimeError, OSError) as ex:
        print("History Timeline: snapshot failed: %s" % ex)
        return None
    store.commit(step, prefs().max_steps)
    _State.obj_count = len(bpy.data.objects)
    _State.strip_offset = 0
    _reset_pending()
    _sync_operator_marker()
    sync_ui()
    tag_redraw()
    return step


def _modal_running():
    """Avoid snapshots in the middle of an interactive tool (grab, knife ...)."""
    wm = bpy.context.window_manager
    for window in wm.windows:
        if len(getattr(window, "modal_operators", ())):
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
    op = _newest_operator()
    new_op = op is not None and (_State.last_op is None or op[:2] != _State.last_op)
    label, idname, category = None, "", None

    if new_op:
        # Selection, navigation, mode switches ... never form a step on their
        # own; whatever they touched is included in the next real step.
        candidate = py_idname(op[1])
        if _match(candidate, ALWAYS_CAPTURE) or not _match(candidate, _ignore_patterns()):
            label, idname = op[2], candidate
    elif _State.strong_change:
        label, category = _describe_change()

    if label is None or not bpy.data.is_dirty:
        _reset_pending()
        _sync_operator_marker()
        return None
    return capture(label, idname, category)


def _tick():
    if _State.restoring or not prefs().auto_capture:
        _State.timer_running = False
        _reset_pending()
        return None
    wait = prefs().debounce
    if time.monotonic() - _State.last_change < wait or _modal_running() or _is_playing():
        return 0.2
    _State.timer_running = False
    try:
        flush_pending()
    except Exception as ex:  # never let a timer die silently mid-session
        print("History Timeline: capture error: %s" % ex)
    return None


def _ensure_timer():
    if not _State.timer_running:
        _State.timer_running = True
        bpy.app.timers.register(_tick, first_interval=0.2)


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
    strong = False
    names = []
    for update in depsgraph.updates:
        if update.is_updated_geometry or update.is_updated_transform or update.is_updated_shading:
            strong = True
        id_data = update.id
        if isinstance(id_data, bpy.types.Object):
            names.append(id_data.name)
    _State.any_change = True
    _State.strong_change |= strong
    for name in names:
        if name not in _State.changed_ids:
            _State.changed_ids.append(name)
    _State.last_change = time.monotonic()
    _ensure_timer()


@persistent
def on_undo_redo(*_args):
    # Blender's own undo moves the data but the timeline keeps its snapshots.
    _reset_pending()
    _sync_operator_marker()


@persistent
def on_save_post(*_args):
    if _State.saving_copy:
        return
    path = bpy.data.filepath
    store = _State.store
    root = bpy.path.abspath(prefs().history_root) if prefs().history_root else ""
    new_dir = storage.history_dir_for(path, root)
    if store is not None and os.path.abspath(store.dir) != os.path.abspath(new_dir):
        # First save of an untitled file moves the history, "Save As" copies it.
        store.relocate(new_dir, path, move=storage.is_temp_dir(store.dir))
    store = get_store()
    pending = _State.any_change and _State.timer_running
    store.data["saved_step"] = 0 if pending else store.current
    try:
        store.data["saved_mtime"] = os.path.getmtime(path)
    except OSError:
        store.data["saved_mtime"] = 0.0
    store.save()
    sync_ui()


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

    _State.store = None
    store = get_store()
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
        store.clear()
    sync_ui()
    tag_redraw()


# ---------------------------------------------------------------- restore
class RestoreError(Exception):
    pass


def restore(step_id, deferred=True):
    """Bring the file back to ``step_id``.

    The snapshot is opened and immediately saved over the working file, so the
    rest of Blender (file path, relative paths, recent files) is unaffected.
    The state being left is captured first, so a restore can always be undone
    from the timeline itself.
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

    info = {"target": target, "step": step_id, "dir": store.dir,
            "snapshot": store.path(step)}

    def _do():
        _State.restoring = info
        try:
            _call_with_window(bpy.ops.wm.open_mainfile,
                              filepath=info["snapshot"], load_ui=False)
        except RuntimeError as ex:
            _State.restoring = None
            print("History Timeline: restore failed: %s" % ex)
        return None

    if deferred and not bpy.app.background:
        # Loading a file from inside a button's operator is fragile; do it
        # from a timer once the UI event has been fully handled.
        bpy.app.timers.register(_do, first_interval=0.01)
    else:
        _do()


def _finish_restore(info):
    target = info["target"]
    try:
        _State.saving_copy = True
        bpy.ops.wm.save_as_mainfile(filepath=target, check_existing=False,
                                    compress=prefs().compress, relative_remap=True)
    except RuntimeError as ex:
        print("History Timeline: could not save restored state to %s: %s" % (target, ex))
    finally:
        _State.saving_copy = False
        _State.restoring = None

    _State.store = None
    store = get_store()
    if store.get(info["step"]) is not None:
        store.current = info["step"]
    store.data["saved_step"] = store.current
    try:
        store.data["saved_mtime"] = os.path.getmtime(target)
    except OSError:
        pass
    store.save()
    _sync_operator_marker()
    sync_ui()
    tag_redraw()


# --------------------------------------------------------------- UI mirror
def sync_ui():
    """Mirror the store into WindowManager properties used by the UI list."""
    wm = bpy.context.window_manager
    if wm is None or not hasattr(wm, "fh_steps"):
        return
    store = _State.store
    wm.fh_steps.clear()
    if store is None:
        return
    for step in reversed(store.steps):  # newest first in the list
        item = wm.fh_steps.add()
        item.step_id = step["id"]
        item.label = step["label"]
        item.category = step.get("category", "other")
        item.detail = step.get("detail", "")
        item.stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(step["time"]))
        item.pinned = step.get("pinned", False)
        item.is_current = step["id"] == store.current
        item.rolled_back = store.is_rolled_back(step)
        item.is_saved = step["id"] == store.data.get("saved_step")
    wm.fh_index = min(max(wm.fh_index, 0), max(len(wm.fh_steps) - 1, 0))


HANDLERS = (
    (bpy.app.handlers.depsgraph_update_post, on_depsgraph_update),
    (bpy.app.handlers.undo_post, on_undo_redo),
    (bpy.app.handlers.redo_post, on_undo_redo),
    (bpy.app.handlers.save_post, on_save_post),
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
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    _State.timer_running = False
    _State.store = None
