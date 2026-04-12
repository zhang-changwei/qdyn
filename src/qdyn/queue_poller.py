"""Background poller that dispatches queued submissions to pool workers.

The :func:`queue_dispatch_loop` coroutine is started as an ``asyncio.Task``
inside the FastAPI lifespan and cancelled on shutdown.  It periodically
scans the ``queued_submissions`` table (FIFO order) and dispatches tasks
using a two-pass fairness algorithm:

  Pass 1 — allocate free workers to users who have *no* worker yet.
  Pass 2 — submit remaining tasks to each user's *existing* worker.

This guarantees that new users get a worker before existing users can
pile more work onto their already-allocated worker.

Design notes
------------
- The poller shares the same ``_dispatch_lock`` as the direct submission
  path in ``app.py``, ensuring that "query MongoDB -> select worker ->
  submit_flow" remains atomic.
- Synchronous operations (MongoDB queries, ``workflow.submit()``) are
  offloaded via ``asyncio.to_thread()`` to avoid blocking the event loop.
- A single task failure never interrupts the polling loop; the error is
  recorded and the task is marked FAILED in the queue table.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database import QdynDB
    from .main_workflow import MainWorkflow

logger = logging.getLogger(__name__)


async def queue_dispatch_loop(
    workflow: MainWorkflow,
    db: QdynDB,
    dispatch_lock: asyncio.Lock,
    interval: int = 60,
) -> None:
    """Main polling loop for dispatching queued submissions.

    Parameters
    ----------
    workflow : MainWorkflow
        The initialised workflow instance (provides pool/worker helpers
        and the ``submit()`` method).
    db : QdynDB
        Database handle for queue operations.
    dispatch_lock : asyncio.Lock
        Shared lock that serialises worker selection and submission
        across the direct-submit endpoint and this poller.
    interval : int
        Seconds to sleep between polling rounds (default 60).
    """
    # ---- Startup recovery ------------------------------------------------
    # Recover tasks that got stuck in DISPATCHING state (e.g. after a
    # crash).  These are transitioned back to QUEUED so they can be
    # retried in the regular polling loop.
    try:
        recovered = db.recover_stale_dispatching(timeout_seconds=60)
        if recovered:
            logger.info(
                "Queue poller startup: recovered %d stale DISPATCHING "
                "task(s) back to QUEUED.",
                recovered,
            )
        else:
            logger.info("Queue poller startup: no stale DISPATCHING tasks.")
    except Exception:
        logger.exception("Queue poller: error during startup recovery.")

    # ---- Main loop -------------------------------------------------------
    logger.info(
        "Queue poller started (interval=%ds, pool=%s).",
        interval,
        workflow.active_pool_name,
    )
    try:
        while True:
            # Lightweight stale-DISPATCHING recovery at the start of
            # every round (not just startup).  This catches tasks that
            # got stuck due to post-submit bookkeeping failures or
            # unexpected crashes between polling rounds.
            try:
                recovered = db.recover_stale_dispatching(timeout_seconds=60)
                if recovered:
                    logger.info(
                        "Queue poller: recovered %d stale DISPATCHING "
                        "task(s) back to QUEUED.",
                        recovered,
                    )
            except Exception:
                logger.exception(
                    "Queue poller: error during per-round stale recovery."
                )

            try:
                await _poll_once(workflow, db, dispatch_lock)
            except asyncio.CancelledError:
                raise  # propagate immediately
            except Exception:
                # Catch-all: a bug in the polling round should not kill
                # the poller.  Log and continue on the next cycle.
                logger.exception(
                    "Queue poller: unexpected error in polling round."
                )

            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.info("Queue poller received cancellation — shutting down.")
        return


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _poll_once(
    workflow: MainWorkflow,
    db: QdynDB,
    dispatch_lock: asyncio.Lock,
) -> None:
    """Execute a single polling round using the two-pass fairness algorithm.

    Pass 1: For each queued task (FIFO), if the user has NO worker and a
             free worker is available, allocate the free worker and dispatch.
    Pass 2: All remaining tasks belong to users who already HAVE a worker.
             Submit each to the user's existing worker and clear the queue.
    """
    pool_name = workflow.active_pool_name

    # 1. Any free workers?
    free_workers = await asyncio.to_thread(
        workflow._get_free_workers, pool_name
    )
    if not free_workers:
        return  # nothing to do this round

    queued = db.list_all_queued()
    if not queued:
        return

    logger.debug(
        "Queue poller: %d task(s) in queue, %d free worker(s).",
        len(queued),
        len(free_workers),
    )

    # ------------------------------------------------------------------
    # Pass 1: Allocate free workers to users without a worker.
    # ------------------------------------------------------------------
    remaining = []  # tasks skipped (user already has a worker)

    for entry in queued:
        username: str = entry["username"]

        # Check if user has any occupied worker.
        user_workers = await asyncio.to_thread(
            workflow._get_user_occupied_workers, username, pool_name
        )

        if user_workers:
            # User already has a worker — defer to Pass 2.
            remaining.append(entry)
            continue

        if not free_workers:
            # No more free workers — defer to next polling round.
            remaining.append(entry)
            continue

        # Allocate a free worker for this user.
        worker = free_workers.pop(0)
        await _claim_and_dispatch(
            workflow, db, dispatch_lock,
            entry, pool_name, worker,
        )

    # ------------------------------------------------------------------
    # Pass 2: Submit remaining tasks to each user's existing worker.
    # ------------------------------------------------------------------
    for entry in remaining:
        task_id: str = entry["task_id"]
        username = entry["username"]

        user_workers = await asyncio.to_thread(
            workflow._get_user_occupied_workers, username, pool_name
        )
        if not user_workers:
            # Edge case: user's worker freed between Pass 1 and Pass 2.
            # Check if we still have free workers from the original batch.
            if free_workers:
                worker = free_workers.pop(0)
                await _claim_and_dispatch(
                    workflow, db, dispatch_lock,
                    entry, pool_name, worker,
                )
            else:
                # No free worker available; leave in queue for next round.
                logger.debug(
                    "Queue poller: user '%s' worker freed but no free "
                    "workers left — task %s stays queued.",
                    username,
                    task_id,
                )
            continue

        # Submit to the user's existing worker.
        worker = user_workers[0]
        await _claim_and_dispatch(
            workflow, db, dispatch_lock,
            entry, pool_name, worker,
        )


async def _claim_and_dispatch(
    workflow: MainWorkflow,
    db: QdynDB,
    dispatch_lock: asyncio.Lock,
    entry: dict,
    pool_name: str,
    worker: str,
) -> None:
    """Claim a queued task and dispatch it to *worker*.

    Handles the full lifecycle: claim -> deserialise -> submit -> bookkeep.
    On failure the task is marked FAILED (or released back to QUEUED for
    TOCTOU races).
    """
    task_id: str = entry["task_id"]
    username: str = entry["username"]
    payload_json: str = entry["payload_json"]

    # Claim the task (atomic QUEUED -> DISPATCHING).
    if not db.claim_queued(task_id):
        logger.debug(
            "Queue poller: failed to claim task %s (already "
            "claimed or cancelled).",
            task_id,
        )
        return

    # Idempotency guard: check if this task was already submitted to
    # jf-remote (e.g. after a crash between submit_flow and local
    # bookkeeping).  If so, reconcile and skip re-dispatch.
    try:
        jc = workflow._ensure_job_controller()
        existing_flow = jc.get_flow_info_by_flow_uuid(task_id)
        if existing_flow is not None:
            logger.warning(
                "Queue poller: task %s already exists in jf-remote "
                "(flow found). Reconciling — marking as SUBMITTED.",
                task_id,
            )
            # Reconcile: fill in job_ids from MongoDB using canonical
            # step keys (nvt/nve/scf/pre_namd/namd), not job function
            # names (qdyn_nve etc.).
            _JOB_NAME_TO_STEP = {
                "qdyn_nvt": "nvt",
                "qdyn_nve": "nve",
                "qdyn_scf_task": "scf",
                "qdyn_pre_namd": "pre_namd",
                "qdyn_namd": "namd",
            }
            jobs_info = jc.get_jobs_info(flow_ids=[task_id])
            job_ids_map = {}
            for ji in jobs_info:
                job_name = ji.name if hasattr(ji, 'name') else ''
                step = _JOB_NAME_TO_STEP.get(job_name, job_name)
                job_ids_map.setdefault(step, []).append(ji.uuid)

            # Get the actual worker from the first job (the real
            # worker the flow was submitted to, not the poller's
            # current candidate).
            actual_worker = worker  # fallback
            if jobs_info:
                first_job = jobs_info[0]
                if hasattr(first_job, 'worker') and first_job.worker:
                    actual_worker = first_job.worker

            try:
                db.update_task_dispatch_info(
                    task_id, job_ids_map, actual_worker
                )
                db.mark_submitted(
                    task_id, job_ids_map, actual_worker
                )
            except Exception:
                # At minimum mark submitted to prevent re-dispatch
                try:
                    db.mark_submitted(task_id, {}, actual_worker)
                except Exception:
                    pass
            return
    except Exception as exc:
        logger.debug(
            "Queue poller: idempotency check for task %s failed: %s "
            "(proceeding with dispatch)",
            task_id,
            exc,
        )

    # Deserialise payload.
    from .input import InputT  # deferred to avoid circular imports

    try:
        payload = json.loads(payload_json)
        input_obj = InputT.model_validate(payload["input"])
        method = payload.get("method", "namd")
        resume = payload.get("resume", False)
        prev_task_id = payload.get("prev_task_id", "")
    except Exception as exc:
        logger.error(
            "Queue poller: failed to deserialise payload for task "
            "%s: %s",
            task_id,
            exc,
        )
        db.mark_queue_failed(task_id, f"Payload deserialisation error: {exc}")
        return

    # Dispatch under lock.
    try:
        runtime_worker, job_ids = await _locked_dispatch(
            workflow,
            dispatch_lock,
            task_id=task_id,
            username=username,
            pool_name=pool_name,
            input_obj=input_obj,
            method=method,
            resume=resume,
            prev_task_id=prev_task_id,
            target_worker=worker,
        )
    except Exception as exc:
        logger.error(
            "Queue poller: dispatch failed for task %s: %s",
            task_id,
            exc,
        )
        db.mark_queue_failed(task_id, str(exc))
        return

    if runtime_worker is None:
        # Worker became unavailable between selection and lock
        # acquisition (TOCTOU).  Release the claim so the task is
        # retried on the next polling round.
        db.release_claim(task_id)
        logger.info(
            "Queue poller: released claim for task %s — worker "
            "no longer available (TOCTOU).",
            task_id,
        )
        return

    # Success — update bookkeeping.
    # update_task_dispatch_info fills in job_ids and worker on the
    # existing task_owners row (which was created with empty job_ids
    # when the task was enqueued).  We do NOT call assign_task because
    # the row already exists.
    #
    # This block is wrapped in its own try/except because the flow has
    # already been submitted to jf-remote at this point.  If the local
    # bookkeeping fails, we must NOT let the exception bubble up and
    # kill the rest of the polling round — mark the task FAILED so it
    # doesn't stay stuck in DISPATCHING forever.
    try:
        db.update_task_dispatch_info(task_id, job_ids, runtime_worker)
        db.mark_submitted(task_id, job_ids, runtime_worker)
    except Exception as exc:
        logger.warning(
            "Queue poller: post-submit bookkeeping failed for task "
            "%s (flow already submitted to jf-remote): %s",
            task_id,
            exc,
        )
        try:
            db.mark_queue_failed(
                task_id,
                f"Post-submit bookkeeping error (flow submitted): {exc}",
            )
        except Exception:
            logger.exception(
                "Queue poller: failed to mark task %s as FAILED after "
                "bookkeeping error.",
                task_id,
            )
        return

    logger.info(
        "Queue poller: dispatched task %s -> worker %s (user=%s, "
        "pool=%s).",
        task_id,
        runtime_worker,
        username,
        pool_name,
    )


async def _locked_dispatch(
    workflow: MainWorkflow,
    dispatch_lock: asyncio.Lock,
    *,
    task_id: str,
    username: str,
    pool_name: str,
    input_obj,
    method: str,
    resume: bool,
    prev_task_id: str,
    target_worker: str,
):
    """Submit to *target_worker* under the dispatch lock.

    The caller has already determined which worker to use.  This method
    acquires the lock and calls ``workflow.submit()`` directly with the
    pre-selected worker.

    Returns ``(effective_worker, job_ids)`` on success, or
    ``(None, None)`` if submission fails.
    """
    async with dispatch_lock:
        # Submit via jobflow-remote (synchronous, offloaded to thread).
        final_task_id, job_ids, effective_worker = await asyncio.to_thread(
            workflow.submit,
            input=input_obj,
            method=method,
            stru=input_obj.stru,
            stru_format=input_obj.stru_format,
            stru_hash=input_obj.stru_hash,
            resume=resume,
            prev_task_id=prev_task_id,
            task_id=task_id,
            username=username,
            pool_name=pool_name,
            runtime_worker=target_worker,
        )

        return effective_worker, job_ids
