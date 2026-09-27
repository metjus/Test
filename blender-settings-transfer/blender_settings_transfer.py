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

    def resolve(ids, strict=True):
        out = set()
        for i in ids:
            node = by_id.get(i)
            if node is None:
                # Allow the short name shown in 'list', e.g. "node_wrangler"
                # instead of "scripts/addons/node_wrangler.py".
                matches = [n for n in by_id.values() if not n.is_group and
                           (n.id.endswith("/" + i) or n.label == i)]
                if not matches and not strict:
                    continue  # excluding something that isn't there is fine
                if not matches:
                    raise SystemExit("Unknown item: %r  (use the 'list' command to see ids)" % i)
                for m in matches:
                    out.add(m.path)
                continue
            out.update(l.path for l in node.leaves())
        return out

    selected = resolve(include) if include else {l.path for r in tree for l in r.leaves()}
    if exclude:
        selected -= resolve(exclude, strict=False)
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

COLORS = {
    "bg": "#f3f4f6",
    "card": "#ffffff",
    "border": "#dde0e5",
    "text": "#1d2127",
    "muted": "#6b7280",
    "accent": "#e87d0d",
    "accent_hover": "#f28d22",
    "accent_press": "#c86a08",
    "accent_soft": "#fdf1e4",
    "accent_disabled": "#efc9a2",
    "header": "#1e2126",
    "header_text": "#ffffff",
    "header_muted": "#9aa1ab",
    "header_hover": "#2c3037",
    "check_border": "#a9b0ba",
}


def _enable_windows_dpi_awareness():
    """Without this Windows renders the window blurry on scaled displays."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _make_checkbox_image(tk, size, state, bg):
    """Draw a rounded checkbox (state True/False/None=partial) as a PhotoImage."""
    c = COLORS
    img = tk.PhotoImage(width=size, height=size)
    radius = max(2.0, size / 5.0)
    border = max(1.0, size / 12.0)
    stroke = max(1.5, size / 9.0)

    def inside(x, y, inset):
        lo, hi = inset + radius, size - 1 - inset - radius
        dx = max(lo - x, 0, x - hi)
        dy = max(lo - y, 0, y - hi)
        return dx * dx + dy * dy <= radius * radius

    def near_segment(px, py, ax, ay, bx, by):
        ax, ay, bx, by = ax * size, ay * size, bx * size, by * size
        vx, vy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
        dx, dy = px - (ax + t * vx), py - (ay + t * vy)
        return dx * dx + dy * dy <= (stroke / 2.0) ** 2

    transparent = []
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            if not inside(x, y, 0):
                row.append(bg)
                transparent.append((x, y))
            elif state is False:
                row.append(c["card"] if inside(x, y, border) else c["check_border"])
            else:
                mark = (near_segment(px, py, 0.26, 0.52, 0.43, 0.69) or
                        near_segment(px, py, 0.43, 0.69, 0.75, 0.33)) if state else \
                    (abs(py - size / 2.0) <= stroke / 2.0 and size * 0.27 <= px <= size * 0.73)
                row.append("#ffffff" if mark else c["accent"])
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows))
    for x, y in transparent:
        try:
            img.tk.call(img.name, "transparency", "set", x, y, 1)
        except Exception:
            break
    return img


def run_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, font as tkfont
    except ImportError:
        print("tkinter is not available in this Python. Use the command line instead "
              "(run with --help to see the commands).")
        return 1
    import queue
    import threading

    _enable_windows_dpi_awareness()
    C = COLORS

    class CheckTree(tk.Frame):
        """A card with a Treeview whose rows can be ticked on/off by clicking."""

        def __init__(self, master, app, empty_text, on_change=None):
            super().__init__(master, bg=C["card"], highlightthickness=1,
                             highlightbackground=C["border"], highlightcolor=C["border"])
            self.app = app
            self.on_change = None
            self.tv = ttk.Treeview(self, columns=("size",), selectmode="browse")
            self.tv.heading("#0", text="ITEM", anchor="w")
            self.tv.heading("size", text="SIZE", anchor="e")
            self.tv.column("#0", width=app.px(460), stretch=True)
            self.tv.column("size", width=app.px(100), anchor="e", stretch=False)
            self.tv.tag_configure("group", font=app.font_bold)
            self.tv.tag_configure("leaf", foreground=C["text"])
            sb = ttk.Scrollbar(self, orient="vertical", command=self.tv.yview)
            self.tv.configure(yscrollcommand=sb.set)
            self.tv.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=(1, 0))
            sb.grid(row=0, column=1, sticky="ns")
            tk.Frame(self, bg=C["border"], height=1).grid(row=1, column=0, columnspan=2, sticky="ew")
            self.desc_var = tk.StringVar()
            tk.Label(self, textvariable=self.desc_var, bg=C["card"], fg=C["muted"], font=app.font_small,
                     anchor="w", justify="left", wraplength=app.px(760), padx=app.px(14), pady=app.px(10)
                     ).grid(row=2, column=0, columnspan=2, sticky="ew")
            self.rowconfigure(0, weight=1)
            self.columnconfigure(0, weight=1)
            self.empty = tk.Label(self, text=empty_text, bg=C["card"], fg=C["muted"], font=app.font_body,
                                  justify="center")
            self.tv.bind("<Button-1>", self._click)
            self.tv.bind("<space>", self._key_toggle)
            self.tv.bind("<<TreeviewSelect>>", self._select)
            self.nodes = {}
            self.state = {}
            self.load([])
            self.on_change = on_change

        def load(self, tree, checked=True):
            self.tv.delete(*self.tv.get_children())
            self.nodes.clear()
            self.state.clear()

            def add(parent, n):
                iid = self.tv.insert(parent, "end", text="", values=(human_size(n.total_size()),),
                                     tags=("group" if n.is_group else "leaf",))
                self.nodes[iid] = n
                self.state[iid] = checked
                for c in n.children:
                    add(iid, c)

            for n in tree:
                add("", n)
            if tree:
                self.empty.place_forget()
                self.desc_var.set("Click a row to tick or untick it. Expand groups with the arrow "
                                  "to pick single add-ons.")
            else:
                self.empty.place(relx=0.5, rely=0.42, anchor="center")
                self.desc_var.set("")
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
                    self.state[iid] = True
                elif all(s is False for s in states):
                    self.state[iid] = False
                else:
                    self.state[iid] = None
            self.tv.item(iid, image=self.app.check_images[self.state[iid]],
                         text="  " + self.nodes[iid].label)
            return self.state[iid]

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

        def roots(self):
            return [self.nodes[i] for i in self.tv.get_children()]

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
            if n:
                self.desc_var.set(n.desc or n.path or "")

        def selected_paths(self):
            return {n.path for iid, n in self.nodes.items() if not n.is_group and self.state[iid]}

        def selected_size(self):
            return sum(n.size for iid, n in self.nodes.items() if not n.is_group and self.state[iid])

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(TOOL_NAME)
            self.configure(bg=C["bg"])
            self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
            self._setup_fonts()
            self._setup_style()
            size = self.px(20)
            self.check_images = {s: _make_checkbox_image(tk, size, s, C["card"]) for s in (True, False, None)}
            self.iconphoto(True, _make_checkbox_image(tk, 64, True, C["bg"]))
            self.geometry("%dx%d" % (self.px(900), self.px(760)))
            self.minsize(self.px(680), self.px(560))

            self.installs = find_installations()
            self.busy = False
            self.action_buttons = []
            self._build_header()
            self._build_footer()
            self.body = tk.Frame(self, bg=C["bg"])
            self.body.pack(fill="both", expand=True, padx=self.px(22), pady=(self.px(16), 0))
            self.pages = {"export": tk.Frame(self.body, bg=C["bg"]), "import": tk.Frame(self.body, bg=C["bg"])}
            self._build_export(self.pages["export"])
            self._build_import(self.pages["import"])
            self.show_page("export")

        # ---- look & feel ---------------------------------------------------
        def px(self, v):
            return int(round(v * self.scale))

        def _setup_fonts(self):
            base = tkfont.nametofont("TkDefaultFont")
            if sys.platform == "win32":
                base.configure(family="Segoe UI", size=10)
            elif sys.platform != "darwin":
                base.configure(size=10)
            for name in ("TkTextFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(name).configure(family=base.cget("family"), size=base.cget("size"))
                except tk.TclError:
                    pass
            fam, sz = base.cget("family"), base.cget("size")
            self.font_body = tkfont.Font(family=fam, size=sz)
            self.font_bold = tkfont.Font(family=fam, size=sz, weight="bold")
            self.font_small = tkfont.Font(family=fam, size=max(sz - 1, 8))
            self.font_step = tkfont.Font(family=fam, size=max(sz - 1, 8), weight="bold")
            self.font_title = tkfont.Font(family=fam, size=sz + 6, weight="bold")
            self.font_big = tkfont.Font(family=fam, size=sz + 1, weight="bold")

        def _setup_style(self):
            s = ttk.Style(self)
            s.theme_use("clam")
            px = self.px
            s.configure(".", background=C["bg"], foreground=C["text"], bordercolor=C["border"],
                        lightcolor=C["border"], darkcolor=C["border"], focuscolor=C["accent"],
                        troughcolor=C["bg"], font=self.font_body)
            s.configure("Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["text"],
                        rowheight=px(32), borderwidth=0, relief="flat", indent=px(24))
            s.map("Treeview", background=[("selected", C["accent_soft"])],
                  foreground=[("selected", C["text"])])
            s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
            s.configure("Treeview.Heading", background=C["card"], foreground=C["muted"], relief="flat",
                        borderwidth=0, font=self.font_step, padding=(px(10), px(8)))
            s.map("Treeview.Heading", background=[("active", C["card"])])
            s.configure("TButton", background=C["card"], foreground=C["text"], bordercolor=C["border"],
                        lightcolor=C["card"], darkcolor=C["card"], relief="flat", padding=(px(14), px(7)))
            s.map("TButton", background=[("disabled", C["bg"]), ("pressed", "#e6e8ec"), ("active", "#eef0f3")],
                  foreground=[("disabled", C["muted"])])
            s.configure("Accent.TButton", background=C["accent"], foreground="#ffffff", bordercolor=C["accent"],
                        lightcolor=C["accent"], darkcolor=C["accent"], font=self.font_big,
                        padding=(px(26), px(10)))
            s.map("Accent.TButton",
                  background=[("disabled", C["accent_disabled"]), ("pressed", C["accent_press"]),
                              ("active", C["accent_hover"])],
                  bordercolor=[("disabled", C["accent_disabled"]), ("pressed", C["accent_press"]),
                               ("active", C["accent_hover"])],
                  lightcolor=[("disabled", C["accent_disabled"]), ("active", C["accent_hover"])],
                  darkcolor=[("disabled", C["accent_disabled"]), ("active", C["accent_hover"])],
                  foreground=[("disabled", "#ffffff")])
            s.configure("TCombobox", fieldbackground=C["card"], background=C["card"], arrowcolor=C["muted"],
                        bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"],
                        padding=(px(8), px(6)), arrowsize=px(14))
            s.map("TCombobox", fieldbackground=[("readonly", C["card"])],
                  bordercolor=[("focus", C["accent"])], selectbackground=[("readonly", C["card"])],
                  selectforeground=[("readonly", C["text"])])
            s.configure("TEntry", fieldbackground=C["card"], bordercolor=C["border"], lightcolor=C["card"],
                        darkcolor=C["card"], padding=(px(8), px(6)))
            s.configure("TCheckbutton", background=C["bg"], indicatorbackground=C["card"],
                        indicatorforeground=C["accent"], focuscolor=C["bg"])
            s.map("TCheckbutton", background=[("active", C["bg"])],
                  indicatorbackground=[("selected", C["card"])])
            s.configure("Vertical.TScrollbar", background=C["bg"], troughcolor=C["card"], bordercolor=C["card"],
                        lightcolor=C["bg"], darkcolor=C["bg"], arrowcolor=C["muted"], gripcount=0)
            s.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor=C["border"],
                        bordercolor=C["border"], lightcolor=C["accent"], darkcolor=C["accent"],
                        thickness=px(4))
            self.option_add("*TCombobox*Listbox.font", self.font_body)
            self.option_add("*TCombobox*Listbox.selectBackground", C["accent_soft"])
            self.option_add("*TCombobox*Listbox.selectForeground", C["text"])

        # ---- layout pieces -------------------------------------------------
        def _build_header(self):
            px = self.px
            h = tk.Frame(self, bg=C["header"], padx=px(22), pady=px(14))
            h.pack(fill="x")
            titles = tk.Frame(h, bg=C["header"])
            titles.pack(side="left")
            tk.Label(titles, text=TOOL_NAME, bg=C["header"], fg=C["header_text"],
                     font=self.font_title).pack(anchor="w")
            tk.Label(titles, text="Move preferences, layout and add-ons to another computer",
                     bg=C["header"], fg=C["header_muted"], font=self.font_small).pack(anchor="w")
            seg = tk.Frame(h, bg=C["header_hover"], padx=px(3), pady=px(3))
            seg.pack(side="right")
            self.seg_buttons = {}
            for key, text in (("export", "Export"), ("import", "Import")):
                b = tk.Label(seg, text=text, font=self.font_bold, padx=px(22), pady=px(6), cursor="hand2")
                b.pack(side="left")
                b.bind("<Button-1>", lambda e, k=key: self.show_page(k))
                self.seg_buttons[key] = b

        def _build_footer(self):
            px = self.px
            f = tk.Frame(self, bg=C["bg"])
            f.pack(side="bottom", fill="x", padx=px(22), pady=(px(6), px(12)))
            self.status = tk.StringVar(value="Ready.")
            tk.Label(f, textvariable=self.status, bg=C["bg"], fg=C["muted"], font=self.font_small,
                     anchor="w").pack(side="bottom", fill="x")
            self.footer = f
            self.progress = ttk.Progressbar(f, mode="determinate")  # shown only while working

        def show_page(self, key):
            if self.busy:
                return
            for k, page in self.pages.items():
                page.pack_forget()
                on = k == key
                self.seg_buttons[k].configure(bg=C["accent"] if on else C["header_hover"],
                                              fg="#ffffff" if on else C["header_muted"])
            self.pages[key].pack(fill="both", expand=True)

        def _step(self, parent, number, title, hint=None):
            px = self.px
            row = tk.Frame(parent, bg=C["bg"])
            row.pack(fill="x", pady=(px(10), px(6)))
            tk.Label(row, text=str(number), bg=C["accent"], fg="#ffffff", font=self.font_step,
                     width=2, pady=px(1)).pack(side="left")
            tk.Label(row, text=title, bg=C["bg"], fg=C["text"], font=self.font_bold,
                     padx=px(10)).pack(side="left")
            if hint:
                tk.Label(row, text=hint, bg=C["bg"], fg=C["muted"], font=self.font_small).pack(side="left")
            return row

        def _folder_picker(self, parent, var, on_change, allow_new):
            row = tk.Frame(parent, bg=C["bg"])
            cb = ttk.Combobox(row, textvariable=var, values=[l for l, _ in self.installs],
                              state="normal" if allow_new else "readonly", font=self.font_body)
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
            ttk.Button(row, text="Browse…", command=browse).pack(side="left", padx=(self.px(8), 0))
            return row

        def _path_from(self, text):
            text = text.strip()
            for label, path in self.installs:
                if text == label:
                    return path
            if VERSION_RE.match(text):  # user typed just a version like "4.3"
                return os.path.join(default_root(), text)
            return text

        def _action_bar(self, parent, tree, summary_var, button_text, command):
            px = self.px
            bar = tk.Frame(parent, bg=C["bg"])
            bar.pack(side="bottom", fill="x", pady=(px(12), 0))  # reserve room before the tree
            ttk.Button(bar, text="Select all", command=lambda: tree.set_all(True)).pack(side="left")
            ttk.Button(bar, text="Select none", command=lambda: tree.set_all(False)).pack(
                side="left", padx=(px(6), 0))
            btn = ttk.Button(bar, text=button_text, style="Accent.TButton", command=command)
            btn.pack(side="right")
            tk.Label(bar, textvariable=summary_var, bg=C["bg"], fg=C["muted"], font=self.font_small,
                     padx=px(14)).pack(side="right")
            self.action_buttons.append(btn)
            return bar

        # ---- background work -----------------------------------------------
        def _run_task(self, work, done):
            """Run ``work(progress)`` in a thread so the window stays responsive."""
            self._set_busy(True)
            q = queue.Queue()

            def progress(i, total, name):
                q.put(("progress", i, total, name))

            def runner():
                try:
                    q.put(("ok", work(progress)))
                except Exception as e:  # reported in the UI thread
                    q.put(("error", e))

            threading.Thread(target=runner, daemon=True).start()

            def poll():
                last = None
                try:
                    while True:
                        msg = q.get_nowait()
                        if msg[0] == "progress":
                            last = msg
                        else:
                            if last:
                                self._show_progress(*last[1:])
                            self._set_busy(False)
                            done(msg[0] == "ok", msg[1])
                            return
                except queue.Empty:
                    pass
                if last:
                    self._show_progress(*last[1:])
                self.after(40, poll)
            poll()

        def _show_progress(self, i, total, name):
            self.progress["maximum"] = max(total, 1)
            self.progress["value"] = i
            self.status.set("%d / %d   %s" % (i, total, name))

        def _set_busy(self, busy):
            self.busy = busy
            if busy:
                self.progress["value"] = 0
                self.progress.pack(fill="x", pady=(0, self.px(6)))
            else:
                self.progress.pack_forget()
            for b in self.action_buttons:
                b.state(["disabled"] if busy else ["!disabled"])
            self.configure(cursor="watch" if busy else "")

        # ---- export page ---------------------------------------------------
        def _build_export(self, f):
            self._step(f, 1, "Blender installation to export from")
            self.exp_src = tk.StringVar(value=self.installs[0][0] if self.installs else "")
            self._folder_picker(f, self.exp_src, self._load_export, allow_new=False).pack(fill="x")
            self._step(f, 2, "Choose what to export", "Click a row to tick or untick it")
            self.exp_tree = CheckTree(f, self, "No Blender settings found.\n\n"
                                      "Pick an installation above, or use Browse… for a portable Blender.",
                                      on_change=self._export_summary)
            self.exp_summary = tk.StringVar()
            self._action_bar(f, self.exp_tree, self.exp_summary, "Export…", self._do_export)
            self.exp_tree.pack(fill="both", expand=True)
            self._load_export()

        def _load_export(self):
            base = self._path_from(self.exp_src.get())
            self.exp_base = base
            if base and os.path.isdir(base):
                self.exp_tree.load(scan_installation(base))
                self.status.set("Loaded %s" % base)
            else:
                self.exp_tree.load([])
                self.status.set("No Blender user folder found – use Browse… to pick one."
                                if not base else "Folder not found: %s" % base)

        def _export_summary(self):
            n = len(self.exp_tree.selected_paths())
            self.exp_summary.set("%d item%s selected · %s" % (n, "" if n == 1 else "s",
                                                             human_size(self.exp_tree.selected_size())))

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
            base, tree = self.exp_base, self.exp_tree.roots()

            def done(ok, result):
                if not ok:
                    self.status.set("Export failed.")
                    messagebox.showerror(TOOL_NAME, "Export failed:\n%s" % result)
                    return
                self.status.set("Exported %d files to %s" % (result, out))
                messagebox.showinfo(TOOL_NAME, "Exported %d files to:\n%s" % (result, out))

            self._run_task(lambda progress: export_package(base, tree, sel, out, progress), done)

        # ---- import page ---------------------------------------------------
        def _build_import(self, f):
            px = self.px
            self._step(f, 1, "Settings package")
            row = tk.Frame(f, bg=C["bg"])
            row.pack(fill="x")
            self.imp_pkg = tk.StringVar()
            ttk.Entry(row, textvariable=self.imp_pkg, state="readonly", font=self.font_body).pack(
                side="left", fill="x", expand=True)
            ttk.Button(row, text="Open package…", command=self._open_pkg).pack(side="left", padx=(px(8), 0))
            self.imp_info = tk.StringVar()
            tk.Label(f, textvariable=self.imp_info, bg=C["bg"], fg=C["muted"], font=self.font_small,
                     anchor="w").pack(fill="x", pady=(px(4), 0))

            self._step(f, 2, "Import into", "Pick an installation, type a version like 4.3, or Browse…")
            self.imp_dst = tk.StringVar(value=self.installs[0][0] if self.installs else "")
            self._folder_picker(f, self.imp_dst, self._import_target_changed, allow_new=True).pack(fill="x")
            self.imp_dst_info = tk.StringVar()
            tk.Label(f, textvariable=self.imp_dst_info, bg=C["bg"], fg=C["muted"], font=self.font_small,
                     anchor="w").pack(fill="x", pady=(px(4), 0))

            self._step(f, 3, "Choose what to import")
            self.imp_tree = CheckTree(f, self, "Open a settings package (.zip) to see what's inside.",
                                      on_change=self._import_summary)
            self.imp_summary = tk.StringVar()
            bar = self._action_bar(f, self.imp_tree, self.imp_summary, "Import", self._do_import)
            self.imp_tree.pack(fill="both", expand=True)
            self.imp_backup = tk.BooleanVar(value=True)
            ttk.Checkbutton(bar, text="Back up replaced files", variable=self.imp_backup).pack(
                side="left", padx=(px(14), 0))
            self.imp_manifest = None
            self._import_target_changed()

        def _import_summary(self):
            n = len(self.imp_tree.selected_paths())
            self.imp_summary.set("%d item%s selected" % (n, "" if n == 1 else "s") if self.imp_tree.nodes else "")

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
            self.imp_info.set("Exported from Blender %s on %s · %s" % (
                m.get("blender_version") or "?", m.get("source_platform", "?"),
                (m.get("created") or "?").replace("T", " ")))
            self.imp_tree.load(tree_from_manifest(m))
            # Default target: same version as the package.
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
                self.imp_dst_info.set("→ %s" % base)
            else:
                self.imp_dst_info.set("→ %s   (new folder, will be created)" % base)

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
            msg = "Import %d items into:\n%s\n\nMake sure Blender is CLOSED – it overwrites " \
                  "preferences when it quits." % (len(sel), base)
            if pv and tv and pv != tv:
                msg += "\n\nNote: package is from Blender %s, target is %s." % (pv, tv)
            if not messagebox.askokcancel(TOOL_NAME, msg):
                return
            pkg, backup = self.imp_pkg.get(), self.imp_backup.get()

            def work(progress):
                os.makedirs(base, exist_ok=True)
                return import_package(pkg, base, sel, backup=backup, progress=progress)

            def done(ok, result):
                if not ok:
                    self.status.set("Import failed.")
                    messagebox.showerror(TOOL_NAME, "Import failed:\n%s" % result)
                    return
                n, bk = result
                text = "Imported %d files into:\n%s" % (n, base)
                if bk:
                    text += "\n\nPrevious files backed up to:\n%s" % bk
                self.status.set("Imported %d files into %s" % (n, base))
                self.installs = find_installations()
                messagebox.showinfo(TOOL_NAME, text + "\n\nYou can start Blender now.")

            self._run_task(work, done)

    App().mainloop()
    return 0


if __name__ == "__main__":
    # A windowed .exe/.app has no console: give print() somewhere to go.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    # Older macOS passes a "-psn_..." process id when an .app is double-clicked.
    sys.exit(cli([a for a in sys.argv[1:] if not a.startswith("-psn_")]) or 0)
