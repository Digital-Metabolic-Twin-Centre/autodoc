from services.sphinx_services import (
    _sample_docs_files,
    _write_sample_sphinx_scaffold,
    detect_navigation_conflict,
    propose_architecture_navigation,
    update_sphinx_navigation_for_architecture,
)


def test_sample_docs_files_follow_shared_template_with_autoapi():
    files = _sample_docs_files("OpenKinetics Predictor")

    assert "docs/conf.py" in files
    assert "docs/index.rst" in files
    assert "docs/api_reference.rst" in files
    assert "docs/project/overview.rst" in files
    assert 'html_theme = "sphinx_rtd_theme"' in files["docs/conf.py"]
    assert 'autoapi_dirs = ["../autoapi_include"]' in files["docs/conf.py"]
    assert "autoapi_add_toctree_entry = False" in files["docs/conf.py"]
    assert "api_reference" in files["docs/index.rst"]
    assert "Auto Doc" not in files["docs/index.rst"]
    assert "Repository Analysis and Sphinx Publishing" not in files["docs/index.rst"]
    assert "Turn repository structure" not in files["docs/index.rst"]
    assert (
        "Generated API entries will appear here after the mirrored Python tree is analysed."
        in files["docs/api_reference.rst"]
    )
    assert "project/overview" in files["docs/index.rst"]
    assert "cd docs" in files["docs/README.rst"]
    assert "Documentation Notes" not in files["docs/README.rst"]
    assert "docs/build/html/index.html" in files["docs/README.rst"]


def test_write_sample_sphinx_scaffold_creates_docs_layout(tmp_path):
    _write_sample_sphinx_scaffold(str(tmp_path), "OpenKinetics Predictor")

    assert (tmp_path / "docs" / "conf.py").exists()
    assert (tmp_path / "docs" / "index.rst").exists()
    assert (tmp_path / "docs" / "api_reference.rst").exists()
    assert (tmp_path / "docs" / "_static" / "custom-wide.css").exists()
    assert (tmp_path / "docs" / "Makefile").exists()


def test_detect_navigation_conflict_returns_false_when_index_missing():
    conflict, entry = detect_navigation_conflict(None, "project/architecture")

    assert conflict is False
    assert entry is None


def test_detect_navigation_conflict_returns_false_when_already_referenced():
    index_content = ".. toctree::\n   :hidden:\n\n   project/architecture\n   README\n"

    conflict, entry = detect_navigation_conflict(index_content, "project/architecture")

    assert conflict is False
    assert entry is None


def test_detect_navigation_conflict_flags_same_leaf_name_at_different_path():
    index_content = ".. toctree::\n   :hidden:\n\n   architecture\n   README\n"

    conflict, entry = detect_navigation_conflict(index_content, "project/architecture")

    assert conflict is True
    assert entry == "architecture"


def test_propose_architecture_navigation_reports_placement(monkeypatch):
    monkeypatch.setattr(
        "services.sphinx_services.fetch_content_from_github",
        lambda repo_path, branch, file_path, token: ".. toctree::\n\n   README\n",
    )

    navigation_update = propose_architecture_navigation(
        "octo-org/example-repo", "main", "secret", "github", "docs/project/architecture.rst"
    )

    assert navigation_update["toctree_entry"] == "project/architecture"
    assert navigation_update["already_referenced"] is False
    assert navigation_update["conflict"] is False


def test_update_sphinx_navigation_for_architecture_inserts_entry(monkeypatch):
    written = {}

    def fake_fetch(repo_path, branch, file_path, token):
        return (
            "Docs\n====\n\n"
            ".. toctree::\n"
            "   :hidden:\n"
            "   :maxdepth: 1\n"
            "   :caption: Project\n\n"
            "   README\n\n"
            ".. toctree::\n"
            "   :hidden:\n"
            "   :maxdepth: 1\n"
            "   :caption: Reference\n\n"
            "   api_reference\n"
        )

    def fake_create_a_file(repo_path, branch, file_path, content, token, provider):
        written["file_path"] = file_path
        written["content"] = content
        return True

    monkeypatch.setattr("services.sphinx_services.fetch_content_from_github", fake_fetch)
    monkeypatch.setattr("services.sphinx_services.create_a_file", fake_create_a_file)

    applied = update_sphinx_navigation_for_architecture(
        "octo-org/example-repo",
        "main",
        "secret",
        "github",
        {"index_path": "docs/index.rst", "toctree_entry": "project/architecture", "already_referenced": False},
    )

    assert applied is True
    assert written["file_path"] == "docs/index.rst"
    assert "project/architecture" in written["content"]
    assert written["content"].index("api_reference") < written["content"].index("project/architecture")


def test_update_sphinx_navigation_for_architecture_moves_existing_entry_to_reference(monkeypatch):
    written = {}

    def fake_fetch(repo_path, branch, file_path, token):
        return (
            "Docs\n====\n\n"
            ".. toctree::\n"
            "   :hidden:\n"
            "   :maxdepth: 1\n"
            "   :caption: Project\n\n"
            "   project/architecture\n"
            "   README\n\n"
            ".. toctree::\n"
            "   :hidden:\n"
            "   :maxdepth: 1\n"
            "   :caption: Reference\n\n"
            "   api_reference\n"
        )

    def fake_create_a_file(repo_path, branch, file_path, content, token, provider):
        written["content"] = content
        return True

    monkeypatch.setattr("services.sphinx_services.fetch_content_from_github", fake_fetch)
    monkeypatch.setattr("services.sphinx_services.create_a_file", fake_create_a_file)

    applied = update_sphinx_navigation_for_architecture(
        "octo-org/example-repo",
        "main",
        "secret",
        "github",
        {"index_path": "docs/index.rst", "toctree_entry": "project/architecture", "already_referenced": True},
    )

    assert applied is True
    assert written["content"].count("project/architecture") == 1
    assert written["content"].index("api_reference") < written["content"].index("project/architecture")


def test_update_sphinx_navigation_for_architecture_skips_when_already_under_reference(monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not write when already referenced under Reference")

    def fake_fetch(repo_path, branch, file_path, token):
        return (
            "Docs\n====\n\n"
            ".. toctree::\n"
            "   :hidden:\n"
            "   :maxdepth: 1\n"
            "   :caption: Reference\n\n"
            "   api_reference\n"
            "   project/architecture\n"
        )

    monkeypatch.setattr("services.sphinx_services.fetch_content_from_github", fake_fetch)
    monkeypatch.setattr("services.sphinx_services.create_a_file", _fail_if_called)

    applied = update_sphinx_navigation_for_architecture(
        "octo-org/example-repo",
        "main",
        "secret",
        "github",
        {"index_path": "docs/index.rst", "toctree_entry": "project/architecture", "already_referenced": True},
    )

    assert applied is True
