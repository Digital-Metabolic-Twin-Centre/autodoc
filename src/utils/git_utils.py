import base64
import fnmatch
import os
import shutil
import subprocess
import tempfile
import urllib.parse
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple

import gitlab
import requests

from config.config import GITHUB_API_URL, GITLAB_API_URL
from config.log_config import LOG_DIR, get_logger
from utils.code_block_extraction import GenericCodeBlockExtractor
from utils.docstring_validation import analyse_docstring_in_blocks

logger = get_logger(__name__)


class GitHubApiError(RuntimeError):
    """Raised when a GitHub API request fails."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        """
        Initializes an exception with a message and an optional status code.

            Args:
                message (str): The error message.
                status_code (Optional[int]): An optional status code associated with the error.

            Returns:
                None

        """
        super().__init__(message)
        self.status_code = status_code


class RepositoryAccessError(RuntimeError):
    """Raised when a repository or branch cannot be accessed for analysis."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        """
        Initializes an exception with a message and an optional status code.

            Args:
                message (str): The error message.
                status_code (Optional[int]): An optional status code associated with the error.

            Returns:
                None

        """
        super().__init__(message)
        self.status_code = status_code


def _github_headers(token: str, accept: str = "application/vnd.github+json") -> Dict[str, str]:
    """
    Generate headers for GitHub API requests.

    Args:
        token (str): The authentication token for GitHub API.
        accept (str): The media type to accept (default is 'application/vnd.github+json').

    Returns:
        Dict[str, str]: A dictionary containing the necessary headers for the request.

    """
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2026-03-10",
    }


def _parse_response_message(response) -> str:
    """
    Parse the response message from an HTTP response.

        Args:
            response (Response): The HTTP response object to parse.

        Returns:
            str: The parsed message or 'Unknown error' if not found.

    """
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])
    return response.text.strip() or "Unknown error"


def _raise_github_repository_access_error(response, repo_path: str, branch: str, path: str = "") -> None:
    """
    Raises a RepositoryAccessError based on the GitHub API response for a repository access attempt.

        Args:
            response: The API response object from GitHub.
            repo_path (str): The path of the GitHub repository.
            branch (str): The branch name to check.
            path (str, optional): The specific path in the repository.

        Returns:
            None: Raises an error if access is denied or repository is not found.

    """
    message = _parse_response_message(response)
    branch_label = branch or "<unspecified>"
    if response.status_code == 404:
        if "No commit found for the ref" in message:
            raise RepositoryAccessError(
                f"Branch '{branch_label}' was not found in GitHub repository '{repo_path}'.",
                status_code=404,
            )
        target = f"/{path}" if path else ""
        raise RepositoryAccessError(
            f"GitHub repository '{repo_path}'{target} was not found or is not accessible with this token.",
            status_code=404,
        )
    if response.status_code in {401, 403}:
        raise RepositoryAccessError(
            "GitHub rejected access to repository "
            f"'{repo_path}' on branch '{branch_label}'. Check that the token can read "
            "repository contents for this repo or fork.",
            status_code=response.status_code,
        )
    raise RepositoryAccessError(
        f"GitHub repository access failed for '{repo_path}' on branch '{branch_label}': {message}",
        status_code=response.status_code,
    )


def extract_repo_path(repo_url: str, provider: str = "github") -> str:
    """
    Extracts the repository path from a full URL.
    Args:
        repo_url (str): Full repository URL (e.g., 'https://github.com/user/repo' or 'user/repo').
        provider (str): Git provider ("github" or "gitlab").
    Returns:
        str: Repository path (e.g., 'user/repo').
    """
    if repo_url.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(repo_url)
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return path
    return repo_url


@contextmanager
def clone_repository(
    repo_url: str, token: str, branch: str = "main", provider: str = "github"
) -> Generator[str, None, None]:
    """
    Clone a repository to logs/.clones/ directory and yield the path.

    Automatically cleans up the temporary directory when done.

    Args:
        repo_url (str): Repository URL or path (e.g., 'user/repo' or 'https://github.com/user/repo').
        token (str): Authentication token (GitHub or GitLab).
        branch (str): Branch to clone. Defaults to 'main'.
        provider (str): Git provider ('github' or 'gitlab'). Defaults to 'github'.

    Yields:
        str: Path to the cloned repository directory.

    Raises:
        RepositoryAccessError: If clone fails.
    """
    # Convert repo path/URL to full clone URL
    if repo_url.startswith(("http://", "https://")):
        clone_url = repo_url
    else:
        if provider.lower() == "github":
            clone_url = f"https://github.com/{repo_url}.git"
        elif provider.lower() == "gitlab":
            clone_url = f"https://gitlab.com/{repo_url}.git"
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    # Use logs directory for clones instead of /tmp
    clones_dir = os.path.join(LOG_DIR, ".clones")
    os.makedirs(clones_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    temp_dir = os.path.join(clones_dir, f"clone_{timestamp}")

    try:
        logger.info(f"Cloning {clone_url} to {temp_dir}")

        # Clone with token authentication
        if provider.lower() == "github":
            git_url_with_token = clone_url.replace("https://", f"https://x-access-token:{token}@")
        elif provider.lower() == "gitlab":
            git_url_with_token = clone_url.replace("https://", f"https://oauth2:{token}@")
        else:
            git_url_with_token = clone_url

        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", branch, git_url_with_token, temp_dir],
            check=True,
            timeout=300,
            capture_output=True,
        )
        logger.info(f"Successfully cloned repository to {temp_dir}")
        yield temp_dir
    except subprocess.TimeoutExpired as e:
        raise RepositoryAccessError(
            f"Clone operation timed out after 300 seconds for {repo_url}",
            status_code=408,
        ) from e
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
        if "Repository not found" in error_msg or "not found" in error_msg.lower():
            raise RepositoryAccessError(
                f"Repository '{repo_url}' not found or is not accessible with provided token.",
                status_code=404,
            ) from e
        elif "authentication" in error_msg.lower() or "permission" in error_msg.lower():
            raise RepositoryAccessError(
                f"Authentication failed for repository '{repo_url}'. Check your token.",
                status_code=401,
            ) from e
        else:
            raise RepositoryAccessError(
                f"Failed to clone repository '{repo_url}': {error_msg}",
                status_code=400,
            ) from e
    except Exception as e:
        raise RepositoryAccessError(
            f"Unexpected error cloning repository '{repo_url}': {str(e)}",
            status_code=500,
        ) from e
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Cleaned up temporary directory {temp_dir}")
        _cleanup_old_clones()


def _cleanup_old_clones(keep_count: int = 10) -> None:
    """
    Clean up old clone directories, keeping only the most recent ones.

    Args:
       keep_count (int): Number of clones to keep. Defaults to 10.
    """
    clones_dir = os.path.join(LOG_DIR, ".clones")
    if not os.path.isdir(clones_dir):
        return

    try:
        clones = []
        for entry in os.listdir(clones_dir):
            if entry.startswith("clone_"):
                full_path = os.path.join(clones_dir, entry)
                if os.path.isdir(full_path):
                    clones.append((entry, full_path))

        # Sort by name (timestamp-based)
        clones.sort()

        # Remove old clones
        if len(clones) > keep_count:
            for _, old_clone in clones[:-keep_count]:
                try:
                    shutil.rmtree(old_clone, ignore_errors=True)
                    logger.debug(f"Cleaned up old clone directory: {old_clone}")
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"Error during clone cleanup: {e}")


def list_repository_files(repo_path: str, branch: str = "main", provider: str = "github") -> List[Dict]:
    """
    List all files in a local repository using filesystem traversal.

    Args:
        repo_path (str): Path to the local cloned repository.
        branch (str): Branch name (unused for local repos, kept for compatibility).
        provider (str): Git provider (unused for local repos, kept for compatibility).

    Returns:
        List[Dict]: List of file dicts with 'name', 'path', and 'type' keys.
    """
    repo_root = Path(repo_path)
    gitignore_patterns = _get_gitignore_patterns_from_local(repo_path)
    logger.info(f"Gitignore patterns: {gitignore_patterns}")

    files = []
    for local_path in repo_root.rglob("*"):
        rel_path = local_path.relative_to(repo_root)
        rel_path_str = str(rel_path).replace("\\", "/")

        # Skip .git directory
        if ".git" in rel_path.parts:
            continue

        # Check gitignore patterns
        if should_ignore(rel_path.name, gitignore_patterns):
            continue

        if local_path.is_file():
            files.append(
                {
                    "name": local_path.name,
                    "path": rel_path_str,
                    "type": "file",
                }
            )
        elif local_path.is_dir():
            files.append(
                {
                    "name": local_path.name,
                    "path": rel_path_str,
                    "type": "dir",
                }
            )

    return files


def _get_gitignore_patterns_from_local(repo_path: str) -> List[str]:
    """
    Read .gitignore patterns from a local repository.

    Args:
        repo_path (str): Path to the local repository.

    Returns:
        List[str]: List of gitignore patterns.
    """
    gitignore_path = Path(repo_path) / ".gitignore"
    if not gitignore_path.exists():
        return []

    try:
        patterns = []
        with open(gitignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        return patterns
    except Exception as e:
        logger.warning(f"Failed to read .gitignore: {e}")
        return []


def get_gitignore_patterns(
    repo_path: str, access_token: str, branch: str = "main", provider: str = "github"
) -> List[str]:
    """
    DEPRECATED: Use _get_gitignore_patterns_from_local() instead.

    This function is kept for backwards compatibility.
    Fetches .gitignore file from the repository and returns a list of patterns to ignore.

    Args:
        repo_path (str): Repository path (e.g., 'user/repo') or local path.
        access_token (str): Authentication token (unused if repo_path is local).
        branch (str, optional): Branch name. Defaults to "main".
        provider (str, optional): Git provider ("github" or "gitlab"). Defaults to "github".
    Returns:
        List[str]: List of ignore patterns from .gitignore.
    """
    # If repo_path is a local path, read from local
    if os.path.isdir(repo_path):
        return _get_gitignore_patterns_from_local(repo_path)

    # Otherwise, try API access (legacy fallback)
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


def read_file_content_from_local(repo_path: str, file_path: str) -> Optional[str]:
    """
    Read file content from a local cloned repository.

    Args:
        repo_path (str): Path to the local cloned repository.
        file_path (str): Relative path to the file within the repository.

    Returns:
        Optional[str]: File content if successful, None otherwise.
    """
    try:
        full_path = Path(repo_path) / file_path
        if not full_path.exists() or not full_path.is_file():
            logger.warning(f"File not found: {full_path}")
            return None
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return None


def read_file_bytes_from_local(repo_path: str, file_path: str) -> Optional[bytes]:
    """
    Read file bytes from a local cloned repository.

    Args:
        repo_path (str): Path to the local cloned repository.
        file_path (str): Relative path to the file within the repository.

    Returns:
        Optional[bytes]: File bytes if successful, None otherwise.
    """
    try:
        full_path = Path(repo_path) / file_path
        if not full_path.exists() or not full_path.is_file():
            logger.warning(f"File not found: {full_path}")
            return None
        return full_path.read_bytes()
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return None


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
                "Accept": "application/vnd.github.v3.raw",
            },
            params={"ref": branch},
            timeout=10,
        )
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"GitHub fetch error: {e}")
    return None


def fetch_content_bytes_from_github(repo_path: str, branch: str, file_path: str, access_token: str) -> Optional[bytes]:
    """
    Fetches the raw bytes of a file from a GitHub repository.
    """
    url = f"{GITHUB_API_URL}/repos/{repo_path}/contents/{file_path}"
    try:
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3.raw",
            },
            params={"ref": branch},
            timeout=10,
        )
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"GitHub byte fetch error: {e}")
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
            timeout=10,
        )
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"GitLab fetch error: {e}")
    return None


def fetch_repo_tree(
    repo_url: str,
    access_token: str,
    branch: str = "main",
    provider: str = "github",
    local_repo_path: Optional[str] = None,
) -> List[Dict]:
    """
    Get the file tree from a repository.

    If local_repo_path is provided, reads from that local directory (for already-cloned repos).
    Otherwise, clones the repository temporarily and reads the tree (caller must clean up).

    Args:
        repo_url (str): Repository URL or path (e.g., 'user/repo' or full URL).
        access_token (str): Authentication token.
        branch (str, optional): Branch name. Defaults to "main".
        provider (str, optional): Git provider ('github' or 'gitlab'). Defaults to 'github'.
        local_repo_path (str, optional): Path to a pre-cloned local repository. If provided,
                                         reads from this directory instead of cloning.

    Returns:
        List[Dict]: List of files and directories in the repository.

    Raises:
        RepositoryAccessError: If clone or traversal fails.
    """
    try:
        if local_repo_path:
            # Use pre-cloned repo
            files = list_repository_files(local_repo_path, branch, provider)
            logger.info(f"Fetched repo tree from local path, {len(files)} files found.")
            return files
        else:
            # Clone and fetch (caller is responsible for cleanup)
            temp_dir = tempfile.mkdtemp(prefix="autodoc_repo_")
            try:
                clone_url = (
                    repo_url
                    if repo_url.startswith(("http://", "https://"))
                    else (
                        f"https://github.com/{repo_url}.git"
                        if provider.lower() == "github"
                        else f"https://gitlab.com/{repo_url}.git"
                    )
                )

                if provider.lower() == "github":
                    clone_url = clone_url.replace("https://", f"https://x-access-token:{access_token}@")
                elif provider.lower() == "gitlab":
                    clone_url = clone_url.replace("https://", f"https://oauth2:{access_token}@")

                subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", branch, clone_url, temp_dir],
                    check=True,
                    timeout=300,
                    capture_output=True,
                )
                logger.info(f"Successfully cloned repository to {temp_dir}")
                files = list_repository_files(temp_dir, branch, provider)
                logger.info(f"Fetched repo tree, {len(files)} files found.")
                return files
            except subprocess.TimeoutExpired as e:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise RepositoryAccessError(
                    f"Clone operation timed out after 300 seconds for {repo_url}",
                    status_code=408,
                ) from e
            except subprocess.CalledProcessError as e:
                shutil.rmtree(temp_dir, ignore_errors=True)
                error_msg = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
                if "Repository not found" in error_msg or "not found" in error_msg.lower():
                    raise RepositoryAccessError(
                        f"Repository '{repo_url}' not found or is not accessible with provided token.",
                        status_code=404,
                    ) from e
                elif "authentication" in error_msg.lower():
                    raise RepositoryAccessError(
                        f"Authentication failed for repository '{repo_url}'. Check your token.",
                        status_code=401,
                    ) from e
                else:
                    raise RepositoryAccessError(
                        f"Failed to clone repository '{repo_url}': {error_msg}",
                        status_code=400,
                    ) from e
    except RepositoryAccessError:
        raise
    except Exception as e:
        logger.error(f"Error fetching repo tree: {e}")
        raise RepositoryAccessError(f"Failed to fetch repository tree: {str(e)}", status_code=500) from e


def validate_docstring(
    tech_stack: str,
    repo_path: str,
    branch: str,
    file_path: str,
    access_token: str,
    provider: str = "github",
) -> Optional[Tuple[bool, List[Dict[str, str]], List[Dict[str, str]]]]:
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
        return False, [], []
    language = tech_stack.lower()
    if language not in {"python", "javascript", "typescript", "matlab"}:
        logger.warning("Unknown technology stack. Cannot validate docstring.")
        return False, [], []

    extractor = GenericCodeBlockExtractor(content, file_name)
    code_blocks = extractor.code_block_extractor()
    analysis = analyse_docstring_in_blocks(
        code_blocks,
        file_name=file_name,
        file_path=file_path,
        language=language,
    )

    missing_items = []
    present_items = []
    for item in analysis["docstring_analysis"]:
        if item["missing_docstring"]:
            missing_items.append(item)
        else:
            present_items.append(item)

    return len(missing_items) == 0, missing_items, present_items


def create_directory_and_add_files(
    repo_url: str,
    dir_path: str,
    file_paths: list,
    branch: str,
    token: str,
    provider: str = "github",
) -> bool:
    """
    Creates a new directory in the remote repository and adds multiple files
    to it in a single commit.

    Args:
        repo_url (str): Repository path (e.g., 'user/repo').
        dir_path (str): Directory path to create (e.g., 'autoapi_include').
        file_paths (list): List of file paths in the repo to copy into the new directory.
        branch (str): Branch name.
        token (str): Access token.
        provider (str): 'github' or 'gitlab'.
    Returns:
        bool: True if operation succeeded, False otherwise.
    """

    if provider == "github":
        # Prepare the tree for the commit
        base_api_url = GITHUB_API_URL
        # 1. Get the latest commit SHA of the branch
        ref_url = f"{base_api_url}/repos/{repo_url}/git/refs/heads/{branch}"
        ref_resp = requests.get(ref_url, headers=_github_headers(token))
        if ref_resp.status_code != 200:
            logger.error(f"Failed to get branch ref: {ref_resp.text}")
            return False
        latest_commit_sha = ref_resp.json()["object"]["sha"]

        # 2. Get the tree SHA
        commit_url = f"{base_api_url}/repos/{repo_url}/git/commits/{latest_commit_sha}"
        commit_resp = requests.get(commit_url, headers=_github_headers(token))
        if commit_resp.status_code != 200:
            logger.error(f"Failed to get commit: {commit_resp.text}")
            return False
        base_tree_sha = commit_resp.json()["tree"]["sha"]

        desired_paths = {f"{dir_path}/{file_path}" for file_path in file_paths}

        current_items = list_github_tree(repo_url, branch, token, recursive=True)
        stale_paths = sorted(
            item.get("path", "")
            for item in current_items
            if item.get("type") == "blob"
            and item.get("path", "").startswith(f"{dir_path}/")
            and item.get("path", "") not in desired_paths
        )

        # 3. Prepare blobs for each file
        tree = []
        # Add files
        for file_path in file_paths:
            content = fetch_content_from_github(repo_url, branch, file_path, token)
            if content is None:
                logger.warning(f"Could not fetch content for {file_path}, skipping.")
                continue
            tree.append(
                {
                    "path": f"{dir_path}/{file_path}",
                    "mode": "100644",
                    "type": "blob",
                    "content": content,
                }
            )

        for stale_path in stale_paths:
            tree.append(
                {
                    "path": stale_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": None,
                }
            )

        # 4. Create a new tree
        tree_url = f"{base_api_url}/repos/{repo_url}/git/trees"
        tree_resp = requests.post(
            tree_url,
            headers=_github_headers(token),
            json={"base_tree": base_tree_sha, "tree": tree},
        )
        if tree_resp.status_code not in (200, 201):
            logger.error(f"Failed to create tree: {tree_resp.text}")
            return False
        new_tree_sha = tree_resp.json()["sha"]

        # 5. Create a new commit
        commit_url = f"{base_api_url}/repos/{repo_url}/git/commits"
        commit_message = f"Create {dir_path} directory and added files"
        commit_resp = requests.post(
            commit_url,
            headers=_github_headers(token),
            json={
                "message": commit_message,
                "tree": new_tree_sha,
                "parents": [latest_commit_sha],
            },
        )
        if commit_resp.status_code not in (200, 201):
            logger.error(f"Failed to create commit: {commit_resp.text}")
            return False
        new_commit_sha = commit_resp.json()["sha"]

        # 6. Update the branch reference
        update_ref_url = f"{base_api_url}/repos/{repo_url}/git/refs/heads/{branch}"
        update_resp = requests.patch(
            update_ref_url,
            headers=_github_headers(token),
            json={"sha": new_commit_sha},
        )
        if update_resp.status_code not in (200, 201):
            logger.error(f"Failed to update branch ref: {update_resp.text}")
            return False

        return True

    elif provider == "gitlab":
        # GitLab: Use the "commit multiple actions" API
        project_path_encoded = urllib.parse.quote_plus(repo_url)
        api_url = f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/commits"
        actions = []
        desired_paths = {f"{dir_path}/{file_path}" for file_path in file_paths}
        # Check if .gitkeep already exists
        gitkeep_path = f"{dir_path}/.gitkeep"
        gitkeep_exists = False
        try:
            gitkeep_path_encoded = urllib.parse.quote_plus(gitkeep_path)
            check_url = (
                f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/files/{gitkeep_path_encoded}"
            )
            check_resp = requests.get(
                check_url,
                headers={"PRIVATE-TOKEN": token},
                params={"ref": branch},
                timeout=10,
            )
            gitkeep_exists = check_resp.status_code == 200
        except requests.RequestException:
            pass

        if not gitkeep_exists:
            actions.append({"action": "create", "file_path": gitkeep_path, "content": ""})

        try:
            gl = gitlab.Gitlab(GITLAB_API_URL, private_token=token)
            project = gl.projects.get(repo_url)
            tree_items = project.repository_tree(path=dir_path, ref=branch, recursive=True)
            stale_paths = sorted(
                item.get("path", "")
                for item in tree_items
                if item.get("type") == "blob"
                and item.get("path", "") not in desired_paths
                and item.get("path", "") != gitkeep_path
            )
        except Exception:
            stale_paths = []

        for stale_path in stale_paths:
            actions.append({"action": "delete", "file_path": stale_path})

        for file_path in file_paths:
            content = fetch_content_from_gitlab(repo_url, branch, file_path, token)
            if content is None:
                logger.warning(f"Could not fetch content for {file_path}, skipping.")
                continue
            # Check if file already exists in target directory
            target_path = f"{dir_path}/{file_path}"
            file_exists = False
            try:
                target_path_encoded = urllib.parse.quote_plus(target_path)
                check_url = (
                    f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/files/{target_path_encoded}"
                )
                check_resp = requests.get(
                    check_url,
                    headers={"PRIVATE-TOKEN": token},
                    params={"ref": branch},
                    timeout=10,
                )
                file_exists = check_resp.status_code == 200
            except requests.RequestException:
                pass

            action_type = "update" if file_exists else "create"
            logger.info(f"{'Updating' if file_exists else 'Adding'} file {target_path} to commit actions.")
            actions.append({"action": action_type, "file_path": target_path, "content": content})

        if not actions:
            logger.warning("No actions to commit.")
            return True

        logger.info(f"Prepared {len(actions)} actions for commit.")
        data = {
            "branch": branch,
            "commit_message": f"Update {dir_path} directory with documentation files",
            "actions": actions,
        }
        headers = {"PRIVATE-TOKEN": token}
        resp = requests.post(api_url, headers=headers, json=data)
        if resp.status_code not in (200, 201):
            error_msg = resp.text
            logger.error(f"GitLab commit error: {error_msg}")
            if "insufficient_scope" in error_msg.lower():
                logger.error(
                    "Token has insufficient permissions. Make sure the token "
                    "includes 'write_repository' scope in addition to "
                    "'api' and 'read_api'."
                )
            elif "not allowed to push" in error_msg.lower() or "protected" in error_msg.lower():
                logger.error(
                    f"Branch '{branch}' is protected. Either use a different "
                    "branch, unprotect the branch, or add yourself as an "
                    "allowed pusher in GitLab settings."
                )
            return False
        return True

    else:
        logger.error("Unsupported provider")
        return False


def create_a_file(repo_url, branch, file_path, content, token, provider):
    """
    Create or update a file in a specified repository on GitHub or GitLab.

        Args:
            repo_url (str): The repository URL.
            branch (str): The branch name.
            file_path (str): The path of the file to create/update.
            content (str or bytes): The content to write to the file.
            token (str): The access token for authentication.
            provider (str): The service provider ('github' or 'gitlab').

        Returns:
            bool: True if the operation was successful, False otherwise.

    """
    if isinstance(content, bytes):
        content_bytes = content
        content_text = None
    else:
        content_bytes = content.encode()
        content_text = content

    if provider == "github":
        # GitHub: Create or update a file using the REST API
        api_url = f"{GITHUB_API_URL}/repos/{repo_url}/contents/{file_path}"
        headers = _github_headers(token)
        # Check if file exists to get its SHA
        get_resp = requests.get(api_url, headers=headers, params={"ref": branch})
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
        else:
            sha = None
        data = {
            "message": f"Create or update {file_path}",
            "content": base64.b64encode(content_bytes).decode(),
            "branch": branch,
        }
        if sha:
            data["sha"] = sha
        resp = requests.put(api_url, headers=headers, json=data)
        if resp.status_code not in (201, 200):
            logger.error(f"GitHub create/update file error: {resp.text}")
            return False
        return True

    elif provider == "gitlab":
        # GitLab: Create or update a file using the REST API
        project_path_encoded = urllib.parse.quote_plus(repo_url)
        file_path_encoded = urllib.parse.quote_plus(file_path)
        api_url = f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/files/{file_path_encoded}"
        headers = {"PRIVATE-TOKEN": token}
        # Check if file exists
        get_resp = requests.get(api_url, headers=headers, params={"ref": branch})
        if get_resp.status_code == 200:
            method = requests.put
            commit_message = f"Update {file_path}"
        else:
            method = requests.post
            commit_message = f"Create {file_path}"
        if content_text is None:
            data = {
                "branch": branch,
                "content": base64.b64encode(content_bytes).decode(),
                "commit_message": commit_message,
                "encoding": "base64",
            }
        else:
            data = {
                "branch": branch,
                "content": content_text,
                "commit_message": commit_message,
            }
        resp = method(api_url, headers=headers, json=data)
        if resp.status_code not in (201, 200):
            logger.error(f"GitLab create/update file error: {resp.text}")
            return False
        return True

    else:
        logger.error("Unsupported provider")
        return False


def ensure_github_branch(repo_url: str, source_branch: str, new_branch: str, token: str) -> bool:
    """
    Ensures a GitHub branch exists by creating it from another branch when needed.
    """
    branch_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/refs/heads/{new_branch}"
    existing_resp = requests.get(branch_url, headers=_github_headers(token))
    if existing_resp.status_code == 200:
        return True
    if existing_resp.status_code not in (404,):
        logger.error(f"Failed to check branch {new_branch}: {existing_resp.text}")
        return False

    source_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/refs/heads/{source_branch}"
    source_resp = requests.get(source_url, headers=_github_headers(token))
    if source_resp.status_code != 200:
        logger.error(f"Failed to get source branch ref: {source_resp.text}")
        return False

    source_sha = source_resp.json()["object"]["sha"]
    create_resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/refs",
        headers=_github_headers(token),
        json={"ref": f"refs/heads/{new_branch}", "sha": source_sha},
    )
    if create_resp.status_code not in (200, 201, 422):
        logger.error(f"Failed to create branch {new_branch}: {create_resp.text}")
        return False
    return True


def configure_github_pages(repo_url: str, pages_branch: str, token: str, path: str = "/") -> bool:
    """
    Configures GitHub Pages to publish from a branch without GitHub Actions.
    """
    api_url = f"{GITHUB_API_URL}/repos/{repo_url}/pages"
    payload = {
        "build_type": "legacy",
        "source": {"branch": pages_branch, "path": path},
    }
    get_resp = requests.get(api_url, headers=_github_headers(token))
    if get_resp.status_code == 200:
        pages_config = get_resp.json()
        current_source = pages_config.get("source") or {}
        if current_source.get("branch") == pages_branch and current_source.get("path") == path:
            logger.info("GitHub Pages is already configured for %s%s.", pages_branch, path)
            return True
        resp = requests.put(api_url, headers=_github_headers(token), json=payload)
        success_codes = (204,)
    elif get_resp.status_code == 404:
        resp = requests.post(api_url, headers=_github_headers(token), json=payload)
        success_codes = (201,)
    else:
        message = _parse_response_message(get_resp)
        logger.error(f"Failed to inspect GitHub Pages settings: {get_resp.text}")
        raise GitHubApiError(
            f"GitHub Pages inspection failed for '{repo_url}': {message}",
            status_code=get_resp.status_code,
        )

    if resp.status_code not in success_codes:
        message = _parse_response_message(resp)
        logger.error(f"Failed to configure GitHub Pages: {resp.text}")
        raise GitHubApiError(
            f"GitHub Pages configuration failed for '{repo_url}': {message}",
            status_code=resp.status_code,
        )
    return True


def request_github_pages_build(repo_url: str, token: str) -> bool:
    """
    Requests a GitHub Pages rebuild for a legacy branch-based site.
    """
    api_url = f"{GITHUB_API_URL}/repos/{repo_url}/pages/builds"
    resp = requests.post(api_url, headers=_github_headers(token))
    if resp.status_code not in (201,):
        message = _parse_response_message(resp)
        logger.error(f"GitHub Pages build request failed: {resp.text}")
        raise GitHubApiError(
            f"GitHub Pages rebuild request failed for '{repo_url}': {message}",
            status_code=resp.status_code,
        )
    return True


def list_github_tree(repo_url: str, ref: str, token: str, recursive: bool = True) -> List[Dict]:
    """
    Lists files in a GitHub tree for the given ref.
    """
    api_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/trees/{ref}"
    params = {"recursive": "1"} if recursive else None
    resp = requests.get(api_url, headers=_github_headers(token), params=params)
    if resp.status_code != 200:
        logger.error(f"Failed to fetch GitHub tree for {ref}: {resp.text}")
        return []
    data = resp.json()
    return data.get("tree", [])


def download_github_branch_snapshot(repo_url: str, branch: str, token: str, destination_dir: str) -> bool:
    """
    Downloads a GitHub branch snapshot into a local directory.
    """
    tree_items = list_github_tree(repo_url, branch, token, recursive=True)
    if not tree_items:
        logger.error("No files found while downloading branch snapshot for %s.", branch)
        return False

    for item in tree_items:
        if item.get("type") != "blob":
            continue
        file_path = item.get("path", "")
        content = fetch_content_bytes_from_github(repo_url, branch, file_path, token)
        if content is None:
            logger.warning("Could not download %s from %s.", file_path, branch)
            continue
        local_path = os.path.join(destination_dir, file_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as file_handle:
            file_handle.write(content)

    return True


def create_github_blob(repo_url: str, token: str, content: bytes) -> Optional[str]:
    """
    Creates a GitHub blob and returns its SHA.
    """
    try:
        payload = {"content": content.decode("utf-8"), "encoding": "utf-8"}
    except UnicodeDecodeError:
        payload = {
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        }

    resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/blobs",
        headers=_github_headers(token),
        json=payload,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Failed to create blob: {resp.text}")
        return None
    return resp.json().get("sha")


def publish_github_directory_to_branch(
    repo_url: str,
    source_branch: str,
    source_dir: str,
    target_branch: str,
    token: str,
    target_dir: str = "",
) -> bool:
    """
    Copies a built static directory from one branch to another in a single commit.
    """
    if not ensure_github_branch(repo_url, source_branch, target_branch, token):
        return False

    source_items = list_github_tree(repo_url, source_branch, token, recursive=True)
    source_prefix = source_dir.strip("/")
    source_files = [
        item
        for item in source_items
        if item.get("type") == "blob" and item.get("path", "").startswith(f"{source_prefix}/")
    ]
    if not source_files:
        logger.warning(
            "No built documentation files found under %s on branch %s.",
            source_dir,
            source_branch,
        )
        return False

    ref_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/refs/heads/{target_branch}"
    ref_resp = requests.get(ref_url, headers=_github_headers(token))
    if ref_resp.status_code != 200:
        logger.error(f"Failed to get target branch ref: {ref_resp.text}")
        return False
    latest_commit_sha = ref_resp.json()["object"]["sha"]

    commit_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/commits/{latest_commit_sha}"
    commit_resp = requests.get(commit_url, headers=_github_headers(token))
    if commit_resp.status_code != 200:
        logger.error(f"Failed to get target branch commit: {commit_resp.text}")
        return False
    base_tree_sha = commit_resp.json()["tree"]["sha"]

    target_items = list_github_tree(repo_url, target_branch, token, recursive=True)
    target_paths = {
        item.get("path", "")
        for item in target_items
        if item.get("type") == "blob" and item.get("path", "") != ".nojekyll"
    }

    target_prefix = target_dir.strip("/")
    tree = []
    published_paths = set()
    for item in source_files:
        source_path = item["path"]
        relative_path = source_path[len(source_prefix) + 1 :]
        target_path = f"{target_prefix}/{relative_path}" if target_prefix else relative_path
        content = fetch_content_from_github(repo_url, source_branch, source_path, token)
        if content is None:
            logger.warning(f"Could not fetch built documentation file {source_path}, skipping.")
            continue
        tree.append(
            {
                "path": target_path,
                "mode": "100644",
                "type": "blob",
                "content": content,
            }
        )
        published_paths.add(target_path)

    tree.append({"path": ".nojekyll", "mode": "100644", "type": "blob", "content": ""})
    published_paths.add(".nojekyll")

    stale_paths = sorted(target_paths - published_paths)
    for stale_path in stale_paths:
        tree.append(
            {
                "path": stale_path,
                "mode": "100644",
                "type": "blob",
                "sha": None,
            }
        )

    tree_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/trees"
    tree_resp = requests.post(
        tree_url,
        headers=_github_headers(token),
        json={"base_tree": base_tree_sha, "tree": tree},
    )
    if tree_resp.status_code not in (200, 201):
        logger.error(f"Failed to create publish tree: {tree_resp.text}")
        return False
    new_tree_sha = tree_resp.json()["sha"]

    commit_resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/commits",
        headers=_github_headers(token),
        json={
            "message": f"Publish docs from {source_branch} to {target_branch}",
            "tree": new_tree_sha,
            "parents": [latest_commit_sha],
        },
    )
    if commit_resp.status_code not in (200, 201):
        logger.error(f"Failed to create publish commit: {commit_resp.text}")
        return False
    new_commit_sha = commit_resp.json()["sha"]

    update_resp = requests.patch(
        ref_url,
        headers=_github_headers(token),
        json={"sha": new_commit_sha},
    )
    if update_resp.status_code not in (200, 201):
        logger.error(f"Failed to update publish branch ref: {update_resp.text}")
        return False

    return True


def publish_local_directory_to_github_branch(
    repo_url: str,
    local_dir: str,
    target_branch: str,
    token: str,
    source_branch_for_seed: str,
    target_dir: str = "",
) -> bool:
    """
    Publishes a local directory to a GitHub branch in a single commit.
    """
    if not ensure_github_branch(repo_url, source_branch_for_seed, target_branch, token):
        raise GitHubApiError(
            f"GitHub publish failed for '{repo_url}': could not create or access branch '{target_branch}'."
        )

    ref_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/refs/heads/{target_branch}"
    ref_resp = requests.get(ref_url, headers=_github_headers(token))
    if ref_resp.status_code != 200:
        logger.error(f"Failed to get target branch ref: {ref_resp.text}")
        raise GitHubApiError(
            f"GitHub publish failed for '{repo_url}': {_parse_response_message(ref_resp)}",
            status_code=ref_resp.status_code,
        )
    latest_commit_sha = ref_resp.json()["object"]["sha"]

    commit_resp = requests.get(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/commits/{latest_commit_sha}",
        headers=_github_headers(token),
    )
    if commit_resp.status_code != 200:
        logger.error(f"Failed to get target branch commit: {commit_resp.text}")
        raise GitHubApiError(
            f"GitHub publish failed for '{repo_url}': {_parse_response_message(commit_resp)}",
            status_code=commit_resp.status_code,
        )
    base_tree_sha = commit_resp.json()["tree"]["sha"]

    target_items = list_github_tree(repo_url, target_branch, token, recursive=True)
    target_paths = {
        item.get("path", "")
        for item in target_items
        if item.get("type") == "blob" and item.get("path", "") != ".nojekyll"
    }

    target_prefix = target_dir.strip("/")
    tree = []
    published_paths = set()
    for root, _, files in os.walk(local_dir):
        for file_name in files:
            local_path = os.path.join(root, file_name)
            relative_path = os.path.relpath(local_path, local_dir).replace(os.sep, "/")
            target_path = f"{target_prefix}/{relative_path}" if target_prefix else relative_path
            with open(local_path, "rb") as file_handle:
                blob_sha = create_github_blob(repo_url, token, file_handle.read())
            if not blob_sha:
                raise GitHubApiError(f"GitHub publish failed for '{repo_url}': could not create blob for {target_path}.")
            tree.append(
                {
                    "path": target_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                }
            )
            published_paths.add(target_path)

    nojekyll_sha = create_github_blob(repo_url, token, b"")
    if not nojekyll_sha:
        raise GitHubApiError(f"GitHub publish failed for '{repo_url}': could not create blob for .nojekyll.")
    tree.append({"path": ".nojekyll", "mode": "100644", "type": "blob", "sha": nojekyll_sha})
    published_paths.add(".nojekyll")

    stale_paths = sorted(target_paths - published_paths)
    for stale_path in stale_paths:
        tree.append({"path": stale_path, "mode": "100644", "type": "blob", "sha": None})

    tree_resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/trees",
        headers=_github_headers(token),
        json={"base_tree": base_tree_sha, "tree": tree},
    )
    if tree_resp.status_code not in (200, 201):
        logger.error(f"Failed to create publish tree: {tree_resp.text}")
        raise GitHubApiError(
            f"GitHub publish failed for '{repo_url}': {_parse_response_message(tree_resp)}",
            status_code=tree_resp.status_code,
        )
    new_tree_sha = tree_resp.json()["sha"]

    new_commit_resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/commits",
        headers=_github_headers(token),
        json={
            "message": f"Publish docs to {target_branch}",
            "tree": new_tree_sha,
            "parents": [latest_commit_sha],
        },
    )
    if new_commit_resp.status_code not in (200, 201):
        logger.error(f"Failed to create publish commit: {new_commit_resp.text}")
        raise GitHubApiError(
            f"GitHub publish failed for '{repo_url}': {_parse_response_message(new_commit_resp)}",
            status_code=new_commit_resp.status_code,
        )
    new_commit_sha = new_commit_resp.json()["sha"]

    update_resp = requests.patch(
        ref_url,
        headers=_github_headers(token),
        json={"sha": new_commit_sha},
    )
    if update_resp.status_code not in (200, 201):
        logger.error(f"Failed to update publish branch ref: {update_resp.text}")
        raise GitHubApiError(
            f"GitHub publish failed for '{repo_url}': {_parse_response_message(update_resp)}",
            status_code=update_resp.status_code,
        )

    return True


def commit_files_to_github_branch(
    repo_url: str,
    branch: str,
    files: Dict[str, str],
    token: str,
    commit_message: str,
) -> bool:
    """
    Commits multiple text files to an existing GitHub branch.
    """
    if not files:
        logger.warning("No files provided for GitHub commit.")
        return False

    ref_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/refs/heads/{branch}"
    ref_resp = requests.get(ref_url, headers=_github_headers(token))
    if ref_resp.status_code != 200:
        logger.error(f"Failed to get target branch ref: {ref_resp.text}")
        return False
    latest_commit_sha = ref_resp.json()["object"]["sha"]

    commit_resp = requests.get(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/commits/{latest_commit_sha}",
        headers=_github_headers(token),
    )
    if commit_resp.status_code != 200:
        logger.error(f"Failed to get target branch commit: {commit_resp.text}")
        return False
    base_tree_sha = commit_resp.json()["tree"]["sha"]

    tree = [
        {
            "path": file_path,
            "mode": "100644",
            "type": "blob",
            "content": content,
        }
        for file_path, content in files.items()
    ]

    tree_resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/trees",
        headers=_github_headers(token),
        json={"base_tree": base_tree_sha, "tree": tree},
    )
    if tree_resp.status_code not in (200, 201):
        logger.error(f"Failed to create suggestion tree: {tree_resp.text}")
        return False

    new_commit_resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/git/commits",
        headers=_github_headers(token),
        json={
            "message": commit_message,
            "tree": tree_resp.json()["sha"],
            "parents": [latest_commit_sha],
        },
    )
    if new_commit_resp.status_code not in (200, 201):
        logger.error(f"Failed to create suggestion commit: {new_commit_resp.text}")
        return False

    update_resp = requests.patch(
        ref_url,
        headers=_github_headers(token),
        json={"sha": new_commit_resp.json()["sha"]},
    )
    if update_resp.status_code not in (200, 201):
        logger.error(f"Failed to update suggestion branch ref: {update_resp.text}")
        return False

    return True


def create_github_pull_request(
    repo_url: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str,
    token: str,
) -> Optional[str]:
    """
    Opens a GitHub pull request and returns its URL.
    """
    resp = requests.post(
        f"{GITHUB_API_URL}/repos/{repo_url}/pulls",
        headers=_github_headers(token),
        json={
            "title": title,
            "head": head_branch,
            "base": base_branch,
            "body": body,
        },
    )
    if resp.status_code not in (200, 201):
        logger.error(f"Failed to create GitHub pull request: {resp.text}")
        if resp.status_code == 403:
            raise GitHubApiError(
                "GitHub rejected pull request creation. Check that the token has "
                "'Pull requests: Read and write' permission for this repository and "
                "that organization SSO/access is approved.",
                status_code=resp.status_code,
            )
        raise GitHubApiError(
            f"GitHub pull request creation failed: {resp.text}",
            status_code=resp.status_code,
    )
    return resp.json().get("html_url")


def list_open_github_pull_requests(repo_url: str, base_branch: str, token: str) -> List[Dict]:
    """
    Lists open GitHub pull requests targeting the provided base branch.
    """
    resp = requests.get(
        f"{GITHUB_API_URL}/repos/{repo_url}/pulls",
        headers=_github_headers(token),
        params={"state": "open", "base": base_branch, "per_page": 100},
    )
    if resp.status_code != 200:
        logger.error(f"Failed to list GitHub pull requests: {resp.text}")
        return []
    payload = resp.json()
    return payload if isinstance(payload, list) else []


def list_github_pull_request_files(repo_url: str, pull_number: int, token: str) -> List[Dict]:
    """
    Lists files changed in a GitHub pull request.
    """
    resp = requests.get(
        f"{GITHUB_API_URL}/repos/{repo_url}/pulls/{pull_number}/files",
        headers=_github_headers(token),
        params={"per_page": 100},
    )
    if resp.status_code != 200:
        logger.error(f"Failed to list GitHub pull request files: {resp.text}")
        return []
    payload = resp.json()
    return payload if isinstance(payload, list) else []
