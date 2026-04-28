from fastapi.testclient import TestClient

from main import app
from services.doc_services import RepoAnalysisError
from services.sphinx_services import (
    PublishPagesError,
    _ensure_api_index,
    _ensure_sphinx_project_name,
    _project_name_from_repo_path,
)

client = TestClient(app)


def test_root_endpoint_returns_welcome_message():
    response = client.get("/")

    assert response.status_code == 200
    assert "Visit /docs" in response.json()["message"]


def test_generate_endpoint_returns_success_when_services_succeed(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "router.router.analyze_repo",
        lambda provider, repo_url, token, branch, target_folders, model: (
            captured.update({"model": model}) or "analysis.csv",
            [{"file_name": "a.py"}],
        ),
    )
    monkeypatch.setattr(
        "router.router.create_sphinx_setup",
        lambda provider, repo_url, token, branch, analysis_file: True,
    )

    response = client.post(
        "/generate",
        json={
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "branch": "main",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert captured["model"] == "gpt-4o-mini"


def test_generate_endpoint_returns_not_found_when_analysis_is_empty(monkeypatch):
    def fail_analysis(provider, repo_url, token, branch, target_folders, model):
        raise RepoAnalysisError(
            "Repository was reachable, but no supported source files were found.",
            status_code=404,
        )

    monkeypatch.setattr("router.router.analyze_repo", fail_analysis)

    response = client.post(
        "/generate",
        json={
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "branch": "main",
        },
    )

    assert response.status_code == 404
    assert "no supported source files" in response.json()["detail"].lower()


def test_generate_endpoint_uses_provided_model(monkeypatch):
    captured = {}

    def fake_analyze_repo(provider, repo_url, token, branch, target_folders, model):
        captured["model"] = model
        return "analysis.csv", [{"file_name": "a.py"}]

    monkeypatch.setattr("router.router.analyze_repo", fake_analyze_repo)
    monkeypatch.setattr(
        "router.router.create_sphinx_setup",
        lambda provider, repo_url, token, branch, analysis_file: True,
    )

    response = client.post(
        "/generate",
        json={
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "branch": "main",
            "model": "gpt-4.1-mini",
        },
    )

    assert response.status_code == 200
    assert captured["model"] == "gpt-4.1-mini"


def test_publish_pages_returns_specific_publish_error(monkeypatch):
    def fail_publish(repo_url, branch, token):
        raise PublishPagesError("GitHub Pages configuration failed.")

    monkeypatch.setattr("router.router.publish_github_pages", fail_publish)

    response = client.post(
        "/publish-pages",
        json={
            "repo_url": "example/project",
            "token": "secret",
            "branch": "docs-review",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "GitHub Pages configuration failed."


def test_project_name_from_repo_path_humanizes_repo_name():
    assert (
        _project_name_from_repo_path("Digital-Metabolic-Twin-Centre/test_documentation_sphinx_site")
        == "Test Documentation Sphinx Site"
    )


def test_ensure_api_index_replaces_sphinx_quickstart_homepage(tmp_path):
    index_path = tmp_path / "docs" / "source" / "index.rst"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        "Welcome to Project_Name's documentation!\n"
        "========================================\n\n"
        "Add your content using ``reStructuredText`` syntax.\n",
        encoding="utf-8",
    )

    _ensure_api_index(str(index_path), "Example Project")

    index_text = index_path.read_text(encoding="utf-8")
    assert "Example Project" in index_text
    assert "autoapi/index" in index_text
    assert "Add your content" not in index_text


def test_ensure_sphinx_project_name_replaces_placeholder(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text('project = "Project_Name"\nextensions = []\n', encoding="utf-8")

    _ensure_sphinx_project_name(str(conf_path), "Example Project")

    assert 'project = "Example Project"' in conf_path.read_text(encoding="utf-8")


def test_suggest_python_docstrings_pr_returns_success(monkeypatch):
    captured = {}

    def fake_create_pr(
        provider, repo_url, token, base_branch, suggestion_branch, title, max_docstrings
    ):
        captured["suggestion_branch"] = suggestion_branch
        return {
            "status": "success",
            "pull_request_url": "https://github.com/example/project/pull/1",
        }

    monkeypatch.setattr(
        "router.router.create_python_docstring_pull_request",
        fake_create_pr,
    )
    monkeypatch.setattr(
        "router.router._default_docstring_suggestion_branch",
        lambda: "autodocs-docstring-suggestions-20260424-1430",
    )

    response = client.post(
        "/suggest-python-docstrings-pr",
        json={
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "base_branch": "main",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert (
        captured["suggestion_branch"]
        == "autodocs-docstring-suggestions-20260424-1430"
    )


def test_suggest_python_docstrings_pr_uses_provided_suggestion_branch(monkeypatch):
    captured = {}

    def fake_create_pr(
        provider, repo_url, token, base_branch, suggestion_branch, title, max_docstrings
    ):
        captured["suggestion_branch"] = suggestion_branch
        return {
            "status": "success",
            "pull_request_url": "https://github.com/example/project/pull/1",
        }

    monkeypatch.setattr(
        "router.router.create_python_docstring_pull_request",
        fake_create_pr,
    )

    response = client.post(
        "/suggest-python-docstrings-pr",
        json={
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "base_branch": "main",
            "suggestion_branch": "autodocs/custom-branch",
        },
    )

    assert response.status_code == 200
    assert captured["suggestion_branch"] == "autodocs/custom-branch"


def test_suggest_python_docstrings_pr_requires_base_branch():
    response = client.post(
        "/suggest-python-docstrings-pr",
        json={
            "provider": "github",
            "repo_url": "example/project",
            "token": "secret",
            "base_branch": "",
        },
    )

    assert response.status_code == 400
