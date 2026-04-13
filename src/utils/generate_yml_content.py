def generate_gitlab_ci_file() -> bool:
    """
    Generates a .gitlab-ci.yml file in the specified remote GitLab repository.

    Args:
        repo_path (str): Repository path (e.g., 'user/repo').
        access_token (str): GitLab private token.
        branch (str, optional): Branch name. Defaults to "main".

    Returns:
        bool: True if the file was created successfully, False otherwise.
    """
    gitlab_ci_content = """stages:
  - docs
  - deploy

variables:
  PY_VERSION: "3.11"
  DOCS_SRC: "docs/source"
  BUILD_DIR: "docs/build/html"
  CONF_PY: "docs/source/conf.py"
  PROJECT_NAME: "API Documentation"
  PROJECT_AUTHOR: "Development Team"

build_sphinx:
  stage: docs
  image: python:${PY_VERSION}
  before_script:
    - python -m pip install uv
    - uv pip install --system sphinx==8.2.3 sphinx-autoapi==3.6.0 sphinx-rtd-theme==3.0.2
  script:
    # Create docs directory structure if it doesn't exist
    - mkdir -p docs/source
    - |
      if [ ! -f "$CONF_PY" ]; then
        sphinx-quickstart --quiet --project "$PROJECT_NAME" \\
          --author "$PROJECT_AUTHOR" --sep --makefile \\
          --batchfile --ext-autodoc docs
      fi
    # Update conf.py with autoapi settings
    - |
      if [ -f "update_conf.py" ]; then
        python update_conf.py "$CONF_PY"
      fi
    # Build the documentation
    - sphinx-build -b html "$DOCS_SRC" "$BUILD_DIR"
  artifacts:
    paths:
      - docs/build/html
    expire_in: 1 week
  only:
    - dev
    - main

pages:
  stage: deploy
  dependencies:
    - build_sphinx
  script:
    # GitLab Pages expects content in a 'public' directory
    - mkdir -p public
    - cp -r docs/build/html/* public/
  artifacts:
    paths:
      - public
  only:
    - dev
    - main
"""

    return gitlab_ci_content


def generate_github_actions_file() -> str:
    """
    Generates a GitHub Actions workflow file for building Sphinx docs.

    Returns:
        str: Workflow file content.
    """
    github_actions_content = """name: Build Docs

on:
  push:
    branches:
      - main
      - dev
  pull_request:
    branches:
      - main
      - dev

jobs:
  docs:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up uv
        uses: astral-sh/setup-uv@v5

      - name: Install documentation dependencies
        run: uv pip install --system sphinx==8.2.3 sphinx-autoapi==3.6.0 sphinx-rtd-theme==3.0.2

      - name: Ensure docs scaffolding exists
        run: |
          mkdir -p docs/source
          if [ ! -f "docs/source/conf.py" ]; then
            sphinx-quickstart --quiet --project "API Documentation" \
              --author "Development Team" --sep --makefile \
              --batchfile --ext-autodoc docs
          fi

      - name: Update Sphinx AutoAPI configuration
        run: |
          if [ -f "update_conf.py" ]; then
            python update_conf.py "docs/source/conf.py"
          fi

      - name: Build documentation
        run: sphinx-build -b html docs/source docs/build/html

      - name: Upload documentation artifact
        uses: actions/upload-artifact@v4
        with:
          name: docs-html
          path: docs/build/html
"""

    return github_actions_content
