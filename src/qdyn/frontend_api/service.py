"""Compatibility facade for frontend API services.

All business logic has been moved to domain-specific modules.  This
module re-exports every public and test-visible symbol so that existing
``from qdyn.frontend_api.service import ...`` statements continue to
work without modification.
"""

# --- common helpers ---
from ._common import (  # noqa: F401
    _detect_step_type,
    _dt_str,
    _get_task_run_dir_access,
)

# --- file & download services ---
from .files import (  # noqa: F401
    build_download_zip,
    get_job_images,
    list_job_files,
    list_subdir_files,
    serve_job_file,
    serve_subdir_file,
)

# --- input parameter display ---
from .job_inputs import (  # noqa: F401
    _flatten_parameter_mapping,
    get_job_input_params,
)

# --- MD timeseries ---
from .md_timeseries import get_job_md_timeseries  # noqa: F401

# --- preview (merged builder + orchestration) ---
from .preview import (  # noqa: F401
    _enrich_with_layer_constraints,
    _get_constraint_params_for_task,
    compute_structure_preview,
)

# --- progress ---
from .progress import (  # noqa: F401
    _get_scf_progress,
    _get_scf_progress_from_log_text,
    get_job_progress,
)

# --- task & job status ---
from .task_status import (  # noqa: F401
    derive_job_state,
    derive_task_status,
    get_job_error_detail,
    get_job_error_summary,
    get_job_info_safe,
    get_task_detail,
    get_task_summary_list,
)


__all__ = [
    # router-public
    "derive_job_state",
    "derive_task_status",
    "get_job_info_safe",
    "get_job_error_summary",
    "get_job_error_detail",
    "get_task_summary_list",
    "get_task_detail",
    "get_job_input_params",
    "list_job_files",
    "build_download_zip",
    "serve_job_file",
    "serve_subdir_file",
    "list_subdir_files",
    "get_job_progress",
    "get_job_images",
    "get_job_md_timeseries",
    "compute_structure_preview",
    # test-visible
    "_dt_str",
    "_detect_step_type",
    "_flatten_parameter_mapping",
    "_get_scf_progress",
    "_get_scf_progress_from_log_text",
    "_enrich_with_layer_constraints",
    "_get_constraint_params_for_task",
]
