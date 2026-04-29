#!/usr/bin/env python3
"""
Run the local quality checks we want before pushing to GitHub.

Usage:
    python3 prepush_check.py
    python3 prepush_check.py --docker
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_step(title: str, command: list[str], env: dict[str, str] | None = None) -> None:
    print(f"\n==> {title}")
    print(" ".join(command))
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def ensure_tool(tool_name: str) -> None:
    if shutil.which(tool_name) is None:
        print(
            f"Error: '{tool_name}' is not installed or not on PATH. "
            f"Install it first, then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run lint, tests, docs build, and optional Docker build before pushing."
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Also run the Docker image build check.",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    ensure_tool("uv")

    test_env = os.environ.copy()
    test_env.setdefault("OPENAI_API_KEY", "test-key")

    try:
        run_step(
            "Sync development dependencies",
            ["uv", "sync", "--group", "dev", "--no-install-project"],
        )
        run_step(
            "Run Ruff",
            ["uv", "run", "ruff", "check", "src", "tests"],
        )
        run_step(
            "Run pytest",
            [
                "uv",
                "run",
                "pytest",
                "--cov=src",
                "--cov-report=term-missing",
                "--cov-report=xml",
            ],
            env=test_env,
        )
        run_step(
            "Sync documentation dependencies",
            ["uv", "sync", "--group", "docs", "--no-install-project"],
        )
        run_step(
            "Build Sphinx docs",
            [
                "uv",
                "run",
                "sphinx-build",
                "-W",
                "-b",
                "html",
                "docs",
                "docs/build/html",
            ],
        )

        if args.docker:
            ensure_tool("docker")
            run_step(
                "Build Docker image",
                ["docker", "build", "-t", "autodoc:prepush", "."],
            )
    except subprocess.CalledProcessError as exc:
        print(f"\nCheck failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode

    print("\nAll pre-push checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
