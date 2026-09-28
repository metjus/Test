# SPDX-License-Identifier: GPL-3.0-or-later
"""On-disk history store with deduplicated, compressed snapshots.

A snapshot is not kept as a full ``.blend`` copy. The written file is cut at
Blender's own block boundaries: big blocks (mesh arrays, images ...) are cut
into 256 KiB pieces with their header kept apart, runs of small blocks are
grouped into bundles whose boundaries depend on the block contents (so they
re-align after an insertion). Every piece is stored once, zlib-compressed,
under its SHA-1 in ``chunks/``, and a step is only a small *manifest* listing
the pieces in order. An edit therefore usually adds just the few kilobytes of
blocks that really changed, even for very large files.

Layout of ``<name>_history/``::

    history.json            step list, timeline marker, bookkeeping
    manifests/step_00012.fhm
    chunks/ab/cdef0123...   content-addressed, shared by all steps

This module does not import ``bpy``; the heavy work (hashing, compressing)
runs on a worker thread.
"""

import hashlib
import json
import os
import queue
import shutil
import struct
import tempfile
import threading
import time
import zlib

INDEX_NAME = "history.json"
FORMAT_VERSION = 2

PIECE = 256 * 1024       # max bytes per chunk
SMALL_BLOCK = 64 * 1024  # smaller blocks are bundled together
BUNDLE_MAX = 256 * 1024
MANIFEST_MAGIC = b"FHM1"     # records inline (1.1.0)
MANIFEST_MAGIC_V2 = b"FHM2"  # records stored as deduplicated pieces
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
GZIP_MAGIC = b"\x1f\x8b"


class CorruptHistory(Exception):
    pass


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


def is_compressed_blend(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return head.startswith(ZSTD_MAGIC) or head.startswith(GZIP_MAGIC)


def _atomic_write(path, data):
    tmp = "%s.%d.tmp" % (path, threading.get_ident())
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


# ------------------------------------------------------------ .blend split
def _detect_format(head):
    """Return (file header size, BHead struct, index of the length field)."""
    if not head.startswith(b"BLENDER") or len(head) < 12:
        return None
    marker = head[7:8]
    if marker in (b"-", b"_"):
        # Classic header: BLENDER-v402 (pointer size, endianness, version).
        endian = "<" if head[8:9] == b"v" else ">"
        ptr = "Q" if marker == b"-" else "I"
        return 12, struct.Struct(endian + "4si" + ptr + "ii"), 1
    if head[7:9].isdigit():
        # Blender 5 header: BLENDER17-01v500, large 64-bit block headers.
        size = int(head[7:9])
        return size, struct.Struct("<4siQqq"), 3
    return None


def _fixed_pieces(fh):
    while True:
        piece = fh.read(PIECE)
        if not piece:
            return
        yield "C", piece


def _blocks(fh):
    """Yield ``("I", bytes)`` inline, ``("C", bytes)`` chunk and
    ``("S", bytes)`` small-block segments of a .blend file.

    Concatenating all segments always gives back the exact input: the block
    parser only chooses *where* to cut, so an unknown or odd file format
    merely dedupes worse, it can never corrupt a snapshot.
    """
    head = fh.read(17)
    fmt = _detect_format(head)
    fh.seek(0)
    if fmt is None:
        yield from _fixed_pieces(fh)
        return
    header_size, bhead, len_index = fmt
    yield "I", fh.read(header_size)
    while True:
        raw = fh.read(bhead.size)
        if len(raw) < bhead.size:
            if raw:
                yield "I", raw
            return
        fields = bhead.unpack(raw)
        length = fields[len_index]
        if length < 0:
            yield "I", raw
            yield from _fixed_pieces(fh)
            return
        if length <= SMALL_BLOCK:
            # Header and data together: small blocks carry pointers anyway.
            yield "S", raw + fh.read(length)
        else:
            # Only the header holds the (session dependent) address, so big
            # payloads dedupe even across reloads of the file.
            yield "I", raw
            remaining = length
            while remaining > 0:
                piece = fh.read(min(PIECE, remaining))
                if not piece:
                    return
                yield "C", piece
                remaining -= len(piece)
        if fields[0] == b"ENDB":
            yield from _fixed_pieces(fh)  # trailing bytes, normally none
            return


def split_blend(fh):
    """Yield ``("I", bytes)`` (kept in the manifest) and ``("C", bytes)``
    (stored as a chunk) segments; small blocks are merged into bundles."""
    bundle = []
    size = 0
    for kind, data in _blocks(fh):
        if kind == "S":
            bundle.append(data)
            size += len(data)
            # Content-defined boundary: ~16 blocks per bundle on average.
            if size >= BUNDLE_MAX or zlib.crc32(data) & 15 == 0:
                yield "C", b"".join(bundle)
                bundle, size = [], 0
            continue
        if bundle:
            yield "C", b"".join(bundle)
            bundle, size = [], 0
        yield kind, data
    if bundle:
        yield "C", b"".join(bundle)


# ------------------------------------------------------------- chunk store
def _parse_records(data, pos, origin):
    """Yield ``("I", bytes)`` and ``("C", digest, size)`` manifest records."""
    end = len(data)
    while pos < end:
        kind = data[pos:pos + 1]
        if kind == b"I":
            (size,) = struct.unpack_from("<I", data, pos + 1)
            yield "I", data[pos + 5:pos + 5 + size]
            pos += 5 + size
        elif kind == b"C":
            digest = data[pos + 1:pos + 21]
            (size,) = struct.unpack_from("<I", data, pos + 21)
            yield "C", digest, size
            pos += 25
        else:
            raise CorruptHistory("Bad record in %s" % origin)


class ChunkStore:
    """Content-addressed chunk files plus per-step manifests.

    A manifest's record list is itself cut into content-defined pieces that
    are stored as chunks, so consecutive steps share almost all of it; the
    manifest file only lists those pieces (a few hundred bytes).

    Chunks are reference counted in memory (built by one :meth:`scan` per
    session), so deleting a step costs one manifest read, not a scan of the
    whole history. Only the worker thread may call the mutating methods.
    """

    def __init__(self, root):
        self.root = root
        self._refs = None   # hex digest -> number of manifests using it
        self.used = 0       # bytes of manifests + referenced chunks

    @property
    def chunks_dir(self):
        return os.path.join(self.root, "chunks")

    @property
    def manifests_dir(self):
        return os.path.join(self.root, "manifests")

    def chunk_path(self, hexdigest):
        return os.path.join(self.chunks_dir, hexdigest[:2], hexdigest[2:])

    # ------------------------------------------------------------ writing
    def _put(self, data, level):
        """Store ``data`` once. Returns (digest, bytes newly written)."""
        digest = hashlib.sha1(data).digest()
        path = self.chunk_path(digest.hex())
        if os.path.exists(path):
            return digest, 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        packed = zlib.compress(data, level)
        _atomic_write(path, packed)
        return digest, len(packed)

    def ingest(self, src, manifest_path, level=1):
        """Store ``src`` (an uncompressed .blend) as chunks + manifest.

        Returns ``(raw_size, bytes_added_to_disk)``.
        """
        records = bytearray()
        pieces = []
        referenced = set()
        raw_size = added = 0

        def cut():
            nonlocal added
            digest, new = self._put(bytes(records), 6)
            added += new
            pieces.append(digest + struct.pack("<I", len(records)))
            referenced.add(digest)
            records.clear()

        with open(src, "rb") as fh:
            for kind, data in split_blend(fh):
                raw_size += len(data)
                if kind == "I":
                    records += b"I" + struct.pack("<I", len(data)) + data
                    continue
                digest, new = self._put(data, level)
                added += new
                referenced.add(digest)
                records += b"C" + digest + struct.pack("<I", len(data))
                # Content-defined cut (~1 in 64 chunk records) keeps the
                # pieces of consecutive manifests aligned.
                if digest[0] < 4 or len(records) >= 64 * 1024:
                    cut()
        if records:
            cut()

        packed = zlib.compress(MANIFEST_MAGIC_V2 + b"".join(pieces), 6)
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
        _atomic_write(manifest_path, packed)
        added += len(packed)
        if self._refs is not None:
            for digest in referenced:
                key = digest.hex()
                self._refs[key] = self._refs.get(key, 0) + 1
            self.used += added
        return raw_size, added

    # ------------------------------------------------------------ reading
    def _load_chunk(self, digest, size):
        path = self.chunk_path(digest.hex())
        try:
            with open(path, "rb") as fh:
                data = zlib.decompress(fh.read())
        except (OSError, zlib.error) as ex:
            raise CorruptHistory("Missing or damaged chunk %s (%s)" % (path, ex))
        if len(data) != size or hashlib.sha1(data).digest() != digest:
            raise CorruptHistory("Chunk %s does not match its hash" % path)
        return data

    def _manifest_pieces(self, manifest_path):
        """Return (format, payload): v2 piece list or v1 inline records."""
        try:
            with open(manifest_path, "rb") as fh:
                data = zlib.decompress(fh.read())
        except (OSError, zlib.error) as ex:
            raise CorruptHistory("Cannot read %s: %s" % (manifest_path, ex))
        if data.startswith(MANIFEST_MAGIC_V2):
            body = data[len(MANIFEST_MAGIC_V2):]
            return 2, [(body[i:i + 20], struct.unpack_from("<I", body, i + 20)[0])
                       for i in range(0, len(body), 24)]
        if data.startswith(MANIFEST_MAGIC):
            return 1, data
        raise CorruptHistory("%s is not a history manifest" % manifest_path)

    def read_manifest(self, manifest_path):
        """Yield ``("I", bytes)`` and ``("C", digest, size)`` records."""
        version, payload = self._manifest_pieces(manifest_path)
        if version == 1:
            yield from _parse_records(payload, len(MANIFEST_MAGIC), manifest_path)
            return
        for digest, size in payload:
            yield from _parse_records(self._load_chunk(digest, size), 0, manifest_path)

    def _referenced(self, manifest_path):
        """Hex digests of every chunk a manifest needs (pieces included)."""
        version, payload = self._manifest_pieces(manifest_path)
        refs = set()
        if version == 2:
            refs.update(digest.hex() for digest, _ in payload)
        for record in self.read_manifest(manifest_path):
            if record[0] == "C":
                refs.add(record[1].hex())
        return refs

    def materialize(self, manifest_path, out_path):
        """Rebuild the .blend of a manifest, verifying every chunk."""
        tmp = out_path + ".partial"
        try:
            with open(tmp, "wb") as out:
                for record in self.read_manifest(manifest_path):
                    if record[0] == "I":
                        out.write(record[1])
                    else:
                        out.write(self._load_chunk(record[1], record[2]))
            os.replace(tmp, out_path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    # ----------------------------------------------------------- cleanup
    def scan(self):
        """Rebuild reference counts, delete orphaned chunks, return disk use.

        Runs once per session; afterwards :meth:`ingest` and :meth:`release`
        keep the counts up to date incrementally.
        """
        refs = {}
        used = 0
        if os.path.isdir(self.manifests_dir):
            for name in os.listdir(self.manifests_dir):
                path = os.path.join(self.manifests_dir, name)
                if not name.endswith(".fhm"):
                    continue
                try:
                    for key in self._referenced(path):
                        refs[key] = refs.get(key, 0) + 1
                    used += os.path.getsize(path)
                except CorruptHistory as ex:
                    print("History Timeline: %s" % ex)
        if os.path.isdir(self.chunks_dir):
            for sub in os.listdir(self.chunks_dir):
                subdir = os.path.join(self.chunks_dir, sub)
                for name in os.listdir(subdir):
                    path = os.path.join(subdir, name)
                    if sub + name in refs:
                        used += os.path.getsize(path)
                    else:
                        os.remove(path)  # orphan (or an interrupted write)
                if not os.listdir(subdir):
                    os.rmdir(subdir)
        self._refs = refs
        self.used = used
        return used

    def release(self, manifest_path):
        """Delete a step's manifest and every chunk only it used.

        Returns the bytes still in use afterwards.
        """
        if self._refs is None:
            self.scan()
        try:
            keys = self._referenced(manifest_path)
            size = os.path.getsize(manifest_path)
        except (CorruptHistory, OSError) as ex:
            print("History Timeline: %s" % ex)
            keys, size = set(), 0
        try:
            os.remove(manifest_path)
            self.used -= size
        except OSError:
            pass
        for key in keys:
            count = self._refs.get(key, 0) - 1
            if count > 0:
                self._refs[key] = count
                continue
            self._refs.pop(key, None)
            path = self.chunk_path(key)
            try:
                self.used -= os.path.getsize(path)
                os.remove(path)
            except OSError:
                pass
        return self.used


# ------------------------------------------------------------------ worker
class Worker:
    """Runs storage jobs one at a time, off the UI thread.

    Results are handed back through :meth:`poll` / :meth:`wait`, which must be
    called from Blender's main thread. With ``threaded=False`` jobs run
    immediately (background mode and tests).
    """

    def __init__(self):
        self.threaded = True
        self._jobs = queue.Queue()
        self._results = queue.Queue()
        self._thread = None
        self.outstanding = 0

    def submit(self, fn, *args, on_done=None):
        self.outstanding += 1
        if not self.threaded:
            self._finish(on_done, *self._call(fn, args))
            return
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="HistoryTimeline", daemon=True)
            self._thread.start()
        self._jobs.put((fn, args, on_done))

    @staticmethod
    def _call(fn, args):
        try:
            return fn(*args), None
        except Exception as ex:  # reported to on_done on the main thread
            return None, ex

    def _run(self):
        while True:
            fn, args, on_done = self._jobs.get()
            result, error = self._call(fn, args)
            self._results.put((on_done, result, error))

    def _finish(self, on_done, result, error):
        self.outstanding -= 1
        if on_done is not None:
            on_done(result, error)
        elif error is not None:
            print("History Timeline: background job failed: %s" % error)

    def poll(self):
        """Process finished jobs. Returns True while jobs are outstanding."""
        while True:
            try:
                item = self._results.get_nowait()
            except queue.Empty:
                break
            self._finish(*item)
        return self.outstanding > 0

    def wait(self):
        """Block until every submitted job has finished."""
        while self.outstanding > 0:
            self._finish(*self._results.get())


# ------------------------------------------------------------ history store
class HistoryStore:
    """A linear list of snapshot steps with a movable "current" marker.

    Restoring an older step never deletes anything: the marker moves back and
    later steps are shown as *rolled back* (like Fusion's timeline marker).
    New work after a rollback is appended with ``parent`` pointing at the step
    it branched from, so every state ever captured stays reachable.
    """

    def __init__(self, directory, blend_path=""):
        self.dir = directory
        self._chunks = None
        self._released = []
        self._positions = None  # step id -> index, rebuilt after list changes
        self.data = {
            "version": FORMAT_VERSION,
            "blend": blend_path,
            "next_id": 1,
            "current": 0,
            "saved_step": 0,
            "saved_mtime": 0.0,
            "disk_bytes": 0,
            "steps": [],
        }

    # ------------------------------------------------------------------ io
    @property
    def index_path(self):
        return os.path.join(self.dir, INDEX_NAME)

    @property
    def chunks(self):
        if self._chunks is None or self._chunks.root != self.dir:
            self._chunks = ChunkStore(self.dir)
        return self._chunks

    def take_released(self):
        """Manifests of removed steps, to be passed to ChunkStore.release."""
        paths, self._released = self._released, []
        return paths

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
            # Drop steps whose manifest never got written (e.g. Blender quit
            # while it was being stored) or that predate this format.
            store.data["steps"] = [
                s for s in store.data["steps"] if "manifest" in s and os.path.isfile(store.path(s))
            ]
            for step in store.steps:
                step.pop("pending", None)
            store._positions = None
            if store.get(store.current) is None:
                store.data["current"] = store.steps[-1]["id"] if store.steps else 0
            store.data["version"] = FORMAT_VERSION
        if blend_path:
            store.data["blend"] = blend_path
        store.remove_temp_files()
        return store

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.index_path + ".tmp"
        # dumps() uses the C encoder; dump() to a file would not (10x slower).
        text = json.dumps(self.data, separators=(",", ":"))
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self.index_path)

    def remove_temp_files(self):
        if not os.path.isdir(self.dir):
            return
        for name in os.listdir(self.dir):
            if name.startswith(".ingest_") or name.startswith(".snapshot"):
                try:
                    os.remove(os.path.join(self.dir, name))
                except OSError:
                    pass

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
        """Manifest file of ``step``."""
        return os.path.join(self.dir, "manifests", step["manifest"])

    def snapshot_path(self):
        """Where a snapshot is written before being chunked."""
        return os.path.join(self.dir, ".snapshot.blend")

    def ingest_path(self, step):
        return os.path.join(self.dir, ".ingest_%05d.blend" % step["id"])

    def index_of(self, step_id):
        if self._positions is None:
            self._positions = {s["id"]: i for i, s in enumerate(self.steps)}
        return self._positions.get(step_id, -1)

    def get(self, step_id):
        idx = self.index_of(step_id)
        return self.steps[idx] if idx >= 0 else None

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

    @property
    def disk_bytes(self):
        return self.data.get("disk_bytes", 0)

    # ------------------------------------------------------------- editing
    def new_step(self, label, idname="", category="other", detail=""):
        """Reserve a step id. Add it with :meth:`commit`."""
        step_id = self.data["next_id"]
        self.data["next_id"] = step_id + 1
        return {
            "id": step_id,
            "manifest": "step_%05d.fhm" % step_id,
            "label": label,
            "idname": idname,
            "category": category,
            "detail": detail,
            "time": time.time(),
            "parent": self.current,
            "pinned": False,
            "pending": True,
            "raw_size": 0,
            "added": 0,
        }

    def commit(self, step):
        """Add a (pending) step; the index is saved once it is stored."""
        self.steps.append(step)
        self._positions = None
        self.current = step["id"]
        return step

    def _removable(self):
        return [s for s in self.steps
                if not s.get("pinned") and not s.get("pending") and s["id"] != self.current]

    def prune(self, max_steps):
        """Drop the oldest unpinned steps until at most ``max_steps`` remain.

        Returns the number of removed steps (see :meth:`take_released`).
        """
        excess = len(self.steps) - max_steps if max_steps else 0
        removed = 0
        for step in self._removable()[:max(0, excess)]:
            self._remove(step)
            removed += 1
        return removed

    def drop_oldest(self):
        removable = self._removable()
        if not removable:
            return False
        self._remove(removable[0])
        return True

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
        # Files are deleted by the worker (ChunkStore.release), which also
        # frees the chunks nothing else uses.
        self._released.append(self.path(step))
        self.steps.remove(step)
        self._positions = None

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
