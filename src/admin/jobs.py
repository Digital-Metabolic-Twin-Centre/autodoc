import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Callable

from admin.database import SessionLocal
from admin.models import RunRecord
from services.workflow_service import WorkflowRunResult

EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autodoc-admin")


def _update_run(run_id: int, updater: Callable[[RunRecord], None]) -> None:
    with SessionLocal() as session:
        run = session.get(RunRecord, run_id)
        if run is None:
            return
        updater(run)
        session.add(run)
        session.commit()


def enqueue_run(run_id: int, runner: Callable[[], WorkflowRunResult]) -> None:
    EXECUTOR.submit(_execute_run, run_id, runner)


def _execute_run(run_id: int, runner: Callable[[], WorkflowRunResult]) -> None:
    started_at = datetime.now(UTC)

    def mark_running(run: RunRecord) -> None:
        run.status = "running"
        run.started_at = started_at

    _update_run(run_id, mark_running)

    try:
        result = runner()
        completed_at = datetime.now(UTC)

        def mark_completed(run: RunRecord) -> None:
            run.status = "completed"
            run.completed_at = completed_at
            run.duration_seconds = (completed_at - started_at).total_seconds()
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
            run.status = "failed"
            run.completed_at = completed_at
            run.duration_seconds = (completed_at - started_at).total_seconds()
            run.error_message = error_message

        _update_run(run_id, mark_failed)
