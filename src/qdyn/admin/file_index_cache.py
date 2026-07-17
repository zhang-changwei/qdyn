"""Background file index cache with in-memory snapshot.

Periodically scans work_dir_base and builds an in-memory file manifest:
- per-leaf: ``{file_summary, file_count, size_bytes}``
- basename inverted index: ``{basename: [(leaf_path, full_name, size)]}``
- basename aggregation stats: ``{basename: {total_size, count}}``

The snapshot is built off-request in a background thread and published via
an atomic reference swap (``self._index = new_snapshot``).  Request threads
only read the current snapshot and never touch the filesystem, so the
33.5 s HDD scan no longer blocks the ``/api/admin/files`` response.

State machine (stage 1, no ``stale``):
- ``building``: initial build or refresh in progress, no/index not ready
- ``ready``: a snapshot is available for queries
- ``error``: last refresh failed; old snapshot (if any) is still served

Stage 1 scope: full scan every refresh, no SQLite persistence, no mtime
incremental, no full scrub, no stale state.  These are deferred to stages
2-4 per the Codex design report.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main_workflow import MainWorkflow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Immutable snapshot dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileIndexSnapshot:
    """Immutable in-memory file index.

    Built entirely off-request in a background thread.  Once published via
    ``FileIndexCache._index = snapshot``, it is never mutated; a new refresh
    builds a fresh snapshot and atomically replaces the reference.

    Attributes
    ----------
    leaf_summaries : dict[str, list[dict]]
        ``leaf_rel_path -> [{name, size}, ...]`` (sorted by name).
    leaf_counts : dict[str, int]
        ``leaf_rel_path -> file_count``.
    leaf_sizes : dict[str, int]
        ``leaf_rel_path -> size_bytes`` (sum of regular file st_size).
    basename_index : dict[str, list[tuple[str, str, int]]]
        ``basename -> [(leaf_rel_path, full_name, size), ...]``.
    basename_stats : dict[str, tuple[int, int]]
        ``basename -> (total_size, count)``.
    indexed_at : float
        ``time.time()`` when the snapshot was published.
    """

    leaf_summaries: dict[str, list[dict]]
    leaf_counts: dict[str, int]
    leaf_sizes: dict[str, int]
    basename_index: dict[str, list[tuple[str, str, int]]]
    basename_stats: dict[str, tuple[int, int]]
    indexed_at: float


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

STATUS_BUILDING = "building"
STATUS_READY = "ready"
STATUS_ERROR = "error"


# ---------------------------------------------------------------------------
# FileIndexCache
# ---------------------------------------------------------------------------


class FileIndexCache:
    """Background file manifest builder with in-memory atomic swap.

    Parameters
    ----------
    work_dir_base : str
        Absolute path to the jf-remote work_dir (e.g. ``/data/.../runs``).
    manager_getter : callable
        Returns the ``MainWorkflow`` instance (used to resolve pool_cfg
        and build the ``uuid -> task`` map at query time — *not* during
        the background scan, to keep the scan self-contained).
    interval : int
        Background refresh interval in seconds (default 300).
    """

    def __init__(
        self,
        work_dir_base: str,
        manager_getter: Callable[[], "MainWorkflow"],
        interval: int = 300,
    ) -> None:
        self._work_dir_base = work_dir_base
        self._manager_getter = manager_getter
        self._interval = interval

        # Current snapshot (None until first successful build).
        self._index: FileIndexSnapshot | None = None

        # Status: one of STATUS_BUILDING / STATUS_READY / STATUS_ERROR.
        self._status: str = STATUS_BUILDING
        self._last_error: str | None = None

        # Refresh coordination.
        self._lock = threading.Lock()
        self._refreshing = False
        self._dirty = False  # invalidate requested while a refresh was running

    # ------------------------------------------------------------------
    # Public query methods (called from request threads)
    # ------------------------------------------------------------------

    @property
    def status(self) -> str:
        """Current index status: ``building`` / ``ready`` / ``error``."""
        return self._status

    @property
    def last_error(self) -> str | None:
        """Error message from the last failed refresh, if any."""
        return self._last_error

    @property
    def indexed_at(self) -> float | None:
        """Timestamp of the current snapshot, or None if never built."""
        snap = self._index
        return snap.indexed_at if snap is not None else None

    def get_entries(self) -> list[dict]:
        """Return per-leaf lightweight entries.

        Each entry has ``path``, ``size_bytes``, ``file_count``,
        ``file_summary_ready``.  Does **not** include ``file_summary``
        (use :meth:`get_leaf_summary` for that).
        """
        snap = self._index
        if snap is None:
            return []
        entries: list[dict] = []
        for leaf_path, size_bytes in snap.leaf_sizes.items():
            entries.append(
                {
                    "path": leaf_path,
                    "size_bytes": size_bytes,
                    "file_count": snap.leaf_counts.get(leaf_path, 0),
                    "file_summary_ready": True,
                }
            )
        return entries

    def search(self, query: str) -> list[dict]:
        """Search the basename inverted index.

        Returns a list of ``{leaf_path, file_name, basename, size}`` dicts
        for all files whose basename contains ``query`` (case-insensitive).
        """
        snap = self._index
        if snap is None or not query:
            return []
        q = query.lower()
        results: list[dict] = []
        for basename, hits in snap.basename_index.items():
            if q not in basename.lower():
                continue
            for leaf_path, full_name, size in hits:
                results.append(
                    {
                        "leaf_path": leaf_path,
                        "file_name": full_name,
                        "basename": basename,
                        "size": size,
                    }
                )
        return results

    def get_stats(self) -> list[dict]:
        """Return basename aggregation stats ``[{name, totalSize, count}]``."""
        snap = self._index
        if snap is None:
            return []
        return [
            {"name": name, "totalSize": total, "count": count}
            for name, (total, count) in snap.basename_stats.items()
        ]

    def get_leaf_summary(self, leaf_path: str) -> list[dict] | None:
        """Return ``file_summary`` for a single leaf, or None if not indexed."""
        snap = self._index
        if snap is None:
            return None
        return snap.leaf_summaries.get(leaf_path)

    # ------------------------------------------------------------------
    # Invalidation (called after deletes / manual refresh)
    # ------------------------------------------------------------------

    def invalidate(self) -> None:
        """Mark the index dirty and trigger a background refresh.

        If a refresh is already running, the dirty flag is set so that the
        current refresh will run another round after it finishes.  This
        coalesces multiple invalidation requests into at most one extra
        refresh, avoiding thundering-herd re-scans.
        """
        self._dirty = True
        if self._refreshing:
            # A refresh is in progress; it will pick up the dirty flag and
            # run another round.  No need to start a new thread.
            return
        # Start a background refresh in a daemon thread.  We use a plain
        # thread (not asyncio) because the scan is purely synchronous IO
        # and should not block the event loop.
        thread = threading.Thread(
            target=self._refresh_sync,
            name="file-index-refresh",
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # Background refresh
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Periodically refresh the index (asyncio background task)."""
        logger.info(
            "FileIndexCache background task started (interval=%ds, base=%s).",
            self._interval,
            self._work_dir_base,
        )
        try:
            while True:
                await asyncio.to_thread(self._refresh_sync)
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("FileIndexCache background task stopped.")
            raise

    def _refresh_sync(self) -> None:
        """Synchronous refresh (runs in a thread).

        Loops until no coalesced invalidation is pending, so repeated
        invalidate() calls during a refresh are collapsed into a bounded
        number of extra rounds instead of unbounded recursion.
        """
        with self._lock:
            if self._refreshing:
                # Another thread is already refreshing; respect dirty flag.
                self._dirty = True
                return
            self._refreshing = True
            self._dirty = False

        try:
            while True:
                try:
                    self._do_refresh()
                    self._status = STATUS_READY
                    self._last_error = None
                except Exception as exc:
                    self._status = STATUS_ERROR
                    self._last_error = str(exc)
                    logger.warning("FileIndexCache refresh failed: %s", exc)
                    # On error, stop the loop; the next invalidate() can retry.
                    break

                with self._lock:
                    if not self._dirty:
                        break
                    # Coalesced invalidation arrived during this round;
                    # clear it and run one more round.
                    self._dirty = False
        finally:
            with self._lock:
                self._refreshing = False

    def _do_refresh(self) -> None:
        """Build a new snapshot and atomically swap it in."""
        base = self._work_dir_base
        if not base or not os.path.isdir(base):
            raise FileNotFoundError(
                f"work_dir_base not found or not a directory: {base}"
            )

        base_resolved = Path(base).resolve()

        # Accumulators for the new snapshot.
        leaf_summaries: dict[str, list[dict]] = {}
        leaf_counts: dict[str, int] = {}
        leaf_sizes: dict[str, int] = {}
        basename_index: dict[str, list[tuple[str, str, int]]] = {}
        basename_stats: dict[str, tuple[int, int]] = {}

        # Walk the bucket tree.  We reuse the same 4-level bucket layout
        # logic as service._scan_bucket_level / _scan_bucket_tree, but
        # inline it here to keep the cache self-contained (the scan must
        # not depend on service.py module-level state).
        entries: list[tuple[str, str]] = []  # (leaf_abs_path, leaf_rel_path)
        try:
            for l1 in sorted(base_resolved.iterdir()):
                if not l1.is_dir() or l1.name.startswith("."):
                    continue
                if len(l1.name) == 2:
                    self._scan_bucket_level(
                        l1, 1, base_resolved, entries
                    )
                else:
                    # Worker-prefixed layout: worker_name/xx/xx/xx/uuid_idx
                    self._scan_bucket_tree(
                        l1, 0, 4, base_resolved, entries
                    )
        except OSError as exc:
            logger.warning("Error walking work_dir_base: %s", exc)

        for leaf_abs, leaf_rel in entries:
            file_summary = self._scan_file_summary(leaf_abs)
            file_summary.sort(key=lambda f: f["name"])
            size_bytes = sum(f["size"] for f in file_summary)
            leaf_summaries[leaf_rel] = file_summary
            leaf_counts[leaf_rel] = len(file_summary)
            leaf_sizes[leaf_rel] = size_bytes

            # Build basename index and stats.
            for f in file_summary:
                full_name = f["name"]
                size = f["size"]
                bn = (
                    full_name.rsplit("/", 1)[-1]
                    if "/" in full_name
                    else full_name
                )
                basename_index.setdefault(bn, []).append(
                    (leaf_rel, full_name, size)
                )
                cur = basename_stats.get(bn)
                if cur is None:
                    basename_stats[bn] = (size, 1)
                else:
                    basename_stats[bn] = (cur[0] + size, cur[1] + 1)

        snapshot = FileIndexSnapshot(
            leaf_summaries=leaf_summaries,
            leaf_counts=leaf_counts,
            leaf_sizes=leaf_sizes,
            basename_index=basename_index,
            basename_stats=basename_stats,
            indexed_at=time.time(),
        )

        # Atomic reference swap.  CPython GIL guarantees that the
        # assignment of ``self._index`` is atomic; any request thread
        # that already holds a reference to the old snapshot continues
        # to read it without interference.
        self._index = snapshot

        logger.info(
            "FileIndexCache refreshed: %d leaf dirs, %d files, %d basenames.",
            len(leaf_summaries),
            sum(leaf_counts.values()),
            len(basename_stats),
        )

    # ------------------------------------------------------------------
    # Directory walking helpers (mirror service.py bucket layout)
    # ------------------------------------------------------------------

    def _scan_bucket_level(
        self,
        current: Path,
        depth: int,
        base: Path,
        entries: list[tuple[str, str]],
    ) -> None:
        """Descend 2-char bucket directories until leaf (depth 4)."""
        try:
            for child in sorted(current.iterdir()):
                if not child.is_dir():
                    continue
                if depth < 3 and len(child.name) == 2:
                    self._scan_bucket_level(
                        child, depth + 1, base, entries
                    )
                else:
                    entries.append(
                        (str(child), str(child.relative_to(base)))
                    )
        except OSError:
            pass

    def _scan_bucket_tree(
        self,
        current: Path,
        depth: int,
        max_depth: int,
        base: Path,
        entries: list[tuple[str, str]],
    ) -> None:
        """Scan worker-prefixed layouts (worker_name/xx/xx/xx/uuid_idx)."""
        try:
            for child in sorted(current.iterdir()):
                if not child.is_dir():
                    continue
                if depth + 1 < max_depth and len(child.name) == 2:
                    self._scan_bucket_tree(
                        child, depth + 1, max_depth, base, entries
                    )
                elif depth + 1 >= max_depth:
                    entries.append(
                        (str(child), str(child.relative_to(base)))
                    )
                else:
                    self._scan_bucket_tree(
                        child, depth + 1, max_depth, base, entries
                    )
        except OSError:
            pass

    @staticmethod
    def _scan_file_summary(dir_path: str, prefix: str = "") -> list[dict]:
        """Recursively scan a directory and return ``[{name, size}]``.

        Subdirectory files are prefixed with the relative path, e.g.
        ``scf_000/OUTCAR``.  ``size`` is ``st_size`` of regular files
        (follow_symlinks=False), consistent with the post-subagent-D
        size_bytes convention (not ``du -sb``).
        """
        result: list[dict] = []
        try:
            with os.scandir(dir_path) as it:
                for entry in it:
                    try:
                        name = (
                            f"{prefix}{entry.name}" if prefix else entry.name
                        )
                        if entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            result.append({"name": name, "size": st.st_size})
                        elif entry.is_dir(follow_symlinks=False):
                            result.extend(
                                FileIndexCache._scan_file_summary(
                                    entry.path, prefix=f"{name}/"
                                )
                            )
                    except OSError:
                        pass
        except OSError:
            pass
        return result
