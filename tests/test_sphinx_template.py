from services.sphinx_services import _sample_docs_files, _write_sample_sphinx_scaffold


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
    assert "autoapi/src/index" in files["docs/api_reference.rst"]
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
