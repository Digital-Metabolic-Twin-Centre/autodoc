import os
import re
import subprocess
import sys
import tempfile
from ast import (
    AsyncFunctionDef,
    ClassDef,
    FunctionDef,
    ImportFrom,
    Module,
    parse,
)
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import requests

from config.config import (
    AUTOAPI_DIRECTORY,
    BUILD_DIR,
    CONF_PY,
    CONFIGURATION_UPDATE_FILE,
    DOCS_SRC,
    GITHUB_API_URL,
    GITHUB_PAGES_BRANCH,
    GITHUB_PAGES_PATH,
    GITHUB_PAGES_README_FILE,
    GITLAB_API_URL,
    GITLAB_YML_FILE,
    PIPELINE_EMAIL,
    PIPELINE_USERNAME,
    PROJECT_AUTHOR,
    PROJECT_NAME,
)
from config.log_config import get_logger, get_run_log_dir
from utils.generate_yml_content import (
    generate_github_pages_readme,
    generate_gitlab_ci_file,
)
from utils.git_utils import (
    configure_github_pages,
    create_a_file,
    create_directory_and_add_files,
    download_github_branch_snapshot,
    ensure_github_branch,
    extract_repo_path,
    publish_local_directory_to_github_branch,
    request_github_pages_build,
)

logger = get_logger(__name__)
DOCS_SCAFFOLD_DIR = Path(__file__).resolve().parents[2] / "docs" / "scaffold"
SAMPLE_DOCS_FALLBACK_TEXTS = {
    "conf.py": (
        'from datetime import datetime\n\n'
        'project = "Student Project Documentation"\n'
        'author = "Digital Metabolic Twin Centre"\n'
        'copyright = f"{datetime.now().year}, {author}"\n\n'
        "extensions = [\n"
        '    "sphinx.ext.autodoc",\n'
        '    "sphinx.ext.napoleon",\n'
        "]\n\n"
        'templates_path = ["_templates"]\n'
        'exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]\n\n'
        'html_theme = "sphinx_rtd_theme"\n'
        'html_static_path = ["_static"]\n'
        'html_css_files = ["custom-wide.css"]\n'
    ),
    "index.rst": (
        "Student Project Documentation\n"
        "=============================\n\n"
        "Welcome to your project docs.\n\n"
        ".. toctree::\n"
        "   :maxdepth: 1\n"
        "   :caption: Project\n\n"
        "   project/overview\n"
        "   project/objectives\n"
        "   project/plan\n"
        "   project/results\n\n"
        ".. toctree::\n"
        "   :maxdepth: 1\n"
        "   :caption: Progress\n\n"
        "   logbook/weekly_updates\n\n"
        ".. toctree::\n"
        "   :maxdepth: 1\n"
        "   :caption: Notes\n\n"
        "   README\n"
    ),
    "project/overview.rst": (
        "Project Overview\n"
        "================\n\n"
        "- Project title: <replace>\n"
        "- Student name: <replace>\n"
        "- Supervisor: <replace>\n"
        "- One-paragraph summary: <replace>\n"
    ),
    "project/objectives.rst": (
        "Objectives\n"
        "==========\n\n"
        "- Objective 1: <replace>\n"
        "- Objective 2: <replace>\n"
        "- Objective 3: <replace>\n\n"
        "Success criteria\n"
        "----------------\n\n"
        "- Criterion 1: <replace>\n"
        "- Criterion 2: <replace>\n"
    ),
    "project/plan.rst": (
        "Project Plan\n"
        "============\n\n"
        "1. Discovery and setup\n"
        "2. Design and implementation\n"
        "3. Testing and evaluation\n"
        "4. Final report and demo\n\n"
        "Milestones\n"
        "----------\n\n"
        "+-----------+------------+------------+\n"
        "| Milestone | Start date | End date   |\n"
        "+===========+============+============+\n"
        "| M1        | <replace>  | <replace>  |\n"
        "+-----------+------------+------------+\n"
        "| M2        | <replace>  | <replace>  |\n"
        "+-----------+------------+------------+\n"
    ),
    "project/results.rst": (
        "Results\n"
        "=======\n\n"
        "- Deliverable 1: <replace>\n"
        "- Deliverable 2: <replace>\n"
        "- Key findings: <replace>\n"
        "- Lessons learned: <replace>\n"
    ),
    "logbook/weekly_updates.rst": (
        "Weekly Updates\n"
        "==============\n\n"
        "Week of <YYYY-MM-DD>\n"
        "--------------------\n\n"
        "- Goals:\n"
        "- Work done:\n"
        "- Problems faced:\n"
        "- Next steps:\n"
    ),
    "_static/custom-wide.css": (
        ".wy-nav-content {\n"
        "    max-width: none !important;\n"
        "    width: 100% !important;\n"
        "    margin: 0 !important;\n"
        "}\n"
    ),
}
AUTOAPI_CONF_MARKER_START = "# AUTODOC AUTOAPI RUNTIME SETTINGS START"
AUTOAPI_CONF_MARKER_END = "# AUTODOC AUTOAPI RUNTIME SETTINGS END"
AUTOAPI_WARNINGS_TO_SUPPRESS = ["autoapi.python_import_resolution"]
DEFAULT_AUTOAPI_IGNORE_PATTERNS = [
    "*/migrations/*",
    "*/migrations.py",
    "*/tests/*",
    "*/test_*.py",
    "*/urls.py",
    "*/urls_*.py",
    "*/views.py",
    "*/views_*.py",
    "*/settings.py",
    "*/settings_*.py",
    "*/asgi.py",
    "*/wsgi.py",
]
RISKY_AUTOAPI_PATH_PATTERNS = [
    re.compile(r"(^|/)migrations/"),
    re.compile(r"(^|/)migrations\.py$"),
    re.compile(r"(^|/)tests?/"),
    re.compile(r"(^|/)urls(_v\d+)?\.py$"),
    re.compile(r"(^|/)views?(_.*)?\.py$"),
    re.compile(r"(^|/)settings?(_.*)?\.py$"),
    re.compile(r"(^|/)(asgi|wsgi)\.py$"),
]
LOW_CONTENT_MIN_MEANINGFUL_LINES = 8


class PublishPagesError(RuntimeError):
    """Raised when a GitHub Pages publish step fails."""


def _raise_publish_error(message: str) -> None:
    logger.error(message)
    raise PublishPagesError(message)


def _extract_autoapi_module_names(build_output: str) -> list[str]:
    module_names = re.findall(r"module '([^']+)'", build_output or "")
    module_names.extend(
        match.replace("/", ".")
        for match in re.findall(r"autoapi/([A-Za-z0-9_./-]+)/index\.rst", build_output or "")
    )
    unique_module_names = []
    seen = set()
    for module_name in module_names:
        if module_name in seen:
            continue
        seen.add(module_name)
        unique_module_names.append(module_name)
    return unique_module_names


def _extract_module_name_from_autoapi_path(autoapi_root: Path, file_path: Path) -> str:
    relative_file = file_path.relative_to(autoapi_root).as_posix()
    if relative_file.endswith("/__init__.py"):
        return relative_file[: -len("/__init__.py")].replace("/", ".")
    if relative_file.endswith(".py"):
        return relative_file[:-3].replace("/", ".")
    return relative_file.replace("/", ".")


def _to_autoapi_ignore_pattern(relative_file: str) -> str:
    return f"*/{relative_file.lstrip('/')}"


def _classify_autoapi_file(autoapi_root: Path, file_path: Path) -> tuple[bool, str]:
    relative_file = file_path.relative_to(autoapi_root).as_posix()
    for pattern in RISKY_AUTOAPI_PATH_PATTERNS:
        if pattern.search(relative_file):
            return False, f"path-pattern:{pattern.pattern}"

    file_text = file_path.read_text(encoding="utf-8")
    try:
        parsed: Module = parse(file_text)
    except SyntaxError:
        return False, "syntax-error"

    if any(
        isinstance(node, ImportFrom) and any(alias.name == "*" for alias in node.names)
        for node in parsed.body
    ):
        return False, "import-star"

    meaningful_lines = [line for line in file_text.splitlines() if line.strip()]
    if len(meaningful_lines) < LOW_CONTENT_MIN_MEANINGFUL_LINES:
        return False, "low-content"

    has_public_shape = any(
        isinstance(node, (FunctionDef, AsyncFunctionDef, ClassDef)) for node in parsed.body
    )
    if not has_public_shape:
        return False, "non-meaningful-module"

    return True, "included"


def _find_autoapi_skip_candidates(temp_dir: str, module_name: str) -> list[Path]:
    autoapi_root = Path(temp_dir) / AUTOAPI_DIRECTORY
    if not autoapi_root.exists():
        return []
    normalized_module_path = module_name.replace(".", "/")
    path_candidates = [
        autoapi_root / f"{normalized_module_path}.py",
        autoapi_root / normalized_module_path / "__init__.py",
    ]
    existing_path_candidates = [candidate for candidate in path_candidates if candidate.exists()]
    if existing_path_candidates:
        return existing_path_candidates
    module_leaf = module_name.split(".")[-1]
    matches = []
    for path in autoapi_root.rglob("*.py"):
        if path.stem == module_leaf:
            matches.append(path)
    return matches


def _collect_prebuild_autoapi_ignores(temp_dir: str) -> tuple[list[str], list[dict[str, str]]]:
    autoapi_root = Path(temp_dir) / AUTOAPI_DIRECTORY
    if not autoapi_root.exists():
        return [], []

    ignore_patterns: list[str] = []
    skipped_files: list[dict[str, str]] = []
    for file_path in autoapi_root.rglob("*.py"):
        should_include, reason = _classify_autoapi_file(autoapi_root, file_path)
        if should_include:
            continue
        relative_file = file_path.relative_to(autoapi_root).as_posix()
        module_name = _extract_module_name_from_autoapi_path(autoapi_root, file_path)
        ignore_patterns.append(_to_autoapi_ignore_pattern(relative_file))
        skipped_files.append(
            {
                "file": f"{AUTOAPI_DIRECTORY}/{relative_file}",
                "module": module_name,
                "reason": reason,
            }
        )
    return ignore_patterns, skipped_files


def _module_names_to_ignore_patterns(
    temp_dir: str, module_names: list[str]
) -> tuple[list[str], list[dict[str, str]]]:
    autoapi_root = Path(temp_dir) / AUTOAPI_DIRECTORY
    if not autoapi_root.exists():
        return [], []

    ignore_patterns: list[str] = []
    skipped_files: list[dict[str, str]] = []
    for module_name in module_names:
        for candidate in _find_autoapi_skip_candidates(temp_dir, module_name):
            relative_file = candidate.relative_to(autoapi_root).as_posix()
            ignore_patterns.append(_to_autoapi_ignore_pattern(relative_file))
            skipped_files.append(
                {
                    "file": f"{AUTOAPI_DIRECTORY}/{relative_file}",
                    "module": module_name,
                    "reason": "fallback-module-failure",
                }
            )
    return ignore_patterns, skipped_files


def _format_python_list(values: list[str]) -> str:
    return "[\n" + "".join(f"    {value!r},\n" for value in values) + "]"


def _apply_autoapi_runtime_settings(conf_py_path: str, ignore_patterns: list[str]) -> None:
    conf_path = Path(conf_py_path)
    if not conf_path.exists():
        return

    unique_ignores = sorted(set(DEFAULT_AUTOAPI_IGNORE_PATTERNS + ignore_patterns))
    runtime_block = (
        f"{AUTOAPI_CONF_MARKER_START}\n"
        f"autoapi_ignore = {_format_python_list(unique_ignores)}\n"
        f"suppress_warnings = {_format_python_list(AUTOAPI_WARNINGS_TO_SUPPRESS)}\n"
        f"{AUTOAPI_CONF_MARKER_END}\n"
    )
    conf_text = conf_path.read_text(encoding="utf-8")
    marker_pattern = re.compile(
        rf"{re.escape(AUTOAPI_CONF_MARKER_START)}.*?{re.escape(AUTOAPI_CONF_MARKER_END)}\n?",
        flags=re.DOTALL,
    )
    if marker_pattern.search(conf_text):
        conf_text = marker_pattern.sub(runtime_block, conf_text)
    else:
        conf_text = conf_text.rstrip() + "\n\n" + runtime_block
    conf_path.write_text(conf_text, encoding="utf-8")


def _build_sphinx_once(temp_dir: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "sphinx", "-b", "html", DOCS_SRC, BUILD_DIR],
        cwd=temp_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _write_skipped_autoapi_report(skipped_files: list[dict]) -> None:
    if not skipped_files:
        return
    run_log_dir = get_run_log_dir()
    if not run_log_dir:
        return
    report_path = Path(run_log_dir) / "skipped_autoapi_files.txt"
    with open(report_path, "w", encoding="utf-8") as report_file:
        report_file.write("Skipped AutoAPI Files\n")
        report_file.write("=====================\n\n")
        for item in skipped_files:
            report_file.write(f"- file: {item['file']}\n")
            report_file.write(f"  module: {item['module']}\n")
            report_file.write(f"  reason: {item['reason']}\n\n")


def _run_sphinx_build_with_autoapi_filters(temp_dir: str, conf_py_path: str) -> subprocess.CompletedProcess:
    prebuild_ignore_patterns, prebuild_skipped = _collect_prebuild_autoapi_ignores(temp_dir)
    active_ignore_patterns = list(prebuild_ignore_patterns)
    skipped_files = list(prebuild_skipped)

    logger.info(
        "AutoAPI pre-filter completed: included rules=%s, proactively skipped files=%s.",
        len(sorted(set(DEFAULT_AUTOAPI_IGNORE_PATTERNS + active_ignore_patterns))),
        len(prebuild_skipped),
    )
    _apply_autoapi_runtime_settings(conf_py_path, active_ignore_patterns)
    build_result = _build_sphinx_once(temp_dir)
    if build_result.returncode == 0:
        _write_skipped_autoapi_report(skipped_files)
        return build_result

    build_output = "\n".join(
        part for part in [build_result.stderr.strip(), build_result.stdout.strip()] if part
    )
    failed_modules = _extract_autoapi_module_names(build_output)
    fallback_ignore_patterns, fallback_skipped = _module_names_to_ignore_patterns(
        temp_dir, failed_modules
    )
    new_fallback_ignores = sorted(set(fallback_ignore_patterns) - set(active_ignore_patterns))
    if not new_fallback_ignores:
        _write_skipped_autoapi_report(skipped_files)
        return build_result

    skipped_files.extend(
        item
        for item in fallback_skipped
        if _to_autoapi_ignore_pattern(item["file"].replace(f"{AUTOAPI_DIRECTORY}/", ""))
        in new_fallback_ignores
    )
    active_ignore_patterns.extend(new_fallback_ignores)
    logger.warning(
        "AutoAPI fallback activated. Added %s module ignores after initial Sphinx failure.",
        len(new_fallback_ignores),
    )
    _apply_autoapi_runtime_settings(conf_py_path, active_ignore_patterns)
    retry_result = _build_sphinx_once(temp_dir)
    _write_skipped_autoapi_report(skipped_files)
    return retry_result


def _project_name_from_repo_path(repo_path: str) -> str:
    repo_name = repo_path.rstrip("/").split("/")[-1]
    name = repo_name.replace("-", " ").replace("_", " ").strip()
    return name.title() if name else PROJECT_NAME


def _load_sample_text(relative_path: str) -> str:
    sample_path = DOCS_SCAFFOLD_DIR / relative_path
    if sample_path.exists():
        return sample_path.read_text(encoding="utf-8")

    fallback_text = SAMPLE_DOCS_FALLBACK_TEXTS.get(relative_path)
    if fallback_text is not None:
        return fallback_text

    raise FileNotFoundError(f"Missing sample template for {relative_path}: {sample_path}")


def _build_sample_conf(project_name: str) -> str:
    conf_text = _load_sample_text("conf.py")
    conf_text = re.sub(
        r'project\s*=\s*"[^"]+"',
        f'project = "{project_name}"',
        conf_text,
        count=1,
    )
    if '"autoapi.extension"' not in conf_text and "'autoapi.extension'" not in conf_text:
        conf_text = conf_text.replace(
            '"sphinx.ext.napoleon",',
            '"sphinx.ext.napoleon",\n    "autoapi.extension",',
        )
    additions = [
        'autoapi_type = "python"',
        'autoapi_dirs = ["../../autoapi_include"]',
        "autoapi_keep_files = False",
        "autoapi_generate_api_docs = True",
    ]
    if not all(addition in conf_text for addition in additions):
        conf_text += "\n\n" + "\n".join(
            addition for addition in additions if addition not in conf_text
        ) + "\n"
    return conf_text


def _build_sample_index(project_name: str) -> str:
    index_text = _load_sample_text("index.rst")
    lines = index_text.splitlines()
    if len(lines) >= 2:
        lines[0] = project_name
        lines[1] = "=" * len(project_name)
    index_text = "\n".join(lines).rstrip() + "\n"
    if "autoapi/index" not in index_text:
        index_text += (
            "\n.. toctree::\n"
            "   :maxdepth: 1\n"
            "   :caption: API Reference\n\n"
            "   autoapi/index\n"
        )
    return index_text


def _build_sample_overview(project_name: str) -> str:
    overview_text = _load_sample_text("project/overview.rst")
    return overview_text.replace("<replace>", project_name, 1)


def _build_sample_makefile() -> str:
    return (
        "SPHINXBUILD   = sphinx-build\n"
        "SOURCEDIR     = source\n"
        "BUILDDIR      = build\n\n"
        ".PHONY: help clean html\n\n"
        "help:\n"
        '\t@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)"\n\n'
        "clean:\n"
        "\trm -rf build/*\n\n"
        "html:\n"
        '\t$(SPHINXBUILD) -b html "$(SOURCEDIR)" "$(BUILDDIR)/html"\n'
    )


def _build_sample_readme() -> str:
    return (
        "Documentation Notes\n"
        "===================\n\n"
        "These pages are written in reStructuredText (`.rst`) and built by Sphinx.\n\n"
        "Local preview\n"
        "-------------\n\n"
        ".. code-block:: bash\n\n"
        "   cd docs\n"
        "   python -m pip install sphinx sphinx-autoapi sphinx-rtd-theme\n"
        "   make html\n\n"
        "Open ``docs/build/html/index.html`` in your browser.\n"
    )


def _sample_docs_files(project_name: str) -> dict[str, str]:
    return {
        "docs/Makefile": _build_sample_makefile(),
        CONF_PY: _build_sample_conf(project_name),
        f"{DOCS_SRC}/index.rst": _build_sample_index(project_name),
        f"{DOCS_SRC}/README.rst": _build_sample_readme(),
        f"{DOCS_SRC}/project/overview.rst": _build_sample_overview(project_name),
        f"{DOCS_SRC}/project/objectives.rst": _load_sample_text("project/objectives.rst"),
        f"{DOCS_SRC}/project/plan.rst": _load_sample_text("project/plan.rst"),
        f"{DOCS_SRC}/project/results.rst": _load_sample_text("project/results.rst"),
        f"{DOCS_SRC}/logbook/weekly_updates.rst": _load_sample_text("logbook/weekly_updates.rst"),
        f"{DOCS_SRC}/_static/custom-wide.css": _load_sample_text("_static/custom-wide.css"),
    }


def _remote_text_file_exists(
    repo_path: str,
    branch: str,
    file_path: str,
    token: str,
    provider: str,
) -> bool:
    normalized_provider = provider.lower()
    if normalized_provider == "github":
        return (
            requests.get(
                f"{GITHUB_API_URL}/repos/{repo_path}/contents/{file_path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                },
                params={"ref": branch},
                timeout=10,
            ).status_code
            == 200
        )
    project_path_encoded = quote_plus(repo_path)
    file_path_encoded = quote_plus(file_path)
    return (
        requests.get(
            (
                f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/files/"
                f"{file_path_encoded}"
            ),
            headers={"PRIVATE-TOKEN": token},
            params={"ref": branch},
            timeout=10,
        ).status_code
        == 200
    )


def _create_sample_sphinx_scaffold(
    repo_path: str,
    branch: str,
    token: str,
    provider: str,
    project_name: str,
) -> bool:
    for file_path, content in _sample_docs_files(project_name).items():
        if _remote_text_file_exists(repo_path, branch, file_path, token, provider):
            continue
        created = create_a_file(repo_path, branch, file_path, content, token, provider)
        if not created:
            logger.error("Failed to create sample scaffold file %s.", file_path)
            return False
    return True


def _write_sample_sphinx_scaffold(root_dir: str, project_name: str) -> None:
    for file_path, content in _sample_docs_files(project_name).items():
        destination = Path(root_dir) / file_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _ensure_sphinx_project_name(conf_py_path: str, project_name: str) -> None:
    if not os.path.exists(conf_py_path):
        return

    with open(conf_py_path, "r", encoding="utf-8") as conf_file:
        conf_text = conf_file.read()

    if re.search(r"project\s*=\s*['\"]Project_Name['\"]", conf_text):
        conf_text = re.sub(
            r"project\s*=\s*['\"]Project_Name['\"]",
            f'project = "{project_name}"',
            conf_text,
            count=1,
        )
        with open(conf_py_path, "w", encoding="utf-8") as conf_file:
            conf_file.write(conf_text)


def _ensure_api_index(index_path: str, project_name: str) -> None:
    default_markers = (
        "Add your content using ``reStructuredText`` syntax.",
        "Welcome to Project_Name's documentation!",
        "Welcome to Project Name's documentation!",
    )
    should_write = not os.path.exists(index_path)
    if not should_write:
        with open(index_path, "r", encoding="utf-8") as index_file:
            index_text = index_file.read()
        should_write = any(marker in index_text for marker in default_markers)

    if not should_write:
        return

    underline = "=" * len(project_name)
    content = f"""{project_name}
{underline}

API Reference
-------------

.. toctree::
   :maxdepth: 2

   autoapi/index
"""
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    with open(index_path, "w", encoding="utf-8") as index_file:
        index_file.write(content)


def create_sphinx_setup(provider, repo_url, token, branch, docstring_analysis_file):

    # Extract repo path from URL
    repo_path = extract_repo_path(repo_url, provider)
    logger.info(f"Extracted repo path: {repo_path}")
    project_name = _project_name_from_repo_path(repo_path)

    # FETCH FILES WITH COMPLETE OR HIGH DOCSTRING COVERAGE
    DOCSTRING_THRESHOLD = 0.75  # 75% threshold for including files
    files_with_all_docstrings = []
    files_with_high_coverage = []

    df = pd.read_csv(docstring_analysis_file)

    # Handle empty dataframe
    if df.empty:
        logger.warning("No files to analyze. Docstring analysis file is empty.")
        return False

    for file_path, group in df.groupby("file_path"):
        total = len(group)
        with_docs = (~group["missing_docstring"]).sum()
        coverage = with_docs / total if total > 0 else 0

        if coverage == 1.0:
            files_with_all_docstrings.append(file_path)
        elif coverage >= DOCSTRING_THRESHOLD:
            files_with_high_coverage.append(file_path)

    # Combine files with 100% and high coverage
    files_to_document = files_with_all_docstrings + files_with_high_coverage

    logger.info(
        "Files with 100%% docstrings (%s): %s",
        len(files_with_all_docstrings),
        files_with_all_docstrings,
    )
    logger.info(
        "Files with ≥%.0f%% docstrings (%s): %s",
        DOCSTRING_THRESHOLD * 100,
        len(files_with_high_coverage),
        files_with_high_coverage,
    )
    logger.info(f"Total files to document: {len(files_to_document)}")

    # Skip directory creation if no files meet criteria
    if not files_to_document:
        logger.warning(
            "No files with ≥%.0f%% docstring coverage found. "
            "Skipping Sphinx setup.",
            DOCSTRING_THRESHOLD * 100,
        )
        return False

    # CREATE DIRECTORY AND ADD FILES WITH ADEQUATE DOCSTRING COVERAGE
    dir = create_directory_and_add_files(
        repo_path, AUTOAPI_DIRECTORY, files_to_document, branch, token, provider
    )
    if not dir:
        logger.error("Directory creation failed.")
        return False

    scaffold_created = _create_sample_sphinx_scaffold(
        repo_path, branch, token, provider, project_name
    )
    if not scaffold_created:
        logger.error("Sample Sphinx scaffold creation failed.")
        return False

    # CREATE A FILE TO UPDATE CONF.PY FILE FOR SPHINX AUTOAPI
    conf_file_path = os.path.join(
        os.path.dirname(__file__), "..", "utils", "update_conf_content.py"
    )
    conf_file_path = os.path.abspath(conf_file_path)
    with open(conf_file_path, "r") as f:
        conf_content = f.read()
    config_file_created = create_a_file(
        repo_path, branch, CONFIGURATION_UPDATE_FILE, conf_content, token, provider
    )
    if not config_file_created:
        logger.error(f"{CONFIGURATION_UPDATE_FILE} file creation failed.")
        return False

    if provider == "gitlab":
        # CREATE A .gitlab-ci.yml FILE
        gitlab_ci_content = generate_gitlab_ci_file()
        yml_file_created = create_a_file(
            repo_path, branch, GITLAB_YML_FILE, gitlab_ci_content, token, provider
        )
        if not yml_file_created:
            logger.error(f"{GITLAB_YML_FILE} file creation failed.")
            return False
        logger.info(f"{GITLAB_YML_FILE} file created successfully.")

        # Trigger GitLab pipeline (optional)
        variables = {
            "DOCS_SRC": DOCS_SRC,
            "BUILD_DIR": BUILD_DIR,
            "CONF_PY": CONF_PY,
            "PROJECT_NAME": PROJECT_NAME,
            "PROJECT_AUTHOR": PROJECT_AUTHOR,
            "GIT_USER_EMAIL": PIPELINE_EMAIL,
            "GIT_USER_NAME": PIPELINE_USERNAME,
        }
        success = trigger_gitlab_pipeline(repo_path, branch, token, variables)
        if not success:
            logger.warning(
                "GitLab pipeline trigger failed. Pipeline must be triggered "
                "manually or CI_TRIGGER_PIPELINE_TOKEN environment variable "
                "is not set."
            )
        else:
            logger.info("Pipeline triggered successfully!")

        # Return True since Sphinx setup files were created successfully
        return True

    if provider == "github":
        pages_readme_created = create_a_file(
            repo_path,
            branch,
            GITHUB_PAGES_README_FILE,
            generate_github_pages_readme(branch, GITHUB_PAGES_BRANCH),
            token,
            provider,
        )
        if not pages_readme_created:
            logger.error("GitHub Pages publish guide creation failed.")
            return False

        logger.info(
            "GitHub repository prepared for manual review. Publish to %s after build review.",
            GITHUB_PAGES_BRANCH,
        )
        return True

    logger.error(f"Unsupported provider for Sphinx setup: {provider}")
    return False


def publish_github_pages(repo_url: str, source_branch: str, token: str) -> bool:
    """
    Publishes reviewed GitHub docs output from a source branch to gh-pages.
    """
    repo_path = extract_repo_path(repo_url, "github")
    project_name = _project_name_from_repo_path(repo_path)

    pages_branch_ready = ensure_github_branch(repo_path, source_branch, GITHUB_PAGES_BRANCH, token)
    if not pages_branch_ready:
        _raise_publish_error(
            "GitHub Pages branch setup failed. Check that the source branch exists and "
            "the token can read and write repository contents."
        )

    pages_configured = configure_github_pages(
        repo_path, GITHUB_PAGES_BRANCH, token, path=GITHUB_PAGES_PATH
    )
    if not pages_configured:
        _raise_publish_error(
            "GitHub Pages configuration failed. GitHub usually returns this when the "
            "token is missing Pages read/write access, the repository does not allow "
            "Pages configuration by that token, or the token owner lacks admin access "
            "to the repository."
        )

    with tempfile.TemporaryDirectory(prefix="autodoc-pages-") as temp_dir:
        snapshot_downloaded = download_github_branch_snapshot(
            repo_path, source_branch, token, temp_dir
        )
        if not snapshot_downloaded:
            _raise_publish_error(
                "Downloading the reviewed GitHub branch failed. Check that the branch "
                f"'{source_branch}' exists and the token can read repository contents."
            )

        conf_py_path = os.path.join(temp_dir, CONF_PY)
        docs_source_dir = os.path.join(temp_dir, DOCS_SRC)
        index_path = os.path.join(docs_source_dir, "index.rst")
        build_dir = os.path.join(temp_dir, BUILD_DIR)
        update_conf_path = os.path.join(temp_dir, CONFIGURATION_UPDATE_FILE)

        os.makedirs(docs_source_dir, exist_ok=True)

        if not os.path.exists(conf_py_path):
            _write_sample_sphinx_scaffold(temp_dir, project_name)

        if os.path.exists(update_conf_path):
            update_conf_result = subprocess.run(
                [sys.executable, update_conf_path, conf_py_path],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if update_conf_result.returncode != 0:
                logger.error("Updating conf.py failed: %s", update_conf_result.stderr)
                _raise_publish_error(
                    "Updating Sphinx conf.py failed: "
                    f"{update_conf_result.stderr.strip()}"
                )

        _ensure_sphinx_project_name(conf_py_path, project_name)
        _ensure_api_index(index_path, project_name)

        build_result = _run_sphinx_build_with_autoapi_filters(temp_dir, conf_py_path)
        if build_result.returncode != 0:
            build_output = "\n".join(
                part for part in [build_result.stderr.strip(), build_result.stdout.strip()] if part
            )
            logger.error("Sphinx build failed: %s", build_output)
            _raise_publish_error(f"Sphinx build failed: {build_output}")

        if not os.path.isdir(build_dir):
            _raise_publish_error(f"Sphinx build did not produce {BUILD_DIR}.")

        published = publish_local_directory_to_github_branch(
            repo_path,
            build_dir,
            GITHUB_PAGES_BRANCH,
            token,
            source_branch_for_seed=source_branch,
        )
        if not published:
            _raise_publish_error(
                "Publishing built docs to the GitHub Pages branch failed. Check that "
                "the token can write repository contents and the gh-pages branch is not protected."
            )

    request_github_pages_build(repo_path, token)
    logger.info("Published reviewed docs from %s to %s.", source_branch, GITHUB_PAGES_BRANCH)
    return True


def trigger_gitlab_pipeline(
    repo_url: str, branch: str, token: str, variables: dict[str, str] | None = None
) -> bool:
    """
    Triggers a GitLab pipeline for the given project and branch.

    Args:
        repo_url (str): The GitLab project path (e.g., 'namespace/project').
        branch (str): The branch to trigger the pipeline on.
        token (str): GitLab private token.
        variables (dict, optional): Pipeline variables.

    Returns:
        bool: True if the pipeline was triggered successfully, False otherwise.
    """
    project_path_encoded = quote_plus(repo_url)
    api_url = f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/trigger/pipeline"
    headers = {"PRIVATE-TOKEN": token}
    trigger_token = os.getenv("CI_TRIGGER_PIPELINE_TOKEN")

    data = {"token": trigger_token, "ref": branch}

    if variables:
        for key, value in variables.items():
            data[f"variables[{key}]"] = value

    if not trigger_token:
        logger.warning(
            "CI_TRIGGER_PIPELINE_TOKEN environment variable not set. Cannot trigger pipeline."
        )
        return False

    try:
        response = requests.post(api_url, headers=headers, data=data, timeout=10)
        if response.status_code in (200, 201):
            logger.info(f"Pipeline triggered for {repo_url} on branch {branch}.")
            return True
        else:
            logger.error(
                f"Failed to trigger pipeline: {response.text} (Status: {response.status_code})"
            )
            return False
    except Exception as e:
        logger.error(f"Exception while triggering pipeline: {e}")
        return False
