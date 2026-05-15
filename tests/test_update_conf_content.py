import ast

import pytest

from utils.update_conf_content import update_conf


def test_update_conf_adds_autoapi_and_napoleon_extensions(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("extensions = ['sphinx.ext.autodoc']\n", encoding="utf-8")

    update_conf(str(conf_path))

    text = conf_path.read_text(encoding="utf-8")
    assert "'autoapi.extension'" in text
    assert "'sphinx.ext.napoleon'" in text
    assert "autoapi_dirs = ['../autoapi_include']" in text
    assert "autoapi_add_toctree_entry = False" in text


def test_update_conf_preserves_valid_python_for_multiline_extensions(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text(
        "extensions = [\n"
        "    'sphinx.ext.autodoc',\n"
        "]\n"
        "project = 'Example'\n",
        encoding="utf-8",
    )

    update_conf(str(conf_path))

    text = conf_path.read_text(encoding="utf-8")
    ast.parse(text)
    assert "'autoapi.extension'" in text
    assert "'sphinx.ext.napoleon'" in text


def test_update_conf_rejects_non_list_extensions(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("extensions = ('sphinx.ext.autodoc',)\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must define 'extensions' as a Python list"):
        update_conf(str(conf_path))
