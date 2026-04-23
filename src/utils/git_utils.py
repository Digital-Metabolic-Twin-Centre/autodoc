import base64
import fnmatch
import os
import urllib.parse
from typing import Dict, List, Optional, Tuple

import gitlab
import requests

from config.config import GITHUB_API_URL, GITLAB_API_URL
from config.log_config import get_logger
from utils.code_block_extraction import GenericCodeBlockExtractor
from utils.docstring_validation import analyze_docstring_in_blocks

logger = get_logger(__name__)


def _github_headers(token: str, accept: str = "application/vnd.github+json") -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2026-03-10",
    }


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


def get_gitignore_patterns(
    repo_path: str, access_token: str, branch: str = "main", provider: str = "github"
) -> List[str]:
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


def fetch_content_from_github(
    repo_path: str, branch: str, file_path: str, access_token: str
) -> Optional[str]:
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
        return response.text if response.text else None
    except Exception as e:
        logger.error(f"GitHub fetch error: {e}")
    return None


def fetch_content_bytes_from_github(
    repo_path: str, branch: str, file_path: str, access_token: str
) -> Optional[bytes]:
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
        return response.content if response.content else None
    except Exception as e:
        logger.error(f"GitHub byte fetch error: {e}")
    return None


def fetch_content_from_gitlab(
    repo_path: str, branch: str, file_path: str, private_token: str
) -> Optional[str]:
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
    url = (
        f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/files/"
        f"{file_path_encoded}/raw"
    )
    try:
        response = requests.get(
            url,
            headers={"PRIVATE-TOKEN": private_token},
            params={"ref": branch},
            timeout=10,
        )
        response.raise_for_status()
        return response.text if response.text else None
    except Exception as e:
        logger.error(f"GitLab fetch error: {e}")
    return None


def fetch_repo_tree(
    repo_path: str, access_token: str, branch: str = "main", provider: str = "github"
) -> List[Dict]:
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
                "Accept": "application/vnd.github.v3+json",
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
            if should_ignore(item["name"], gitignore_patterns):
                continue
            if item.get("type") in ["dir", "tree"]:
                sub_items = _fetch_tree(os.path.join(path, item["name"]) if path else item["name"])
                all_files.extend(sub_items)
            elif item.get("type") in ["file", "blob"]:
                all_files.append(item)
        return all_files

    try:
        repository_files = _fetch_tree()
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    return repository_files


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
        return False, None, None
    language = tech_stack.lower()
    if language not in {"python", "javascript", "typescript", "matlab"}:
        logger.warning("Unknown technology stack. Cannot validate docstring.")
        return False, None, None

    extractor = GenericCodeBlockExtractor(content, file_name)
    code_blocks = extractor.code_block_extractor()
    analysis = analyze_docstring_in_blocks(
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

        # 3. Prepare blobs for each file
        tree = []
        existing_names = set()
        # Add files
        for file_path in file_paths:
            content = fetch_content_from_github(repo_url, branch, file_path, token)
            if content is None:
                logger.warning(f"Could not fetch content for {file_path}, skipping.")
                continue
            file_name = os.path.basename(file_path)
            if file_name in existing_names:
                parent_folder = os.path.basename(os.path.dirname(file_path))
                file_name = f"{parent_folder}_{file_name}"
            existing_names.add(file_name)
            tree.append(
                {
                    "path": f"{dir_path}/{file_name}",
                    "mode": "100644",
                    "type": "blob",
                    "content": content,
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
        existing_names = set()

        # Check if .gitkeep already exists
        gitkeep_path = f"{dir_path}/.gitkeep"
        gitkeep_exists = False
        try:
            gitkeep_path_encoded = urllib.parse.quote_plus(gitkeep_path)
            check_url = (
                f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/"
                f"repository/files/{gitkeep_path_encoded}"
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

        for file_path in file_paths:
            content = fetch_content_from_gitlab(repo_url, branch, file_path, token)
            if content is None:
                logger.warning(f"Could not fetch content for {file_path}, skipping.")
                continue
            file_name = os.path.basename(file_path)
            # If file_name already exists, add parent folder name
            if file_name in existing_names:
                parent_folder = os.path.basename(os.path.dirname(file_path))
                file_name = f"{parent_folder}_{file_name}"
            existing_names.add(file_name)

            # Check if file already exists in target directory
            target_path = f"{dir_path}/{file_name}"
            file_exists = False
            try:
                target_path_encoded = urllib.parse.quote_plus(target_path)
                check_url = (
                    f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/"
                    f"repository/files/{target_path_encoded}"
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
            logger.info(
                f"{'Updating' if file_exists else 'Adding'} file {file_name} to commit actions."
            )
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
            "content": base64.b64encode(content.encode()).decode(),
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
        api_url = (
            f"{GITLAB_API_URL}/api/v4/projects/{project_path_encoded}/repository/files/"
            f"{file_path_encoded}"
        )
        headers = {"PRIVATE-TOKEN": token}
        # Check if file exists
        get_resp = requests.get(api_url, headers=headers, params={"ref": branch})
        if get_resp.status_code == 200:
            method = requests.put
            commit_message = f"Update {file_path}"
        else:
            method = requests.post
            commit_message = f"Create {file_path}"
        data = {"branch": branch, "content": content, "commit_message": commit_message}
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
        resp = requests.put(api_url, headers=_github_headers(token), json=payload)
        success_codes = (204,)
    elif get_resp.status_code == 404:
        resp = requests.post(api_url, headers=_github_headers(token), json=payload)
        success_codes = (201,)
    else:
        logger.error(f"Failed to inspect GitHub Pages settings: {get_resp.text}")
        return False

    if resp.status_code not in success_codes:
        logger.error(f"Failed to configure GitHub Pages: {resp.text}")
        return False
    return True


def request_github_pages_build(repo_url: str, token: str) -> bool:
    """
    Requests a GitHub Pages rebuild for a legacy branch-based site.
    """
    api_url = f"{GITHUB_API_URL}/repos/{repo_url}/pages/builds"
    resp = requests.post(api_url, headers=_github_headers(token))
    if resp.status_code not in (201,):
        logger.warning(f"GitHub Pages build request failed: {resp.text}")
        return False
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


def download_github_branch_snapshot(
    repo_url: str, branch: str, token: str, destination_dir: str
) -> bool:
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
        payload = {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"}

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
        if item.get("type") == "blob"
        and item.get("path", "").startswith(f"{source_prefix}/")
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
        return False

    ref_url = f"{GITHUB_API_URL}/repos/{repo_url}/git/refs/heads/{target_branch}"
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
                return False
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
        return False
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
        return False
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
        return False
    new_commit_sha = new_commit_resp.json()["sha"]

    update_resp = requests.patch(
        ref_url,
        headers=_github_headers(token),
        json={"sha": new_commit_sha},
    )
    if update_resp.status_code not in (200, 201):
        logger.error(f"Failed to update publish branch ref: {update_resp.text}")
        return False

    return True
