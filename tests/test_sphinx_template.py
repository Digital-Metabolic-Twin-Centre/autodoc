from services.sphinx_services import (
    _sample_docs_files,
    _write_sample_sphinx_scaffold,
    apply_architecture_navigation_update,
)


def test_sample_docs_files_follow_shared_template_with_autoapi():
    files = _sample_docs_files("OpenKinetics Predictor")

    assert "docs/conf.py" in files
    assert "docs/index.rst" in files
    assert "docs/api_reference.rst" in files
    assert "docs/project/overview.rst" in files
    assert "docs/project/architecture.rst" in files
    assert 'html_theme = "sphinx_rtd_theme"' in files["docs/conf.py"]
    assert 'autoapi_dirs = ["../autoapi_include"]' in files["docs/conf.py"]
    assert "autoapi_add_toctree_entry = False" in files["docs/conf.py"]
    assert "api_reference" in files["docs/index.rst"]
    assert "project/architecture" in files["docs/index.rst"]
    assert (
        "Generated API entries will appear here after the mirrored Python tree is analysed."
        in files["docs/api_reference.rst"]
    )
    assert "project/overview" in files["docs/index.rst"]
    assert "cd docs" in files["docs/README.rst"]
    assert "docs/build/html/index.html" in files["docs/README.rst"]


def test_write_sample_sphinx_scaffold_creates_docs_layout(tmp_path):
    _write_sample_sphinx_scaffold(str(tmp_path), "OpenKinetics Predictor")

    assert (tmp_path / "docs" / "conf.py").exists()
    assert (tmp_path / "docs" / "index.rst").exists()
    assert (tmp_path / "docs" / "api_reference.rst").exists()
    assert (tmp_path / "docs" / "_static" / "custom-wide.css").exists()
    assert (tmp_path / "docs" / "Makefile").exists()


def test_apply_architecture_navigation_update_does_not_duplicate_entries(tmp_path):
    repo_dir = tmp_path / "repo"
    docs_dir = repo_dir / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "index.rst").write_text(
        "Project\n=======\n\n.. toctree::\n   :maxdepth: 1\n\n   project/overview\n",
        encoding="utf-8",
    )

    assert (
        apply_architecture_navigation_update(
            str(repo_dir),
            "main",
            "secret",
            "github",
            "docs/project/architecture.rst",
            "Example Project",
        )
        is True
    )
    assert (
        apply_architecture_navigation_update(
            str(repo_dir),
            "main",
            "secret",
            "github",
            "docs/project/architecture.rst",
            "Example Project",
        )
        is True
    )

    index_text = (docs_dir / "index.rst").read_text(encoding="utf-8")
    assert index_text.count("project/architecture") == 1
