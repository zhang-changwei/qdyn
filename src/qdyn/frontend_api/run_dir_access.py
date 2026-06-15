"""Unified access to job run directories (local or remote).

Provides an abstract interface for accessing files in a job's run directory,
with concrete implementations for local filesystem and remote SSH hosts.
The remote implementation uses jobflow-remote's host abstraction to execute
commands and transfer files over SSH.
"""

import os
import shlex
import tempfile
import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class FileInfo:
    """Metadata for a file in a run directory."""

    name: str
    size: int
    is_file: bool


@dataclass
class ScfSubdirStatus:
    """Status of a single scf_* subdirectory.

    Status is derived exclusively from root-level qdyn_scf.log categories:
    ENDED (normal/posthamgnn/overlap), RUNNING (prehamgnn/hamgnn), or PENDING.
    """

    status: str  # "ENDED", "RUNNING", "PENDING"
    file_count: int


_SCF_COMPLETED_LOG_CATEGORIES = {"normal", "posthamgnn", "overlap"}
_SCF_RUNNING_LOG_CATEGORIES = {"prehamgnn", "hamgnn"}


def _scf_statuses_from_log(log_path: Path) -> dict[str, str]:
    """Parse qdyn_scf.log and return per-frame status dict.

    Reads data rows (skipping the 2-line header) and maps each global_idx to
    its final status.  ENDED takes priority over RUNNING for the same frame.

    Returns an empty dict if the log is missing, unreadable, or malformed.
    """
    statuses: dict[str, str] = {}
    if not log_path.is_file():
        return statuses
    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()
        for line in lines[2:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            global_idx = parts[1]
            category = parts[2]
            if category in _SCF_COMPLETED_LOG_CATEGORIES:
                statuses[global_idx] = "ENDED"
            elif category in _SCF_RUNNING_LOG_CATEGORIES:
                if statuses.get(global_idx) != "ENDED":
                    statuses[global_idx] = "RUNNING"
    except OSError:
        return {}
    return statuses


def _infer_local_scf_status(
    subdir: Path,
    status_from_log: dict[str, str],
) -> str:
    """Look up a frame's status from the log-derived status map.

    Returns PENDING for any frame not present in the map.
    """
    return status_from_log.get(subdir.name, "PENDING")


class RunDirAccess(ABC):
    """Restricted job run directory access interface.

    Provides safe, validated access to files in a job's run directory.
    All filename/subdir arguments are validated to prevent path traversal.
    """

    @property
    @abstractmethod
    def run_dir_path(self) -> str:
        """Return the raw run_dir path string (for display/logging)."""
        ...

    @abstractmethod
    def is_available(self) -> bool: ...

    # --- Root-level file access (safe, no subdirs) ---

    @abstractmethod
    def list_root_files(self) -> List[FileInfo]: ...

    @abstractmethod
    def root_file_exists(self, name: str) -> bool: ...

    @abstractmethod
    def read_root_text(self, name: str) -> str: ...

    @abstractmethod
    def read_root_tail(self, name: str, max_bytes: int = 4096) -> str: ...

    @abstractmethod
    def download_root_file(self, name: str) -> bytes: ...

    # --- Controlled subdirectory access (for progress/attempts) ---

    @abstractmethod
    def list_subdirs(self, prefix: str = "") -> List[str]: ...

    @abstractmethod
    def subdir_file_exists(self, subdir: str, name: str) -> bool: ...

    @abstractmethod
    def read_subdir_text(self, subdir: str, name: str) -> str: ...

    @abstractmethod
    def read_subdir_tail(
        self, subdir: str, name: str, max_bytes: int = 4096
    ) -> str: ...

    @abstractmethod
    def list_subdir_files(self, subdir: str) -> List[FileInfo]:
        """List files inside a validated subdirectory."""
        ...

    @abstractmethod
    def download_subdir_file(self, subdir: str, name: str) -> bytes:
        """Download a file from a validated subdirectory."""
        ...

    # --- Batch operations (reduce SSH roundtrips for remote) ---

    @abstractmethod
    def scan_scf_status(self) -> Dict[str, ScfSubdirStatus]:
        """Scan all scf_* subdirs for SCF frame status from root qdyn_scf.log categories.

        Returns a dict keyed by subdirectory name (e.g. "scf_000") with
        ``ScfSubdirStatus`` values containing the detected status
        (ENDED / RUNNING / PENDING) and the file count.

        Status is derived solely from qdyn_scf.log category records in the
        root run directory.  No marker files or product files are examined.
        For remote workers this executes a single SSH command instead of
        O(N) individual round-trips.
        """
        ...

    @abstractmethod
    def read_multiple_root_texts(self, names: List[str]) -> Dict[str, str]:
        """Read multiple root-level text files in one pass.

        Returns a dict mapping filename to its text content.  Missing
        files are omitted from the result (no error raised).

        For remote workers this executes a single SSH command instead of
        N individual ``cat`` calls.
        """
        ...

    # --- Internal path validation ---

    @staticmethod
    def _validate_name(name: str) -> str:
        """Validate a single filename (no path separators, no ..)."""
        if not name or "/" in name or "\\" in name or ".." in name:
            raise ValueError(f"Invalid filename: {name!r}")
        return name

    @staticmethod
    def _validate_subdir(subdir: str) -> str:
        """Validate a subdirectory name (single component)."""
        if not subdir or "/" in subdir or "\\" in subdir or ".." in subdir:
            raise ValueError(f"Invalid subdirectory: {subdir!r}")
        return subdir


class LocalRunDirAccess(RunDirAccess):
    """Local filesystem implementation."""

    def __init__(self, run_dir: Path):
        self._dir = run_dir

    @property
    def run_dir_path(self) -> str:
        return str(self._dir)

    def is_available(self) -> bool:
        return self._dir.is_dir()

    def list_root_files(self) -> List[FileInfo]:
        return [
            FileInfo(name=e.name, size=e.stat().st_size, is_file=True)
            for e in self._dir.iterdir()
            if e.is_file()
        ]

    def root_file_exists(self, name: str) -> bool:
        self._validate_name(name)
        return (self._dir / name).is_file()

    def read_root_text(self, name: str) -> str:
        self._validate_name(name)
        return (self._dir / name).read_text(errors="replace")

    def read_root_tail(self, name: str, max_bytes: int = 4096) -> str:
        self._validate_name(name)
        p = self._dir / name
        sz = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, sz - max_bytes))
            return f.read().decode(errors="replace")

    def download_root_file(self, name: str) -> bytes:
        self._validate_name(name)
        return (self._dir / name).read_bytes()

    def list_subdirs(self, prefix: str = "") -> List[str]:
        return sorted(
            d.name
            for d in self._dir.iterdir()
            if d.is_dir() and d.name.startswith(prefix)
        )

    def subdir_file_exists(self, subdir: str, name: str) -> bool:
        self._validate_subdir(subdir)
        self._validate_name(name)
        return (self._dir / subdir / name).is_file()

    def read_subdir_text(self, subdir: str, name: str) -> str:
        self._validate_subdir(subdir)
        self._validate_name(name)
        return (self._dir / subdir / name).read_text(errors="replace")

    def read_subdir_tail(
        self, subdir: str, name: str, max_bytes: int = 4096
    ) -> str:
        self._validate_subdir(subdir)
        self._validate_name(name)
        p = self._dir / subdir / name
        sz = p.stat().st_size
        with open(p, "rb") as f:
            f.seek(max(0, sz - max_bytes))
            return f.read().decode(errors="replace")

    def list_subdir_files(self, subdir: str) -> List[FileInfo]:
        self._validate_subdir(subdir)
        d = self._dir / subdir
        if not d.is_dir():
            return []
        return [
            FileInfo(name=e.name, size=e.stat().st_size, is_file=True)
            for e in d.iterdir()
            if e.is_file()
        ]

    def download_subdir_file(self, subdir: str, name: str) -> bytes:
        self._validate_subdir(subdir)
        self._validate_name(name)
        return (self._dir / subdir / name).read_bytes()

    def scan_scf_status(self) -> Dict[str, ScfSubdirStatus]:
        result: Dict[str, ScfSubdirStatus] = {}
        status_from_log = _scf_statuses_from_log(self._dir / "qdyn_scf.log")
        for d in sorted(self._dir.iterdir()):
            if not d.is_dir() or not d.name.startswith("scf_"):
                continue
            status = _infer_local_scf_status(d, status_from_log)
            file_count = sum(1 for e in d.iterdir() if e.is_file())
            result[d.name] = ScfSubdirStatus(status=status, file_count=file_count)
        return result

    def read_multiple_root_texts(self, names: List[str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for name in names:
            self._validate_name(name)
            p = self._dir / name
            if p.is_file():
                result[name] = p.read_text(errors="replace")
        return result


class RemoteRunDirAccess(RunDirAccess):
    """Remote implementation using jobflow-remote's host abstraction.

    All remote paths are shell-quoted via ``shlex.quote()`` to prevent
    injection.  Commands are executed through the host's ``execute()``
    method which returns ``(stdout, stderr, returncode)``.
    """

    def __init__(self, run_dir: str, host):
        self._dir = run_dir
        self._host = host  # BaseHost (RemoteHost or SeparatedTransferHost)

    @property
    def run_dir_path(self) -> str:
        return self._dir

    def _exec(self, cmd: str) -> str:
        """Execute remote command, return stdout. Raise on non-zero exit."""
        stdout, stderr, returncode = self._host.execute(cmd)
        if returncode != 0:
            raise RuntimeError(
                f"Remote command failed (rc={returncode}): {stderr}"
            )
        return stdout

    def _remote_path(self, *parts: str) -> str:
        """Build a quoted remote path."""
        return shlex.quote(os.path.join(self._dir, *parts))

    def _download_via_exec_base64(self, *parts: str) -> bytes:
        """Download a remote file via SSH stdout as base64 text.

        Some remote hosts intermittently fail on Paramiko/Fabric SFTP
        transfers with errors such as ``Garbage packet received`` even
        though ordinary remote command execution still works. In that
        case we fall back to reading the file remotely, base64-encoding
        it, and decoding it locally.
        """
        remote_path = os.path.join(self._dir, *parts)
        quoted_path = repr(remote_path)
        cmd = (
            "python3 -c "
            + shlex.quote(
                "import base64, pathlib, sys; "
                f"sys.stdout.write(base64.b64encode(pathlib.Path({quoted_path}).read_bytes()).decode('ascii'))"
            )
        )
        data = self._exec(cmd).strip()
        return base64.b64decode(data) if data else b""

    def is_available(self) -> bool:
        try:
            stdout, _, rc = self._host.execute(
                f"test -d {shlex.quote(self._dir)} && echo ok"
            )
            return rc == 0 and "ok" in stdout
        except Exception:
            return False

    def list_root_files(self) -> List[FileInfo]:
        cmd = (
            f"find {shlex.quote(self._dir)} -maxdepth 1 -type f "
            f"-printf '%f\\t%s\\n' 2>/dev/null"
        )
        try:
            out = self._exec(cmd)
        except RuntimeError:
            return []
        files = []
        for line in out.strip().split("\n"):
            if "\t" in line:
                name, size = line.rsplit("\t", 1)
                files.append(
                    FileInfo(name=name, size=int(size), is_file=True)
                )
        return files

    def root_file_exists(self, name: str) -> bool:
        self._validate_name(name)
        try:
            stdout, _, rc = self._host.execute(
                f"test -f {self._remote_path(name)} && echo ok"
            )
            return rc == 0 and "ok" in stdout
        except Exception:
            return False

    def read_root_text(self, name: str) -> str:
        self._validate_name(name)
        return self._exec(f"cat {self._remote_path(name)}")

    def read_root_tail(self, name: str, max_bytes: int = 4096) -> str:
        self._validate_name(name)
        return self._exec(
            f"tail -c {max_bytes} {self._remote_path(name)}"
        )

    def download_root_file(self, name: str) -> bytes:
        self._validate_name(name)
        try:
            return self._download_via_exec_base64(name)
        except Exception:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            try:
                self._host.get(os.path.join(self._dir, name), tmp_path)
                with open(tmp_path, "rb") as f:
                    return f.read()
            finally:
                os.unlink(tmp_path)

    def list_subdirs(self, prefix: str = "") -> List[str]:
        pattern = f"{prefix}*" if prefix else "*"
        cmd = (
            f"find {shlex.quote(self._dir)} -maxdepth 1 -mindepth 1 -type d "
            f"-name {shlex.quote(pattern)} -printf '%f\\n' 2>/dev/null | sort"
        )
        try:
            out = self._exec(cmd)
        except RuntimeError:
            return []
        return [d for d in out.strip().split("\n") if d]

    def subdir_file_exists(self, subdir: str, name: str) -> bool:
        self._validate_subdir(subdir)
        self._validate_name(name)
        try:
            stdout, _, rc = self._host.execute(
                f"test -f {self._remote_path(subdir, name)} && echo ok"
            )
            return rc == 0 and "ok" in stdout
        except Exception:
            return False

    def read_subdir_text(self, subdir: str, name: str) -> str:
        self._validate_subdir(subdir)
        self._validate_name(name)
        return self._exec(f"cat {self._remote_path(subdir, name)}")

    def read_subdir_tail(
        self, subdir: str, name: str, max_bytes: int = 4096
    ) -> str:
        self._validate_subdir(subdir)
        self._validate_name(name)
        return self._exec(
            f"tail -c {max_bytes} {self._remote_path(subdir, name)}"
        )

    def list_subdir_files(self, subdir: str) -> List[FileInfo]:
        self._validate_subdir(subdir)
        sub_path = os.path.join(self._dir, subdir)
        cmd = (
            f"find {shlex.quote(sub_path)} -maxdepth 1 -type f "
            f"-printf '%f\\t%s\\n' 2>/dev/null"
        )
        try:
            out = self._exec(cmd)
        except RuntimeError:
            return []
        files = []
        for line in out.strip().split("\n"):
            if "\t" in line:
                name, size = line.rsplit("\t", 1)
                files.append(
                    FileInfo(name=name, size=int(size), is_file=True)
                )
        return files

    def download_subdir_file(self, subdir: str, name: str) -> bytes:
        self._validate_subdir(subdir)
        self._validate_name(name)
        try:
            return self._download_via_exec_base64(subdir, name)
        except Exception:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            try:
                self._host.get(os.path.join(self._dir, subdir, name), tmp_path)
                with open(tmp_path, "rb") as f:
                    return f.read()
            finally:
                os.unlink(tmp_path)

    def scan_scf_status(self) -> Dict[str, ScfSubdirStatus]:
        """Scan all scf_* subdirs in a single SSH command.

        Reads the root-level qdyn_scf.log with awk to derive each frame's
        status (ENDED/RUNNING/PENDING) from log categories only.  No marker
        files or product files are examined.  File counts are obtained via
        ``find -maxdepth 1 -type f``.  Output is parsed from TSV lines:
        ``name\\tstatus\\tfile_count``.
        """
        qdir = shlex.quote(self._dir)
        # awk processes qdyn_scf.log once per directory name; ENDED takes
        # priority over RUNNING for the same frame.
        # The awk program is placed in single quotes so shell does not expand $2/$3;
        # the f-string only interpolates {qdir}.
        awk_prog = (
            'NR > 2 && $2 == name { '
            'if ($3 == "normal" || $3 == "posthamgnn" || $3 == "overlap") { st="ENDED" } '
            'else if (($3 == "prehamgnn" || $3 == "hamgnn") && st != "ENDED") { st="RUNNING" } '
            '} END { if (st != "") print st; else print "PENDING" }'
        )
        cmd = (
            f'log={qdir}/qdyn_scf.log; '
            f"for d in {qdir}/scf_*/; do "
            f'[ -d "$d" ] || continue; '
            f'name=$(basename "$d"); '
            f'if [ -f "$log" ]; then '
            f"s=$(awk -v name=\"$name\" '{awk_prog}' \"$log\"); "
            f'else s=PENDING; fi; '
            f'c=$(find "$d" -maxdepth 1 -type f 2>/dev/null | wc -l); '
            f'echo "$name\t$s\t$c"; '
            f"done"
        )
        result: Dict[str, ScfSubdirStatus] = {}
        try:
            stdout, _, rc = self._host.execute(cmd)
            if rc != 0:
                return result
            for line in stdout.strip().split("\n"):
                if not line or "\t" not in line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    name = parts[0]
                    status = parts[1].strip()
                    try:
                        file_count = int(parts[2].strip())
                    except ValueError:
                        file_count = 0
                    result[name] = ScfSubdirStatus(
                        status=status, file_count=file_count
                    )
        except Exception:
            pass
        return result

    def read_multiple_root_texts(self, names: List[str]) -> Dict[str, str]:
        """Read multiple root-level files in a single SSH command.

        Uses a delimiter-separated output so that file boundaries can be
        parsed reliably even when file contents contain arbitrary text.
        """
        for n in names:
            self._validate_name(n)
        if not names:
            return {}

        qdir = shlex.quote(self._dir)
        # Use a unique delimiter unlikely to appear in VASP input files
        delim = "====QDYN_FILE_BOUNDARY===="
        # Build a command that prints delimiter+filename header, then cats
        # the file, for each requested name.  Missing files are skipped.
        parts = []
        for n in names:
            qn = shlex.quote(n)
            parts.append(
                f'if [ -f {qdir}/{qn} ]; then '
                f'echo "{delim}{qn}"; '
                f"cat {qdir}/{qn}; fi"
            )
        cmd = "; ".join(parts)

        result: Dict[str, str] = {}
        try:
            stdout, _, rc = self._host.execute(cmd)
            if rc != 0:
                return result
            # Split on delimiter lines to extract file contents
            sections = stdout.split(delim)
            for section in sections[1:]:  # skip empty part before first delim
                # First line after delimiter is the filename
                newline_pos = section.find("\n")
                if newline_pos == -1:
                    continue
                fname = section[:newline_pos].strip()
                content = section[newline_pos + 1 :]
                if fname:
                    result[fname] = content
        except Exception:
            pass
        return result
