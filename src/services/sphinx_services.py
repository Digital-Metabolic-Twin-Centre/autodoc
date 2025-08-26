import os
import pandas as pd
import urllib

import requests
from config.config import AUTOAPI_DIRECTORY, CONFIGURATION_UPDATE_FILE, GITLAB_API_URL, GITLAB_YML_FILE, PROJECT_AUTHOR
from config.config import DOCS_SRC, BUILD_DIR, CONF_PY, PIPELINE_USERNAME, PIPELINE_EMAIL, PROJECT_NAME
from config.log_config import get_logger
from utils.git_utils import create_directory_and_add_files, create_a_file
from utils.generate_yml_content import generate_gitlab_ci_file

logger = get_logger(__name__)

def create_sphinx_setup(provider, repo_url, token, branch, docstring_analysis_file):

    #FETCH FILES WITH NO MISSING DOCSTRING
    files_with_all_docstrings = []
    df = pd.read_csv(docstring_analysis_file)
    for file_path, group in df.groupby('file_path'):
        if (~group['missing_docstring']).all():
            files_with_all_docstrings.append(file_path)
    logger.info(f"Files with all docstrings: {files_with_all_docstrings}")

    #CREATE DIRECTORY AND ADD FILES WITH NO MISSING DOCSTRINGS
    dir = create_directory_and_add_files(repo_url, AUTOAPI_DIRECTORY, files_with_all_docstrings, branch, token, provider)
    if not dir:
        logger.error("Directory creation failed.")
        return False

    #CREATE A FILE TO UPDATE CONF.PY FILE FOR SPHINX AUTOAPI
    conf_file_path = os.path.join(os.path.dirname(__file__), '..', 'utils', 'update_conf_content.py')
    conf_file_path = os.path.abspath(conf_file_path)
    with open(conf_file_path, "r") as f:
        conf_content = f.read()
    config_file_created = create_a_file(repo_url, branch, CONFIGURATION_UPDATE_FILE, conf_content, token, provider)
    if not config_file_created:
        logger.error(f"{CONFIGURATION_UPDATE_FILE} file creation failed.")
        return False

    if provider == "gitlab":
        #CREATE A .gitlab-ci.yml FILE
        gitlab_ci_content = generate_gitlab_ci_file()
        yml_file_created = create_a_file(repo_url, branch, GITLAB_YML_FILE, gitlab_ci_content, token, provider)
        if not yml_file_created:
            logger.error(f"{GITLAB_YML_FILE} file creation failed.")
            return False
        logger.info(f"{GITLAB_YML_FILE} file created successfully.")

        #Trigger GitLab pipeline
        variables = {
            "DOCS_SRC": DOCS_SRC,
            "BUILD_DIR": BUILD_DIR,
            "CONF_PY": CONF_PY,
            "PROJECT_NAME": PROJECT_NAME,
            "PROJECT_AUTHOR": PROJECT_AUTHOR,
            "GIT_USER_EMAIL": PIPELINE_EMAIL,
            "GIT_USER_NAME": PIPELINE_USERNAME
        }
        success = trigger_gitlab_pipeline(repo_url, branch, token, variables)
        if not success:
            logger.error("GitLab pipeline trigger failed.")
            return False
        print("Pipeline triggered successfully!")
        return True
    #logic for github actions similar to pipeline in gitlab

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
    trigger_token = os.getenv('CI_TRIGGER_PIPELINE_TOKEN')

    data = {
        "token": trigger_token,
        "ref": branch
    }

    if variables:
        for key, value in variables.items():
            data[f"variables[{key}]"] = value
            

    try:
        response = requests.post(api_url, headers=headers, data=data, timeout=10)
        if response.status_code in (200, 201):
            print(f"Pipeline triggered for {repo_url} on branch {branch}.")
            return True
        else:
            print(f"Failed to trigger pipeline: {response.text}")
            print(response.reason)
            return False
    except Exception as e:
        print(f"Exception while triggering pipeline: {e}")
        return False