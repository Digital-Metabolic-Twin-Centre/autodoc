def generate_gitlab_ci_file() -> str:
    """
    Generates the contents of a `.gitlab-ci.yml` file for building docs.

    Returns:
        str: GitLab CI configuration content.
    """
    gitlab_ci_content = """stages:
  - docs
  - deploy

variables:
  PY_VERSION: "3.11"
  DOCS_SRC: "docs"
  BUILD_DIR: "docs/build/html"
  CONF_PY: "docs/conf.py"
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
    - mkdir -p docs
    - |
      if [ ! -f "$CONF_PY" ]; then
        sphinx-quickstart --quiet --project "$PROJECT_NAME" \\
          --author "$PROJECT_AUTHOR" --makefile \\
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
          mkdir -p docs
          if [ ! -f "docs/conf.py" ]; then
            sphinx-quickstart --quiet --project "API Documentation" \
              --author "Development Team" --makefile \
              --batchfile --ext-autodoc docs
          fi

      - name: Update Sphinx AutoAPI configuration
        run: |
          if [ -f "update_conf.py" ]; then
            python update_conf.py "docs/conf.py"
          fi

      - name: Build documentation
        run: sphinx-build -b html docs docs/build/html

      - name: Upload documentation artifact
        uses: actions/upload-artifact@v4
        with:
          name: docs-html
          path: docs/build/html
"""

    return github_actions_content


def generate_github_pages_index(project_name: str = "API Documentation") -> str:
    """
    Generates a small landing page for a branch-based GitHub Pages site.

    Args:
        project_name (str): Display name shown on the landing page.

    Returns:
        str: Static HTML content.
    """
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{project_name}</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f7f4ec;
        --fg: #182028;
        --muted: #5d6773;
        --panel: #fffdf8;
        --line: #d8d2c3;
        --accent: #0a7b83;
      }}
      * {{
        box-sizing: border-box;
      }}
      body {{
        margin: 0;
        font-family: Georgia, "Times New Roman", serif;
        background:
          radial-gradient(circle at top right, rgba(10, 123, 131, 0.12), transparent 35%),
          linear-gradient(180deg, #fbf9f2, var(--bg));
        color: var(--fg);
      }}
      main {{
        max-width: 760px;
        margin: 0 auto;
        padding: 72px 24px;
      }}
      .card {{
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 20px;
        padding: 32px;
        box-shadow: 0 18px 50px rgba(24, 32, 40, 0.08);
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: clamp(2.2rem, 6vw, 3.6rem);
        line-height: 1.05;
      }}
      p {{
        font-size: 1.05rem;
        line-height: 1.7;
        color: var(--muted);
      }}
      code {{
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
        color: var(--accent);
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="card">
        <h1>{project_name}</h1>
        <p>
          This GitHub Pages branch has been prepared for branch-based publishing.
          Push your built static documentation into this branch to replace this placeholder.
        </p>
        <p>
          The recommended flow is to build your docs locally, then publish the generated HTML
          to <code>gh-pages</code>.
        </p>
      </section>
    </main>
  </body>
</html>
"""
