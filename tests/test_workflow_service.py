import pytest

from models.repo_request import PublishPagesRequest, RepoRequest
from services.workflow_service import (
    _github_pages_url,
    _notify_progress,
    _summarize_generate,
    execute_generate_request,
    execute_publish_request,
)


def test_notify_progress_invokes_callback_when_present():
    calls = []

    def callback(percent, message):
        calls.append((percent, message))

    _notify_progress(callback, 42.0, "halfway")

    assert calls == [(42.0, "halfway")]


def test_notify_progress_no_op_when_callback_missing():
    _notify_progress(None, 42.0, "halfway")


def test_summarize_generate_counts_docstrings_for_files_with_generated_content():
    docstring_analysis = [
        {
            "docstring_analysis": [
                {"generated_docstring": "text"},
                {"generated_docstring": None},
            ]
        },
        {"docstring_analysis": [{"generated_docstring": None}]},
    ]

    files_analyzed, docstrings_generated, skipped_files = _summarize_generate(docstring_analysis)

    assert files_analyzed == 2
    assert docstrings_generated == 1
    assert skipped_files == 1


def test_github_pages_url_returns_none_for_path_without_owner():
    assert _github_pages_url("justname") is None


def test_execute_generate_request_raises_value_error_for_missing_token():
    req = RepoRequest(provider="github", repo_url="octo/example", token="", branch="main")

    with pytest.raises(ValueError):
        execute_generate_request(req)


def test_execute_generate_request_raises_permission_error_when_sphinx_setup_fails(monkeypatch):
    req = RepoRequest(provider="github", repo_url="octo/example", token="tok", branch="main")
    monkeypatch.setattr(
        "services.workflow_service.analyse_repo",
        lambda *args, **kwargs: ("/tmp/octo-example/analysis.json", [], []),
    )
    monkeypatch.setattr("services.workflow_service.create_sphinx_setup", lambda *args, **kwargs: False)

    with pytest.raises(PermissionError):
        execute_generate_request(req)


def test_execute_publish_request_raises_permission_error_when_publish_fails(monkeypatch):
    req = PublishPagesRequest(repo_url="octo/example", token="tok", branch="main")
    monkeypatch.setattr("services.workflow_service.publish_github_pages", lambda *args, **kwargs: False)

    with pytest.raises(PermissionError):
        execute_publish_request(req)
