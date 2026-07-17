from __future__ import annotations

import logging
import shlex
from pathlib import Path, PurePosixPath
import re
from typing import Any

from jobflow_remote import JobController

from .errors import ConfigError, ValidationError
from .params import TERMINAL_STATES
from .frontend_api.run_dir_access import (
    LocalRunDirAccess,
    RemoteRunDirAccess,
    RunDirAccess,
)

logger = logging.getLogger(__name__)

REMOTE_WORKER_TYPES = {"remote", "separated_transfer"}


class WorkerPool:

    def __init__(
        self, 
        job_controller: JobController, 
        pool_name: str,
        config: dict[str, Any],
        jf_config: dict[str, Any],
    ):
        self.jc = job_controller
        self.name = pool_name
        self._remote: bool | None = None
        self._workers: list[str] | None = None

        # resolve pool context
        if self.name not in config['worker_pools']:
            raise ValidationError(
                f"Pool '{self.name}' not found in config. "
                f"Available: {list(config['worker_pools'].keys())}"
            )
        pool_def = config['worker_pools'][self.name]
        self.pool_cfg: dict[str, Any] = pool_def['pool']
        self.worker_cfg: dict[str, Any] = pool_def['worker']
        self.get_pool_workers(jf_config=jf_config)

    def get_pool_workers(self, jf_config: dict[str, Any] | None = None) -> list[str]:
        """Return runtime worker names belonging to a pool.

        Scans jf_config['workers'] for names matching the pattern
        ``{pool_name}_\\d{3,}`` (e.g. local_slurm_001, local_slurm_002).
        Results are sorted lexicographically.
        """
        if not self._workers:
            if jf_config is None:
                raise ValidationError("jf_config is required to get pool workers")

            pattern = re.compile(rf"^{re.escape(self.name)}_\d{{3,}}$")
            workers = sorted(w for w in jf_config['workers'] if pattern.match(w))

            if not workers:
                raise ConfigError(
                    f"No runtime workers found for pool '{self.name}'. "
                    "Run src/scripts/generate_jf_config.py and "
                    "ensure jf-remote config is up to date."
                )
            self._workers = workers
        return self._workers

    @property
    def remote(self) -> bool:
        """Whether this pool uses remote transport."""
        if self._remote is None:
            self._remote = self.worker_cfg['type'] in REMOTE_WORKER_TYPES
        return self._remote


    def check_file_exists(self, path: str) -> bool:
        if self.remote:
            host = self._get_remote_host(self.get_pool_workers()[0])
            if path.startswith("~"):
                path = path.replace("~", "$HOME", 1)
            stdout, _, rc = host.execute(f'test -f "{path}" && echo ok')
            return rc == 0 and "ok" in stdout
        return Path(path).expanduser().resolve().is_file()

    def user_file_exists(self, file_type: str, file_hash: str) -> bool:
        """Return whether a pool user-data file exists.

        For local pools this checks the local filesystem directly. For remote pools
        this checks the transfer host attached to the pool.
        """
        path = self.get_user_file_path(file_type, file_hash)
        if self.remote:
            host = self._get_remote_host(self.get_pool_workers()[0])
            stdout, _, rc = host.execute(f"test -f {shlex.quote(path)} && echo ok")
            return rc == 0 and "ok" in stdout
        return Path(path).is_file()
    
    def get_user_file_path(self, file_type: str, file_hash: str | None = None) -> str:
        parts = [file_type, file_hash]
        if file_hash is None:
            parts = [file_type]
        base = self.pool_cfg['user_data']
        if self.remote:
            return str(PurePosixPath(base, *parts))
        return str(Path(base).joinpath(*parts))


    def upload_user_file(
        self,
        *,
        file_type: str,
        local_path: str | Path,
        file_hash: str,
    ) -> str:
        """Place a local file into the target pool's shared user-data area.

        Local pools move the file into the canonical hash path. Remote pools upload
        it to the transfer worker if the destination file does not already exist.

        Args:
            file_type: A string categorizing the file (e.g. "trajectory", "model").
            local_path: Path to the local file to upload.
            file_hash: Optional The content hash of the file, 
                used as the filename in the pool.

        Returns:
            The final pool path.
        """
        path = self.get_user_file_path(file_type, file_hash)
        if self.remote:
            if not self.user_file_exists(file_type, file_hash):
                return self._upload_user_file_to_remote(
                    local_path=local_path,
                    remote_path=path,
                )
            return path

        local_path = Path(local_path)
        final_path = Path(path)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if not final_path.exists():
            local_path.replace(final_path)
        else:
            local_path.unlink(missing_ok=True)
        return str(final_path)

    def delete_user_file(
        self,
        *,
        file_type: str,
        file_hash: str,
    ) -> None:
        """Delete a pool user-data file if it exists."""
        path = self.get_user_file_path(file_type, file_hash)
        if self.remote:
            host = self._get_remote_host(self.get_pool_workers()[0])
            host.execute(f"rm -f {shlex.quote(path)}")
            return
        Path(path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Pool occupancy queries (MongoDB)
    # ------------------------------------------------------------------

    _TERMINAL_STATES = TERMINAL_STATES

    def get_occupancy(self) -> dict[str, int]:
        """Query the number of SUBMITTED+RUNNING jobs per pool worker.

        Returns a dict mapping each pool worker name to its active slot
        count.  Workers with zero active jobs are included with value 0.

        Uses MongoDB aggregation on the jobs collection for accuracy,
        matching the jf-remote Runner's own ``max_jobs`` accounting.
        """
        pool_workers = self.get_pool_workers()

        pipeline = [
            {
                "$match": {
                    "worker": {"$in": pool_workers},
                    "state": {"$in": ["SUBMITTED", "RUNNING"]},
                }
            },
            {
                "$group": {
                    "_id": "$worker",
                    "active_slots": {"$sum": 1},
                }
            },
        ]
        result = {w: 0 for w in pool_workers}
        for doc in self.jc.jobs.aggregate(pipeline):
            result[doc["_id"]] = doc["active_slots"]
        return result

    def get_user_occupied_workers(self, username: str) -> list[str]:
        """Return the list of pool workers currently occupied by *username*.

        A worker is "occupied" if it has at least one non-terminal job
        whose ``job.metadata.qdyn_user`` matches *username*.
        """
        pool_workers = self.get_pool_workers()
        if not pool_workers:
            return []

        pipeline = [
            {
                "$match": {
                    "worker": {"$in": pool_workers},
                    "job.metadata.qdyn_user": username,
                    "state": {"$nin": list(self._TERMINAL_STATES)},
                }
            },
            {"$group": {"_id": "$worker"}},
        ]
        return [doc["_id"] for doc in self.jc.jobs.aggregate(pipeline)]

    def get_free_workers(self) -> list[str]:
        """Return pool workers that have zero non-terminal jobs.

        A worker is "free" (idle) when it has no jobs in any non-terminal
        state.  Results are sorted lexicographically, matching the order
        returned by :meth:`_get_pool_workers`.
        """
        pool_workers = self.get_pool_workers()
        if not pool_workers:
            return []

        busy_pipeline = [
            {
                "$match": {
                    "worker": {"$in": pool_workers},
                    "state": {"$nin": list(self._TERMINAL_STATES)},
                }
            },
            {"$group": {"_id": "$worker"}},
        ]
        busy = {doc["_id"] for doc in self.jc.jobs.aggregate(busy_pipeline)}
        return [w for w in pool_workers if w not in busy]

    def select_runtime_worker(self, username: str) -> tuple[str | None, str]:
        """Select a runtime worker for a new submission.

        Selection logic:
        1. Check whether the pool has any free worker (zero non-terminal
           jobs).  If not, return ``(None, "pool_full")`` -- the caller
           must enqueue the task.
        2. If the user already occupies a worker, submit to that existing
           worker (``"existing"``).  Otherwise allocate a free worker
           (``"new"``).  Each user occupies at most one worker.

        Returns
        -------
        (worker_name, "existing")
            User already has a worker; submit to it.
        (worker_name, "new")
            User has no worker yet; a free worker was allocated.
        (None, "pool_full")
            No free workers in the pool; task must be queued.
        """
        name = self.name
        pool_workers = self.get_pool_workers()
        if not pool_workers:
            logging.warning(
                f"No runtime workers found for pool '{name}'. "
                f"Did you run src/scripts/generate_jf_config.py?"
            )
            return None, "pool_full"

        # 1. Any free worker in the pool?
        free_workers = self.get_free_workers()
        if not free_workers:
            logging.info(
                f"No free workers available in pool '{name}' "
                f"(all {len(pool_workers)} workers are busy)."
            )
            return None, "pool_full"

        # 2. Check whether the user already occupies a worker.
        user_workers = self.get_user_occupied_workers(username)

        if user_workers:
            # User already has a worker -- route to it.
            logging.info(
                f"User '{username}' already has worker '{user_workers[0]}' "
                f"in pool '{name}' -- submitting to existing worker."
            )
            return user_workers[0], "existing"

        # 3. Allocate a free worker for this user.
        selected = free_workers[0]
        logging.info(
            f"Allocated free worker '{selected}' for user '{username}' "
            f"in pool '{name}'."
        )
        return selected, "new"

    # ------------------------------------------------------------------
    # Remote pool utilities
    # ------------------------------------------------------------------

    def build_run_dir_access(self, job_uuid: str) -> RunDirAccess | None:
        """Return a local or remote run-directory accessor for a job UUID.

        Returns ``None`` only when job info cannot be retrieved or the
        job has no ``run_dir``.  The returned accessor is **not** probed
        for availability -- callers that need a preflight check should
        invoke ``access.is_available()`` explicitly, otherwise the first
        file operation will surface any missing-directory error.
        """
        try:
            job_info = self.jc.get_job_info(job_id=job_uuid)
        except Exception:
            return None

        if job_info is None or not job_info.run_dir:
            return None

        run_dir = str(job_info.run_dir)
        worker_name = job_info.worker

        if self.remote:
            try:
                host = self._get_shared_host(self.jc.project, worker_name)
                return RemoteRunDirAccess(run_dir, host)
            except Exception:
                logger.warning(
                    "Failed to create remote access for worker %s, job %s",
                    worker_name,
                    job_uuid,
                    exc_info=True,
                )
                return None

        local_dir = Path(run_dir)
        if local_dir.is_dir():
            return LocalRunDirAccess(local_dir)
        return None

    def build_run_dir_access_batch(
        self, job_uuids: list[str]
    ) -> dict[str, RunDirAccess | None]:
        """Build run-dir accessors for many job UUIDs in one Mongo query.

        For each UUID the highest-index job document is selected (matching
        the single-UUID ``get_job_info`` semantics).  Remote accessors are
        constructed without an ``is_available`` probe -- see
        :meth:`build_run_dir_access`.

        Args:
            job_uuids: Job UUIDs to look up.  Duplicate UUIDs are folded
                into a single result entry.

        Returns:
            A dict mapping each input UUID to a ``RunDirAccess`` (or
            ``None`` when the job is missing, has no ``run_dir``, or the
            remote host cannot be reached).  UUIDs not found in Mongo are
            omitted from the result.
        """
        unique_uuids = list(dict.fromkeys(job_uuids))
        if not unique_uuids:
            return {}

        # Fetch all job docs for the given UUIDs in one query, then pick
        # the highest index per UUID locally (mirrors the single-UUID
        # ``sort=[["index", DESCENDING]], limit=1`` behaviour).
        cursor = self.jc.jobs.find(
            {"uuid": {"$in": unique_uuids}},
            projection=["uuid", "index", "worker", "run_dir"],
        )

        latest_by_uuid: dict[str, object] = {}
        for doc in cursor:
            uid = doc.get("uuid")
            idx = doc.get("index", 0)
            prev = latest_by_uuid.get(uid)
            if prev is None or idx >= prev.get("index", 0):
                latest_by_uuid[uid] = doc

        result: dict[str, RunDirAccess | None] = {}
        for uid, doc in latest_by_uuid.items():
            run_dir = doc.get("run_dir")
            if not run_dir:
                result[uid] = None
                continue
            worker_name = doc.get("worker")
            if self.remote:
                try:
                    host = self._get_shared_host(self.jc.project, worker_name)
                    result[uid] = RemoteRunDirAccess(str(run_dir), host)
                except Exception:
                    logger.warning(
                        "Failed to create remote access for worker %s, job %s",
                        worker_name, uid, exc_info=True,
                    )
                    result[uid] = None
            else:
                local_dir = Path(str(run_dir))
                result[uid] = (
                    LocalRunDirAccess(local_dir)
                    if local_dir.is_dir()
                    else None
                )
        return result


    def _get_remote_host(self, worker_name: str):

        return self._get_shared_host(self.jc.project, worker_name)

    @staticmethod
    def _get_shared_host(project: Any, worker_name: str):
        from jobflow_remote.utils.remote import SharedHosts

        with SharedHosts(project) as shared:
            host = shared.get_host(worker_name)
        return host

    def _upload_user_file_to_remote(
        self,
        *,
        local_path: str | Path,
        remote_path: str | PurePosixPath,
    ) -> str:
        host = self._get_remote_host(self.get_pool_workers()[0])
        local_path = Path(local_path)
        remote_path = PurePosixPath(str(remote_path))

        try:
            host.mkdir(str(remote_path.parent), recursive=True, exist_ok=True)
            host.put(str(local_path), str(remote_path))
        except Exception as exc:
            remote_host = self.worker_cfg.get('host', '')
            raise ConfigError(
                f"Failed to upload file to remote worker pool "
                f"'{self.name}' (host={remote_host}). "
                f"Check SSH connectivity and work_dir permissions. "
                f"Target: {remote_path}"
            ) from exc

        return str(remote_path)

    def _build_remote_python_command(self, python_code: str, use_sys_py: bool = False) -> str:
        commands: list[str] = []

        if not use_sys_py and self.worker_cfg['installed']['python']:
            pre_run = self.worker_cfg['pre_run']['python']
            if pre_run:
                commands.append(pre_run)

            for key, value in self.worker_cfg['export']['python'].items():
                commands.append(f"export {key}={shlex.quote(str(value))}")

            for module_name in self.worker_cfg['modules']['python']:
                commands.append(f"module load {shlex.quote(str(module_name))}")

        commands.append("python3 -c " + shlex.quote(python_code))
        return "\n".join(commands)
