import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

from admin.models import RepositoryConfig
from admin.router import (
    _build_architecture_approval_request,
    _build_architecture_generation_request,
    _read_artifact_preview,
    _run_log_entries,
    trigger_architecture_approve,
)


def test_run_log_entries_prioritize_key_logs(tmp_path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "app.log").write_text("app\n", encoding="utf-8")
    (artifact_dir / "sphinx_build.log").write_text("sphinx\n", encoding="utf-8")
    (artifact_dir / "skipped_autoapi_files.txt").write_text("skip\n", encoding="utf-8")
    (artifact_dir / "notes.json").write_text("{}", encoding="utf-8")

    run = SimpleNamespace(
        artifact_dir=str(artifact_dir),
        log_path=str(artifact_dir / "app.log"),
    )

    entries = _run_log_entries(run)

    assert [entry["name"] for entry in entries] == [
        "app.log",
        "sphinx_build.log",
        "skipped_autoapi_files.txt",
    ]


def test_read_artifact_preview_truncates_large_files(tmp_path):
    artifact_path = tmp_path / "sphinx_build.log"
    artifact_path.write_text("x" * 20, encoding="utf-8")

    content, truncated = _read_artifact_preview(artifact_path, max_chars=10)

    assert content == "x" * 10
    assert truncated is True


def test_architecture_request_builders_use_repository_defaults(monkeypatch):
    monkeypatch.setattr("admin.router.decrypt_token", lambda token: "secret")

    repository = RepositoryConfig(
        name="Example Repo",
        provider="github",
        repo_url="example/project",
        repo_path="example/project",
        default_branch="main",
        target_folders_json='["src"]',
        preferred_model="gpt-4o-mini",
        reuse_doc=True,
        docstring_threshold=0.5,
        low_content_min_lines=4,
        encrypted_token="encrypted-token",
        token_last4="cret",
    )

    generation = _build_architecture_generation_request(repository, output_path="docs/project/architecture.rst")
    approval = _build_architecture_approval_request(
        repository,
        draft_id="arch-1",
        overwrite_existing=True,
    )

    assert generation.output_path == "docs/project/architecture.rst"
    assert generation.branch == "main"
    assert approval.draft_id == "arch-1"
    assert approval.overwrite_existing is True


def test_trigger_architecture_approve_queues_reviewed_draft(monkeypatch):
    repository = RepositoryConfig(
        name="Example Repo",
        provider="github",
        repo_url="example/project",
        repo_path="example/project",
        default_branch="main",
        target_folders_json='["src"]',
        preferred_model="gpt-4o-mini",
        reuse_doc=True,
        docstring_threshold=0.5,
        low_content_min_lines=4,
        encrypted_token="encrypted-token",
        token_last4="cret",
    )
    fake_session = SimpleNamespace(get=lambda model, repository_id: repository)
    captured = {}

    monkeypatch.setattr("admin.router.decrypt_token", lambda token: "secret")
    monkeypatch.setattr("admin.router.SessionLocal", lambda: nullcontext(fake_session))
    monkeypatch.setattr("admin.router._create_run_record", lambda *args, **kwargs: captured.setdefault("run_id", 99))
    monkeypatch.setattr(
        "admin.router.enqueue_run",
        lambda run_id, endpoint, payload: captured.update({"endpoint": endpoint}),
    )
    monkeypatch.setattr("admin.router._redirect", lambda url, request: url)

    response = asyncio.run(
        trigger_architecture_approve(
            request=SimpleNamespace(),
            admin_user="admin",
            repository_id=1,
            draft_id="arch-1",
            branch="main",
            output_path="docs/project/architecture.rst",
            overwrite_existing=True,
            approval_note="approved",
        )
    )

    assert response == "/admin/runs/99"
    assert captured["endpoint"] == "/approve-architecture-docs"
