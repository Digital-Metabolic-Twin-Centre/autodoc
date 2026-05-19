import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing import Process
from threading import Condition, Lock, Thread
from typing import Any

from admin.database import SessionLocal
from admin.models import RunRecord
from models.repo_request import DocstringPullRequestRequest, PublishPagesRequest, RepoRequest
from services.workflow_service import (
    WorkflowRunResult,
    execute_docstring_pr_request,
    execute_generate_request,
    execute_publish_request,
)


@dataclass
class QueuedJob:
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


def _update_run(run_id: int, updater) -> None:
    with SessionLocal() as session:
        run = session.get(RunRecord, run_id)
        if run is None:
            return
        updater(run)
        session.add(run)
        session.commit()


def _duration_seconds(
    started_at: datetime | None,
    finished_at: datetime | None,
) -> float:
    if started_at is None or finished_at is None:
        return 0.0
    normalized_started_at = started_at
    normalized_finished_at = finished_at
    if normalized_started_at.tzinfo is None and normalized_finished_at.tzinfo is not None:
        normalized_finished_at = normalized_finished_at.replace(tzinfo=None)
    elif normalized_started_at.tzinfo is not None and normalized_finished_at.tzinfo is None:
        normalized_started_at = normalized_started_at.replace(tzinfo=None)
    return (normalized_finished_at - normalized_started_at).total_seconds()


def _mark_cancelled(run_id: int, message: str) -> None:
    cancelled_at = datetime.now(UTC)

    def apply(run: RunRecord) -> None:
        run.status = "cancelled"
        run.completed_at = cancelled_at
        run.duration_seconds = _duration_seconds(run.started_at, cancelled_at)
        run.error_message = message

    _update_run(run_id, apply)


def _ensure_dispatcher() -> None:
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
    with QUEUE_CONDITION:
        JOB_QUEUE.append(QueuedJob(run_id=run_id, endpoint=endpoint, payload=payload))
        QUEUE_CONDITION.notify()
    _ensure_dispatcher()


def _dispatch_loop() -> None:
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
                run.completed_at = datetime.now(UTC)
                run.duration_seconds = _duration_seconds(run.started_at, run.completed_at)
                run.error_message = UNEXPECTED_EXIT_MESSAGE
                session.add(run)
                session.commit()


def request_run_cancellation(run_id: int) -> str:
    with QUEUE_CONDITION:
        for index, job in enumerate(JOB_QUEUE):
            if job.run_id == run_id:
                del JOB_QUEUE[index]
                _mark_cancelled(run_id, "Run was cancelled before execution started.")
                return "cancelled"

    with PROCESS_LOCK:
        active_process = CURRENT_PROCESS
        active_run_id = CURRENT_RUN_ID

    if active_run_id == run_id and active_process is not None and active_process.is_alive():
        active_process.terminate()
        active_process.join(timeout=10)
        _mark_cancelled(run_id, "Run was cancelled while execution was in progress.")
        return "cancelled"

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
    started_at = datetime.now(UTC)

    with SessionLocal() as session:
        run = session.get(RunRecord, run_id)
        if run is None or run.status == "cancelled":
            return
        run.status = "running"
        run.started_at = started_at
        session.add(run)
        session.commit()

    try:
        result = _execute_endpoint(endpoint, payload)
        completed_at = datetime.now(UTC)

        def mark_completed(run: RunRecord) -> None:
            run.status = "completed"
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
            run.completed_at = completed_at
            run.duration_seconds = _duration_seconds(started_at, completed_at)
            run.error_message = error_message

        _update_run(run_id, mark_failed)


def _execute_endpoint(endpoint: str, payload: dict[str, Any]) -> WorkflowRunResult:
    if endpoint == "/generate":
        return execute_generate_request(RepoRequest(**payload))
    if endpoint == "/publish-pages":
        return execute_publish_request(PublishPagesRequest(**payload))
    if endpoint == "/suggest-python-docstrings-pr":
        return execute_docstring_pr_request(DocstringPullRequestRequest(**payload))
    raise ValueError(f"Unsupported endpoint for queued execution: {endpoint}")
