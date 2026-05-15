import os
import re
import shutil

from config.log_config import LOG_DIR, RUN_TIMESTAMP, bind_repo_log_dir


def _repo_base_dir(repo_path: str, provider: str) -> str:
    normalized_provider = str(provider or "unknown").strip().lower() or "unknown"
    normalized_repo_path = str(repo_path or "unknown").strip().strip("/") or "unknown"
    repo_key = re.sub(r"[^A-Za-z0-9._-]+", "__", normalized_repo_path)
    return os.path.join(LOG_DIR, normalized_provider, repo_key)


def build_repo_output_dir(repo_path: str, provider: str) -> str:
    """
    Returns the repo-scoped output directory for the current run.
    """
    output_dir = os.path.join(_repo_base_dir(repo_path, provider), f"app_{RUN_TIMESTAMP}")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def build_repo_output_file(repo_path: str, provider: str, filename: str) -> str:
    return os.path.join(build_repo_output_dir(repo_path, provider), filename)


def bind_repo_run_log_dir(repo_path: str, provider: str) -> str:
    return bind_repo_log_dir(build_repo_output_dir(repo_path, provider))


def clear_repo_output_history(repo_path: str, provider: str) -> None:
    repo_dir = _repo_base_dir(repo_path, provider)
    if os.path.isdir(repo_dir):
        shutil.rmtree(repo_dir)


def find_latest_repo_run_dir(repo_path: str, provider: str) -> str | None:
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
