# Auto Doc

Auto Doc is a FastAPI service that analyzes GitHub and GitLab repositories, identifies missing or weak documentation, generates docstring suggestions with OpenAI, scaffolds a Sphinx documentation site, and publishes reviewed output to GitHub Pages.

It is built to help teams move from under-documented source code to a usable docs site with less manual setup and less repetitive review work.

## What It Does

- Connects to GitHub and GitLab repositories through provider APIs
- Scans Python, JavaScript, TypeScript, and MATLAB source files
- Detects documentation coverage at module, class, and function level
- Generates missing Python docstring suggestions with OpenAI
- Reuses previous suggestion artifacts when `reuse_doc=true`
- Creates a Sphinx docs scaffold for the target repository
- Mirrors Python sources into `autoapi_include/` for AutoAPI output
- Publishes built HTML documentation to `gh-pages`
- Includes an internal admin dashboard for saved repositories, runs, logs, and workflow triggers

## Current Workflow

1. Analyze a repository branch with `/generate`
2. Review generated documentation suggestions and scaffolded docs changes
3. Optionally create a docstring suggestion pull request with `/suggest-python-docstrings-pr`
4. Publish the reviewed branch to GitHub Pages with `/publish-pages`

## Project Layout

```text
.
├── src/
│   ├── main.py
│   ├── admin/         # Admin auth, persistence, dashboard routes, run jobs
│   ├── config/        # App configuration and logging
│   ├── models/        # Request models
│   ├── router/        # Public API routes
│   ├── services/      # Analysis, docstring PR, Sphinx, publish workflows
│   ├── templates/     # Jinja admin UI templates
│   └── utils/         # Repo, docstring, and path helpers
├── docs/              # Sphinx docs for this project
├── autoapi_include/   # Example mirrored Python source tree for AutoAPI
├── diagrams/          # Architecture diagrams
├── tests/
├── pyproject.toml
└── docker-compose.yaml
```

## Architecture

### System Context

![System Context diagram](/diagrams/SystemContext-001.png)

For a closer look at the internal structure, see the [Container diagram](diagrams/img/Container-001.png) and the [Component diagram](diagrams/img/Component-001.png).

## Stack

- FastAPI
- OpenAI API
- Sphinx + AutoAPI
- Jinja2 + HTMX
- SQLite + SQLAlchemy
- Docker
- `uv` for environment and dependency management

## Requirements

- Python 3.11+
- `uv`
- OpenAI API key
- GitHub or GitLab token for the target repository
- Docker, if you want to run it in a container

## Environment

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your-openai-api-key
ADMIN_PASSWORD=choose-a-strong-password
ADMIN_SECRET_KEY=choose-a-long-random-secret

# Optional
# ADMIN_USERNAME=admin
# ADMIN_SQLITE_PATH=/app/data/admin.db
# ADMIN_DEFAULT_MODEL=gpt-4o-mini
# CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token
```

## Local Setup

```sh
uv venv
source .venv/bin/activate
uv sync --group dev --no-install-project
```

Run the app:

```sh
uv run uvicorn main:app --app-dir src --reload
```

Or:

```sh
uv run python src/main.py
```

The app runs at `http://localhost:8000`.

- `GET /` redirects to `/admin`
- `GET /docs` serves the FastAPI OpenAPI UI
- `GET /admin` opens the internal dashboard

## Docker

```sh
docker compose up --build
```

## Admin Dashboard

The built-in dashboard lets you:

- Save repository configurations for GitHub and GitLab
- Store access tokens in encrypted form
- Trigger generate, publish, and docstring PR workflows
- Track live run status
- Review run history, log snippets, and generated artifacts

State-changing admin actions are protected with authentication and CSRF checks.

## API Endpoints

### `POST /generate`

Analyzes a repository branch and writes documentation scaffold files to that branch.

### `POST /suggest-python-docstrings-pr`

Creates a branch and pull request with suggested Python docstring changes.

### `POST /publish-pages`

Builds the reviewed docs branch and publishes the static output to `gh-pages`.

## Runtime Output

Each run writes artifacts under a repo-specific log directory, for example:

```text
logs/<provider>/<repo>/app_<timestamp>/
```

Typical outputs include:

- `app.log`
- `block_analysis.csv`
- `suggested_docstring.txt`
- `suggested_docstrings.json`
- `skipped_autoapi_files.txt` when publish fallback excludes files

## Status

This repository currently contains the core Auto Doc service, its admin dashboard, Sphinx scaffolding flow, and GitHub Pages publishing workflow.
