import pytest

from utils.git_utils import (
    GitHubApiError,
    RepositoryAccessError,
    configure_github_pages,
    create_a_file,
    create_directory_and_add_files,
    create_github_blob,
    create_github_pull_request,
    download_github_branch_snapshot,
    ensure_github_branch,
    extract_repo_path,
    fetch_content_bytes_from_github,
    fetch_content_from_github,
    fetch_content_from_gitlab,
    fetch_repo_tree,
    list_github_pull_request_files,
    list_github_tree,
    list_open_github_pull_requests,
    publish_local_directory_to_github_branch,
    request_github_pages_build,
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
        self.content = b""  # Default empty bytes

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text or self._payload.get("message", "request failed"))


def test_fetch_repo_tree_reports_missing_branch(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "git clone", stderr=b"fatal: Remote branch missing-branch not found")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RepositoryAccessError, match="not found or is not accessible"):
        fetch_repo_tree("example/project", "secret", branch="missing-branch", provider="github")


def test_fetch_repo_tree_reports_inaccessible_repo(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, "git clone", stderr=b"fatal: Authentication failed for 'https://github.com/example/project.git/'"
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RepositoryAccessError, match="Authentication failed"):
        fetch_repo_tree("example/project", "secret", branch="main", provider="github")


def test_fetch_repo_tree_redacts_token_embedded_in_clone_error(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            "git clone",
            stderr=(
                b"error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403 "
                b"for 'https://x-access-token:ghp_abcdefghijklmnopqrstuvwxyz123456@github.com/example/project.git/'"
            ),
        )

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RepositoryAccessError) as exc_info:
        fetch_repo_tree("example/project", "secret", branch="main", provider="github")

    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in str(exc_info.value)
    assert "https://***:***@github.com" in str(exc_info.value)


def test_fetch_repo_tree_uses_partial_single_branch_clone_with_configurable_timeout(monkeypatch):
    import subprocess

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs["timeout"]
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setenv("AUTODOC_GIT_CLONE_TIMEOUT", "2400")
    monkeypatch.setattr("subprocess.run", fake_run)

    assert fetch_repo_tree("example/project", "secret", branch="main", provider="github") == []

    assert captured["command"][:7] == [
        "git",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--filter=blob:none",
        "--branch",
    ]
    assert captured["command"][7] == "main"
    assert captured["timeout"] == 2400
    assert captured["env"]["GIT_LFS_SKIP_SMUDGE"] == "1"


def test_fetch_repo_tree_clone_timeout_message_mentions_large_repo_option(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("git clone", timeout=2400)

    monkeypatch.setenv("AUTODOC_GIT_CLONE_TIMEOUT", "2400")
    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(RepositoryAccessError, match="AUTODOC_GIT_CLONE_TIMEOUT"):
        fetch_repo_tree("example/project", "secret", branch="main", provider="github")


def test_fetch_content_from_github_preserves_empty_file(monkeypatch):
    monkeypatch.setattr("utils.git_utils.requests.get", lambda *args, **kwargs: DummyResponse(200, text=""))

    assert fetch_content_from_github("example/project", "main", "__init__.py", "secret") == ""


def test_fetch_content_bytes_from_github_preserves_empty_file(monkeypatch):
    response = DummyResponse(200, text="")
    response.content = b""
    monkeypatch.setattr("utils.git_utils.requests.get", lambda *args, **kwargs: response)

    assert fetch_content_bytes_from_github("example/project", "main", "__init__.py", "secret") == b""


def test_download_github_branch_snapshot_prefers_clone(monkeypatch, tmp_path):
    from contextlib import contextmanager

    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()
    (clone_dir / "api").mkdir()
    (clone_dir / "api" / "tasks.py").write_text("print('ok')\n", encoding="utf-8")
    (clone_dir / ".git").mkdir()
    destination_dir = tmp_path / "snapshot"
    destination_dir.mkdir()

    @contextmanager
    def fake_clone_repository(repo_url, token, branch, provider):
        assert (repo_url, token, branch, provider) == ("example/project", "secret", "main", "github")
        yield str(clone_dir)

    monkeypatch.setattr("utils.git_utils.clone_repository", fake_clone_repository)
    monkeypatch.setattr(
        "utils.git_utils.fetch_content_bytes_from_github",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("GitHub byte fetch should not be called")),
    )

    assert download_github_branch_snapshot("example/project", "main", "secret", str(destination_dir)) is True
    assert (destination_dir / "api" / "tasks.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not (destination_dir / ".git").exists()


def test_configure_github_pages_raises_exact_github_error(monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        return DummyResponse(404, {"message": "Not Found"}, text='{"message":"Not Found"}')

    def fake_post(url, headers=None, json=None, **kwargs):
        return DummyResponse(
            403,
            {"message": "Resource not accessible by personal access token"},
            text='{"message":"Resource not accessible by personal access token"}',
        )

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)

    with pytest.raises(GitHubApiError, match="Resource not accessible by personal access token"):
        configure_github_pages("example/project", "gh-pages", "secret")


def test_request_github_pages_build_raises_exact_github_error(monkeypatch):
    def fake_post(url, headers=None, **kwargs):
        return DummyResponse(
            403,
            {"message": "Resource not accessible by personal access token"},
            text='{"message":"Resource not accessible by personal access token"}',
        )

    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)

    with pytest.raises(GitHubApiError, match="Resource not accessible by personal access token"):
        request_github_pages_build("example/project", "secret")


def test_publish_local_directory_to_github_branch_raises_non_fast_forward_error(monkeypatch, tmp_path):
    docs_dir = tmp_path / "build"
    docs_dir.mkdir()
    (docs_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    def fake_get(url, headers=None, params=None, **kwargs):
        if url.endswith("/git/refs/heads/gh-pages"):
            return DummyResponse(200, {"object": {"sha": "commitsha"}})
        if url.endswith("/git/commits/commitsha"):
            return DummyResponse(200, {"tree": {"sha": "treesha"}})
        raise AssertionError(f"Unexpected GET {url}")

    def fake_post(url, headers=None, json=None, **kwargs):
        if url.endswith("/git/blobs"):
            return DummyResponse(201, {"sha": "blobsha"})
        if url.endswith("/git/trees"):
            return DummyResponse(201, {"sha": "newtree"})
        if url.endswith("/git/commits"):
            return DummyResponse(201, {"sha": "newcommit"})
        raise AssertionError(f"Unexpected POST {url}")

    def fake_patch(url, headers=None, json=None, **kwargs):
        return DummyResponse(
            422,
            {"message": "Update is not a fast forward"},
            text='{"message":"Update is not a fast forward","status":"422"}',
        )

    monkeypatch.setattr("utils.git_utils.ensure_github_branch", lambda *args, **kwargs: True)
    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)
    monkeypatch.setattr("utils.git_utils.requests.patch", fake_patch)
    monkeypatch.setattr("utils.git_utils.list_github_tree", lambda *args, **kwargs: [])

    with pytest.raises(GitHubApiError, match="Update is not a fast forward"):
        publish_local_directory_to_github_branch(
            "example/project",
            str(docs_dir),
            "gh-pages",
            "secret",
            "main",
        )


def test_create_directory_and_add_files_preserves_nested_paths_for_github(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None, **kwargs):
        if url.endswith("/git/refs/heads/main"):
            return DummyResponse(200, {"object": {"sha": "commitsha"}})
        if url.endswith("/git/commits/commitsha"):
            return DummyResponse(200, {"tree": {"sha": "treesha"}})
        raise AssertionError(f"Unexpected GET {url}")

    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        if json is None:
            json = {}
        if url.endswith("/git/trees"):
            captured["tree"] = json.get("tree", [])
            return DummyResponse(201, {"sha": "newtree"})
        if url.endswith("/git/commits"):
            return DummyResponse(201, {"sha": "newcommit"})
        raise AssertionError(f"Unexpected POST {url}")

    def fake_patch(url, headers=None, json=None, **kwargs):
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
    def fake_get(url, headers=None, params=None, timeout=None, **kwargs):
        if url.endswith("/git/refs/heads/main"):
            return DummyResponse(200, {"object": {"sha": "commitsha"}})
        if url.endswith("/git/commits/commitsha"):
            return DummyResponse(200, {"tree": {"sha": "treesha"}})
        raise AssertionError(f"Unexpected GET {url}")

    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        if json is None:
            json = {}
        if url.endswith("/git/trees"):
            captured["tree"] = json.get("tree", [])
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

    def fake_get(url, headers, **kwargs):
        calls.append(("get", url, headers))
        return DummyResponse(200, {"source": {"branch": "gh-pages", "path": "/"}})

    def fake_put(url, headers, json, **kwargs):
        calls.append(("put", url, headers, json))
        return DummyResponse(403, text="should not update")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.put", fake_put)

    assert configure_github_pages("example/project", "gh-pages", "secret") is True
    assert [call[0] for call in calls] == ["get"]


def test_configure_github_pages_updates_when_source_differs(monkeypatch):
    calls = []

    def fake_get(url, headers, **kwargs):
        calls.append(("get", url, headers))
        return DummyResponse(200, {"source": {"branch": "main", "path": "/"}})

    def fake_put(url, headers, json, **kwargs):
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
    def fake_post(url, headers, json, **kwargs):
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


def test_architecture_draft_generation_never_calls_provider_write_helper(monkeypatch):
    """Regression guard: architecture generation is read-only and must never mutate the repo."""
    from contextlib import contextmanager
    from pathlib import Path

    from services.architecture_services import generate_architecture_draft

    fixture_repo_dir = str(Path(__file__).parent / "fixtures" / "architecture_repo")

    @contextmanager
    def _fake_clone(repo_url, token, branch, provider):
        yield fixture_repo_dir

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("architecture generation must never write to the target repository")

    monkeypatch.setattr("services.architecture_services.clone_repository", _fake_clone)
    monkeypatch.setattr("services.architecture_services.fetch_content_from_github", lambda *a, **k: None)
    monkeypatch.setattr("services.architecture_services.fetch_content_from_gitlab", lambda *a, **k: None)
    monkeypatch.setattr("services.sphinx_services.fetch_content_from_github", lambda *a, **k: None)
    monkeypatch.setattr("services.sphinx_services.fetch_content_from_gitlab", lambda *a, **k: None)
    monkeypatch.setattr("utils.git_utils.create_a_file", _fail_if_called)

    result = generate_architecture_draft(
        provider="github",
        repo_url="octo-org/widgets",
        token="secret",
        branch="main",
        target_folders=[],
        output_path="docs/project/architecture.rst",
        include_diagrams=True,
        reuse_existing_docs=True,
    )

    assert result["draft_id"]
    assert result["status"] in {"success", "partial"}


def test_fetch_content_from_gitlab_returns_text_on_success(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        assert headers == {"PRIVATE-TOKEN": "secret"}
        assert params == {"ref": "main"}
        return DummyResponse(200, text="print('hello')\n")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    content = fetch_content_from_gitlab("group/project", "main", "app.py", "secret")

    assert content == "print('hello')\n"


def test_fetch_content_from_gitlab_returns_none_on_error(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(404, text="Not Found")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    assert fetch_content_from_gitlab("group/project", "main", "missing.py", "secret") is None


def test_create_a_file_creates_new_file_on_github(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, **kwargs):
        calls.append(("get", url))
        return DummyResponse(404)

    def fake_put(url, headers=None, json=None, **kwargs):
        calls.append(("put", url, json))
        return DummyResponse(201)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.put", fake_put)

    result = create_a_file("example/project", "main", "docs/new.rst", "content", "secret", "github")

    assert result is True
    assert calls[0][0] == "get"
    assert calls[1][0] == "put"
    assert "sha" not in calls[1][2]


def test_create_a_file_updates_existing_file_on_github(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(200, {"sha": "abc123"})

    captured = {}

    def fake_put(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return DummyResponse(200)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.put", fake_put)

    result = create_a_file("example/project", "main", "docs/existing.rst", "content", "secret", "github")

    assert result is True
    assert captured["json"]["sha"] == "abc123"


def test_create_a_file_returns_false_on_github_error(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(404)

    def fake_put(url, headers=None, json=None, **kwargs):
        return DummyResponse(422, text="validation failed")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.put", fake_put)

    assert create_a_file("example/project", "main", "docs/new.rst", "content", "secret", "github") is False


def test_create_a_file_creates_new_file_on_gitlab(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(404)

    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return DummyResponse(201)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)

    result = create_a_file("group/project", "main", "docs/new.rst", "content", "secret", "gitlab")

    assert result is True
    assert captured["json"]["commit_message"] == "Create docs/new.rst"


def test_create_a_file_updates_existing_file_on_gitlab(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(200)

    captured = {}

    def fake_put(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return DummyResponse(200)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.put", fake_put)

    result = create_a_file("group/project", "main", "docs/existing.rst", "content", "secret", "gitlab")

    assert result is True
    assert captured["json"]["commit_message"] == "Update docs/existing.rst"


def test_create_a_file_returns_false_for_unsupported_provider():
    assert create_a_file("example/project", "main", "docs/new.rst", "content", "secret", "bitbucket") is False


def test_ensure_github_branch_returns_true_when_branch_already_exists(monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        return DummyResponse(200)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    assert ensure_github_branch("example/project", "main", "gh-pages", "secret") is True


def test_ensure_github_branch_creates_branch_from_source_when_missing(monkeypatch):
    calls = []

    def fake_get(url, headers=None, **kwargs):
        if url.endswith("/heads/gh-pages"):
            return DummyResponse(404)
        calls.append("get-source")
        return DummyResponse(200, {"object": {"sha": "source-sha"}})

    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return DummyResponse(201)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)
    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)

    assert ensure_github_branch("example/project", "main", "gh-pages", "secret") is True
    assert calls == ["get-source"]
    assert captured["json"] == {"ref": "refs/heads/gh-pages", "sha": "source-sha"}


def test_ensure_github_branch_returns_false_when_source_branch_missing(monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        if url.endswith("/heads/gh-pages"):
            return DummyResponse(404)
        return DummyResponse(404)

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    assert ensure_github_branch("example/project", "missing-source", "gh-pages", "secret") is False


def test_list_github_tree_returns_entries_on_success(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        assert params == {"recursive": "1"}
        return DummyResponse(200, {"tree": [{"path": "docs/index.rst", "type": "blob"}]})

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    tree = list_github_tree("example/project", "main", "secret")

    assert tree == [{"path": "docs/index.rst", "type": "blob"}]


def test_list_github_tree_returns_empty_list_on_error(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(404, text="Not Found")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    assert list_github_tree("example/project", "missing-ref", "secret") == []


def test_create_github_blob_returns_sha_on_success(monkeypatch):
    def fake_post(url, headers=None, json=None, **kwargs):
        assert json == {"content": "hello", "encoding": "utf-8"}
        return DummyResponse(201, {"sha": "blob-sha"})

    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)

    assert create_github_blob("example/project", "secret", b"hello") == "blob-sha"


def test_create_github_blob_returns_none_on_error(monkeypatch):
    def fake_post(url, headers=None, json=None, **kwargs):
        return DummyResponse(422, text="validation failed")

    monkeypatch.setattr("utils.git_utils.requests.post", fake_post)

    assert create_github_blob("example/project", "secret", b"hello") is None


def test_list_open_github_pull_requests_returns_list_on_success(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        assert params["base"] == "main"
        return DummyResponse(200, [{"number": 1, "title": "Add docstrings"}])

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    prs = list_open_github_pull_requests("example/project", "main", "secret")

    assert prs == [{"number": 1, "title": "Add docstrings"}]


def test_list_open_github_pull_requests_returns_empty_list_on_error(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(500, text="server error")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    assert list_open_github_pull_requests("example/project", "main", "secret") == []


def test_list_github_pull_request_files_returns_list_on_success(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(200, [{"filename": "src/app.py"}])

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    files = list_github_pull_request_files("example/project", 42, "secret")

    assert files == [{"filename": "src/app.py"}]


def test_list_github_pull_request_files_returns_empty_list_on_error(monkeypatch):
    def fake_get(url, headers=None, params=None, **kwargs):
        return DummyResponse(404, text="Not Found")

    monkeypatch.setattr("utils.git_utils.requests.get", fake_get)

    assert list_github_pull_request_files("example/project", 42, "secret") == []
