from services.sphinx_services import _sample_docs_files, _write_sample_sphinx_scaffold


def test_sample_docs_files_follow_shared_template_with_autoapi():
    files = _sample_docs_files("OpenKinetics Predictor")

    assert "docs/source/conf.py" in files
    assert "docs/source/index.rst" in files
    assert "docs/source/project/overview.rst" in files
    assert "docs/source/logbook/weekly_updates.rst" in files
    assert 'html_theme = "sphinx_rtd_theme"' in files["docs/source/conf.py"]
    assert 'autoapi_dirs = ["../../autoapi_include"]' in files["docs/source/conf.py"]
    assert "autoapi/index" in files["docs/source/index.rst"]
    assert "project/overview" in files["docs/source/index.rst"]
    assert "cd docs" in files["docs/source/README.rst"]
    assert "docs/build/html/index.html" in files["docs/source/README.rst"]


def test_write_sample_sphinx_scaffold_creates_docs_source_layout(tmp_path):
    _write_sample_sphinx_scaffold(str(tmp_path), "OpenKinetics Predictor")

    assert (tmp_path / "docs" / "source" / "conf.py").exists()
    assert (tmp_path / "docs" / "source" / "index.rst").exists()
    assert (tmp_path / "docs" / "source" / "_static" / "custom-wide.css").exists()
    assert (tmp_path / "docs" / "Makefile").exists()
