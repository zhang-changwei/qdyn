"""MD timeseries data retrieval and sampling services."""

from pathlib import Path

from ._common import _detect_step_type
from ..main_workflow import MainWorkflow
from .models import (
    JobMdTimeseriesResponse,
    MDAttemptItem,
    MDReferenceLines,
    MDSeriesData,
    MDTimeseriesStats,
)


def _resolve_md_attempt_files(
    run_dir: Path,
    attempt: int | None,
) -> tuple[Path, int, list[MDAttemptItem]]:
    """Discover NVT retry attempt directories and resolve source directories.

    Returns
    -------
    tuple of (attempt_dir, selected_attempt, attempts_list)
    """
    attempt_dirs: list[Path] = sorted(
        run_dir.glob("nvt_attempt_*"),
        key=lambda p: int(p.name.split("_")[-1]) if p.name.split("_")[-1].isdigit() else 0,
    )

    attempts: list[MDAttemptItem] = []
    max_archived = 0
    for d in attempt_dirs:
        if not d.is_dir():
            continue
        try:
            num = int(d.name.split("_")[-1])
        except ValueError:
            continue
        max_archived = max(max_archived, num)
        if (d / "qdyn_md.log").is_file():
            attempts.append(MDAttemptItem(
                attempt=num,
                label=f"Attempt {num}",
                is_current=False,
                archived=True,
            ))

    current_num = max_archived + 1
    root_qdyn_log = run_dir / "qdyn_md.log"
    if root_qdyn_log.is_file():
        attempts.append(MDAttemptItem(
            attempt=current_num,
            label=f"Attempt {current_num} (latest)" if attempts else f"Attempt {current_num}",
            is_current=True,
            archived=False,
        ))

    if attempt is None:
        selected = current_num
    else:
        selected = attempt

    if selected == current_num and root_qdyn_log.is_file():
        attempt_dir = run_dir
    else:
        attempt_dir = run_dir / f"nvt_attempt_{selected}"
        qdyn_log_path = attempt_dir / "qdyn_md.log"
        if not qdyn_log_path.is_file():
            raise FileNotFoundError(
                f"qdyn_md.log not found for attempt {selected} "
                f"(looked in {attempt_dir})."
            )

    return attempt_dir, selected, attempts


def _sample_series(series: dict, max_points: int) -> dict:
    """Down-sample series data using fixed-bucket min/max to preserve extremes."""
    n = len(series['steps'])
    if n <= max_points:
        return series

    num_buckets = (max_points - 2) // 2
    if num_buckets < 1:
        num_buckets = 1
    bucket_size = n / num_buckets

    indices: list[int] = [0]
    for b in range(num_buckets):
        start = int(b * bucket_size)
        end = int((b + 1) * bucket_size)
        if start >= n:
            break
        end = min(end, n)

        min_idx = start
        max_idx = start
        for i in range(start, end):
            if series['temperatures'][i] < series['temperatures'][min_idx]:
                min_idx = i
            if series['temperatures'][i] > series['temperatures'][max_idx]:
                max_idx = i

        if min_idx <= max_idx:
            indices.append(min_idx)
            if max_idx != min_idx:
                indices.append(max_idx)
        else:
            indices.append(max_idx)
            if min_idx != max_idx:
                indices.append(min_idx)

    if indices and indices[-1] != n - 1:
        indices.append(n - 1)

    seen: set[int] = set()
    unique: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)

    sampled: dict = {}
    for key, arr in series.items():
        sampled[key] = [arr[i] for i in unique]
    return sampled


def _calc_energy_drift_slope(
    steps: list[int], total_energies: list[float]
) -> float | None:
    """Compute linear regression slope (eV/step) for total energy drift."""
    n = len(total_energies)
    if n < 2 or len(steps) != n:
        return None
    mean_x = sum(steps) / n
    mean_y = sum(total_energies) / n
    ss_xy = 0.0
    ss_xx = 0.0
    for x, y in zip(steps, total_energies):
        dx = x - mean_x
        ss_xy += dx * (y - mean_y)
        ss_xx += dx * dx
    if ss_xx == 0:
        return 0.0
    return ss_xy / ss_xx


def _read_md_references_from_job(run_dir: Path | None) -> dict:
    """Extract MD reference parameters from jfremote_in.json."""
    if run_dir is None:
        return {}
    try:
        import json
        raw = (run_dir / "jfremote_in.json").read_text(encoding="utf-8")
        params = json.loads(raw).get("job", {}).get("function_kwargs", {}).get("parameters", {})
        if not isinstance(params, dict):
            return {}
        return {
            "temp_begin": params.get("temp_begin"),
            "temp_end": params.get("temp_end"),
            "md_dt": params.get("md_dt"),
        }
    except Exception:
        return {}


def _build_md_references(
    step_type: str,
    raw_data: dict,
    series: dict,
    run_dir: Path | None = None,
) -> MDReferenceLines:
    """Assemble reference line data for the chart."""
    job_refs = _read_md_references_from_job(run_dir)
    potim: float | None = job_refs.get("md_dt")
    tebeg: float | None = job_refs.get("temp_begin")
    teend: float | None = job_refs.get("temp_end")

    target_temp: float | None = None
    tol_low: float | None = None
    tol_high: float | None = None
    if step_type == "nvt" and teend is not None:
        target_temp = teend
        tol_low = teend * 0.9
        tol_high = teend * 1.1

    mean_total: float | None = None
    initial_total: float | None = None
    drift: float | None = None
    total_e = series.get('total_energies', [])
    if total_e:
        mean_total = sum(total_e) / len(total_e)
        initial_total = total_e[0]
        if step_type == "nve":
            drift = _calc_energy_drift_slope(series.get('steps', []), total_e)

    return MDReferenceLines(
        potim_fs=potim,
        tebeg=tebeg,
        teend=teend,
        target_temperature=target_temp,
        temperature_tolerance_low=tol_low,
        temperature_tolerance_high=tol_high,
        mean_total_energy=mean_total,
        initial_total_energy=initial_total,
        energy_drift_slope_ev_per_step=drift,
    )


def get_job_md_timeseries(
    manager: MainWorkflow,
    task_id: str,
    job_uuid: str,
    attempt: int | None,
    max_points: int,
) -> JobMdTimeseriesResponse:
    """Build the full MD timeseries response for a job."""
    from ..output_postprocess import parse_md_data_from_qdyn_log

    jc = manager._ensure_job_controller()
    try:
        job_info = jc.get_job_info(job_id=job_uuid)
    except Exception:
        return JobMdTimeseriesResponse(available=False, warning="Failed to query job info.")

    if job_info is None:
        return JobMdTimeseriesResponse(available=False, warning="Job not found.")

    raw_state = job_info.state.value
    job_name = getattr(job_info, "name", "") or ""
    raw_run_dir = getattr(job_info, "run_dir", None)
    if not raw_run_dir:
        return JobMdTimeseriesResponse(available=False, warning="Job run directory not available yet.")

    if manager.get_task_pool(task_id).remote:
        return JobMdTimeseriesResponse(
            available=False,
            step_type=_detect_step_type(job_name, str(raw_run_dir)),
            state=raw_state,
            warning=(
                "MD timeseries is not yet supported for remote workers. "
                "This feature will be available in a future update."
            ),
        )

    run_dir = Path(str(raw_run_dir))
    if not run_dir.is_dir():
        return JobMdTimeseriesResponse(available=False, warning="Job run directory does not exist.")

    step_type = _detect_step_type(job_name, str(run_dir))
    if step_type not in ("nvt", "nve"):
        return JobMdTimeseriesResponse(
            available=False,
            step_type=step_type,
            warning=f"MD timeseries not applicable for step_type '{step_type}'.",
        )

    raw_data: dict | None = None
    selected_attempt: int | None = None
    attempts: list[MDAttemptItem] = []

    if step_type == "nve":
        qdyn_log_path = run_dir / "qdyn_md.log"
        selected_attempt = 1
        attempts = [
            MDAttemptItem(
                attempt=1, label="Attempt 1", is_current=True, archived=False,
            ),
        ]
        try:
            raw_data = parse_md_data_from_qdyn_log(qdyn_log_path)
        except (FileNotFoundError, ValueError) as exc:
            return JobMdTimeseriesResponse(
                available=False,
                step_type=step_type,
                state=raw_state,
                selected_attempt=selected_attempt,
                attempts=attempts,
                warning=str(exc),
            )
    else:
        try:
            attempt_dir, selected_attempt, attempts = (
                _resolve_md_attempt_files(run_dir, attempt)
            )
        except FileNotFoundError as exc:
            return JobMdTimeseriesResponse(
                available=False,
                step_type=step_type,
                state=raw_state,
                warning=str(exc),
            )

        attempt_qdyn_log = attempt_dir / "qdyn_md.log"
        try:
            raw_data = parse_md_data_from_qdyn_log(attempt_qdyn_log)
        except (FileNotFoundError, ValueError) as exc:
            return JobMdTimeseriesResponse(
                available=False,
                step_type=step_type,
                state=raw_state,
                selected_attempt=selected_attempt,
                attempts=attempts,
                warning=str(exc),
            )

    original_points = len(raw_data['steps'])

    if 'time_ps' in raw_data:
        time_fs = [t * 1000.0 for t in raw_data['time_ps']]
    else:
        time_fs = [float(s) for s in raw_data['steps']]

    series_dict = {
        'steps': raw_data['steps'],
        'time_fs': time_fs,
        'temperatures': raw_data['temperatures'],
        'total_energies': raw_data['total_energies'],
        'potential_energies': raw_data['potential_energies'],
        'kinetic_energies': raw_data['kinetic_energies'],
        'converged': raw_data['converged'],
    }

    references = _build_md_references(step_type, raw_data, series_dict, run_dir=run_dir)

    sampled = original_points > max_points
    if sampled:
        series_dict = _sample_series(series_dict, max_points)

    returned_points = len(series_dict['steps'])

    total_from_header = raw_data.get('total_steps', 0)
    total_steps: int | None = int(total_from_header) if total_from_header > 0 else None

    stats = MDTimeseriesStats(
        current_step=raw_data['steps'][-1] if raw_data['steps'] else 0,
        total_steps=total_steps,
        original_points=original_points,
        returned_points=returned_points,
        sampled=sampled,
    )

    series = MDSeriesData(**series_dict)

    return JobMdTimeseriesResponse(
        available=True,
        step_type=step_type,
        state=raw_state,
        selected_attempt=selected_attempt,
        attempts=attempts,
        series=series,
        references=references,
        stats=stats,
    )
