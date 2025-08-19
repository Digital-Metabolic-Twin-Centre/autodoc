import os
import requests
import fnmatch
import urllib.parse
import gitlab
from typing import List, Dict, Optional, Tuple
from config.config import GITHUB_API_URL, GITLAB_API_URL, STACK_FILES
from config.log_config import get_logger

logger = get_logger(__name__)

def get_gitignore_patterns(repo_path: str, access_token: str, branch: str = "main", provider: str = "github") -> List[str]:
    """
    Fetches .gitignore file from the repository and returns a list of patterns to ignore.

    Args:
        repo_path (str): Repository path (e.g., 'user/repo').
        access_token (str): Authentication token.
        branch (str, optional): Branch name. Defaults to "main".
        provider (str, optional): Git provider ("github" or "gitlab"). Defaults to "github".

    Returns:
        List[str]: List of ignore patterns from .gitignore.
    """

    if provider == "github":
        content = fetch_content_from_github(repo_path, branch, ".gitignore", access_token)
    elif provider == "gitlab":
        content = fetch_content_from_gitlab(repo_path, branch, ".gitignore", access_token)
    else:
        return []
    
    if not content:
        return []
    patterns = []
    for line in content.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def should_ignore(name: str, patterns: List[str]) -> bool:
    """
    Checks if a file or directory name matches any ignore pattern.

    Args:
        name (str): File or directory name.
        patterns (List[str]): List of ignore patterns.

    Returns:
        bool: True if the name should be ignored, False otherwise.
    """

    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name + "/", pattern):
            return True
    return False


def fetch_content_from_github(repo_path: str, branch: str, file_path: str, access_token: str) -> Optional[str]:
    """
    Fetches the raw content of a file from a GitHub repository.

    Args:
        repo_path (str): Repository path (e.g., 'user/repo').
        branch (str): Branch name.
        file_path (str): Path to the file in the repository.
        access_token (str): GitHub access token.

    Returns:
        Optional[str]: Raw file content if successful, None otherwise.
    """

    url = f"{GITHUB_API_URL}/repos/{repo_path}/contents/{file_path}"
    
    try:
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3.raw"
            },
            params={"ref": branch},
            timeout=10
        )
        response.raise_for_status()
        return response.text if response.text else None
    except Exception as e:
        logger.error(f"GitHub fetch error: {e}")
    return None


def fetch_content_from_gitlab(repo_path: str, branch: str, file_path: str, private_token: str) -> Optional[str]:
    """
    Fetches the raw content of a file from a GitLab repository.

    Args:
        repo_path (str): Repository path.
        branch (str): Branch name.
        file_path (str): Path to the file in the repository.
        private_token (str): GitLab private token.

    Returns:
        Optional[str]: Raw file content if successful, None otherwise.
    """

    project_path_encoded = urllib.parse.quote_plus(repo_path)
    file_path_encoded = urllib.parse.quote_plus(file_path)
    url = f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/files/{file_path_encoded}/raw"
    
    try:
        response = requests.get(
            url,
            headers={"PRIVATE-TOKEN": private_token},
            params={"ref": branch},
            timeout=10
        )
        response.raise_for_status()
        return response.text if response.text else None
    except Exception as e:
        logger.error(f"GitLab fetch error: {e}")
    return None


def fetch_repo_tree(repo_path: str, access_token: str, branch: str = "main", provider: str = "github") -> List[Dict]:
    """
    Recursively fetches the file and directory tree for a given repository and branch.

    Args:
        repo_path (str): Repository path.
        access_token (str): Authentication token.
        branch (str, optional): Branch name. Defaults to "main".
        provider (str, optional): Git provider ("github" or "gitlab"). Defaults to "github".

    Returns:
        List[Dict]: List of files and directories in the repository.
    """

    repository_files = []
    gitignore_patterns = get_gitignore_patterns(repo_path, access_token, branch, provider)
    logger.info(f"Gitignore patterns: {gitignore_patterns}")

    def _fetch_tree(path: str = "") -> List[Dict]:

        if provider == "github":
            url = f"{GITHUB_API_URL}/repos/{repo_path}/contents/{path}"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            params = {"ref": branch}
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                items = response.json()
                if isinstance(items, dict):
                    items = [items]
            except Exception as e:
                logger.error(f"GitHub tree fetch error: {e}")
                return []
        elif provider == "gitlab":
            gl = gitlab.Gitlab(GITLAB_API_URL, private_token=access_token)
            try:
                project = gl.projects.get(repo_path)
                items = project.repository_tree(path=path, ref=branch)
            except Exception as e:
                logger.error(f"GitLab tree fetch error: {e}")
                return []
        else:
            return []

        all_files = []
        for item in items:
            if should_ignore(item['name'], gitignore_patterns):
                continue
            if item.get('type') in ['dir', 'tree']:
                sub_items = _fetch_tree(os.path.join(path, item['name']) if path else item['name'])
                all_files.extend(sub_items)
            elif item.get('type') in ['file', 'blob']:
                all_files.append(item)
        return all_files

    try:
        repository_files = _fetch_tree()
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    return repository_files

def detect_tech_stack(files: List[Dict]) -> str:
    """
    Detects the technology stack of a repository based on its files.

    Args:
        files (List[Dict]): List of file dictionaries from the repository.

    Returns:
        str: Detected technology stack (e.g., "python"), or "Unknown" if not detected.
    """

    if not files or not all('name' in file for file in files):
        return "Unknown"
    file_names = [file['name'] for file in files]
    stack_files = STACK_FILES
    for filename, tech in stack_files.items():
        if filename in file_names:
            return tech

    return "Unknown"

def validate_docstring(tech_stack: str, repo_path: str, branch: str, file_path: str, access_token: str, provider: str = "github") -> Optional[Tuple[bool, List[Dict[str, str]], List[Dict[str, str]]]]:
    """
    Validates the presence of docstring in a file based on its technology stack.

    Args:
        tech_stack (str): Technology stack (e.g., "python").
        repo_path (str): Repository path.
        branch (str): Branch name.
        file_path (str): Path to the file in the repository.
        access_token (str): Authentication token.
        provider (str, optional): Git provider ("github" or "gitlab"). Defaults to "github".

    Returns:
        Optional[Tuple[bool, List[Dict[str, str]], List[Dict[str, str]]]]:
            - bool: True if docstring is present, False otherwise.
            - List[Dict[str, str]]: Items missing docstring.
            - List[Dict[str, str]]: Items with docstring.
    """

    file_name = os.path.basename(file_path)
    if provider == "github":
        content = fetch_content_from_github(repo_path, branch, file_path, access_token)
    elif provider == "gitlab":
        content = fetch_content_from_gitlab(repo_path, branch, file_path, access_token)
    else:
        content = None
    if content is None or content == "":
        logger.warning(f"Empty file {file_name}. Cannot validate docstring.")
        return False, None, None
    if tech_stack.lower() == "python":
        python_validator = docstring_validation(content, file_name)
        return python_validator.python_validate_docstring()
    logger.warning("Unknown technology stack. Cannot validate docstring.")
    return False, None, None