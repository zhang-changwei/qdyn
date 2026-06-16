"""Structure preview builder and task-level preview orchestration.

Low-level builder functions (atoms_to_vasp_text, build_preview_from_atoms,
build_preview) have no business dependencies.  Task-level orchestration
functions (compute_structure_preview, _try_preview_for_task, etc.) use
delayed imports for MainWorkflow and qdyndb to keep the builder importable
without pulling in heavy business modules.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import ase.io
from ase import Atoms

from ..calc_common import read_stru, read_strus
from ..params import STEP_ORDER
from ..tools.seldyn import extract_constraint_mask
from ._common import _get_task_run_dir_access
from .models import StructurePreviewPayload

if TYPE_CHECKING:
    from ..main_workflow import MainWorkflow

logger = logging.getLogger(__name__)


# =============================================================================
# Low-level structure preview builder (no business dependencies)
# =============================================================================

def atoms_to_vasp_text(atoms: Atoms) -> str:
    """Serialize ASE atoms to POSCAR/VASP text without reordering atoms."""
    buf = io.StringIO()
    ase.io.write(
        buf,
        atoms,
        format="vasp",
        direct=True,
        vasp5=True,
        sort=False,
    )
    return buf.getvalue()


def build_preview_from_atoms(atoms: Atoms) -> StructurePreviewPayload:
    """Build the additive preview payload from an ASE Atoms object."""
    species: list[str] = atoms.get_chemical_symbols()
    cart_coords: list[list[float]] = atoms.get_positions().tolist()
    lattice: list[list[float]] = atoms.cell.tolist()
    pbc: list[bool] = atoms.pbc.tolist()
    constraint_mask = extract_constraint_mask(atoms)

    return StructurePreviewPayload(
        species=species,
        cart_coords=cart_coords,
        lattice=lattice,
        pbc=pbc,
        constraint_mask=constraint_mask,
        format="vasp",
        content=atoms_to_vasp_text(atoms),
    )


def build_preview(content: str, fmt: str = "vasp") -> StructurePreviewPayload:
    """Parse structure text into a format-agnostic preview payload.

    Args:
        content: Structure file content as a string.
        fmt: ASE I/O format string (default "vasp" for POSCAR).

    Returns:
        A StructurePreviewPayload with parsed structure data.

    Raises:
        ValueError: If ASE cannot parse the content.
    """
    try:
        atoms = read_stru(fmt, io.StringIO(content))
    except Exception as exc:
        raise ValueError(f"Failed to parse structure: {exc}") from exc

    if atoms is None:
        raise ValueError("Failed to parse structure: ASE returned None")

    return build_preview_from_atoms(atoms)


# =============================================================================
# Task-level preview orchestration (business dependencies are delayed)
# =============================================================================


def compute_structure_preview(
    task_id: str,
    manager: MainWorkflow,
    *,
    enrich_constraints: bool = True,
):
    """Compute structure preview on-demand for a task.

    Returns StructurePreviewPayload or None.
    """
    from ..database import qdyndb

    result = _try_preview_for_task(task_id, manager)
    if result is not None:
        if enrich_constraints:
            return _enrich_with_layer_constraints(result, task_id)
        return result

    task_meta = qdyndb.get_task_metadata(task_id)
    if task_meta and task_meta.get("prev_task_id"):
        visited: set = {task_id}
        tid = task_meta["prev_task_id"]
        for _ in range(10):
            if not tid or tid in visited:
                break
            visited.add(tid)
            result = _try_preview_for_task(tid, manager)
            if result is not None:
                if enrich_constraints:
                    return _enrich_with_layer_constraints(result, task_id)
                return result
            parent_meta = qdyndb.get_task_metadata(tid)
            if not parent_meta:
                break
            tid = parent_meta.get("prev_task_id")

    return None


def _enrich_with_layer_constraints(preview, task_id: str):
    """If preview has no file-level constraints, compute layer mask
    from the task's InputT constraint_layers parameters."""
    if preview.constraint_mask is not None:
        return preview

    constraint_params = _get_constraint_params_for_task(task_id)
    if not constraint_params:
        return preview

    try:
        from copy import deepcopy

        from ..input import SelDynInputT
        from ..tools.seldyn import add_constraints

        atoms = Atoms(
            symbols=preview.species,
            positions=preview.cart_coords,
            cell=preview.lattice,
            pbc=preview.pbc,
        )

        sel = SelDynInputT(
            constraint_layers=constraint_params["constraint_layers"],
            layer_direction=constraint_params["layer_direction"],
            total_layers=constraint_params["total_layers"],
        )
        atoms_copy = deepcopy(atoms)
        add_constraints(atoms_copy, sel)
        return build_preview_from_atoms(atoms_copy)
    except Exception:
        logger.debug(
            "Failed to compute layer constraints for task %s", task_id,
            exc_info=True,
        )

    return preview


def _get_constraint_params_for_task(task_id: str) -> dict | None:
    """Extract constraint_layers/layer_direction/total_layers from a task's
    InputT, trying queued payload first, then MongoDB job collection."""
    from ..database import qdyndb

    payload_json = qdyndb.get_queued_payload(task_id)
    if payload_json:
        try:
            payload = json.loads(payload_json)
            input_data = payload.get("input", {})
            result = _extract_constraint_params_from_input(input_data)
            if result:
                return result
        except Exception:
            logger.debug(
                "Failed to extract constraint params from queued payload for %s",
                task_id, exc_info=True,
            )

    try:
        from jobflow_remote.config.manager import ConfigManager

        cm = ConfigManager()
        project = cm.get_project()
        jc = project.get_job_controller()

        docs = jc.jobs.find(
            {"job.metadata.qdyn_task_id": task_id},
            {"job.function_kwargs.parameters": 1, "job.index": 1, "_id": 0},
        ).sort("job.index", 1)
        for doc in docs:
            params = (
                doc.get("job", {})
                .get("function_kwargs", {})
                .get("parameters", {})
            )
            if isinstance(params, dict):
                result = _extract_constraint_params_from_input(params)
                if result:
                    return result
    except Exception:
        logger.debug(
            "Failed to read constraint params from MongoDB for task %s",
            task_id, exc_info=True,
        )

    return None


def _extract_constraint_params_from_input(input_data: dict) -> dict | None:
    """Extract constraint params from an input dict."""
    def _try_extract(data: dict) -> dict | None:
        sel = data.get("sel")
        if not isinstance(sel, dict):
            return None
        cl = sel.get("constraint_layers")
        ld = sel.get("layer_direction")
        tl = sel.get("total_layers")
        if not cl or not ld or not tl:
            return None
        try:
            cl_str = " ".join(str(x) for x in cl) if isinstance(cl, list) else str(cl)
            return {
                "constraint_layers": cl_str,
                "layer_direction": str(ld),
                "total_layers": int(tl),
            }
        except (ValueError, TypeError):
            return None

    result = _try_extract(input_data)
    if result:
        return result

    for step_key in ("nvt_input", "nve_input"):
        step_data = input_data.get(step_key)
        if isinstance(step_data, dict):
            result = _try_extract(step_data)
            if result:
                return result

    return None


def _try_preview_for_task(
    task_id: str,
    manager: MainWorkflow,
):
    """Attempt to build a structure preview for a single task."""
    from ..database import qdyndb
    from ..params import STRU_FNAME_MAPPING, STRU_FORMAT_MAPPING, TRAJ_FORMAT_MAPPING

    payload_json = qdyndb.get_queued_payload(task_id)
    if payload_json:
        try:
            payload = json.loads(payload_json)
            input_data = payload.get("input", {})
            stru_text = input_data.get("stru", "")
            stru_format = input_data.get("stru_format", "vasp")

            if stru_text:
                return build_preview(stru_text, fmt=stru_format)

            stru_hash = input_data.get("stru_hash", "")
            if stru_hash:
                preview = _preview_from_traj_hash(
                    stru_hash, stru_format, task_id, manager
                )
                if preview is not None:
                    return preview
        except Exception:
            logger.warning(
                "Failed to build preview from queued payload for task %s",
                task_id,
            )

    meta = qdyndb.get_task_metadata(task_id)
    if meta and meta.get("stru_hash"):
        fmt = meta.get("stru_format") or "vasp"
        preview = _preview_from_traj_hash(
            meta["stru_hash"], fmt, task_id, manager
        )
        if preview is not None:
            return preview

    job_ids = qdyndb.get_task_job_ids(task_id)
    if not job_ids:
        return None

    sorted_steps = sorted(
        job_ids.keys(),
        key=lambda s: STEP_ORDER.get(s, 99),
    )
    first_job_uuid = None
    first_step = None
    for step in sorted_steps:
        uuids = job_ids[step]
        if uuids:
            first_job_uuid = uuids[0]
            first_step = step
            break

    if not first_job_uuid:
        return None

    access = _get_task_run_dir_access(manager, task_id, first_job_uuid)
    access_ok = access is not None and access.is_available()

    software = _resolve_software_for_task(task_id, manager)

    if access_ok and first_step in ("nvt", "nve"):
        stru_filename = STRU_FNAME_MAPPING.get(software)
        if stru_filename and access.root_file_exists(stru_filename):
            try:
                content = access.read_root_text(stru_filename)
                fmt = STRU_FORMAT_MAPPING.get(software, software)
                return build_preview(content, fmt=fmt)
            except Exception:
                logger.warning(
                    "Failed to parse structure from %s in run dir for task %s",
                    stru_filename,
                    task_id,
                )

    if access_ok and first_step == "scf":
        from ..params import TRAJ_FNAME_MAPPING

        traj_filename = TRAJ_FNAME_MAPPING.get(software)
        if traj_filename and access.root_file_exists(traj_filename):
            try:
                content = access.read_root_text(traj_filename)
                ase_fmt = TRAJ_FORMAT_MAPPING.get(software, software)
                return build_preview(content, fmt=ase_fmt)
            except Exception:
                logger.warning(
                    "Failed to parse trajectory from %s for task %s",
                    traj_filename,
                    task_id,
                )

        stru_filename = STRU_FNAME_MAPPING.get(software)
        if stru_filename and access.root_file_exists(stru_filename):
            try:
                content = access.read_root_text(stru_filename)
                fmt = STRU_FORMAT_MAPPING.get(software, software)
                return build_preview(content, fmt=fmt)
            except Exception:
                pass

    if access_ok:
        stru_filename = STRU_FNAME_MAPPING.get(software)
        if stru_filename and access.root_file_exists(stru_filename):
            try:
                content = access.read_root_text(stru_filename)
                fmt = STRU_FORMAT_MAPPING.get(software, software)
                return build_preview(content, fmt=fmt)
            except Exception:
                pass

    preview = _preview_from_job_kwargs(first_job_uuid, manager)
    if preview is not None:
        return preview

    return None


def _preview_from_job_kwargs(
    job_uuid: str,
    manager: MainWorkflow,
):
    """Extract structure data from MongoDB job document and build preview."""
    from ..params import TRAJ_FORMAT_MAPPING

    try:
        jc = manager._ensure_job_controller()
        jobs_col = jc.db[jc.jobs_collection]
        doc = jobs_col.find_one(
            {"uuid": job_uuid},
            {"job.function_kwargs": 1},
        )
        if not doc:
            return None

        kwargs = doc.get("job", {}).get("function_kwargs", {})
        software = kwargs.get("software", "vasp")

        stru_dict = kwargs.get("structure")
        if isinstance(stru_dict, dict) and "positions" in stru_dict:
            import numpy as _np
            for key in stru_dict:
                if isinstance(stru_dict[key], list):
                    stru_dict[key] = _np.array(stru_dict[key])
            atoms = Atoms.fromdict(stru_dict)
            return build_preview_from_atoms(atoms)

        traj_path = kwargs.get("traj_path")
        traj_format = kwargs.get("traj_format", software)

        if traj_path:
            traj_path = Path(traj_path)
            if traj_path.is_file():
                ase_fmt = TRAJ_FORMAT_MAPPING.get(traj_format, traj_format)
                atoms = read_strus(ase_fmt, str(traj_path), first_only=True)[0]
                return build_preview_from_atoms(atoms)
    except Exception:
        logger.warning(
            "Failed to build preview from job kwargs for %s", job_uuid
        )
        return None


def _preview_from_traj_hash(
    stru_hash: str,
    stru_format: str,
    task_id: str,
    manager: MainWorkflow,
):
    """Read the first frame of a trajectory file identified by hash."""
    from ..params import TRAJ_FORMAT_MAPPING

    pool = manager.get_task_pool(task_id)
    traj_path = Path(pool.get_user_file_path('trajectory', stru_hash))
    if not traj_path.is_file():
        return None

    try:
        ase_fmt = TRAJ_FORMAT_MAPPING.get(stru_format, stru_format)
        atoms = read_strus(ase_fmt, str(traj_path), first_only=True)[0]
        return build_preview_from_atoms(atoms)
    except Exception:
        logger.warning(
            "Failed to parse trajectory hash %s for preview", stru_hash
        )
        return None


def _resolve_software_for_task(task_id: str, manager: MainWorkflow) -> str:
    """Determine the software used by a task."""
    from ..database import qdyndb

    payload_json = qdyndb.get_queued_payload(task_id)
    if payload_json:
        try:
            payload = json.loads(payload_json)
            input_data = payload.get("input", {})
            for section in ("nvt_input", "nve_input", "scf_input"):
                data = input_data.get(section)
                if isinstance(data, dict):
                    sw = data.get("software")
                    if sw:
                        return sw
        except Exception:
            pass
    return "vasp"
