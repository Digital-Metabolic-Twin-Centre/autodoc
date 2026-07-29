import yaml

from utils.generate_yml_content import (
    generate_github_actions_file,
    generate_github_pages_index,
    generate_gitlab_ci_file,
)


def test_generate_gitlab_ci_file_is_valid_yaml_with_expected_stages():
    content = generate_gitlab_ci_file()

    parsed = yaml.safe_load(content)

    assert parsed["stages"] == ["docs", "deploy"]
    assert "build_sphinx" in parsed
    assert "pages" in parsed
    assert parsed["pages"]["dependencies"] == ["build_sphinx"]


def test_generate_gitlab_ci_file_references_update_conf_and_sphinx_build():
    content = generate_gitlab_ci_file()

    assert 'python update_conf.py "$CONF_PY"' in content
    assert 'sphinx-build -b html "$DOCS_SRC" "$BUILD_DIR"' in content


def test_generate_github_actions_file_is_valid_yaml_with_expected_triggers():
    content = generate_github_actions_file()

    parsed = yaml.safe_load(content)

    # PyYAML parses the unquoted `on:` key as the boolean True (YAML 1.1).
    triggers = parsed[True]
    assert set(triggers["push"]["branches"]) == {"main", "dev"}
    assert "docs" in parsed["jobs"]
    assert parsed["jobs"]["docs"]["runs-on"] == "ubuntu-latest"


def test_generate_github_actions_file_references_update_conf_and_sphinx_build():
    content = generate_github_actions_file()

    assert 'python update_conf.py "docs/conf.py"' in content
    assert "sphinx-build -b html docs docs/build/html" in content


def test_generate_github_pages_index_embeds_project_name():
    content = generate_github_pages_index("Example Project")

    assert "<title>Example Project</title>" in content
    assert "<h1>Example Project</h1>" in content
    assert content.startswith("<!doctype html>")


def test_generate_github_pages_index_uses_default_project_name():
    content = generate_github_pages_index()

    assert "<title>API Documentation</title>" in content
