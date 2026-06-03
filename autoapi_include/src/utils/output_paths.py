import os
import re
import shutil
from datetime import datetime

from config.log_config import LOG_DIR, bind_repo_log_dir

_ACTIVE_RUN_DIRS: dict[tuple[str, str], str] = {}
LOG_RETENTION_COUNT = 6  # Keep only the last 6 logs per project
_PRESERVED_ARTIFACT_SUFFIXES = (".csv", ".json", ".txt")


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


def _cleanup_old_logs(repo_path: str, provider: str) -> None:
    """
    Remove old log directories, keeping only the last LOG_RETENTION_COUNT for each project.

    Args:
        repo_path (str): The path of the repository.
        provider (str): The provider name for the repository.

    Returns:
        None
    """
    repo_dir = _repo_base_dir(repo_path, provider)
    if not os.path.isdir(repo_dir):
        return

    # Get all log directories for this project
    log_dirs = []
    for entry in os.listdir(repo_dir):
        if entry.startswith("app_") and os.path.isdir(os.path.join(repo_dir, entry)):
            full_path = os.path.join(repo_dir, entry)
            log_dirs.append((entry, full_path))

    # Sort by name (timestamp-based, lexicographic sort works for format YYYYMMDD_HHMMSS)
    log_dirs.sort()

    # Remove old directories beyond retention count
    if len(log_dirs) > LOG_RETENTION_COUNT:
        for _, old_dir in log_dirs[:-LOG_RETENTION_COUNT]:
            try:
                shutil.rmtree(old_dir, ignore_errors=True)
            except Exception:
                # Silently ignore errors during cleanup
                pass


def _copy_previous_run_artifacts(previous_run_dir: str | None, output_dir: str) -> None:
    """
    Copy top-level report artifacts from the previous run into the new run directory.

    This preserves reusable `.csv`, `.json`, and `.txt` outputs before retention cleanup
    removes older run folders.
    """
    if not previous_run_dir or not os.path.isdir(previous_run_dir):
        return

    os.makedirs(output_dir, exist_ok=True)
    for entry in os.listdir(previous_run_dir):
        source_path = os.path.join(previous_run_dir, entry)
        if not os.path.isfile(source_path):
            continue
        if not entry.endswith(_PRESERVED_ARTIFACT_SUFFIXES):
            continue
        target_path = os.path.join(output_dir, entry)
        shutil.copy2(source_path, target_path)


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
    # Clean up old logs, keeping only the last 6
    _cleanup_old_logs(repo_path, provider)
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
    previous_run_dir = find_latest_repo_run_dir(repo_path, provider)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(_repo_base_dir(repo_path, provider), f"app_{timestamp}")
    _copy_previous_run_artifacts(previous_run_dir, output_dir)
    _ACTIVE_RUN_DIRS[repo_key] = output_dir
    # Clean up old logs, keeping only the last 6
    _cleanup_old_logs(repo_path, provider)
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
