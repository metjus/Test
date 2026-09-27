#!/usr/bin/env python3
"""
Blender Settings Transfer
=========================

Export your Blender user setup (preferences, startup layout, add-ons,
extensions, presets, ...) into a single .zip package and import it on
another computer - choosing exactly which parts you want.

Run without arguments to open the GUI:

    python blender_settings_transfer.py

Or use the command line:

    python blender_settings_transfer.py list
    python blender_settings_transfer.py export my_setup.zip
    python blender_settings_transfer.py export my_setup.zip --include preferences startup addons
    python blender_settings_transfer.py import my_setup.zip --version 4.2
    python blender_settings_transfer.py import my_setup.zip --exclude recent_files

Only the Python standard library is used (tkinter for the GUI).
"""

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import zipfile

TOOL_NAME = "Blender Settings Transfer"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DATA_PREFIX = "blender/"  # every exported file lives under this folder in the zip

# Files/folders never worth copying (caches, backups, compiled python).
SKIP_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".blend1", ".blend2")
# Inside "extensions/" these hidden folders hold download caches and unpacked
# Python wheels that are platform specific. Blender rebuilds them itself.
SKIP_EXTENSION_DIRS = {".cache", ".local"}

VERSION_RE = re.compile(r"^\d+\.\d+$")


# ---------------------------------------------------------------------------
# Locating Blender user folders
# ---------------------------------------------------------------------------

def config_roots():
    """Return the folders that contain per-version Blender user folders
    (e.g. ``.../Blender/4.2``) on this computer, most likely first."""
    home = os.path.expanduser("~")
    roots = []
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        roots.append(os.path.join(appdata, "Blender Foundation", "Blender"))
    elif system == "Darwin":
        roots.append(os.path.join(home, "Library", "Application Support", "Blender"))
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        roots.append(os.path.join(xdg, "blender"))
        # Flatpak and Snap installs keep their config elsewhere.
        roots.append(os.path.join(home, ".var", "app", "org.blender.Blender", "config", "blender"))
        roots.append(os.path.join(home, "snap", "blender", "current", ".config", "blender"))
    return roots


def _version_key(v):
    return tuple(int(p) for p in v.split("."))


def find_installations():
    """Return a list of ``(label, path)`` for every Blender user folder found,
    newest version first."""
    found = []
    override = os.environ.get("BLENDER_USER_RESOURCES")
    if override and os.path.isdir(override):
        found.append(("BLENDER_USER_RESOURCES (%s)" % override, override, (999, 0)))
    for root in config_roots():
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if VERSION_RE.match(name) and os.path.isdir(path):
                found.append(("Blender %s  (%s)" % (name, path), path, _version_key(name)))
    found.sort(key=lambda x: x[2], reverse=True)
    return [(label, path) for label, path, _ in found]


def default_root():
    """The folder where a new version folder should be created on import."""
    for root in config_roots():
        if os.path.isdir(root):
            return root
    return config_roots()[0]


def guess_version(path):
    name = os.path.basename(os.path.normpath(path))
    return name if VERSION_RE.match(name) else None


# ---------------------------------------------------------------------------
# Item tree (what can be exported / imported)
# ---------------------------------------------------------------------------

class Node:
    """A selectable entry. Groups have children; leaves have a ``path``
    relative to the Blender version folder (always with forward slashes)."""

    def __init__(self, id, label, path=None, desc="", children=None, size=0):
        self.id = id
        self.label = label
        self.path = path
        self.desc = desc
        self.children = children or []
        self.size = size

    @property
    def is_group(self):
        return self.path is None

    def leaves(self):
        if not self.is_group:
            return [self]
        out = []
        for c in self.children:
            out.extend(c.leaves())
        return out

    def total_size(self):
        return sum(l.size for l in self.leaves())

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


# (id, label, description, kind, relative path)
#   kind "file"     -> a single file
#   kind "dir"      -> a whole folder as one item
#   kind "children" -> one selectable item per entry inside the folder
#   kind "ext"      -> extensions/<repo>/<extension>, grouped by repository
CATEGORIES = [
    ("preferences", "Preferences",
     "Everything from Edit > Preferences: theme, keymap, enabled add-ons and "
     "extensions, input, viewport, file paths, extension repositories ...",
     "file", "config/userpref.blend"),
    ("startup", "Startup file (UI layout)",
     "Your saved startup file: workspaces, editor/panel layout, toolbars and "
     "the default scene (File > Defaults > Save Startup File).",
     "file", "config/startup.blend"),
    ("addons", "Add-ons (legacy / manually installed)",
     "Add-ons installed from .zip / .py into scripts/addons.",
     "children", "scripts/addons"),
    ("extensions", "Extensions (Blender 4.2+)",
     "Extensions installed from extensions.blender.org or from disk.",
     "ext", "extensions"),
    ("presets", "Presets",
     "Saved presets: keymaps, themes, render settings, cameras, operators ...",
     "children", "scripts/presets"),
    ("startup_scripts", "Startup scripts",
     "Python scripts that run every time Blender starts (scripts/startup).",
     "dir", "scripts/startup"),
    ("modules", "Python modules",
     "Extra Python modules (scripts/modules).",
     "dir", "scripts/modules"),
    ("datafiles", "Data files",
     "Custom MatCaps, studio lights, HDRIs, fonts, icons ... (datafiles).",
     "children", "datafiles"),
    ("bookmarks", "File browser bookmarks",
     "Bookmarked folders in the file browser.",
     "file", "config/bookmarks.txt"),
    ("recent_files", "Recent files list",
     "The File > Open Recent list (paths may not exist on the new computer).",
     "file", "config/recent-files.txt"),
]


def _skip(name):
    return name in SKIP_NAMES or name.endswith(SKIP_SUFFIXES)


def path_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if not _skip(d)]
        for f in filenames:
            if not _skip(f):
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    return total


def _pretty_child_label(name):
    base, ext = os.path.splitext(name)
    return base if ext == ".py" else name


def scan_installation(base):
    """Build the item tree from a Blender version folder on disk."""
    roots = []
    for cid, label, desc, kind, rel in CATEGORIES:
        full = os.path.join(base, *rel.split("/"))
        if kind in ("file", "dir"):
            if (kind == "file" and os.path.isfile(full)) or (kind == "dir" and os.path.isdir(full) and os.listdir(full)):
                roots.append(Node(cid, label, rel, desc, size=path_size(full)))
        elif kind == "children":
            if not os.path.isdir(full):
                continue
            kids = []
            for name in sorted(os.listdir(full), key=str.lower):
                if _skip(name):
                    continue
                child_rel = rel + "/" + name
                kids.append(Node(child_rel, _pretty_child_label(name), child_rel,
                                 size=path_size(os.path.join(full, name))))
            if kids:
                roots.append(Node(cid, label, desc=desc, children=kids))
        elif kind == "ext":
            if not os.path.isdir(full):
                continue
            repos = []
            for repo in sorted(os.listdir(full), key=str.lower):
                repo_path = os.path.join(full, repo)
                if repo in SKIP_EXTENSION_DIRS or repo.startswith(".") or not os.path.isdir(repo_path):
                    continue
                kids = []
                for name in sorted(os.listdir(repo_path), key=str.lower):
                    if _skip(name) or name.startswith("."):
                        continue
                    child_rel = "%s/%s/%s" % (rel, repo, name)
                    kids.append(Node(child_rel, name, child_rel,
                                     size=path_size(os.path.join(repo_path, name))))
                if kids:
                    repos.append(Node("%s/%s" % (rel, repo), "Repository: %s" % repo, children=kids))
            if repos:
                roots.append(Node(cid, label, desc=desc, children=repos))
    return roots


def tree_from_manifest(manifest):
    """Rebuild the item tree from a package manifest."""
    return [_node_from_dict(d) for d in manifest.get("items", [])]


def _node_from_dict(d):
    return Node(d["id"], d["label"], d.get("path"), d.get("desc", ""),
                [_node_from_dict(c) for c in d.get("children", [])], d.get("size", 0))


def _node_to_dict(n, selected_paths):
    """Serialize ``n`` keeping only selected leaves. Returns None if empty."""
    if not n.is_group:
        if n.path not in selected_paths:
            return None
        return {"id": n.id, "label": n.label, "path": n.path, "desc": n.desc, "size": n.size}
    kids = [d for d in (_node_to_dict(c, selected_paths) for c in n.children) if d]
    if not kids:
        return None
    return {"id": n.id, "label": n.label, "desc": n.desc, "children": kids}


def select_leaves(tree, include=None, exclude=None):
    """Resolve include/exclude id lists (group ids or leaf ids/paths) to the
    set of selected leaf paths. ``include=None`` means everything."""
    by_id = {}
    for root in tree:
        for n in root.walk():
            by_id[n.id] = n
            if n.path:
                by_id[n.path] = n

    def resolve(ids):
        out = set()
        for i in ids:
            node = by_id.get(i)
            if node is None:
                # Allow the short name shown in 'list', e.g. "node_wrangler"
                # instead of "scripts/addons/node_wrangler.py".
                matches = [n for n in by_id.values() if not n.is_group and
                           (n.id.endswith("/" + i) or n.label == i)]
                if not matches:
                    raise SystemExit("Unknown item: %r  (use the 'list' command to see ids)" % i)
                for m in matches:
                    out.add(m.path)
                continue
            out.update(l.path for l in node.leaves())
        return out

    selected = resolve(include) if include else {l.path for r in tree for l in r.leaves()}
    if exclude:
        selected -= resolve(exclude)
    return selected


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_package(base, tree, selected_paths, out_file, progress=None):
    """Write the selected items of the Blender folder ``base`` to ``out_file``."""
    selected_paths = set(selected_paths)
    if not selected_paths:
        raise ValueError("Nothing selected to export.")

    files = []  # (absolute path, archive name)
    for rel in sorted(selected_paths):
        full = os.path.join(base, *rel.split("/"))
        if os.path.isfile(full):
            files.append((full, DATA_PREFIX + rel))
        elif os.path.isdir(full):
            for dirpath, dirnames, filenames in os.walk(full):
                dirnames[:] = sorted(d for d in dirnames if not _skip(d))
                for f in sorted(filenames):
                    if _skip(f):
                        continue
                    ap = os.path.join(dirpath, f)
                    arc = DATA_PREFIX + os.path.relpath(ap, base).replace(os.sep, "/")
                    files.append((ap, arc))

    manifest = {
        "tool": TOOL_NAME,
        "format_version": FORMAT_VERSION,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "blender_version": guess_version(base),
        "source_platform": platform.system(),
        "items": [d for d in (_node_to_dict(n, selected_paths) for n in tree) if d],
    }

    tmp = out_file + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        for i, (ap, arc) in enumerate(files):
            zf.write(ap, arc)
            if progress:
                progress(i + 1, len(files), arc)
    os.replace(tmp, out_file)
    return len(files)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def read_package(pkg_file):
    with zipfile.ZipFile(pkg_file) as zf:
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError:
            raise ValueError("%s is not a %s package (no manifest)." % (pkg_file, TOOL_NAME))
    if manifest.get("format_version", 0) > FORMAT_VERSION:
        raise ValueError("This package was made by a newer version of this tool.")
    return manifest


def _safe_rel(rel):
    """Reject absolute paths and '..' so a package can't write outside the
    Blender folder."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ":" in parts[0] or any(p in ("", "..") for p in parts):
        raise ValueError("Unsafe path in package: %r" % rel)
    return parts


def import_package(pkg_file, target, selected_paths, backup=True, progress=None):
    """Extract the selected items into the Blender version folder ``target``.
    Existing items that get replaced are first saved into a backup zip.
    Returns ``(files_written, backup_file_or_None)``."""
    selected_paths = sorted(set(selected_paths))
    if not selected_paths:
        raise ValueError("Nothing selected to import.")
    for rel in selected_paths:
        _safe_rel(rel)

    with zipfile.ZipFile(pkg_file) as zf:
        members = []
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith(DATA_PREFIX):
                continue
            rel = info.filename[len(DATA_PREFIX):]
            if any(rel == p or rel.startswith(p + "/") for p in selected_paths):
                members.append((info, _safe_rel(rel)))

        # Back up whatever is about to be replaced.
        existing = [p for p in selected_paths if os.path.exists(os.path.join(target, *p.split("/")))]
        backup_file = None
        if backup and existing:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            name = os.path.basename(os.path.normpath(target))
            backup_file = os.path.join(os.path.dirname(os.path.normpath(target)),
                                       "%s_backup_%s.zip" % (name, stamp))
            with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as bz:
                for rel in existing:
                    full = os.path.join(target, *rel.split("/"))
                    if os.path.isfile(full):
                        bz.write(full, rel)
                    else:
                        for dirpath, _, filenames in os.walk(full):
                            for f in filenames:
                                ap = os.path.join(dirpath, f)
                                bz.write(ap, os.path.relpath(ap, target).replace(os.sep, "/"))

        # Replace (not merge) so old leftovers of an add-on don't linger.
        for rel in existing:
            full = os.path.join(target, *rel.split("/"))
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)

        for i, (info, parts) in enumerate(members):
            dest = os.path.join(target, *parts)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if progress:
                progress(i + 1, len(members), "/".join(parts))
    return len(members), backup_file


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def _resolve_base(args, must_exist=True):
    if args.blender_dir:
        base = os.path.abspath(args.blender_dir)
    elif args.version:
        base = os.path.join(default_root(), args.version)
    else:
        inst = find_installations()
        if not inst:
            raise SystemExit("No Blender user folder found. Use --version or --blender-dir.")
        base = inst[0][1]
    if must_exist and not os.path.isdir(base):
        raise SystemExit("Folder does not exist: %s" % base)
    return base


def _print_tree(nodes, selected=None, indent=0):
    for n in nodes:
        size = human_size(n.total_size())
        mark = ""
        if selected is not None:
            mark = "[x] " if all(l.path in selected for l in n.leaves()) else "[ ] "
        print("%s%s%-40s %10s   id: %s" % ("  " * indent, mark, n.label, size, n.id))
        _print_tree(n.children, selected, indent + 1)


def _cli_progress(i, total, name):
    sys.stdout.write("\r  %d/%d files" % (i, total))
    if i == total:
        sys.stdout.write("\n")
    sys.stdout.flush()


def cli(argv):
    p = argparse.ArgumentParser(description="Export / import Blender settings, add-ons and layout.")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--version", help="Blender version folder, e.g. 4.2 (default: newest found)")
        sp.add_argument("--blender-dir", help="Explicit Blender user folder (the one containing 'config' and 'scripts')")
        sp.add_argument("--include", nargs="+", metavar="ID", help="Only these items/groups (see 'list')")
        sp.add_argument("--exclude", nargs="+", metavar="ID", help="Skip these items/groups")

    sp = sub.add_parser("installs", help="Show Blender user folders found on this computer")
    sp = sub.add_parser("list", help="List exportable items of an installation, or items inside a package")
    sp.add_argument("package", nargs="?", help="A package .zip to inspect instead")
    sp.add_argument("--version")
    sp.add_argument("--blender-dir")
    sp = sub.add_parser("export", help="Export settings to a .zip package")
    sp.add_argument("output", help="Package file to create (.zip)")
    common(sp)
    sp = sub.add_parser("import", help="Import a .zip package")
    sp.add_argument("package", help="Package file to import")
    common(sp)
    sp.add_argument("--no-backup", action="store_true", help="Don't back up files that get replaced")
    sp.add_argument("-y", "--yes", action="store_true", help="Don't ask for confirmation")
    sub.add_parser("gui", help="Open the graphical interface (default)")

    args = p.parse_args(argv)

    if args.cmd in (None, "gui"):
        return run_gui()

    if args.cmd == "installs":
        inst = find_installations()
        if not inst:
            print("No Blender user folders found. Looked in:")
            for r in config_roots():
                print("  " + r)
        for label, _ in inst:
            print(label)
        return 0

    if args.cmd == "list":
        if args.package:
            m = read_package(args.package)
            print("Package from Blender %s on %s, created %s\n" % (
                m.get("blender_version") or "?", m.get("source_platform", "?"), m.get("created", "?")))
            _print_tree(tree_from_manifest(m))
        else:
            base = _resolve_base(args)
            print("Blender folder: %s\n" % base)
            _print_tree(scan_installation(base))
        return 0

    if args.cmd == "export":
        base = _resolve_base(args)
        tree = scan_installation(base)
        selected = select_leaves(tree, args.include, args.exclude)
        print("Exporting from %s" % base)
        _print_tree(tree, selected)
        out = args.output if args.output.lower().endswith(".zip") else args.output + ".zip"
        n = export_package(base, tree, selected, out, _cli_progress)
        print("Wrote %d files to %s" % (n, out))
        return 0

    if args.cmd == "import":
        manifest = read_package(args.package)
        tree = tree_from_manifest(manifest)
        if not args.version and not args.blender_dir and manifest.get("blender_version"):
            args.version = manifest["blender_version"]
            print("No target given; using the package's Blender version %s." % args.version)
        base = _resolve_base(args, must_exist=False)
        selected = select_leaves(tree, args.include, args.exclude)
        print("Importing into %s" % base)
        _print_tree(tree, selected)
        print("\nMake sure Blender is closed - it overwrites preferences when it quits.")
        if not args.yes and input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1
        os.makedirs(base, exist_ok=True)
        n, bk = import_package(args.package, base, selected, backup=not args.no_backup, progress=_cli_progress)
        print("Imported %d files." % n)
        if bk:
            print("Previous files backed up to %s" % bk)
        return 0
    return 0


# ---------------------------------------------------------------------------
# GUI (tkinter)
# ---------------------------------------------------------------------------

CHECKED, UNCHECKED, PARTIAL = "☑", "☐", "▣"


def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("tkinter is not available in this Python. Use the command line instead "
              "(run with --help to see the commands).")
        return 1

    class CheckTree(ttk.Frame):
        """A Treeview whose rows can be ticked on/off by clicking."""

        def __init__(self, master, on_change=None):
            super().__init__(master)
            self.on_change = on_change
            self.tv = ttk.Treeview(self, columns=("size",), selectmode="browse")
            self.tv.heading("#0", text="Item")
            self.tv.heading("size", text="Size")
            self.tv.column("#0", width=420, stretch=True)
            self.tv.column("size", width=90, anchor="e", stretch=False)
            sb = ttk.Scrollbar(self, orient="vertical", command=self.tv.yview)
            self.tv.configure(yscrollcommand=sb.set)
            self.tv.grid(row=0, column=0, sticky="nsew")
            sb.grid(row=0, column=1, sticky="ns")
            self.rowconfigure(0, weight=1)
            self.columnconfigure(0, weight=1)
            self.tv.bind("<Button-1>", self._click)
            self.tv.bind("<space>", self._key_toggle)
            self.tv.bind("<<TreeviewSelect>>", self._select)
            self.nodes = {}
            self.state = {}
            self.desc_var = tk.StringVar()

        def load(self, tree, checked=True):
            self.tv.delete(*self.tv.get_children())
            self.nodes.clear()
            self.state.clear()

            def add(parent, n):
                iid = self.tv.insert(parent, "end", text="", values=(human_size(n.total_size()),),
                                     open=False)
                self.nodes[iid] = n
                self.state[iid] = checked
                for c in n.children:
                    add(iid, c)

            for n in tree:
                add("", n)
            self._refresh_all()

        def _refresh_all(self):
            for iid in self.tv.get_children():
                self._refresh(iid)
            if self.on_change:
                self.on_change()

        def _refresh(self, iid):
            kids = self.tv.get_children(iid)
            if kids:
                states = [self._refresh(k) for k in kids]
                if all(s is True for s in states):
                    st = True
                elif all(s is False for s in states):
                    st = False
                else:
                    st = None
                self.state[iid] = st
            st = self.state[iid]
            mark = CHECKED if st is True else UNCHECKED if st is False else PARTIAL
            self.tv.item(iid, text="%s  %s" % (mark, self.nodes[iid].label))
            return st

        def _set(self, iid, value):
            self.state[iid] = value
            for k in self.tv.get_children(iid):
                self._set(k, value)

        def toggle(self, iid):
            self._set(iid, self.state[iid] is not True)
            self._refresh_all()

        def set_all(self, value):
            for iid in self.tv.get_children():
                self._set(iid, value)
            self._refresh_all()

        def _click(self, event):
            if self.tv.identify_region(event.x, event.y) != "tree":
                return
            if "indicator" in self.tv.identify_element(event.x, event.y):
                return  # expand/collapse arrow
            iid = self.tv.identify_row(event.y)
            if iid:
                self.toggle(iid)

        def _key_toggle(self, _event):
            iid = self.tv.focus()
            if iid:
                self.toggle(iid)

        def _select(self, _event):
            sel = self.tv.selection()
            n = self.nodes.get(sel[0]) if sel else None
            self.desc_var.set((n.desc or (n.path or "")) if n else "")

        def selected_paths(self):
            return {n.path for iid, n in self.nodes.items() if not n.is_group and self.state[iid]}

        def selected_size(self):
            return sum(n.size for iid, n in self.nodes.items() if not n.is_group and self.state[iid])

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(TOOL_NAME)
            self.geometry("760x620")
            self.minsize(600, 480)
            nb = ttk.Notebook(self)
            nb.pack(fill="both", expand=True, padx=8, pady=8)
            self.exp = ttk.Frame(nb, padding=8)
            self.imp = ttk.Frame(nb, padding=8)
            nb.add(self.exp, text="  Export  ")
            nb.add(self.imp, text="  Import  ")
            self.status = tk.StringVar(value="Ready.")
            ttk.Label(self, textvariable=self.status, anchor="w", padding=(10, 0, 10, 6)).pack(fill="x")
            self.progress = ttk.Progressbar(self, mode="determinate")
            self.progress.pack(fill="x", padx=10, pady=(0, 8))
            self.installs = find_installations()
            self._build_export()
            self._build_import()

        # ---- shared widgets ----------------------------------------------
        def _folder_picker(self, parent, var, on_change, allow_new):
            row = ttk.Frame(parent)
            values = [l for l, _ in self.installs]
            cb = ttk.Combobox(row, textvariable=var, values=values,
                              state="normal" if allow_new else "readonly")
            cb.pack(side="left", fill="x", expand=True)
            cb.bind("<<ComboboxSelected>>", lambda e: on_change())
            if allow_new:
                cb.bind("<Return>", lambda e: on_change())
                cb.bind("<FocusOut>", lambda e: on_change())

            def browse():
                d = filedialog.askdirectory(title="Choose the Blender user folder (e.g. .../Blender/4.2)")
                if d:
                    var.set(d)
                    on_change()
            ttk.Button(row, text="Browse...", command=browse).pack(side="left", padx=(6, 0))
            return row

        def _path_from(self, text):
            text = text.strip()
            for label, path in self.installs:
                if text == label:
                    return path
            if VERSION_RE.match(text):  # user typed just a version like "4.3"
                return os.path.join(default_root(), text)
            return text

        def _tree_block(self, parent, tree_widget):
            tree_widget.pack(fill="both", expand=True, pady=(6, 4))
            btns = ttk.Frame(parent)
            btns.pack(fill="x")
            ttk.Button(btns, text="Select all", command=lambda: tree_widget.set_all(True)).pack(side="left")
            ttk.Button(btns, text="Select none", command=lambda: tree_widget.set_all(False)).pack(side="left", padx=6)
            ttk.Label(parent, textvariable=tree_widget.desc_var, wraplength=700, foreground="#555",
                      justify="left").pack(fill="x", pady=(6, 0))
            return btns

        def _set_progress(self, i, total, name):
            self.progress["maximum"] = total
            self.progress["value"] = i
            self.status.set("%d/%d  %s" % (i, total, name))
            self.update_idletasks()

        # ---- export tab ----------------------------------------------------
        def _build_export(self):
            f = self.exp
            ttk.Label(f, text="1. Blender installation to export from:").pack(anchor="w")
            self.exp_src = tk.StringVar(value=self.installs[0][0] if self.installs else "")
            self._folder_picker(f, self.exp_src, self._load_export, allow_new=False).pack(fill="x", pady=(2, 8))
            ttk.Label(f, text="2. Tick what you want to export (click a row to toggle):").pack(anchor="w")
            self.exp_tree = CheckTree(f, on_change=self._export_summary)
            btns = self._tree_block(f, self.exp_tree)
            self.exp_summary = tk.StringVar()
            ttk.Label(btns, textvariable=self.exp_summary).pack(side="left", padx=12)
            ttk.Button(btns, text="Export...", command=self._do_export).pack(side="right")
            self._load_export()

        def _load_export(self):
            base = self._path_from(self.exp_src.get())
            self.exp_base = base
            if base and os.path.isdir(base):
                self.exp_tree.load(scan_installation(base))
                self.status.set("Loaded %s" % base)
            else:
                self.exp_tree.load([])
                self.status.set("No Blender user folder found - use Browse... to pick one."
                                if not base else "Folder not found: %s" % base)

        def _export_summary(self):
            n = len(self.exp_tree.selected_paths())
            self.exp_summary.set("%d items, %s" % (n, human_size(self.exp_tree.selected_size())))

        def _do_export(self):
            sel = self.exp_tree.selected_paths()
            if not sel:
                messagebox.showwarning(TOOL_NAME, "Nothing selected.")
                return
            ver = guess_version(self.exp_base) or "custom"
            out = filedialog.asksaveasfilename(
                title="Save settings package", defaultextension=".zip",
                initialfile="blender_%s_settings_%s.zip" % (ver, datetime.date.today().isoformat()),
                filetypes=[("Zip package", "*.zip")])
            if not out:
                return
            try:
                tree = [self.exp_tree.nodes[i] for i in self.exp_tree.tv.get_children()]
                n = export_package(self.exp_base, tree, sel, out, self._set_progress)
            except Exception as e:  # show any failure to the user
                messagebox.showerror(TOOL_NAME, "Export failed:\n%s" % e)
                self.status.set("Export failed.")
                return
            self.status.set("Exported %d files to %s" % (n, out))
            messagebox.showinfo(TOOL_NAME, "Exported %d files to:\n%s" % (n, out))

        # ---- import tab ----------------------------------------------------
        def _build_import(self):
            f = self.imp
            ttk.Label(f, text="1. Settings package (.zip):").pack(anchor="w")
            row = ttk.Frame(f)
            row.pack(fill="x", pady=(2, 8))
            self.imp_pkg = tk.StringVar()
            ttk.Entry(row, textvariable=self.imp_pkg, state="readonly").pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="Open...", command=self._open_pkg).pack(side="left", padx=(6, 0))
            self.imp_info = tk.StringVar(value="No package loaded.")
            ttk.Label(f, textvariable=self.imp_info, foreground="#555").pack(anchor="w")

            ttk.Label(f, text="2. Import into (pick an installation, type a version like 4.2, or Browse):"
                      ).pack(anchor="w", pady=(8, 0))
            self.imp_dst = tk.StringVar(value=self.installs[0][0] if self.installs else "")
            self._folder_picker(f, self.imp_dst, self._import_target_changed, allow_new=True).pack(fill="x", pady=(2, 0))
            self.imp_dst_info = tk.StringVar()
            ttk.Label(f, textvariable=self.imp_dst_info, foreground="#555").pack(anchor="w")

            ttk.Label(f, text="3. Tick what you want to import:").pack(anchor="w", pady=(8, 0))
            self.imp_tree = CheckTree(f)
            btns = self._tree_block(f, self.imp_tree)
            self.imp_backup = tk.BooleanVar(value=True)
            ttk.Checkbutton(btns, text="Back up files that get replaced", variable=self.imp_backup
                            ).pack(side="left", padx=12)
            ttk.Button(btns, text="Import", command=self._do_import).pack(side="right")
            self.imp_manifest = None
            self._import_target_changed()

        def _open_pkg(self):
            path = filedialog.askopenfilename(title="Open settings package",
                                              filetypes=[("Zip package", "*.zip"), ("All files", "*.*")])
            if not path:
                return
            try:
                m = read_package(path)
            except Exception as e:
                messagebox.showerror(TOOL_NAME, str(e))
                return
            self.imp_manifest = m
            self.imp_pkg.set(path)
            self.imp_info.set("Exported from Blender %s on %s, %s" % (
                m.get("blender_version") or "?", m.get("source_platform", "?"), m.get("created", "?")))
            self.imp_tree.load(tree_from_manifest(m))
            # Default target: same version as the package, if nothing matches yet.
            pv = m.get("blender_version")
            if pv:
                match = [l for l, p in self.installs if guess_version(p) == pv]
                self.imp_dst.set(match[0] if match else pv)
            self._import_target_changed()

        def _import_target_changed(self):
            base = self._path_from(self.imp_dst.get())
            if not base:
                self.imp_dst_info.set("")
            elif os.path.isdir(base):
                self.imp_dst_info.set("Target: %s" % base)
            else:
                self.imp_dst_info.set("Target: %s  (will be created)" % base)

        def _do_import(self):
            if not self.imp_manifest:
                messagebox.showwarning(TOOL_NAME, "Open a settings package first.")
                return
            sel = self.imp_tree.selected_paths()
            if not sel:
                messagebox.showwarning(TOOL_NAME, "Nothing selected.")
                return
            base = self._path_from(self.imp_dst.get())
            if not base:
                messagebox.showwarning(TOOL_NAME, "Choose where to import to.")
                return
            pv, tv = self.imp_manifest.get("blender_version"), guess_version(base)
            msg = "Import %d items into:\n%s\n\nMake sure Blender is CLOSED - it overwrites " \
                  "preferences when it quits." % (len(sel), base)
            if pv and tv and pv != tv:
                msg += "\n\nNote: package is from Blender %s, target is %s." % (pv, tv)
            if not messagebox.askokcancel(TOOL_NAME, msg):
                return
            try:
                os.makedirs(base, exist_ok=True)
                n, bk = import_package(self.imp_pkg.get(), base, sel,
                                       backup=self.imp_backup.get(), progress=self._set_progress)
            except Exception as e:
                messagebox.showerror(TOOL_NAME, "Import failed:\n%s" % e)
                self.status.set("Import failed.")
                return
            text = "Imported %d files into:\n%s" % (n, base)
            if bk:
                text += "\n\nPrevious files backed up to:\n%s" % bk
            self.status.set("Imported %d files." % n)
            self.installs = find_installations()
            messagebox.showinfo(TOOL_NAME, text + "\n\nYou can start Blender now.")

    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]) or 0)
