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
  gitlab_ci_content = """stages: [docs]

variables:
  PY_VERSION: "3.11"
  DOCS_SRC: ${DOCS_SRC}
  BUILD_DIR: ${BUILD_DIR}
  CONF_PY: ${CONF_PY}
  PROJECT_NAME: ${PROJECT_NAME}
  PROJECT_AUTHOR: ${PROJECT_AUTHOR}
  GIT_USER_EMAIL: ${GIT_USER_EMAIL}
  GIT_USER_NAME: ${GIT_USER_NAME}

build_sphinx_manual:
  stage: docs
  image: python:${PY_VERSION}
  allow_failure: false
  only:
    - triggers
  before_script:
    - python -m pip install --upgrade pip
    - python -m venv venv
    - source venv/bin/activate
    - pip install --upgrade pip
    - if [ -f requirements.txt ]; then pip install -r requirements.txt || true; fi
    - pip install sphinx
    - pip install sphinx-autoapi
    # Run sphinx-quickstart if conf.py does not exist
    - |
      if [ ! -f "$CONF_PY" ]; then
        sphinx-quickstart --quiet --project "$PROJECT_NAME" --author "$PROJECT_AUTHOR" --sep --makefile --batchfile --ext-autodoc docs
      fi
  script:
    # Commit and push all Sphinx-related files if there are changes
    - python update_conf.py $CONF_PY
    - sphinx-build -b html "$DOCS_SRC" "$BUILD_DIR"
    - |
      git config --global user.email "$GIT_USER_EMAIL"
      git config --global user.name "$GIT_USER_NAME"
      git add docs
      git add docs/build -f
      git add update_conf.py
      git diff --cached --quiet || git commit -m "Add/update Sphinx docs structure through CI/CD pipeline"
      git push https://gitlab-ci-token:${CI_PUSH_TOKEN}@${CI_SERVER_HOST}/${CI_PROJECT_PATH}.git HEAD:${CI_COMMIT_REF_NAME}
  artifacts:
    paths:
      - docs/build/html
    expire_in: 1 week
"""

  return gitlab_ci_content