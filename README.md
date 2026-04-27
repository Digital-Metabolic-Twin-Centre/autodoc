# Auto-Doc

Auto-Doc is a FastAPI service that analyzes a GitHub or GitLab repository for missing
docstrings, suggests docstrings with OpenAI, and prepares Sphinx AutoAPI documentation files
in the target repository.

This branch uses branch-based GitHub Pages publishing. The `/generate` endpoint prepares the
selected source branch for review, and the `/publish-pages` endpoint builds the reviewed Sphinx
site and publishes the generated HTML to `gh-pages`.

## What It Does

- Reads repository trees from GitHub or GitLab using provider APIs.
- Scans Python, JavaScript, TypeScript, and MATLAB source files.
- Detects function, class, and module-level documentation coverage.
- Writes analysis results to `src/files/block_analysis.csv`.
- Writes OpenAI-generated suggestions for missing docstrings to
  `src/files/suggested_docstring.txt`.
- Can open a GitHub pull request with generated Python docstring suggestions for review.
- Copies files with at least 75% docstring coverage into `autoapi_include/` in the target
  repository.
- Adds `update_conf.py` so the target repository can enable `sphinx-autoapi`.
- For GitLab, creates or updates `.gitlab-ci.yml` and optionally triggers a pipeline.
- For GitHub, creates a review guide on the selected branch and can publish built HTML to
  `gh-pages` through `/publish-pages`.

## Project Layout

```text
.
├── Dockerfile
├── docker-compose.yaml
├── docs/
│   └── source/                 # Sphinx documentation for this service
├── prepush_check.py            # Local quality gate helper
├── pyproject.toml
├── src/
│   ├── main.py                 # FastAPI application entry point
│   ├── config/                 # Runtime constants and logging setup
│   ├── models/                 # Pydantic request models
│   ├── router/                 # API routes
│   ├── services/               # Repository analysis and Sphinx publishing flows
│   └── utils/                  # Git provider, docstring, and generated file helpers
└── tests/                      # Unit tests
```

Runtime output directories are created as needed:

```text
src/files/
├── block_analysis.csv
└── suggested_docstring.txt

log/
└── app_<timestamp>.log
```

## Requirements

- Python 3.11+
- `uv`
- An OpenAI API key
- A GitHub or GitLab access token for the repository you want to analyze
- Docker, if you want to run the service in a container

For GitHub publishing, the token must be able to read repository contents, write contents, and
manage GitHub Pages settings. For GitLab setup, the token must be able to read the repository and
write files to the selected branch.

### GitHub Token Permissions

For a fine-grained GitHub personal access token, use repository-scoped access and select the target
repository. The minimum permissions are:

- **Contents:** Read and write
- **Metadata:** Read-only

Those permissions are enough for `/generate`, which reads source files and commits generated docs
setup files back to the selected branch.

For `/publish-pages`, also set this permission when GitHub shows it on the token form:

- **Pages:** Read and write

If the token does not include Pages write access, `/publish-pages` may fail when it tries to
configure GitHub Pages, even if `/generate` works.

For `/suggest-python-docstrings-pr`, also set:

- **Pull requests:** Read and write

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

The compose file exposes port `8000` and mounts local `files/` and `log/` directories into the
container paths used by the app.

## API

### `GET /`

Returns a simple welcome message.

### `POST /generate`

Analyzes a repository branch and prepares Sphinx documentation support in that same branch.

```json
{
  "provider": "github",
  "repo_url": "owner/repository",
  "token": "access-token",
  "branch": "docs-review"
}
```

`provider` must be `github` or `gitlab`. `repo_url` can be a provider URL such as
`https://github.com/owner/repository` or a repository path such as `owner/repository`.

Successful responses include:

```json
{
  "status": "success",
  "sphinx_setup_created": true,
  "Docstring_analysis": []
}
```

### `POST /publish-pages`

GitHub only. Builds Sphinx HTML from a reviewed source branch, publishes the generated static site
to `gh-pages`, configures branch-based GitHub Pages, and requests a Pages rebuild.

```json
{
  "repo_url": "owner/repository",
  "token": "access-token",
  "branch": "docs-review"
}
```

Successful responses include:

```json
{
  "status": "success",
  "published_branch": "gh-pages",
  "source_branch": "docs-review"
}
```

### `POST /suggest-python-docstrings-pr`

GitHub only. Applies previously generated Python function/class docstring suggestions, commits the
changes to a suggestion branch, and opens a pull request for review. Run `/generate` first; this
endpoint uses the structured suggestions created during that analysis instead of making another
OpenAI request.

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

`suggestion_branch` is optional. When omitted, Auto-Doc creates a unique branch name such as
`autodocs-docstring-suggestions-20260424-1430`.

Successful responses include:

```json
{
  "status": "success",
  "provider": "github",
  "base_branch": "main",
  "suggestion_branch": "autodocs-docstring-suggestions-20260424-1430",
  "pull_request_url": "https://github.com/owner/repository/pull/12",
  "files_changed": 3,
  "docstrings_added": 10,
  "changed_files": ["src/example.py"]
}
```

## Repository Flow

1. Call `/generate` with a repository, token, branch, and provider.
2. Auto-Doc scans supported files and writes local analysis output.
3. Files with at least 75% docstring coverage are copied into `autoapi_include/` in the target
   repository branch.
4. Auto-Doc commits `update_conf.py` to the target branch.
5. For GitLab, Auto-Doc commits `.gitlab-ci.yml` and tries to trigger a pipeline when
   `CI_TRIGGER_PIPELINE_TOKEN` is set.
6. For GitHub, review the generated branch changes, then call `/publish-pages` to build the docs
   and publish the HTML to `gh-pages`.
7. Optionally call `/suggest-python-docstrings-pr` to open a separate GitHub pull request with
   Python docstring suggestions for missing function/class docstrings.

## Local Checks

```sh
uv run ruff check src tests
uv run pytest
uv run sphinx-build -W -b html docs/source docs/build/html
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

- Generated docstrings should be reviewed before being applied to source code.
- Unsupported files are skipped during analysis.
- Empty repositories, inaccessible branches, or tokens without enough permissions cause the API to
  return an error.
- The current GitHub flow does not create a GitHub Actions workflow. It publishes by building
  reviewed docs server-side and committing static HTML to `gh-pages`.
