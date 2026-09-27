#!/usr/bin/env python3
"""
Blender Fox Transfer
=========================

Export your Blender user setup (preferences, startup layout, add-ons,
extensions, presets, ...) into a single .zip package and import it on
another computer - choosing exactly which parts you want.

Run without arguments to open the GUI:

    python blender_fox_transfer.py

Or use the command line:

    python blender_fox_transfer.py list
    python blender_fox_transfer.py export my_setup.zip
    python blender_fox_transfer.py export my_setup.zip --include preferences startup addons
    python blender_fox_transfer.py import my_setup.zip --version 4.2
    python blender_fox_transfer.py import my_setup.zip --exclude recent_files

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

TOOL_NAME = "Blender Fox Transfer"
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
    "accent": "#ec6408",
    "accent_hover": "#f57a22",
    "accent_press": "#c8420a",
    "accent_soft": "#fdeee3",
    "accent_disabled": "#f3c3a0",
    "header": "#1e2126",
    "header_text": "#ffffff",
    "header_muted": "#9aa1ab",
    "header_hover": "#2c3037",
    "check_border": "#a9b0ba",
}


# Fox logo, embedded so the single .py / .exe needs no extra files.
LOGO_PNG = {
    44: (
        "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"
        "DcptLWEJ2MuRAAAAAElFTkSuQmCC"
    ),
    88: (
        "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"
    ),
    128: (
        "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"
        "nEp00ImY3vnQ3Y8pzkB652K7Z3R0GpPUgiM1Zsr5Qwq43Q9Qu+13xNf9GLlnFbvXOirTD+PwH9yKREE3sFqtsm3btqbmYTsxRsVi"
        "8wWqX38X9UuXY3vCzhdPUjIuGu+be92sD9/45K8eN7dyTuDJ7vMF+pu1y5etXq2XL14cPf5Hl24865mnXG9Htp0p9UrGifXNmZIq"
        "SDYi3j6EF0ffY0/FZHKUV19H9c7bMflMWII2EEZTirnJZKjXhfJIaDPLFyeo2P3dtwb7akIPpAhSG4eta0h2bwnElO5ZmL752K5+"
        "iLKdNQcbBbeeYvmaVHC7NxLf/1eq1/6Yyq/Oo/bz9+P+8lPMzrWMlrPs3uSY/ZaP033ko8F7dqUd0PV6HWtNy8V5B5kcNrJUv3I2"
        "yWU/xzQWH0lKxkfV3llrzGnvOPWgZ582uHLpUpElq/Rv94h/w+3yxYujJatWJTe84ZTT8vde8ws3NpqPjXEiWNWWkoBX4fBvXU3p"
        "0OPZ+fsfsu69LyHqzoWKWEeELQ2SetosEtaot1eZMcuTyXhcMjk7eChZdmM0q0grlGygfh2skTpoPXUQBZC+OUj/POiaAaVp2KgL"
        "sQbvquj4EFreBSNb0aGt6Ng4Eqdqs0XwkmH3zojBByr0PupEDvrqVYyOjrJz5y7GK5Ww8O2cCJdAoQtTHaP2pbcRX/NHpCeLhKGU"
        "Sbe4qNY1bU3t8S942iM/+OX1ywcG7N/Syv4P6XZpUMpvfsMzTrNrrlwu1ZHuKhknDQ9jDH6sRvH4x3HEV64gGd3FHS8+Bj+4A2kb"
        "KauYcH5ImEYuDbK9hpp9JhPIIL29nsiEYVbaJs73UL6MT+XPzR7SMG3MC5K0gOYTSDQIirlJmppNhyIm9avWIkawBsbLsGubBCa5"
        "U+Z99vfU938Eg9tCHSFQ4dupcwmmux+23Mv4/7wZXXMbpjuXLj5Jj/FRrdi/pnLCc572yPMvWL83qPefdgS03767Hn/5YqLH/XTN"
        "Pa867Ul/MuWhZ+WTak9dJTESIDeTy1K7dx1Oakw76bmMr7+b8VtuxBYyzVEv7U2cbRTfFoavUC4bKuWAIeTzaRpOGiQ/BAtoH2DR"
        "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"
    ),
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
            self.logo = {n: tk.PhotoImage(data=d) for n, d in LOGO_PNG.items()}
            self.iconphoto(True, self.logo[128], self.logo[44])
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
            tk.Label(h, image=self.logo[88 if self.scale >= 1.5 else 44], bg=C["header"]).pack(
                side="left", padx=(0, px(12)))
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
