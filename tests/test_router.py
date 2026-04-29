from fastapi.testclient import TestClient

from main import app
from services.doc_services import RepoAnalysisError
from services.sphinx_services import (
    PublishPagesError,
    _apply_autoapi_runtime_settings,
    _classify_autoapi_file,
    _collect_prebuild_autoapi_ignores,
    _extract_autoapi_module_names,
    _extract_module_name_from_autoapi_path,
    _find_autoapi_skip_candidates,
    _module_names_to_ignore_patterns,
    _run_sphinx_build_with_autoapi_filters,
    _to_autoapi_ignore_pattern,
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
        lambda provider, repo_url, token, branch, target_folders, model, reuse_doc: (
            captured.update({"model": model, "reuse_doc": reuse_doc}) or "analysis.csv",
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
    assert captured["reuse_doc"] is False


def test_generate_endpoint_returns_not_found_when_analysis_is_empty(monkeypatch):
    def fail_analysis(provider, repo_url, token, branch, target_folders, model, reuse_doc):
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

    def fake_analyze_repo(provider, repo_url, token, branch, target_folders, model, reuse_doc):
        captured["model"] = model
        captured["reuse_doc"] = reuse_doc
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
    assert captured["reuse_doc"] is False


def test_generate_endpoint_uses_reuse_doc_flag(monkeypatch):
    captured = {}

    def fake_analyze_repo(provider, repo_url, token, branch, target_folders, model, reuse_doc):
        captured["reuse_doc"] = reuse_doc
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
            "reuse_doc": True,
        },
    )

    assert response.status_code == 200
    assert captured["reuse_doc"] is True


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


def test_extract_autoapi_module_names_reads_modules_from_sphinx_error():
    build_output = (
        "ExtensionError: ... module 'autoapi_include.job_views'\n"
        "ExtensionError: ... module 'settings_docker'\n"
    )

    modules = _extract_autoapi_module_names(build_output)

    assert modules == ["autoapi_include.job_views", "settings_docker"]


def test_extract_autoapi_module_names_reads_modules_from_docutils_errors():
    build_output = (
        "/tmp/repo/docs/source/autoapi/urls_v1/index.rst:18: ERROR: Unexpected indentation.\n"
        "/tmp/repo/docs/source/autoapi/tools/gpu_embed_service/index.rst:4: WARNING: x\n"
    )

    modules = _extract_autoapi_module_names(build_output)

    assert modules == ["urls_v1", "tools.gpu_embed_service"]


def test_find_autoapi_skip_candidates_matches_module_leaf(tmp_path):
    autoapi_dir = tmp_path / "autoapi_include"
    (autoapi_dir / "api" / "views").mkdir(parents=True)
    (autoapi_dir / "webKinPred").mkdir(parents=True)
    (autoapi_dir / "api" / "views" / "job_views.py").write_text("", encoding="utf-8")
    (autoapi_dir / "webKinPred" / "settings_docker.py").write_text("", encoding="utf-8")

    job_view_matches = _find_autoapi_skip_candidates(str(tmp_path), "autoapi_include.job_views")
    settings_matches = _find_autoapi_skip_candidates(str(tmp_path), "settings_docker")

    assert [path.relative_to(tmp_path).as_posix() for path in job_view_matches] == [
        "autoapi_include/api/views/job_views.py"
    ]
    assert [path.relative_to(tmp_path).as_posix() for path in settings_matches] == [
        "autoapi_include/webKinPred/settings_docker.py"
    ]


def test_find_autoapi_skip_candidates_prefers_full_module_path(tmp_path):
    autoapi_dir = tmp_path / "autoapi_include"
    (autoapi_dir / "api").mkdir(parents=True)
    (autoapi_dir / "api" / "urls_v1.py").write_text("", encoding="utf-8")

    matches = _find_autoapi_skip_candidates(str(tmp_path), "api.urls_v1")

    assert [path.relative_to(tmp_path).as_posix() for path in matches] == [
        "autoapi_include/api/urls_v1.py"
    ]


def test_extract_module_name_from_autoapi_path_handles_package_init(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    module_path = autoapi_root / "api" / "pkg" / "__init__.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("", encoding="utf-8")

    assert _extract_module_name_from_autoapi_path(autoapi_root, module_path) == "api.pkg"


def test_classify_autoapi_file_skips_by_risky_name_pattern(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    file_path = autoapi_root / "api" / "urls_v1.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("def endpoint():\n    return 1\n", encoding="utf-8")

    should_include, reason = _classify_autoapi_file(autoapi_root, file_path)

    assert should_include is False
    assert reason.startswith("path-pattern:")


def test_classify_autoapi_file_skips_import_star(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    file_path = autoapi_root / "api" / "module.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(
        "from package.sub import *\n\n"
        "def alpha():\n"
        "    return 1\n"
        "def beta():\n"
        "    return 2\n"
        "def gamma():\n"
        "    return 3\n",
        encoding="utf-8",
    )

    should_include, reason = _classify_autoapi_file(autoapi_root, file_path)

    assert should_include is False
    assert reason == "import-star"


def test_collect_prebuild_autoapi_ignores_tracks_skipped_files(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    included_file = autoapi_root / "api" / "service.py"
    skipped_file = autoapi_root / "api" / "views.py"
    included_file.parent.mkdir(parents=True)
    included_file.write_text(
        (
            "import os\n"
            "import json\n\n"
            "def alpha():\n    return os.name\n"
            "def beta():\n    return 2\n"
            "class Handler:\n    pass\n"
        ),
        encoding="utf-8",
    )
    skipped_file.write_text(
        "def endpoint():\n    return 1\n"
        "def secondary():\n    return 2\n"
        "def tertiary():\n    return 3\n",
        encoding="utf-8",
    )

    ignore_patterns, skipped = _collect_prebuild_autoapi_ignores(str(tmp_path))

    assert "*/api/views.py" in ignore_patterns
    assert "api/service.py" not in ignore_patterns
    assert any(item["reason"].startswith("path-pattern:") for item in skipped)


def test_module_names_to_ignore_patterns_maps_module_failures(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    module_path = autoapi_root / "api" / "broken.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("def ok():\n    return 1\n", encoding="utf-8")

    ignore_patterns, skipped = _module_names_to_ignore_patterns(str(tmp_path), ["api.broken"])

    assert ignore_patterns == ["*/api/broken.py"]
    assert skipped[0]["reason"] == "fallback-module-failure"


def test_apply_autoapi_runtime_settings_writes_ignore_and_suppressions(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("project = 'X'\n", encoding="utf-8")

    _apply_autoapi_runtime_settings(str(conf_path), ["api/broken.py", "api/broken.py"])

    conf_text = conf_path.read_text(encoding="utf-8")
    assert "AUTODOC AUTOAPI RUNTIME SETTINGS START" in conf_text
    assert "autoapi_ignore = [" in conf_text
    assert "'api/broken.py'" in conf_text
    assert "suppress_warnings = [" in conf_text
    assert "'autoapi.python_import_resolution'" in conf_text


def test_to_autoapi_ignore_pattern_adds_prefix_wildcard():
    assert _to_autoapi_ignore_pattern("api/views.py") == "*/api/views.py"


def test_classify_autoapi_file_skips_settings_module_name(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    file_path = autoapi_root / "webKinPred" / "settings_docker.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("from ..x import y\n", encoding="utf-8")

    should_include, reason = _classify_autoapi_file(autoapi_root, file_path)

    assert should_include is False
    assert reason.startswith("path-pattern:")


def test_run_sphinx_build_with_autoapi_filters_uses_single_fallback_retry(tmp_path, monkeypatch):
    autoapi_root = tmp_path / "autoapi_include"
    conf_path = tmp_path / "docs" / "source" / "conf.py"
    build_path = tmp_path / "docs" / "build" / "html"
    broken_module = autoapi_root / "api" / "broken.py"
    good_module = autoapi_root / "api" / "service.py"
    broken_module.parent.mkdir(parents=True)
    conf_path.parent.mkdir(parents=True)
    build_path.mkdir(parents=True)
    broken_module.write_text(
        "import json\n\n"
        "def broken():\n    return json.loads('{}')\n"
        "def x():\n    return 1\n"
        "def y():\n    return 2\n"
        "def z():\n    return 3\n",
        encoding="utf-8",
    )
    good_module.write_text(
        "import os\n\n"
        "def ok():\n    return os.name\n"
        "def x():\n    return 1\n"
        "def y():\n    return 2\n"
        "class A:\n    pass\n",
        encoding="utf-8",
    )
    conf_path.write_text("project = 'X'\n", encoding="utf-8")

    calls = {"count": 0}

    def fake_run(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return type(
                "Result",
                (),
                {
                    "returncode": 1,
                    "stderr": "/tmp/docs/source/autoapi/api/broken/index.rst:10: ERROR: bad",
                    "stdout": "",
                },
            )()
        return type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("services.sphinx_services.subprocess.run", fake_run)
    monkeypatch.setattr("services.sphinx_services.get_run_log_dir", lambda: str(tmp_path))

    result = _run_sphinx_build_with_autoapi_filters(str(tmp_path), str(conf_path))

    assert result.returncode == 0
    assert calls["count"] == 2
    report_text = (tmp_path / "skipped_autoapi_files.txt").read_text(encoding="utf-8")
    assert "fallback-module-failure" in report_text


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
