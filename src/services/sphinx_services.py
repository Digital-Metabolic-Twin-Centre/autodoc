import os
import subprocess
import sys
import tempfile
import urllib

import pandas as pd
import requests

from config.config import (
    AUTOAPI_DIRECTORY,
    BUILD_DIR,
    CONF_PY,
    CONFIGURATION_UPDATE_FILE,
    DOCS_SRC,
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
from config.log_config import get_logger
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


def create_sphinx_setup(provider, repo_url, token, branch, docstring_analysis_file):

    # Extract repo path from URL
    repo_path = extract_repo_path(repo_url, provider)
    logger.info(f"Extracted repo path: {repo_path}")

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

    pages_branch_ready = ensure_github_branch(repo_path, source_branch, GITHUB_PAGES_BRANCH, token)
    if not pages_branch_ready:
        logger.error("GitHub Pages branch setup failed.")
        return False

    pages_configured = configure_github_pages(
        repo_path, GITHUB_PAGES_BRANCH, token, path=GITHUB_PAGES_PATH
    )
    if not pages_configured:
        logger.error("GitHub Pages configuration failed.")
        return False

    with tempfile.TemporaryDirectory(prefix="autodoc-pages-") as temp_dir:
        snapshot_downloaded = download_github_branch_snapshot(
            repo_path, source_branch, token, temp_dir
        )
        if not snapshot_downloaded:
            logger.error("Downloading reviewed GitHub branch failed.")
            return False

        conf_py_path = os.path.join(temp_dir, CONF_PY)
        docs_source_dir = os.path.join(temp_dir, DOCS_SRC)
        build_dir = os.path.join(temp_dir, BUILD_DIR)
        update_conf_path = os.path.join(temp_dir, CONFIGURATION_UPDATE_FILE)

        os.makedirs(docs_source_dir, exist_ok=True)

        if not os.path.exists(conf_py_path):
            quickstart_cmd = [
                sys.executable,
                "-m",
                "sphinx.cmd.quickstart",
                "--quiet",
                "--project",
                PROJECT_NAME,
                "--author",
                PROJECT_AUTHOR,
                "--sep",
                "--makefile",
                "--batchfile",
                "--ext-autodoc",
                "docs",
            ]
            quickstart_result = subprocess.run(
                quickstart_cmd,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if quickstart_result.returncode != 0:
                logger.error("Sphinx quickstart failed: %s", quickstart_result.stderr)
                return False

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
                return False

        build_result = subprocess.run(
            [sys.executable, "-m", "sphinx", "-W", "-b", "html", DOCS_SRC, BUILD_DIR],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if build_result.returncode != 0:
            logger.error("Sphinx build failed: %s", build_result.stderr)
            return False

        if not os.path.isdir(build_dir):
            logger.error("Sphinx build did not produce %s.", BUILD_DIR)
            return False

        published = publish_local_directory_to_github_branch(
            repo_path,
            build_dir,
            GITHUB_PAGES_BRANCH,
            token,
            source_branch_for_seed=source_branch,
        )
        if not published:
            logger.error("Publishing built docs to GitHub Pages branch failed.")
            return False

    request_github_pages_build(repo_path, token)
    logger.info("Published reviewed docs from %s to %s.", source_branch, GITHUB_PAGES_BRANCH)
    return True


def trigger_gitlab_pipeline(repo_url: str, branch: str, token: str, variables: dict = None) -> bool:
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
    project_path_encoded = urllib.parse.quote_plus(repo_url)
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
