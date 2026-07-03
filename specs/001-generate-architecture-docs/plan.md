# Implementation Plan: Architecture Documentation Generation

**Branch**: `001-generate-architecture-docs` | **Date**: 2026-07-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-generate-architecture-docs/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Add a review-first architecture documentation workflow that analyzes a target
repository, produces a confidence-labeled architecture draft, integrates the
draft into the repository's existing Sphinx documentation hierarchy, and blocks
commit/publish until explicit maintainer approval. The implementation will reuse
the existing FastAPI request/route/service pattern, repo-scoped artifact
directories, Sphinx scaffold/update utilities, admin run tracking, and provider
write safeguards.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI, Pydantic, SQLAlchemy, Jinja2, HTMX, OpenAI,
requests, python-gitlab, Sphinx, sphinx-autoapi, Docker, uv

**Storage**: Repo-scoped run artifacts under `logs/<provider>/<repo>/app_<timestamp>/`;
existing admin SQLite database for dashboard run records; target repository
documentation files for approved architecture docs

**Testing**: pytest, pytest-cov, httpx, ruff, Sphinx build validation when docs
templates or generated documentation integration changes

**Target Platform**: Linux-compatible web service and container runtime;
GitHub/GitLab-hosted repositories; Sphinx-generated static documentation

**Project Type**: FastAPI web service with internal admin dashboard and
repository documentation generation workflows

**Performance Goals**: Generate a reviewable draft for representative
repositories within the existing asynchronous admin run workflow; preserve
partial results and clear failure states when a repository is too large or
ambiguous for complete analysis

**Constraints**: No automatic commit or publish from generation; no token or
secret leakage in logs/artifacts; reuse existing Sphinx documentation structure
and templates; preserve approved manual edits unless overwrite is confirmed;
confidence labels required for inferred relationships

**Scale/Scope**: One target repository branch per architecture analysis run;
high-level architecture documentation covering project overview, entry points,
services, routers, modules/packages, dependencies, data flow, background jobs,
database models, configuration, environment variables, authentication flow, API
endpoints, diagrams, repository structure, and technology stack

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Review-first documentation automation: PASS. Architecture generation produces
  repo-scoped draft artifacts and does not commit or publish until an explicit
  approval request is made.
- Provider-safe repository operations: PASS. Generation reads repository
  content only; approval is the only mutating path and must target an explicit
  provider, repository, branch, architecture artifact, and overwrite decision.
  Tokens remain request/configuration data and must not be written to logs or
  generated docs.
- Regression protection & quality gates: PASS. Implementation requires tests for
  request validation, architecture analysis classification, confidence labels,
  Sphinx navigation/template integration, manual-edit preservation, approval
  gating, provider failure handling, and generated artifact paths.
- Traceable runtime artifacts: PASS. Each run records draft paths, analysis
  summary, confidence/gap metadata, proposed documentation location, log path,
  and approval state in repo-scoped artifact directories.
- Simple, typed service boundaries: PASS. New behavior maps to Pydantic request
  models, router endpoints, workflow service orchestration, architecture
  analysis utilities, Sphinx integration helpers, and admin job/dashboard
  extension points. No new broad abstraction layer is required.

## Project Structure

### Documentation (this feature)

```text
specs/001-generate-architecture-docs/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── architecture-docs-api.yaml
└── tasks.md
```

### Source Code (repository root)

```text
src/
├── models/
│   └── repo_request.py              # Add architecture generation/approval request models
├── router/
│   └── router.py                    # Add public architecture generation/approval endpoints
├── services/
│   ├── architecture_services.py     # New analysis, draft assembly, confidence/gap logic
│   ├── sphinx_services.py           # Extend Sphinx navigation/template integration helpers
│   └── workflow_service.py          # Add architecture workflow orchestration/results
├── admin/
│   ├── jobs.py                      # Allow admin queue execution for architecture endpoints
│   ├── router.py                    # Add dashboard actions/status for architecture runs
│   └── templates/admin/dashboard.html
└── utils/
    ├── git_utils.py                 # Reuse provider read/write helpers
    └── output_paths.py              # Reuse repo-scoped run artifact helpers

tests/
├── test_architecture_services.py
├── test_router.py
├── test_admin_jobs.py
├── test_sphinx_template.py
├── test_git_utils.py
└── test_output_paths.py
```

**Structure Decision**: Use the existing single-service structure. New
architecture analysis logic belongs in `src/services/architecture_services.py`
because it coordinates repository evidence, draft content, confidence levels,
and review artifacts. HTTP concerns stay in `src/router/router.py`; reusable
request validation stays in `src/models/repo_request.py`; Sphinx-specific
document placement/navigation behavior extends `src/services/sphinx_services.py`.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No constitution violations identified.

## Phase 0: Research

See [research.md](./research.md) for resolved decisions. No unresolved
clarifications remain.

## Phase 1: Design & Contracts

Design artifacts:

- [data-model.md](./data-model.md)
- [contracts/architecture-docs-api.yaml](./contracts/architecture-docs-api.yaml)
- [quickstart.md](./quickstart.md)

### Post-Design Constitution Check

- Review-first documentation automation: PASS. Contracts separate draft
  generation from approval/commit.
- Provider-safe repository operations: PASS. Approval contract requires explicit
  target branch, artifact id, and overwrite confirmation.
- Regression protection & quality gates: PASS. Quickstart and task-ready design
  identify tests for failure, ambiguity, confidence, manual edit preservation,
  and Sphinx integration.
- Traceable runtime artifacts: PASS. Data model includes Analysis Run,
  Architecture Draft, Architecture Section, Architecture Finding, Analysis Gap,
  and Review Decision.
- Simple, typed service boundaries: PASS. Contracts and data model align with
  existing Pydantic/router/service/admin patterns.
