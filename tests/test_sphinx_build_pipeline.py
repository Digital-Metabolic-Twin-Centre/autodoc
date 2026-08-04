"""
Coverage for sphinx_services.py's build/degrade/publish pipeline: the
AutoAPI file classification and ignore-collection logic, the Sphinx build
retry orchestration, and the top-level publish_github_pages flow. This is
the part of the file most likely to break silently (a bad regex or a
reordered fallback step wouldn't fail loudly - it would just quietly stop
degrading gracefully), so these tests exercise the actual retry/degrade
decisions rather than just mocking everything into a boolean.
"""

import subprocess
from pathlib import Path

import pytest

from services.sphinx_services import (
    AUTOAPI_CONF_MARKER_END,
    AUTOAPI_CONF_MARKER_START,
    AUTOAPI_DIRECTORY,
    PublishPagesError,
    _apply_autoapi_runtime_settings,
    _build_degraded_api_reference,
    _build_sphinx_once,
    _classify_autoapi_file,
    _collect_prebuild_autoapi_ignores,
    _degrade_sphinx_publish_after_autoapi_failure,
    _disable_autoapi_in_conf,
    _extract_autoapi_module_names,
    _find_autoapi_skip_candidates,
    _module_names_to_ignore_patterns,
    _run_sphinx_build_with_autoapi_filters,
    _summarize_publish_fallback_reason,
    publish_github_pages,
)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["sphinx-build"], returncode=returncode, stdout=stdout, stderr=stderr)


# --- _classify_autoapi_file ------------------------------------------------


def test_classify_autoapi_file_includes_normal_module(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    autoapi_root.mkdir()
    module = autoapi_root / "widgets.py"
    module.write_text("def build():\n    return 1\n\n\ndef teardown():\n    return None\n", encoding="utf-8")

    included, reason = _classify_autoapi_file(autoapi_root, module)

    assert included is True
    assert reason == "included"


def test_classify_autoapi_file_excludes_risky_path():
    autoapi_root = Path("/repo/autoapi_include")
    file_path = autoapi_root / "app" / "tests" / "test_widgets.py"

    included, reason = _classify_autoapi_file(autoapi_root, file_path)

    assert included is False
    assert reason.startswith("path-pattern:")


def test_classify_autoapi_file_excludes_syntax_error(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    autoapi_root.mkdir()
    module = autoapi_root / "broken.py"
    module.write_text("def build(:\n    pass\n", encoding="utf-8")

    included, reason = _classify_autoapi_file(autoapi_root, module)

    assert included is False
    assert reason == "syntax-error"


def test_classify_autoapi_file_excludes_import_star(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    autoapi_root.mkdir()
    module = autoapi_root / "reexport.py"
    module.write_text("from other_module import *\n\n\ndef build():\n    return 1\n", encoding="utf-8")

    included, reason = _classify_autoapi_file(autoapi_root, module)

    assert included is False
    assert reason == "import-star"


def test_classify_autoapi_file_excludes_low_content(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    autoapi_root.mkdir()
    module = autoapi_root / "stub.py"
    module.write_text("x = 1\n", encoding="utf-8")

    included, reason = _classify_autoapi_file(autoapi_root, module, low_content_min_meaningful_lines=4)

    assert included is False
    assert reason == "low-content"


def test_classify_autoapi_file_excludes_non_meaningful_module(tmp_path):
    autoapi_root = tmp_path / "autoapi_include"
    autoapi_root.mkdir()
    module = autoapi_root / "constants.py"
    module.write_text("FOO = 1\nBAR = 2\nBAZ = 3\nQUX = 4\n", encoding="utf-8")

    included, reason = _classify_autoapi_file(autoapi_root, module, low_content_min_meaningful_lines=4)

    assert included is False
    assert reason == "non-meaningful-module"


# --- _extract_autoapi_module_names -----------------------------------------


def test_extract_autoapi_module_names_from_module_quote_pattern():
    build_output = "autoapi.extension: error loading module 'widgets.core'"

    assert _extract_autoapi_module_names(build_output) == ["widgets.core"]


def test_extract_autoapi_module_names_from_autoapi_index_path():
    build_output = "WARNING: autodoc: failed to import autoapi/widgets/core/index.rst"

    assert _extract_autoapi_module_names(build_output) == ["widgets.core"]


def test_extract_autoapi_module_names_from_mirrored_source_path():
    build_output = "[AutoAPI] Reading files... [ 42%] autoapi_include/widgets/broken.py"

    assert _extract_autoapi_module_names(build_output) == ["widgets.broken"]


def test_extract_autoapi_module_names_dedupes_and_preserves_order():
    build_output = "module 'a.b' failed\nmodule 'a.b' failed again\nmodule 'c.d' failed"

    assert _extract_autoapi_module_names(build_output) == ["a.b", "c.d"]


def test_extract_autoapi_module_names_returns_empty_for_no_match():
    assert _extract_autoapi_module_names("everything is fine") == []


# --- _collect_prebuild_autoapi_ignores --------------------------------------


def test_collect_prebuild_autoapi_ignores_returns_empty_when_autoapi_root_missing(tmp_path):
    ignore_patterns, skipped = _collect_prebuild_autoapi_ignores(str(tmp_path))

    assert ignore_patterns == []
    assert skipped == []


def test_collect_prebuild_autoapi_ignores_flags_bad_files_and_spares_good_ones(tmp_path):
    autoapi_root = tmp_path / AUTOAPI_DIRECTORY
    autoapi_root.mkdir()
    (autoapi_root / "good.py").write_text(
        "def build():\n    return 1\n\n\ndef teardown():\n    return None\n", encoding="utf-8"
    )
    (autoapi_root / "broken.py").write_text("def build(:\n    pass\n", encoding="utf-8")
    tests_dir = autoapi_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_good.py").write_text(
        "def build():\n    return 1\n\n\ndef teardown():\n    return None\n", encoding="utf-8"
    )

    ignore_patterns, skipped = _collect_prebuild_autoapi_ignores(str(tmp_path))

    assert "*/broken.py" in ignore_patterns
    assert "*/tests/test_good.py" in ignore_patterns
    assert "*/good.py" not in ignore_patterns
    reasons = {item["file"]: item["reason"] for item in skipped}
    assert reasons[f"{AUTOAPI_DIRECTORY}/broken.py"] == "syntax-error"
    assert reasons[f"{AUTOAPI_DIRECTORY}/tests/test_good.py"].startswith("path-pattern:")


# --- _find_autoapi_skip_candidates / _module_names_to_ignore_patterns ------


def test_find_autoapi_skip_candidates_matches_direct_module_file(tmp_path):
    autoapi_root = tmp_path / AUTOAPI_DIRECTORY
    (autoapi_root / "widgets").mkdir(parents=True)
    target = autoapi_root / "widgets" / "core.py"
    target.write_text("def build():\n    return 1\n", encoding="utf-8")

    candidates = _find_autoapi_skip_candidates(str(tmp_path), "widgets.core")

    assert candidates == [target]


def test_find_autoapi_skip_candidates_matches_package_init(tmp_path):
    autoapi_root = tmp_path / AUTOAPI_DIRECTORY
    package_dir = autoapi_root / "widgets"
    package_dir.mkdir(parents=True)
    init_file = package_dir / "__init__.py"
    init_file.write_text("VERSION = 1\n", encoding="utf-8")

    candidates = _find_autoapi_skip_candidates(str(tmp_path), "widgets")

    assert candidates == [init_file]


def test_find_autoapi_skip_candidates_falls_back_to_leaf_name_search(tmp_path):
    autoapi_root = tmp_path / AUTOAPI_DIRECTORY
    nested_dir = autoapi_root / "nested" / "path"
    nested_dir.mkdir(parents=True)
    target = nested_dir / "core.py"
    target.write_text("def build():\n    return 1\n", encoding="utf-8")

    candidates = _find_autoapi_skip_candidates(str(tmp_path), "unrelated.module.path.core")

    assert candidates == [target]


def test_find_autoapi_skip_candidates_returns_empty_when_autoapi_root_missing(tmp_path):
    assert _find_autoapi_skip_candidates(str(tmp_path), "widgets.core") == []


def test_module_names_to_ignore_patterns_builds_fallback_entries(tmp_path):
    autoapi_root = tmp_path / AUTOAPI_DIRECTORY
    (autoapi_root / "widgets").mkdir(parents=True)
    (autoapi_root / "widgets" / "core.py").write_text("def build():\n    return 1\n", encoding="utf-8")

    ignore_patterns, skipped = _module_names_to_ignore_patterns(str(tmp_path), ["widgets.core"])

    assert ignore_patterns == ["*/widgets/core.py"]
    assert skipped == [
        {"file": f"{AUTOAPI_DIRECTORY}/widgets/core.py", "module": "widgets.core", "reason": "fallback-module-failure"}
    ]


# --- _apply_autoapi_runtime_settings / _disable_autoapi_in_conf ------------


def test_apply_autoapi_runtime_settings_appends_marker_block_when_absent(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("project = 'Demo'\n", encoding="utf-8")

    _apply_autoapi_runtime_settings(str(conf_path), ["*/widgets/core.py"])

    conf_text = conf_path.read_text(encoding="utf-8")
    assert AUTOAPI_CONF_MARKER_START in conf_text
    assert AUTOAPI_CONF_MARKER_END in conf_text
    assert "*/widgets/core.py" in conf_text
    assert conf_text.count(AUTOAPI_CONF_MARKER_START) == 1


def test_apply_autoapi_runtime_settings_replaces_existing_marker_block(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text(
        "project = 'Demo'\n\n"
        f"{AUTOAPI_CONF_MARKER_START}\n"
        "autoapi_ignore = [\n    '*/old/pattern.py',\n]\n"
        f"{AUTOAPI_CONF_MARKER_END}\n",
        encoding="utf-8",
    )

    _apply_autoapi_runtime_settings(str(conf_path), ["*/widgets/core.py"])

    conf_text = conf_path.read_text(encoding="utf-8")
    assert conf_text.count(AUTOAPI_CONF_MARKER_START) == 1
    assert "*/old/pattern.py" not in conf_text
    assert "*/widgets/core.py" in conf_text


def test_apply_autoapi_runtime_settings_noop_when_conf_missing(tmp_path):
    missing_conf = tmp_path / "conf.py"

    _apply_autoapi_runtime_settings(str(missing_conf), ["*/widgets/core.py"])

    assert not missing_conf.exists()


def test_disable_autoapi_in_conf_strips_extension_and_settings(tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text(
        "extensions = [\n"
        "    'sphinx.ext.autodoc',\n"
        "    'autoapi.extension',\n"
        "]\n"
        "autoapi_dirs = ['../autoapi_include']\n"
        "autoapi_add_toctree_entry = False\n\n"
        f"{AUTOAPI_CONF_MARKER_START}\n"
        "autoapi_ignore = ['*/broken.py']\n"
        f"{AUTOAPI_CONF_MARKER_END}\n",
        encoding="utf-8",
    )

    _disable_autoapi_in_conf(str(conf_path))

    conf_text = conf_path.read_text(encoding="utf-8")
    assert "autoapi.extension" not in conf_text
    assert "autoapi_dirs" not in conf_text
    assert "autoapi_add_toctree_entry" not in conf_text
    assert AUTOAPI_CONF_MARKER_START not in conf_text
    assert "sphinx.ext.autodoc" in conf_text


def test_disable_autoapi_in_conf_noop_when_conf_missing(tmp_path):
    missing_conf = tmp_path / "conf.py"

    _disable_autoapi_in_conf(str(missing_conf))

    assert not missing_conf.exists()


# --- _summarize_publish_fallback_reason / _build_degraded_api_reference ----


def test_summarize_publish_fallback_reason_handles_extension_and_attribute_error():
    reason = "Extension error (autoapi.extension)!\nAttributeError: 'NoneType' object has no attribute 'name'"

    assert (
        _summarize_publish_fallback_reason(reason)
        == "AutoAPI extension failure: 'NoneType' object has no attribute 'name'"
    )


def test_summarize_publish_fallback_reason_handles_bare_attribute_error():
    reason = "some preamble\nAttributeError: boom"

    assert _summarize_publish_fallback_reason(reason) == "AutoAPI failure: boom"


def test_summarize_publish_fallback_reason_skips_reading_files_noise():
    reason = "[AutoAPI] Reading files... [ 10%]\n[AutoAPI] Reading files... [ 20%]\nactual failure line"

    assert _summarize_publish_fallback_reason(reason) == "actual failure line"


def test_summarize_publish_fallback_reason_defaults_when_empty():
    assert _summarize_publish_fallback_reason("") == "AutoAPI build failure"
    assert _summarize_publish_fallback_reason("   ") == "AutoAPI build failure"


def test_build_degraded_api_reference_includes_summarized_reason():
    content = _build_degraded_api_reference("AttributeError: boom")

    assert "API Reference" in content
    assert "Reason: AutoAPI failure: boom" in content
    assert "sphinx_build.log" in content


# --- _degrade_sphinx_publish_after_autoapi_failure --------------------------


def test_degrade_sphinx_publish_after_autoapi_failure_rewrites_conf_and_api_reference(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sphinx_services.get_run_log_dir", lambda: str(tmp_path))
    conf_path = tmp_path / "conf.py"
    conf_path.write_text(
        "extensions = [\n    'autoapi.extension',\n]\nautoapi_dirs = ['../autoapi_include']\n",
        encoding="utf-8",
    )
    docs_source_dir = tmp_path / "docs"
    docs_source_dir.mkdir()

    _degrade_sphinx_publish_after_autoapi_failure(str(conf_path), str(docs_source_dir), "AttributeError: boom")

    conf_text = conf_path.read_text(encoding="utf-8")
    assert "autoapi.extension" not in conf_text
    api_reference_text = (docs_source_dir / "api_reference.rst").read_text(encoding="utf-8")
    assert "Reason: AutoAPI failure: boom" in api_reference_text
    fallback_report = (tmp_path / "sphinx_publish_fallback.txt").read_text(encoding="utf-8")
    assert "AttributeError: boom" in fallback_report


# --- _build_sphinx_once ------------------------------------------------------


def test_build_sphinx_once_invokes_expected_sphinx_build_command(monkeypatch, tmp_path):
    captured = {}

    def fake_run(argv, cwd, capture_output, text, timeout):
        captured["argv"] = argv
        captured["cwd"] = cwd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["timeout"] = timeout
        return _completed(returncode=0)

    monkeypatch.setattr("services.sphinx_services.subprocess.run", fake_run)

    result = _build_sphinx_once(str(tmp_path), "docs", "docs/build/html")

    assert result.returncode == 0
    assert captured["cwd"] == str(tmp_path)
    assert captured["argv"][-2:] == ["docs", "docs/build/html"]
    assert "-b" in captured["argv"] and "html" in captured["argv"]
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["timeout"] == 300


# --- _run_sphinx_build_with_autoapi_filters (the core retry orchestrator) --


def test_run_sphinx_build_with_autoapi_filters_returns_immediately_on_success(monkeypatch, tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("project = 'Demo'\n", encoding="utf-8")
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return _completed(returncode=0)

    monkeypatch.setattr("services.sphinx_services.subprocess.run", fake_run)

    result = _run_sphinx_build_with_autoapi_filters(str(tmp_path), str(conf_path))

    assert result.returncode == 0
    assert len(calls) == 1


def test_run_sphinx_build_with_autoapi_filters_retries_with_fallback_ignore_on_failure(monkeypatch, tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("project = 'Demo'\n", encoding="utf-8")
    autoapi_root = tmp_path / AUTOAPI_DIRECTORY
    (autoapi_root / "widgets").mkdir(parents=True)
    # Long/meaningful enough to pass prebuild classification as "included", so the
    # fallback-ignore-after-build-failure path (not the prebuild filter) is what's under test.
    (autoapi_root / "widgets" / "broken.py").write_text(
        "def build():\n    return 1\n\n\ndef teardown():\n    return None\n", encoding="utf-8"
    )

    results = [
        _completed(returncode=1, stderr="Extension error: module 'widgets.broken' failed to import"),
        _completed(returncode=0),
    ]
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return results[len(calls) - 1]

    monkeypatch.setattr("services.sphinx_services.subprocess.run", fake_run)

    result = _run_sphinx_build_with_autoapi_filters(str(tmp_path), str(conf_path))

    assert result.returncode == 0
    assert len(calls) == 2
    conf_text = conf_path.read_text(encoding="utf-8")
    assert "*/widgets/broken.py" in conf_text


def test_run_sphinx_build_with_autoapi_filters_returns_failure_when_no_fallback_found(monkeypatch, tmp_path):
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("project = 'Demo'\n", encoding="utf-8")
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(1)
        return _completed(returncode=2, stderr="unrecoverable configuration error")

    monkeypatch.setattr("services.sphinx_services.subprocess.run", fake_run)

    result = _run_sphinx_build_with_autoapi_filters(str(tmp_path), str(conf_path))

    assert result.returncode == 2
    assert len(calls) == 1


def test_run_sphinx_build_with_autoapi_filters_writes_build_log(monkeypatch, tmp_path):
    monkeypatch.setattr("services.sphinx_services.get_run_log_dir", lambda: str(tmp_path))
    conf_path = tmp_path / "conf.py"
    conf_path.write_text("project = 'Demo'\n", encoding="utf-8")

    monkeypatch.setattr(
        "services.sphinx_services.subprocess.run",
        lambda *a, **k: _completed(returncode=0, stdout="build ok"),
    )

    _run_sphinx_build_with_autoapi_filters(str(tmp_path), str(conf_path))

    log_text = (tmp_path / "sphinx_build.log").read_text(encoding="utf-8")
    assert "initial-build" in log_text
    assert "build ok" in log_text


# --- publish_github_pages (top-level pipeline) ------------------------------


def _stub_success_dependencies(monkeypatch, downloaded_conf_dir="docs"):
    monkeypatch.setattr("services.sphinx_services.ensure_github_branch", lambda *a, **k: True)
    monkeypatch.setattr("services.sphinx_services.configure_github_pages", lambda *a, **k: True)
    monkeypatch.setattr("services.sphinx_services.update_conf", lambda conf_py_path: None)
    monkeypatch.setattr("services.sphinx_services.publish_local_directory_to_github_branch", lambda *a, **k: True)
    monkeypatch.setattr("services.sphinx_services.request_github_pages_build", lambda *a, **k: True)

    def fake_download(repo_path, branch, token, destination_dir):
        docs_dir = Path(destination_dir) / downloaded_conf_dir
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "conf.py").write_text("project = 'Project_Name'\n", encoding="utf-8")
        (docs_dir / "index.rst").write_text("Welcome to Project_Name's documentation!\n", encoding="utf-8")
        return True

    monkeypatch.setattr("services.sphinx_services.download_github_branch_snapshot", fake_download)


def _make_build_dir_on_success(build_dir: str) -> None:
    Path(build_dir).mkdir(parents=True, exist_ok=True)
    (Path(build_dir) / "index.html").write_text("<html></html>", encoding="utf-8")


def test_publish_github_pages_succeeds_when_build_passes_on_first_try(monkeypatch):
    _stub_success_dependencies(monkeypatch)

    def fake_run(argv, cwd, capture_output, text, timeout):
        build_dir = argv[-1]
        _make_build_dir_on_success(str(Path(cwd) / build_dir) if not Path(build_dir).is_absolute() else build_dir)
        return _completed(returncode=0)

    monkeypatch.setattr("services.sphinx_services.subprocess.run", fake_run)

    assert publish_github_pages("octo-org/example-repo", "main", "secret") is True


def test_publish_github_pages_degrades_and_still_succeeds_when_autoapi_build_fails(monkeypatch):
    _stub_success_dependencies(monkeypatch)
    call_count = {"n": 0}

    def fake_run(argv, cwd, capture_output, text, timeout):
        call_count["n"] += 1
        build_dir_arg = argv[-1]
        build_dir = str(Path(cwd) / build_dir_arg) if not Path(build_dir_arg).is_absolute() else build_dir_arg
        if call_count["n"] == 1:
            # Initial AutoAPI build fails with no module name AutoAPI can extract,
            # so the inner retry-with-ignores loop gives up after one attempt.
            return _completed(returncode=1, stderr="Extension error (autoapi.extension)!\nAttributeError: boom")
        # The degraded (AutoAPI-disabled) rebuild succeeds.
        _make_build_dir_on_success(build_dir)
        return _completed(returncode=0)

    monkeypatch.setattr("services.sphinx_services.subprocess.run", fake_run)

    assert publish_github_pages("octo-org/example-repo", "main", "secret") is True
    assert call_count["n"] == 2


def test_publish_github_pages_raises_when_even_degraded_build_fails(monkeypatch):
    _stub_success_dependencies(monkeypatch)

    monkeypatch.setattr(
        "services.sphinx_services.subprocess.run",
        lambda *a, **k: _completed(returncode=1, stderr="persistent failure"),
    )

    with pytest.raises(PublishPagesError) as exc_info:
        publish_github_pages("octo-org/example-repo", "main", "secret")
    assert exc_info.value.status_code == 422


def test_publish_github_pages_raises_when_branch_setup_fails(monkeypatch):
    monkeypatch.setattr("services.sphinx_services.ensure_github_branch", lambda *a, **k: False)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not proceed past branch setup failure")

    monkeypatch.setattr("services.sphinx_services.download_github_branch_snapshot", _fail_if_called)

    with pytest.raises(PublishPagesError) as exc_info:
        publish_github_pages("octo-org/example-repo", "main", "secret")
    assert exc_info.value.status_code == 403


def test_publish_github_pages_raises_when_no_conf_py_found(monkeypatch):
    monkeypatch.setattr("services.sphinx_services.ensure_github_branch", lambda *a, **k: True)
    monkeypatch.setattr("services.sphinx_services.configure_github_pages", lambda *a, **k: True)
    monkeypatch.setattr("services.sphinx_services.download_github_branch_snapshot", lambda *a, **k: True)

    with pytest.raises(PublishPagesError) as exc_info:
        publish_github_pages("octo-org/example-repo", "main", "secret")
    assert exc_info.value.status_code == 422
