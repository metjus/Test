# SPDX-License-Identifier: GPL-3.0-or-later
"""On-disk history store.

Every history step is a full ``.blend`` snapshot written next to the working
file (``<name>_history/step_00001.blend``) plus one ``history.json`` index.
Nothing lives in Blender's in-memory undo stack, so the timeline survives
closing Blender, crashes and reopening the file days later.
"""

import hashlib
import json
import os
import shutil
import tempfile
import time

INDEX_NAME = "history.json"
FORMAT_VERSION = 1


def history_dir_for(blend_path, custom_root=""):
    """Folder that holds the history of ``blend_path``.

    Unsaved files get a per-process temp folder that is moved next to the
    file on its first save.
    """
    if not blend_path:
        return os.path.join(
            tempfile.gettempdir(), "blender_history_untitled_%d" % os.getpid()
        )
    blend_path = os.path.abspath(blend_path)
    stem = os.path.splitext(os.path.basename(blend_path))[0]
    if custom_root:
        digest = hashlib.sha1(blend_path.encode("utf-8")).hexdigest()[:8]
        return os.path.join(custom_root, "%s_%s" % (stem, digest))
    return os.path.join(os.path.dirname(blend_path), stem + "_history")


def is_temp_dir(path):
    return os.path.basename(path).startswith("blender_history_untitled_")


class HistoryStore:
    """A linear list of snapshot steps with a movable "current" marker.

    Restoring an older step never deletes anything: the marker moves back and
    later steps are shown as *rolled back* (like Fusion's timeline marker).
    New work after a rollback is appended with ``parent`` pointing at the step
    it branched from, so every state ever captured stays reachable.
    """

    def __init__(self, directory, blend_path=""):
        self.dir = directory
        self.data = {
            "version": FORMAT_VERSION,
            "blend": blend_path,
            "next_id": 1,
            "current": 0,
            "saved_step": 0,
            "saved_mtime": 0.0,
            "steps": [],
        }

    # ------------------------------------------------------------------ io
    @property
    def index_path(self):
        return os.path.join(self.dir, INDEX_NAME)

    @classmethod
    def open(cls, directory, blend_path=""):
        store = cls(directory, blend_path)
        if os.path.isfile(store.index_path):
            try:
                with open(store.index_path, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                store.data.update(loaded)
            except (OSError, ValueError) as ex:
                print("History Timeline: could not read %s (%s)" % (store.index_path, ex))
            # Drop entries whose snapshot file vanished.
            store.data["steps"] = [
                s for s in store.data["steps"] if os.path.isfile(store.path(s))
            ]
            if store.get(store.current) is None:
                store.data["current"] = store.steps[-1]["id"] if store.steps else 0
        if blend_path:
            store.data["blend"] = blend_path
        return store

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1)
        os.replace(tmp, self.index_path)

    # ------------------------------------------------------------- queries
    @property
    def steps(self):
        return self.data["steps"]

    @property
    def current(self):
        return self.data["current"]

    @current.setter
    def current(self, step_id):
        self.data["current"] = step_id

    def path(self, step):
        return os.path.join(self.dir, step["file"])

    def get(self, step_id):
        for step in self.steps:
            if step["id"] == step_id:
                return step
        return None

    def index_of(self, step_id):
        for i, step in enumerate(self.steps):
            if step["id"] == step_id:
                return i
        return -1

    def current_index(self):
        return self.index_of(self.current)

    def is_rolled_back(self, step):
        """True when ``step`` lies after the marker (greyed out in the UI)."""
        cur = self.current_index()
        return cur >= 0 and self.index_of(step["id"]) > cur

    def neighbour(self, offset):
        idx = self.current_index()
        if idx < 0:
            return None
        idx += offset
        if 0 <= idx < len(self.steps):
            return self.steps[idx]
        return None

    # ------------------------------------------------------------- editing
    def new_step(self, label, idname="", category="other", detail=""):
        """Reserve a step (id + file name). Call :meth:`commit` once written."""
        step_id = self.data["next_id"]
        self.data["next_id"] = step_id + 1
        return {
            "id": step_id,
            "file": "step_%05d.blend" % step_id,
            "label": label,
            "idname": idname,
            "category": category,
            "detail": detail,
            "time": time.time(),
            "parent": self.current,
            "pinned": False,
            "size": 0,
        }

    def commit(self, step, max_steps=0):
        try:
            step["size"] = os.path.getsize(self.path(step))
        except OSError:
            step["size"] = 0
        self.steps.append(step)
        self.current = step["id"]
        if max_steps:
            self.prune(max_steps)
        self.save()
        return step

    def prune(self, max_steps):
        """Drop the oldest unpinned steps until at most ``max_steps`` remain."""
        removable = [
            s for s in self.steps if not s.get("pinned") and s["id"] != self.current
        ]
        excess = len(self.steps) - max_steps
        for step in removable[:max(0, excess)]:
            self._remove(step)

    def delete(self, step_id):
        step = self.get(step_id)
        if step is None:
            return False
        was_current = step_id == self.current
        idx = self.index_of(step_id)
        self._remove(step)
        if was_current:
            neighbour = self.steps[max(0, idx - 1)] if self.steps else None
            self.current = neighbour["id"] if neighbour else 0
        self.save()
        return True

    def _remove(self, step):
        try:
            os.remove(self.path(step))
        except OSError:
            pass
        self.steps.remove(step)

    def clear(self):
        for step in list(self.steps):
            self._remove(step)
        self.current = 0
        self.data["saved_step"] = 0
        self.save()

    def relocate(self, new_dir, blend_path, move):
        """Move (first save of an unsaved file) or copy (Save As) the history."""
        if os.path.abspath(new_dir) == os.path.abspath(self.dir):
            self.data["blend"] = blend_path
            self.save()
            return
        if os.path.exists(new_dir):
            # Another file's history already lives there: keep it as a backup.
            backup = "%s.old-%d" % (new_dir, int(time.time()))
            os.replace(new_dir, backup)
        if os.path.isdir(self.dir):
            if move:
                shutil.move(self.dir, new_dir)
            else:
                shutil.copytree(self.dir, new_dir)
        self.dir = new_dir
        self.data["blend"] = blend_path
        self.save()

    def total_size(self):
        return sum(s.get("size", 0) for s in self.steps)
