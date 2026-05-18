import os
import re
import shutil
from datetime import datetime

from config.log_config import LOG_DIR, bind_repo_log_dir

_ACTIVE_RUN_DIRS: dict[tuple[str, str], str] = {}


def _repo_base_dir(repo_path: str, provider: str) -> str:
    """
    Constructs a base directory path for a repository.

        Args:
            repo_path (str): The path of the repository.
            provider (str): The provider name for the repository.

        Returns:
            str: The normalized base directory path for the repository.

    """
    normalized_provider = str(provider or "unknown").strip().lower() or "unknown"
    normalized_repo_path = str(repo_path or "unknown").strip().strip("/") or "unknown"
    repo_key = re.sub(r"[^A-Za-z0-9._-]+", "__", normalized_repo_path)
    return os.path.join(LOG_DIR, normalized_provider, repo_key)


def build_repo_output_dir(repo_path: str, provider: str) -> str:
    """
    Returns the repo-scoped output directory for the current run.
    """
    repo_key = (str(provider or "unknown").lower(), str(repo_path or "unknown").strip("/"))
    output_dir = _ACTIVE_RUN_DIRS.get(repo_key)
    if not output_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(_repo_base_dir(repo_path, provider), f"app_{timestamp}")
        _ACTIVE_RUN_DIRS[repo_key] = output_dir
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def build_repo_output_file(repo_path: str, provider: str, filename: str) -> str:
    """
    Constructs the full path for a repository output file.

        Args:
            repo_path (str): The path to the repository.
            provider (str): The provider name associated with the repository.
            filename (str): The name of the output file.

        Returns:
            str: The full path to the output file.

    """
    return os.path.join(build_repo_output_dir(repo_path, provider), filename)


def bind_repo_run_log_dir(repo_path: str, provider: str) -> str:
    """
    Bind the repository run log directory based on the given repository path and provider.

    Args:
        repo_path (str): The path to the repository.
        provider (str): The name of the provider.

    Returns:
        str: The bound repository run log directory path.

    """
    repo_key = (str(provider or "unknown").lower(), str(repo_path or "unknown").strip("/"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(_repo_base_dir(repo_path, provider), f"app_{timestamp}")
    _ACTIVE_RUN_DIRS[repo_key] = output_dir
    return bind_repo_log_dir(output_dir)


def clear_repo_output_history(repo_path: str, provider: str) -> None:
    """
    Clears the output history of a specified repository.

        Args:
            repo_path (str): The path to the repository.
            provider (str): The provider of the repository.

        Returns:
            None: This function does not return a value.

    """
    repo_dir = _repo_base_dir(repo_path, provider)
    repo_key = (str(provider or "unknown").lower(), str(repo_path or "unknown").strip("/"))
    _ACTIVE_RUN_DIRS.pop(repo_key, None)
    if os.path.isdir(repo_dir):
        shutil.rmtree(repo_dir)


def find_latest_repo_run_dir(repo_path: str, provider: str) -> str | None:
    """
    Retrieve the latest run directory for a specified repository.

        Args:
            repo_path (str): The path to the repository.
            provider (str): The provider of the repository.

        Returns:
            str | None: The latest run directory path or None if not found.

    """
    repo_dir = _repo_base_dir(repo_path, provider)
    if not os.path.isdir(repo_dir):
        return None
    run_dirs = [
        os.path.join(repo_dir, entry)
        for entry in os.listdir(repo_dir)
        if entry.startswith("app_") and os.path.isdir(os.path.join(repo_dir, entry))
    ]
    if not run_dirs:
        return None
    return sorted(run_dirs)[-1]
