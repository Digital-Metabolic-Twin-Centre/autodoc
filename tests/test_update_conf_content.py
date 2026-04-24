from utils.update_conf_content import update_conf


def test_update_conf_adds_autoapi_and_napoleon_extensions(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("extensions = ['sphinx.ext.autodoc']\n", encoding="utf-8")

    update_conf(str(conf_path))

    text = conf_path.read_text(encoding="utf-8")
    assert "'autoapi.extension'" in text
    assert "'sphinx.ext.napoleon'" in text
    assert "autoapi_dirs = ['../../autoapi_include']" in text
