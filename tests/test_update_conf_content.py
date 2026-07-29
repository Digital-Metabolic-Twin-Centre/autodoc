import ast

import pytest

import utils.update_conf_content as update_conf_content
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
        "extensions = [\n    'sphinx.ext.autodoc',\n]\nproject = 'Example'\n",
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


def test_update_conf_appends_extensions_block_when_missing(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("project = 'Example'\n", encoding="utf-8")

    update_conf(str(conf_path))

    text = conf_path.read_text(encoding="utf-8")
    ast.parse(text)
    assert "'autoapi.extension'" in text
    assert "'sphinx.ext.napoleon'" in text


def test_update_conf_is_a_no_op_when_conf_py_does_not_exist(tmp_path):
    missing_path = tmp_path / "does-not-exist" / "conf.py"

    update_conf(str(missing_path))

    assert not missing_path.exists()


def test_update_conf_raises_value_error_when_result_would_be_invalid_python(monkeypatch, tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("extensions = ['sphinx.ext.autodoc']\n", encoding="utf-8")

    original_parse = update_conf_content.ast.parse
    call_count = {"n": 0}

    def fake_parse(text, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise SyntaxError("boom", ("conf.py", 1, 1, "bad"))
        return original_parse(text, *args, **kwargs)

    monkeypatch.setattr(update_conf_content.ast, "parse", fake_parse)

    with pytest.raises(ValueError, match="Updated docs/conf.py would be invalid Python"):
        update_conf_content.update_conf(str(conf_path))
