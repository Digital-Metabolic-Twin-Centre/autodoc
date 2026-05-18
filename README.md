# GitHub Pages Deployment Branch

This branch is configured as the GitHub Pages publishing source for this repository.

- Source branch for documentation changes: `main`
- Deployment branch served by GitHub Pages: `gh-pages`

To publish updated docs without GitHub Actions:

## What It Does

- Reads repository trees from GitHub or GitLab using provider APIs.
- Scans Python, JavaScript, TypeScript, and MATLAB source files.
- Detects function, class, and module-level documentation coverage.
- Generates missing docstring suggestions with OpenAI using `gpt-4o-mini` by default.
- Supports `reuse_doc=true` so previously generated suggestions can be reused instead of calling OpenAI again.
- Writes per-run logs and analysis artifacts under `logs/<provider>/<repo>/app_<timestamp>/`.
- Mirrors all analyzed Python files into `autoapi_include/` in the target repository for AutoAPI output.
- Preserves nested package structure inside `autoapi_include/` and removes stale old files during regeneration.
- Scaffolds the target repo with bundled sample Sphinx pages and assets, with optional `docs/scaffold/` overrides if that folder exists.
- Configures AutoAPI against `autoapi_include/` and pre-filters risky files before building docs.
- Writes a skipped-files report when AutoAPI files are excluded during publish fallback.
- Can publish built HTML to `gh-pages` without requiring a GitHub Actions workflow.

## Project Layout

```text
.
├── Dockerfile
├── docker-compose.yaml
├── autoapi_include/            # Example mirrored Python source tree used for AutoAPI
├── diagrams/                   # Architecture diagrams for the project
├── docs/
│   ├── conf.py
│   ├── index.rst
│   └── ...                     # Sphinx docs for this Auto Doc service
├── prepush_check.py
├── pyproject.toml
├── src/
│   ├── main.py                 # FastAPI application entry point
│   ├── config/                 # Runtime constants and logging setup
│   ├── models/                 # Pydantic request models
│   ├── router/                 # API routes
│   ├── services/               # Repository analysis, scaffold, and publish flows
│   └── utils/                  # Git provider, docstring, path, and helper utilities
└── tests/
```

## Runtime Outputs

Each repo run gets its own folder:

```text
logs/
└── github/
    └── owner__repository/
        └── app_<timestamp>/
            ├── app.log
            ├── block_analysis.csv
            ├── suggested_docstring.txt
            ├── suggested_docstrings.json
            └── skipped_autoapi_files.txt   # only when publish skips files
```

What these files mean:

- `app.log`: runtime logs for that repo run
- `block_analysis.csv`: flattened coverage report for analyzed code blocks
- `suggested_docstring.txt`: human-readable generated or reused suggestions
- `suggested_docstrings.json`: structured suggestion cache used by reuse and PR creation
- `skipped_autoapi_files.txt`: files excluded from the publish build because they were risky or failed AutoAPI

## Requirements

- Python 3.11+
- `uv`
- An OpenAI API key
- A GitHub or GitLab access token for the target repository
- Docker, if you want to run the service in a container

### GitHub Token Permissions

For a fine-grained GitHub personal access token, use repository-scoped access and select the target
repository. Recommended minimum permissions:

- `Contents`: Read and write
- `Metadata`: Read-only

For `/publish-pages`, also set:

- `Pages`: Read and write

For `/suggest-python-docstrings-pr`, also set:

- `Pull requests`: Read and write

GitHub can still reject Pages configuration if the token owner lacks enough repository-level access.

## Setup

```sh
uv venv
source .venv/bin/activate
uv sync --group dev --no-install-project
```

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your-openai-api-key
ADMIN_PASSWORD=choose-a-strong-password
ADMIN_SECRET_KEY=choose-a-long-random-secret

# Optional admin overrides
# ADMIN_USERNAME=admin
# ADMIN_SQLITE_PATH=/app/data/admin.db

# Optional, only needed if Auto Doc should trigger GitLab pipelines.
CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token
```

## Run Locally

```sh
uv run uvicorn main:app --app-dir src --reload
```

The service runs at `http://localhost:8000`.
Interactive API docs are available at `http://localhost:8000/docs`.
The root URL `http://localhost:8000/` now redirects to the internal admin dashboard.
The admin dashboard is also available directly at `http://localhost:8000/admin` and uses HTTP Basic auth from `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

You can also run it directly:

```sh
uv run python src/main.py
```

## Run With Docker

```sh
docker compose up --build
```

The compose file exposes port `8000` and mounts the local `logs/` directory into the container.

## Internal Admin Dashboard

The service now includes a lightweight internal dashboard built with FastAPI, HTMX, Jinja templates, TailwindCSS, and SQLite.

What it supports:

- Saved repository configurations for GitHub and GitLab
- Encrypted access token storage using `ADMIN_SECRET_KEY`
- Generate, publish, and docstring PR workflows triggered from the UI
- Live run status polling with HTMX
- Persistent run history, summary metrics, log snippets, and artifact downloads
- Repository-level quick reuse of saved operational defaults

Operational notes:

- Tokens are never shown again in raw form after creation
- Admin pages require HTTP Basic auth
- State-changing admin forms use CSRF tokens
- SQLite data defaults to `data/admin.db` and can be overridden with `ADMIN_SQLITE_PATH`

## API

### `GET /`

Returns a simple welcome message.

### `POST /generate`

Analyzes a repository branch and writes documentation scaffold files to that same branch.

```json
{
  "provider": "github",
  "repo_url": "owner/repository",
  "token": "access-token",
  "branch": "docs-review",
  "target_folders": ["api", "tools"],
  "model": "gpt-4o-mini",
  "reuse_doc": true,
  "docstring_threshold": 0.5,
  "low_content_min_lines": 4
}
```

Notes:

- `provider` must be `github` or `gitlab`
- `repo_url` can be a full URL or `owner/repo`
- `target_folders` is optional and limits analysis scope
- `model` is optional; when omitted, Auto Doc defaults to `gpt-4o-mini`
- `docstring_threshold` defaults to `0.5` and controls which files count as high-coverage in the generated analysis
- `low_content_min_lines` defaults to `4` and is used later when filtering low-signal AutoAPI modules during docs builds
- `reuse_doc=false` starts fresh for that repo and clears prior run history
- `reuse_doc=true` loads the latest matching `suggested_docstrings.json` for the same repo and branch and only generates missing suggestions

Successful responses include:

```json
{
  "status": "success",
  "sphinx_setup_created": true,
  "Docstring_analysis": []
}
```

### `POST /publish-pages`

GitHub only. Downloads the reviewed source branch, builds the Sphinx HTML locally, and publishes the
resulting static site to `gh-pages`.

```json
{
  "repo_url": "owner/repository",
  "token": "access-token",
  "branch": "docs-review",
  "low_content_min_lines": 4
}
```

Important behavior:

- Auto Doc publishes from the branch you specify, so that branch should be reviewed first.
- The build uses the sample Sphinx layout plus AutoAPI over `autoapi_include/`.
- Auto Doc proactively ignores risky AutoAPI files such as common config, URL, migration, and view modules.
- If Sphinx still fails on a module, Auto Doc performs one fallback skip pass and writes `skipped_autoapi_files.txt`.

Successful responses include:

```json
{
  "status": "success",
  "published_branch": "gh-pages",
  "source_branch": "docs-review"
}
```

### `POST /suggest-python-docstrings-pr`

GitHub only. Applies previously generated Python docstring suggestions, commits them to a suggestion
branch, and opens a pull request for review.

```json
{
  "provider": "github",
  "repo_url": "owner/repository",
  "token": "access-token",
  "base_branch": "main",
  "suggestion_branch": "autodocs-docstring-suggestions-20260424-1430",
  "title": "Add suggested Python docstrings",
  "max_docstrings": 50
}
```

This endpoint reuses `suggested_docstrings.json` from `/generate`; it does not call OpenAI again. If you omit `suggestion_branch`, Auto Doc creates one with an `autodocs-docstring-suggestions-<timestamp>` name.

## Generated Repo Structure

When `/generate` prepares a target repo branch, it can add or update files like:

```text
autoapi_include/
docs/
├── Makefile
├── conf.py
├── api_reference.rst
├── index.rst
├── README.rst
├── _static/
│   ├── custom-wide.css
│   └── img/
│       ├── favicon.ico
│       └── logo.png
└── project/
    ├── overview.rst
    ├── objectives.rst
    ├── plan.rst
    └── results.rst
update_conf.py
```

The generated docs scaffold comes from bundled sample templates in the service, with optional `docs/scaffold/` file overrides if that folder is added to this repo.

## Recommended Workflow

Use a review branch, not a production branch:

1. Create a branch such as `docs-review`.
2. Call `/generate` on that branch.
3. Review the committed scaffold, `autoapi_include/`, and analysis outputs.
4. Call `/publish-pages` only after the branch looks correct.
5. Merge the reviewed branch when you are satisfied.
6. Optionally call `/suggest-python-docstrings-pr` for a separate source-docstring PR flow.

## Local Checks

```sh
uv sync --group dev --no-install-project
uv run ruff check src tests
OPENAI_API_KEY=test-key uv run pytest --cov=src --cov-report=term-missing --cov-report=xml
uv sync --group docs --no-install-project
uv run sphinx-build -E -W -b html docs docs/build/html
```

Or run the combined helper:

```sh
python3 prepush_check.py
```

Include the Docker image build check with:

```sh
python3 prepush_check.py --docker
```

## Notes

- `/generate` writes directly to the target branch; it does not open a PR.
- `/generate` requires at least one analyzed Python file on the target branch before it will scaffold Sphinx files.
- `/suggest-python-docstrings-pr` is the PR-based path for Python docstring insertions.
- Reuse matching is exact first, then fuzzy by file path, symbol name, block type, and language.
- A new `app_<timestamp>` log folder is still created for every run, even when `reuse_doc=true`.
- `docstring_threshold` affects reporting and high-coverage classification, but `autoapi_include/` currently mirrors all analyzed Python files rather than only files above that threshold.
- Auto Doc does not try to fix user code; it either includes, ignores, or skips files for docs generation.
- Unsupported files are skipped during analysis.
- Empty repositories, inaccessible branches, or insufficient permissions return API errors.
