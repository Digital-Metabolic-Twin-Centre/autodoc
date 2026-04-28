import os
import re


def _workspace_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def build_repo_output_dir(repo_path: str, provider: str) -> str:
    """
    Returns the repo-scoped output directory under logs/.
    """
    normalized_provider = str(provider or "unknown").strip().lower() or "unknown"
    normalized_repo_path = str(repo_path or "unknown").strip().strip("/") or "unknown"
    repo_key = re.sub(r"[^A-Za-z0-9._-]+", "__", normalized_repo_path)
    output_dir = os.path.join(_workspace_root(), "logs", normalized_provider, repo_key)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def build_repo_output_file(repo_path: str, provider: str, filename: str) -> str:
    return os.path.join(build_repo_output_dir(repo_path, provider), filename)
