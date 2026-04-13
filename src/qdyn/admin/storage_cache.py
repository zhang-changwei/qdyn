"""Background storage size scanner with in-memory cache.

Periodically scans work_dir_base using ``du -sb`` and caches:
- per-job-dir sizes: ``{ job_dir_path: size_bytes }``
- total work_dir_base size
- per-traj-file sizes

Provides aggregation helpers:
- ``get_task_size(task_id, job_ids)`` -> int | None
- ``get_user_size(username, user_task_ids)`` -> int | None
- ``get_total_work_dir_size()`` -> int | None
- ``get_traj_stats()`` -> (total_bytes, file_count)

Runs as an asyncio background task, refreshing every ``interval`` seconds.
"""

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class StorageCache:
    """Background storage size scanner with in-memory cache.

    Parameters
    ----------
    work_dir_base : str
        Absolute path to the jf-remote work_dir (e.g. ``/data/.../runs``).
    traj_dir : str | None
        Absolute path to the trajectory upload directory.
    interval : int
        Refresh interval in seconds (default 300 = 5 minutes).
    """

    def __init__(
        self,
        work_dir_base: str,
        traj_dir: str | None = None,
        interval: int = 300,
    ) -> None:
        self._work_dir_base = work_dir_base
        self._traj_dir = traj_dir
        self._interval = interval

        # Cache state
        self._job_dir_sizes: Dict[str, int] = {}
        self._total_work_dir_bytes: int | None = None
        self._traj_total_bytes: int | None = None
        self._traj_file_count: int = 0
        self._last_refresh: float = 0.0
        self._refreshing: bool = False

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def get_total_work_dir_size(self) -> int | None:
        """Return cached total size of work_dir_base, or None if not yet scanned."""
        return self._total_work_dir_bytes

    def get_traj_stats(self) -> Tuple[int | None, int]:
        """Return (total_bytes, file_count) for the trajectory directory."""
        return self._traj_total_bytes, self._traj_file_count

    def get_job_dir_size(self, run_dir: str) -> int | None:
        """Return cached size for a specific job run_dir, or None if unknown."""
        return self._job_dir_sizes.get(run_dir)

    def get_task_size(
        self, run_dirs: list[str]
    ) -> int | None:
        """Aggregate cached sizes for all run_dirs belonging to a task.

        Parameters
        ----------
        run_dirs : list[str]
            Absolute paths to the job run directories for a task.

        Returns None if the cache has not been populated yet.
        """
        if not self._job_dir_sizes:
            return None
        total = 0
        for rd in run_dirs:
            size = self._job_dir_sizes.get(rd)
            if size is not None:
                total += size
        return total

    @property
    def last_refresh(self) -> float:
        """Timestamp of the last successful refresh (0.0 if never refreshed)."""
        return self._last_refresh

    @property
    def is_stale(self) -> bool:
        """True if the cache has never been refreshed or is past its TTL."""
        if self._last_refresh == 0.0:
            return True
        return (time.time() - self._last_refresh) > self._interval

    # ------------------------------------------------------------------
    # Refresh logic
    # ------------------------------------------------------------------

    async def refresh(self) -> None:
        """Refresh the cache by scanning disk.

        Runs ``du -sb`` in a thread to avoid blocking the event loop.
        """
        if self._refreshing:
            return
        self._refreshing = True
        try:
            await asyncio.to_thread(self._do_refresh)
            self._last_refresh = time.time()
            logger.info(
                "StorageCache refreshed: work_dir=%s bytes, %d job dirs cached, "
                "traj=%s bytes (%d files)",
                self._total_work_dir_bytes,
                len(self._job_dir_sizes),
                self._traj_total_bytes,
                self._traj_file_count,
            )
        except Exception as exc:
            logger.warning("StorageCache refresh failed: %s", exc)
        finally:
            self._refreshing = False

    def _do_refresh(self) -> None:
        """Synchronous refresh (runs in a thread)."""
        # 1. Total work_dir_base size
        self._total_work_dir_bytes = self._du_sb(self._work_dir_base)

        # 2. Scan leaf job directories (4 levels deep: xx/xx/xx/uuid_index)
        new_sizes: Dict[str, int] = {}
        base = self._work_dir_base
        if os.path.isdir(base):
            self._scan_leaf_dirs(base, 0, 4, new_sizes)
        self._job_dir_sizes = new_sizes

        # 3. Trajectory directory
        if self._traj_dir and os.path.isdir(self._traj_dir):
            self._traj_total_bytes = self._du_sb(self._traj_dir)
            self._traj_file_count = self._count_files(self._traj_dir)
        else:
            self._traj_total_bytes = 0
            self._traj_file_count = 0

    def _scan_leaf_dirs(
        self,
        current: str,
        depth: int,
        target_depth: int,
        result: Dict[str, int],
    ) -> None:
        """Recursively descend into the bucket structure and scan leaf dirs.

        The runs directory uses a 4-level bucket layout:
        ``runs/xx/xx/xx/uuid_index/`` where xx are 2-char hex prefixes
        derived from the UUID. Leaf directories at depth 4 are the actual
        job run directories.
        """
        try:
            entries = os.scandir(current)
        except OSError:
            return

        with entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if depth + 1 < target_depth:
                    # Intermediate bucket level -- descend
                    self._scan_leaf_dirs(
                        entry.path, depth + 1, target_depth, result
                    )
                else:
                    # Leaf level -- measure this directory
                    size = self._du_sb(entry.path)
                    if size is not None:
                        result[entry.path] = size

    @staticmethod
    def _du_sb(path: str) -> int | None:
        """Run ``du -sb <path>`` and return the byte count, or None on error."""
        try:
            proc = subprocess.run(
                ["du", "-sb", path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return int(proc.stdout.strip().split("\t", 1)[0])
        except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
            logger.debug("du -sb %s failed: %s", path, exc)
        return None

    @staticmethod
    def _count_files(path: str) -> int:
        """Count regular files in a directory (non-recursive, single level)."""
        count = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        count += 1
        except OSError:
            pass
        return count

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Periodically refresh the cache until cancelled.

        Intended to be started as an ``asyncio.create_task()`` in the
        application lifespan.
        """
        logger.info(
            "StorageCache background task started (interval=%ds).",
            self._interval,
        )
        try:
            while True:
                await self.refresh()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            logger.info("StorageCache background task stopped.")
            raise
