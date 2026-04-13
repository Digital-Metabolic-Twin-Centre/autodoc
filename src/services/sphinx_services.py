import os
import urllib

import pandas as pd
import requests

from config.config import (
    AUTOAPI_DIRECTORY,
    BUILD_DIR,
    CONF_PY,
    CONFIGURATION_UPDATE_FILE,
    DOCS_SRC,
    GITHUB_ACTIONS_FILE,
    GITLAB_API_URL,
    GITLAB_YML_FILE,
    PIPELINE_EMAIL,
    PIPELINE_USERNAME,
    PROJECT_AUTHOR,
    PROJECT_NAME,
)
from config.log_config import get_logger
from utils.generate_yml_content import (
    generate_github_actions_file,
    generate_gitlab_ci_file,
)
from utils.git_utils import (
    create_a_file,
    create_directory_and_add_files,
    extract_repo_path,
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
        github_actions_content = generate_github_actions_file()
        workflow_file_created = create_a_file(
            repo_path,
            branch,
            GITHUB_ACTIONS_FILE,
            github_actions_content,
            token,
            provider,
        )
        if not workflow_file_created:
            logger.error(f"{GITHUB_ACTIONS_FILE} file creation failed.")
            return False
        logger.info(f"{GITHUB_ACTIONS_FILE} file created successfully.")
        return True

    logger.error(f"Unsupported provider for Sphinx setup: {provider}")
    return False


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
