<!--
Sync Impact Report
Version change: 1.0.0 -> 2.0.0
Modified principles:
- Principle 1 placeholder -> I. Review-First Documentation Automation
- Principle 2 placeholder -> II. Provider-Safe Repository Operations
- III. Regression Protection & Quality Gates -> III. Baseline Quality Gates & Change Review
- Principle 4 placeholder -> IV. Traceable Runtime Artifacts
- Principle 5 placeholder -> V. Simple, Typed Service Boundaries
Added sections:
- None
Removed sections:
- None
Templates requiring updates:
- ✅ .specify/templates/plan-template.md
- ✅ .specify/templates/spec-template.md (reviewed; no principle-specific change required)
- ✅ .specify/templates/tasks-template.md
- ✅ .specify/templates/commands/*.md (directory absent; no update required)
Runtime guidance requiring updates:
- ✅ README.md (reviewed; no principle-specific change required)
- ✅ AGENTS.md (reviewed; no principle-specific change required)
- ✅ docs/project/plan.rst (reviewed; no principle-specific change required)
Follow-up TODOs:
- None
-->
# Auto Doc Constitution

## Core Principles

### I. Review-First Documentation Automation
Auto Doc MUST produce documentation changes as reviewable artifacts before any
publishing step. Generated docstrings, Sphinx scaffolds, AutoAPI output, and
GitHub Pages content MUST remain inspectable by a maintainer before they become
the published source of truth. The service MUST preserve enough context for a
reviewer to understand what source files were analyzed, what documentation was
generated, and what changes require human judgment.

Rationale: Auto Doc uses AI-assisted generation in developer repositories, so
maintainers need review control before generated content reaches production
documentation.

### II. Provider-Safe Repository Operations
GitHub and GitLab integrations MUST use explicit repository, branch, and token
inputs for every mutating workflow. Features that clone, write, create pull
requests, trigger pipelines, or publish pages MUST validate provider-specific
paths and avoid implicit writes to default branches unless the workflow
explicitly requires and documents that behavior. Secrets MUST be loaded from
configuration or encrypted storage and MUST NOT be written to logs, generated
documentation, or runtime artifacts.

Rationale: The service operates on external repositories and credentials; a
small ambiguity can publish to the wrong target or expose private access.

### III. Baseline Quality Gates & Change Review

Every implementation MUST pass the repository validation baseline before it is
considered complete. The baseline is the smallest useful set of checks the
project currently maintains: `uv run ruff check src tests`, `uv run pytest`,
and `uv run sphinx-build -E -W -b html docs docs/_build/html` when
documentation sources or Sphinx configuration change. Changes to container or
runtime packaging MUST additionally pass `docker build` or an equivalent build
validation step before merge.

When a change touches API behavior, admin authentication, repository mutation
logic, SQLite schema handling, dependency declarations, or publishing
workflows, the implementation MUST include an explicit review of regression
risk in those areas. That review MAY be manual when the project does not yet
have automated coverage, but it MUST be recorded in the plan, tasks, code
review, or implementation summary and backed by targeted tests or validation
steps where feasible.

Changes that intentionally introduce breaking behavior MUST explicitly document:

- why the change is required
- affected APIs, operators, or users
- any migration, rollback, or manual recovery steps that exist today
- why the breaking change is acceptable at this stage of the project

Critical findings from the baseline checks or targeted review MUST be resolved
before implementation is considered complete unless an explicit exception is
documented and approved.

Rationale: The project has reliable lint, test, documentation, and container
validation gates today, but broader regression categories are still partly
manual. The constitution must require what the repository can consistently
enforce while still making higher-risk changes visible and reviewable.

### IV. Traceable Runtime Artifacts
Each documentation run MUST emit enough structured runtime evidence to support
debugging and review, including logs, analysis summaries, skipped-file reports
where applicable, and generated suggestion artifacts. Artifact paths MUST be
repo-scoped and deterministic enough to avoid cross-run or cross-repository
confusion. Logs MUST describe operational state and failures without leaking
tokens, secrets, generated credentials, or private source content beyond what is
needed for debugging.

Rationale: The value of generated documentation depends on being able to audit
how it was produced and diagnose failed or partial runs.

### V. Simple, Typed Service Boundaries
New behavior MUST fit the existing FastAPI service structure: routers handle
HTTP/API concerns, services coordinate workflows, utilities handle isolated
transformations, Pydantic models validate request data, and admin modules own
dashboard-specific behavior. Shared logic MUST be typed, testable without live
provider credentials where feasible, and kept free of unnecessary abstraction
layers unless they remove duplicated workflow complexity.

Rationale: Clear boundaries keep provider logic, generated-documentation
logic, and admin behavior understandable as the project grows.

## Technology Constraints

Auto Doc targets Python 3.11+ and uses FastAPI, Pydantic, SQLAlchemy, Jinja2,
HTMX, Sphinx, AutoAPI, OpenAI, GitHub/GitLab provider APIs, Docker, and `uv`.
Implementation plans MUST identify affected dependencies and generated
documentation behavior before coding. New runtime dependencies MUST be justified
by a concrete workflow need and pinned or constrained consistently in
`pyproject.toml`/`uv.lock`.

Generated documentation MUST remain compatible with the Sphinx build workflow
and the AutoAPI include strategy. Any change that touches publishing,
scaffolding, or generated files MUST document how maintainers can review and
rebuild the output locally.

## Development Workflow

Feature specifications MUST define independently testable user journeys and
measurable outcomes. Plans MUST pass the Constitution Check before design work
and again before implementation tasks are finalized. Tasks MUST keep setup,
foundational work, user-story implementation, tests, documentation updates, and
cross-cutting concerns traceable to the feature plan.

Code review MUST verify provider safety, changed-path regression risk, test
coverage updates, artifact traceability, secret handling, and Sphinx/build
compatibility for every relevant change. Before merge, maintainers MUST run the
smallest useful validation set, normally `uv run ruff check src tests`, `uv
run pytest`, and `uv run sphinx-build -E -W -b html docs docs/_build/html`
when documentation output or Sphinx configuration changes. Changes that touch
the Docker image, packaging, or deployment path MUST also validate `docker
build` or an equivalent container build step.

## Governance

This constitution supersedes conflicting project practices and templates.
Amendments MUST update this file, include a Sync Impact Report, and propagate
any changed rules into affected Spec Kit templates, runtime guidance, and
developer documentation. Each amendment MUST record the version change and
rationale.

Versioning follows semantic versioning:
- MAJOR: removes or redefines existing principles or governance in a
  backward-incompatible way.
- MINOR: adds a principle, required section, or materially expands compliance
  expectations.
- PATCH: clarifies wording, fixes errors, or updates non-semantic guidance.

Compliance is reviewed during planning, task generation, code review, and
release validation. Any approved exception MUST be documented in the relevant
plan's Complexity Tracking section with the simpler alternative that was
rejected and the reason it was insufficient.



**Version**: 2.0.0 | **Ratified**: 2026-07-03 | **Last Amended**: 2026-07-03
