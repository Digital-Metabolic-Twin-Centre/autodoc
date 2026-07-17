import json
import os
import signal
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing import Process
from threading import Condition, Lock, Thread
from time import sleep
from typing import Any

from admin.database import SessionLocal
from admin.models import RunRecord
from models.repo_request import (
    ArchitectureApprovalRequest,
    ArchitectureGenerationRequest,
    DocstringPullRequestRequest,
    PublishPagesRequest,
    RepoRequest,
)
from services.workflow_service import (
    WorkflowRunResult,
    execute_architecture_approval_request,
    execute_architecture_generation_request,
    execute_docstring_pr_request,
    execute_generate_request,
    execute_publish_request,
)


@dataclass
class QueuedJob:
    """
    Represents a job queued for delivery to an external endpoint.

    Attributes:
        run_id (int): Unique identifier of the associated run.
        endpoint (str): Target endpoint URL or name to send the payload to.
        payload (dict[str, Any]): Data to be delivered with the job.

    """

    run_id: int
    endpoint: str
    payload: dict[str, Any]


JOB_QUEUE: deque[QueuedJob] = deque()
QUEUE_CONDITION = Condition()
DISPATCHER_THREAD: Thread | None = None
DISPATCHER_LOCK = Lock()
CURRENT_PROCESS: Process | None = None
CURRENT_RUN_ID: int | None = None
PROCESS_LOCK = Lock()
UNEXPECTED_EXIT_MESSAGE = "Job process exited unexpectedly before the run could finish."
RESTART_EXIT_MESSAGE = (
    "Run was interrupted because the server stopped before the job could finish."
)
RESTART_QUEUE_MESSAGE = (
    "Run was interrupted because the server stopped before the queued job could start."
)
CANCEL_GRACE_SECONDS = 10.0


def _update_run(run_id: int, updater) -> None:
    """
    Apply an update function to a run record and persist the change.

    Args:
        run_id (int): The ID of the run record to update.
        updater (Callable[[RunRecord], None]): A function that mutates the run record in place.

    Returns:
        None: Returns nothing; silently exits if the run record is not found.

    """
    with SessionLocal() as session:
        run = session.get(RunRecord, run_id)
        if run is None:
            return
        updater(run)
        session.add(run)
        session.commit()


def _set_run_progress(run_id: int, percent: float, message: str) -> None:
    """
    Update the progress percentage and message for a run, clamping the percent to [0, 100].

    Args:
        run_id (int): Identifier of the run to update.
        percent (float): Progress percentage; clamped to the range [0.0, 100.0].
        message (str): Progress message to associate with the run.

    Returns:
        None

    """
    normalized_percent = max(0.0, min(100.0, percent))

    def apply(run: RunRecord) -> None:
        """
        Mark a run as cancelled and update its status fields in place.

        Args:
            run (RunRecord): The run record to update.

        Returns:
            None: The run object is mutated directly.

        """
        run.progress_percent = normalized_percent
        run.progress_message = message

    _update_run(run_id, apply)


def _duration_seconds(
    started_at: datetime | None,
    finished_at: datetime | None,
) -> float:
    """
    Compute the duration in seconds between two datetimes, normalizing timezone awareness if they
    differ.

    Args:
        started_at (datetime | None): Start time, may be naive or timezone-aware.
        finished_at (datetime | None): End time, may be naive or timezone-aware.

    Returns:
        float: Duration in seconds between the two times, or 0.0 if either is None.

    """
    if started_at is None or finished_at is None:
        return 0.0
    normalized_started_at = started_at
    normalized_finished_at = finished_at
    if (
        normalized_started_at.tzinfo is None
        and normalized_finished_at.tzinfo is not None
    ):
        normalized_finished_at = normalized_finished_at.replace(tzinfo=None)
    elif (
        normalized_started_at.tzinfo is not None
        and normalized_finished_at.tzinfo is None
    ):
        normalized_started_at = normalized_started_at.replace(tzinfo=None)
    return (normalized_finished_at - normalized_started_at).total_seconds()


def _mark_cancelled(run_id: int, message: str) -> None:
    """
    Mark a run as cancelled and update its progress and completion metadata.

    Args:
        run_id (int): Identifier of the run to mark as cancelled.
        message (str): Error/cancellation message to record for the run.

    Returns:
        None

    """
    cancelled_at = datetime.now(UTC)

    def apply(run: RunRecord) -> None:
        """
        Update a run record's progress fields in place.

        Args:
            run (RunRecord): The run record whose progress state will be updated.

        Returns:
            None

        """
        run.status = "cancelled"
        run.progress_percent = 100.0
        run.progress_message = "Cancelled"
        run.completed_at = cancelled_at
        run.duration_seconds = _duration_seconds(run.started_at, cancelled_at)
        run.error_message = message

    _update_run(run_id, apply)


def reconcile_interrupted_runs() -> int:
    """
    Mark all interrupted (queued/running) runs as failed and record recovery metadata.

    Args:
        None.

    Returns:
        int: The number of interrupted runs that were reconciled.

    """
    recovered_at = datetime.now(UTC)

    with SessionLocal() as session:
        interrupted_runs = (
            session.query(RunRecord)
            .filter(RunRecord.status.in_(("queued", "running")))
            .all()
        )
        for run in interrupted_runs:
            previous_status = run.status
            run.status = "failed"
            run.progress_percent = 100.0
            run.progress_message = "Failed"
            run.completed_at = recovered_at
            run.duration_seconds = _duration_seconds(run.started_at, recovered_at)
            run.error_message = (
                RESTART_EXIT_MESSAGE
                if previous_status == "running"
                else RESTART_QUEUE_MESSAGE
            )
            session.add(run)
        session.commit()
        return len(interrupted_runs)


def _terminate_process_tree(process: Process) -> bool:
    """
    Terminate a process group gracefully, then forcefully if needed.
    Args:
        process (Process): Process whose process group should be terminated.
    Returns:
        bool: True if the process is stopped or no longer exists; otherwise False.

    """
    if not process.pid:
        return False
    try:
        process_group_id = os.getpgid(process.pid)
    except ProcessLookupError:
        return True

    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return True

    deadline = datetime.now(UTC).timestamp() + CANCEL_GRACE_SECONDS
    while process.is_alive() and datetime.now(UTC).timestamp() < deadline:
        process.join(timeout=0.2)
        sleep(0.05)

    if not process.is_alive():
        return True

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return True

    process.join(timeout=2)
    return not process.is_alive()


def _ensure_dispatcher() -> None:
    """
    Ensure the background admin dispatcher thread is running.

    Args:
        None.
    Returns:
        None: This function does not return a value.

    """
    global DISPATCHER_THREAD
    with DISPATCHER_LOCK:
        if DISPATCHER_THREAD and DISPATCHER_THREAD.is_alive():
            return
        DISPATCHER_THREAD = Thread(
            target=_dispatch_loop,
            name="autodoc-admin-dispatcher",
            daemon=True,
        )
        DISPATCHER_THREAD.start()


def enqueue_run(run_id: int, endpoint: str, payload: dict[str, Any]) -> None:
    """
    Enqueue a run job and notify the dispatcher.

    Args:
        run_id (int): Unique run identifier. endpoint (str): Target endpoint. payload (dict[str,
        Any]): Job payload.
    Returns:
        None: This function does not return a value.

    """
    with QUEUE_CONDITION:
        JOB_QUEUE.append(QueuedJob(run_id=run_id, endpoint=endpoint, payload=payload))
        QUEUE_CONDITION.notify()
    _ensure_dispatcher()


def _dispatch_loop() -> None:
    """
    Continuously dispatch queued jobs into isolated worker processes.

    Args: None.
    Returns: None; runs indefinitely and updates run state after process completion.
    """
    global CURRENT_PROCESS, CURRENT_RUN_ID

    while True:
        with QUEUE_CONDITION:
            while not JOB_QUEUE:
                QUEUE_CONDITION.wait()
            job = JOB_QUEUE.popleft()

        with SessionLocal() as session:
            run = session.get(RunRecord, job.run_id)
            if run is None or run.status == "cancelled":
                continue

        process = Process(
            target=_execute_run_process,
            args=(job.run_id, job.endpoint, job.payload),
            daemon=True,
        )
        with PROCESS_LOCK:
            CURRENT_PROCESS = process
            CURRENT_RUN_ID = job.run_id

        process.start()
        process.join()

        with PROCESS_LOCK:
            CURRENT_PROCESS = None
            CURRENT_RUN_ID = None

        with SessionLocal() as session:
            run = session.get(RunRecord, job.run_id)
            if run is None:
                continue
            if run.status == "running":
                run.status = "failed"
                run.progress_percent = 100.0
                run.progress_message = "Failed"
                run.completed_at = datetime.now(UTC)
                run.duration_seconds = _duration_seconds(
                    run.started_at, run.completed_at
                )
                run.error_message = UNEXPECTED_EXIT_MESSAGE
                session.add(run)
                session.commit()


def request_run_cancellation(run_id: int) -> str:
    """
    Cancel a queued or running run by ID.
    Args:
        run_id (int): Identifier of the run to cancel.
    Returns:
        str: Resulting run status, typically "cancelled", "running", or the existing status.

    """
    with QUEUE_CONDITION:
        for index, job in enumerate(JOB_QUEUE):
            if job.run_id == run_id:
                del JOB_QUEUE[index]
                _mark_cancelled(run_id, "Run was cancelled before execution started.")
                return "cancelled"

    with PROCESS_LOCK:
        active_process = CURRENT_PROCESS
        active_run_id = CURRENT_RUN_ID

    if (
        active_run_id == run_id
        and active_process is not None
        and active_process.is_alive()
    ):
        terminated = _terminate_process_tree(active_process)
        if terminated:
            _mark_cancelled(
                run_id, "Run was cancelled while execution was in progress."
            )
            return "cancelled"
        return "running"

    with SessionLocal() as session:
        run = session.get(RunRecord, run_id)
        if run is None:
            raise ValueError("Run not found.")
        if run.status in {"queued", "running"}:
            message = (
                "Run was cancelled while execution was in progress."
                if run.status == "running"
                else "Run was cancelled before execution started."
            )
            _mark_cancelled(run_id, message)
            return "cancelled"
        return run.status


def _execute_run_process(run_id: int, endpoint: str, payload: dict[str, Any]) -> None:
    """
    Execute a run in a new process session and persist lifecycle state.
    Args:
        run_id (int): Run record ID; endpoint (str): Endpoint to execute; payload (dict[str, Any]):
        Request payload.
    Returns:
        None: This function does not return a value.

    """
    os.setsid()
    started_at = datetime.now(UTC)

    with SessionLocal() as session:
        run = session.get(RunRecord, run_id)
        if run is None or run.status == "cancelled":
            return
        run.status = "running"
        run.progress_percent = 12.0
        run.progress_message = "Starting run"
        run.started_at = started_at
        session.add(run)
        session.commit()

    try:
        result = _execute_endpoint(
            endpoint,
            payload,
            progress_callback=lambda percent, message: _set_run_progress(
                run_id, percent, message
            ),
        )
        completed_at = datetime.now(UTC)

        def mark_completed(run: RunRecord) -> None:
            run.status = "completed"
            run.progress_percent = 100.0
            run.progress_message = "Completed"
            run.completed_at = completed_at
            run.duration_seconds = _duration_seconds(started_at, completed_at)
            run.result_payload = json.dumps(result.response, default=str, indent=2)
            run.summary_output = result.summary_output
            run.artifact_dir = result.artifact_dir
            run.log_path = result.log_path
            run.source_branch = result.source_branch
            run.published_branch = result.published_branch
            run.documentation_url = result.documentation_url
            run.metrics_files_analyzed = result.metrics_files_analyzed
            run.metrics_docstrings_generated = result.metrics_docstrings_generated
            run.metrics_skipped_files = result.metrics_skipped_files

        _update_run(run_id, mark_completed)
    except Exception as exc:
        completed_at = datetime.now(UTC)
        error_message = str(exc)

        def mark_failed(run: RunRecord) -> None:
            if run.status == "cancelled":
                return
            run.status = "failed"
            run.progress_percent = 100.0
            run.progress_message = "Failed"
            run.completed_at = completed_at
            run.duration_seconds = _duration_seconds(started_at, completed_at)
            run.error_message = error_message

        _update_run(run_id, mark_failed)


def _execute_endpoint(
    endpoint: str,
    payload: dict[str, Any],
    progress_callback=None,
) -> WorkflowRunResult:
    """
    Execute a queued workflow request for a supported endpoint.

    Args:
        endpoint (str): Endpoint path identifying the workflow to run.
        payload (dict[str, Any]): Request data used to build the endpoint-specific request model.
        progress_callback (Callable | None): Optional callback for workflow progress updates.

    Returns:
        WorkflowRunResult: Result produced by the selected workflow executor.

    """
    if endpoint == "/generate":
        return execute_generate_request(
            RepoRequest(**payload), progress_callback=progress_callback
        )
    if endpoint == "/publish-pages":
        return execute_publish_request(
            PublishPagesRequest(**payload), progress_callback=progress_callback
        )
    if endpoint == "/suggest-python-docstrings-pr":
        return execute_docstring_pr_request(
            DocstringPullRequestRequest(**payload), progress_callback=progress_callback
        )
    if endpoint == "/generate-architecture-docs":
        return execute_architecture_generation_request(
            ArchitectureGenerationRequest(**payload),
            progress_callback=progress_callback,
        )
    if endpoint == "/approve-architecture-docs":
        return execute_architecture_approval_request(
            ArchitectureApprovalRequest(**payload), progress_callback=progress_callback
        )
    raise ValueError(f"Unsupported endpoint for queued execution: {endpoint}")
