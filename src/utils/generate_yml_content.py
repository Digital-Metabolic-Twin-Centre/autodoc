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
    - pip install --upgrade pip
    - pip install sphinx sphinx-autoapi sphinx-rtd-theme
  script:
    # Create docs directory structure if it doesn't exist
    - mkdir -p docs/source
    - |
      if [ ! -f "$CONF_PY" ]; then
        sphinx-quickstart --quiet --project "$PROJECT_NAME" --author "$PROJECT_AUTHOR" --sep --makefile --batchfile --ext-autodoc docs
      fi
    # Update conf.py with autoapi settings
    - |
      if [ -f "update_conf.py" ]; then
        python update_conf.py
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