# Auto-Doc

Auto-Doc is a FastAPI service that analyzes a GitHub or GitLab repository, generates
docstring suggestions with OpenAI, scaffolds a Sphinx documentation site, and publishes
reviewed HTML to GitHub Pages.

The current workflow is branch-first:

- `/generate` analyzes a target branch and writes documentation scaffold files directly to that branch
- `/publish-pages` builds the reviewed Sphinx site from that branch and publishes the HTML to `gh-pages`
- `/suggest-python-docstrings-pr` opens a separate GitHub pull request with Python docstring insertions

## What It Does

- Reads repository trees from GitHub or GitLab using provider APIs.
- Scans Python, JavaScript, TypeScript, and MATLAB source files.
- Detects function, class, and module-level documentation coverage.
- Generates missing docstring suggestions with OpenAI using `gpt-4o-mini` by default.
- Supports `reuse_doc=true` so previously generated suggestions can be reused instead of calling OpenAI again.
- Writes per-run logs and analysis artifacts under `logs/<provider>/<repo>/app_<timestamp>/`.
- Copies files with at least 75% docstring coverage into `autoapi_include/` in the target repository.
- Preserves nested package structure inside `autoapi_include/` and removes stale old files during regeneration.
- Scaffolds the target repo using the shared `docs/scaffold` Sphinx layout.
- Configures AutoAPI against `autoapi_include/` and pre-filters risky files before building docs.
- Writes a skipped-files report when AutoAPI files are excluded during publish fallback.
- Can publish built HTML to `gh-pages` without requiring a GitHub Actions workflow.

## Project Layout

```text
.
├── docs/scaffold/              # Shared Sphinx template used for generated repos
├── Dockerfile
├── docker-compose.yaml
├── docs/
│   └── source/                 # Sphinx docs for this Auto-Doc service
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

# Optional, only needed if Auto-Doc should trigger GitLab pipelines.
CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token
```

## Run Locally

```sh
uv run uvicorn main:app --app-dir src --reload
```

The service runs at `http://localhost:8000`.
Interactive API docs are available at `http://localhost:8000/docs`.

You can also run it directly:

```sh
uv run python src/main.py
```

## Run With Docker

```sh
docker compose up --build
```

The compose file exposes port `8000` and mounts the local `logs/` directory into the container.

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
  "reuse_doc": true
}
```

Notes:

- `provider` must be `github` or `gitlab`
- `repo_url` can be a full URL or `owner/repo`
- `target_folders` is optional and limits analysis scope
- `model` is optional; when omitted, Auto-Doc defaults to `gpt-4o-mini`
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
  "branch": "docs-review"
}
```

Important behavior:

- Auto-Doc publishes from the branch you specify, so that branch should be reviewed first.
- The build uses the sample Sphinx layout plus AutoAPI over `autoapi_include/`.
- Auto-Doc proactively ignores risky AutoAPI files such as common config, URL, migration, and view modules.
- If Sphinx still fails on a module, Auto-Doc performs one fallback skip pass and writes `skipped_autoapi_files.txt`.

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

This endpoint reuses `suggested_docstrings.json` from `/generate`; it does not call OpenAI again.

## Generated Repo Structure

When `/generate` prepares a target repo branch, it can add or update files like:

```text
autoapi_include/
docs/
├── Makefile
└── source/
    ├── conf.py
    ├── index.rst
    ├── README.rst
    ├── _static/custom-wide.css
    ├── logbook/weekly_updates.rst
    └── project/
        ├── overview.rst
        ├── objectives.rst
        ├── plan.rst
        └── results.rst
update_conf.py
```

The generated docs scaffold is based on `docs/scaffold/`.

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
uv run ruff check src tests
uv run pytest
uv run sphinx-build -b html docs/source docs/build/html
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
- `/suggest-python-docstrings-pr` is the PR-based path for Python docstring insertions.
- Reuse matching is exact first, then fuzzy by file path, symbol name, block type, and language.
- A new `app_<timestamp>` log folder is still created for every run, even when `reuse_doc=true`.
- Auto-Doc does not try to fix user code; it either includes, ignores, or skips files for docs generation.
- Unsupported files are skipped during analysis.
- Empty repositories, inaccessible branches, or insufficient permissions return API errors.
