import pytest

from utils.git_utils import (
    GitHubApiError,
    RepositoryAccessError,
    create_directory_and_add_files,
    configure_github_pages,
    create_github_pull_request,
    extract_repo_path,
    fetch_repo_tree,
    fetch_content_bytes_from_github,
    fetch_content_from_github,
    should_ignore,
)
from utils.update_conf_content import _append_extension


def test_extract_repo_path_strips_protocol_and_git_suffix():
    assert extract_repo_path("https://github.com/example/project.git") == "example/project"


def test_extract_repo_path_accepts_short_form():
    assert extract_repo_path("group/project") == "group/project"


def test_should_ignore_matches_file_and_directory_patterns():
    patterns = ["node_modules", "*.log", "dist/"]

    assert should_ignore("node_modules", patterns) is True
    assert should_ignore("server.log", patterns) is True
    assert should_ignore("dist", patterns) is True
    assert should_ignore("src", patterns) is False


class DummyResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text or self._payload.get("message", "request failed"))


def test_fetch_repo_tree_reports_missing_branch(monkeypatch):
    def fake_get(url, headers, params, timeout):
        return DummyResponse(404, {"message": "No commit found for the ref missing-branch"})

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    with pytest.raises(RepositoryAccessError, match="Branch 'missing-branch' was not found"):
        fetch_repo_tree("example/project", "secret", branch="missing-branch", provider="github")


def test_fetch_repo_tree_reports_inaccessible_repo(monkeypatch):
    def fake_get(url, headers, params, timeout):
        return DummyResponse(404, {"message": "Not Found"})

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    with pytest.raises(RepositoryAccessError, match="was not found or is not accessible"):
        fetch_repo_tree("example/project", "secret", branch="main", provider="github")


def test_fetch_content_from_github_preserves_empty_file(monkeypatch):
    monkeypatch.setattr("utils.git_utils.requests.get", lambda *args, **kwargs: DummyResponse(200, text=""))

    assert fetch_content_from_github("example/project", "main", "__init__.py", "secret") == ""


def test_fetch_content_bytes_from_github_preserves_empty_file(monkeypatch):
    response = DummyResponse(200, text="")
    response.content = b""
    monkeypatch.setattr("utils.git_utils.requests.get", lambda *args, **kwargs: response)

    assert fetch_content_bytes_from_github("example/project", "main", "__init__.py", "secret") == b""


def test_create_directory_and_add_files_preserves_nested_paths_for_github(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/git/refs/heads/main"):
            return DummyResponse(200, {"object": {"sha": "commitsha"}})
        if url.endswith("/git/commits/commitsha"):
            return DummyResponse(200, {"tree": {"sha": "treesha"}})
        raise AssertionError(f"Unexpected GET {url}")

    captured = {}

    def fake_post(url, headers=None, json=None):
        if url.endswith("/git/trees"):
            captured["tree"] = json["tree"]
            return DummyResponse(201, {"sha": "newtree"})
        if url.endswith("/git/commits"):
            return DummyResponse(201, {"sha": "newcommit"})
        raise AssertionError(f"Unexpected POST {url}")

    def fake_patch(url, headers=None, json=None):
        return DummyResponse(200, {})

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)
    monkeypatch.setattr("utils.git_utils.requests.patch", fake_patch)
    monkeypatch.setattr(
        "utils.git_utils.list_github_tree",
        lambda repo_url, branch, token, recursive=True: [],
    )
    monkeypatch.setattr(
        "utils.git_utils.fetch_content_from_github",
        lambda repo_url, branch, file_path, token: "" if file_path.endswith("__init__.py") else "x = 1\n",
    )

    result = create_directory_and_add_files(
        "example/project",
        "autoapi_include",
        ["pkg/__init__.py", "pkg/job_views.py"],
        "main",
        "secret",
        "github",
    )

    assert result is True
    assert {item["path"] for item in captured["tree"]} == {
        "autoapi_include/pkg/__init__.py",
        "autoapi_include/pkg/job_views.py",
    }


def test_create_directory_and_add_files_removes_stale_flattened_github_files(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/git/refs/heads/main"):
            return DummyResponse(200, {"object": {"sha": "commitsha"}})
        if url.endswith("/git/commits/commitsha"):
            return DummyResponse(200, {"tree": {"sha": "treesha"}})
        raise AssertionError(f"Unexpected GET {url}")

    captured = {}

    def fake_post(url, headers=None, json=None):
        if url.endswith("/git/trees"):
            captured["tree"] = json["tree"]
            return DummyResponse(201, {"sha": "newtree"})
        if url.endswith("/git/commits"):
            return DummyResponse(201, {"sha": "newcommit"})
        raise AssertionError(f"Unexpected POST {url}")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)
    monkeypatch.setattr("utils.git_utils.requests.patch", lambda *args, **kwargs: DummyResponse(200, {}))
    monkeypatch.setattr(
        "utils.git_utils.fetch_content_from_github",
        lambda repo_url, branch, file_path, token: "x = 1\n",
    )
    monkeypatch.setattr(
        "utils.git_utils.list_github_tree",
        lambda repo_url, branch, token, recursive=True: [
            {"type": "blob", "path": "autoapi_include/job_views.py"},
            {"type": "blob", "path": "autoapi_include/pkg/old.py"},
            {"type": "blob", "path": "README.md"},
        ],
    )

    result = create_directory_and_add_files(
        "example/project",
        "autoapi_include",
        ["pkg/job_views.py"],
        "main",
        "secret",
        "github",
    )

    assert result is True
    assert {"path": "autoapi_include/job_views.py", "mode": "100644", "type": "blob", "sha": None} in captured["tree"]
    assert {"path": "autoapi_include/pkg/old.py", "mode": "100644", "type": "blob", "sha": None} in captured["tree"]


def test_configure_github_pages_skips_update_when_source_is_already_correct(monkeypatch):
    calls = []

    def fake_get(url, headers):
        calls.append(("get", url, headers))
        return DummyResponse(200, {"source": {"branch": "gh-pages", "path": "/"}})

    def fake_put(url, headers, json):
        calls.append(("put", url, headers, json))
        return DummyResponse(403, text="should not update")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.put", fake_put)

    assert configure_github_pages("example/project", "gh-pages", "secret") is True
    assert [call[0] for call in calls] == ["get"]


def test_configure_github_pages_updates_when_source_differs(monkeypatch):
    calls = []

    def fake_get(url, headers):
        calls.append(("get", url, headers))
        return DummyResponse(200, {"source": {"branch": "main", "path": "/"}})

    def fake_put(url, headers, json):
        calls.append(("put", url, headers, json))
        return DummyResponse(204)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.put", fake_put)

    assert configure_github_pages("example/project", "gh-pages", "secret") is True
    assert [call[0] for call in calls] == ["get", "put"]


def test_append_extension_handles_empty_and_existing_extension_lists():
    assert _append_extension("[]", "autoapi.extension") == "['autoapi.extension']"
    assert (
        _append_extension("['sphinx.ext.autodoc']", "autoapi.extension")
        == "['sphinx.ext.autodoc', 'autoapi.extension']"
    )


def test_create_github_pull_request_raises_permission_error(monkeypatch):
    def fake_post(url, headers, json):
        return DummyResponse(
            403,
            text='{"message":"Resource not accessible by personal access token"}',
        )

    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)

    with pytest.raises(GitHubApiError, match="Pull requests: Read and write"):
        create_github_pull_request(
            "example/project",
            "autodocs-docstring-suggestions",
            "main",
            "Add suggested Python docstrings",
            "Body",
            "secret",
        )
