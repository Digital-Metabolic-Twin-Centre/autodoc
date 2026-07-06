# Quickstart: Architecture Documentation Generation

## Prerequisites

- Python 3.11+
- `uv`
- Valid repository token for the provider being tested
- Environment configured as described in `README.md`
- A test repository with an existing documentation tree and at least one
  application entry point

## Setup

```sh
uv venv
source .venv/bin/activate
uv sync --group dev --no-install-project
```

## Run the service

```sh
uv run uvicorn main:app --app-dir src --reload
```

Open `http://localhost:8000/admin` for the admin dashboard or use the public
API contract in [contracts/architecture-docs-api.yaml](./contracts/architecture-docs-api.yaml).

## Scenario 1: Generate a reviewable draft

Submit an architecture generation request for a repository branch.

Expected outcome:

- Response status is `success` or `partial`.
- Response includes `draft_id`, `draft_path`, `proposed_output_path`,
  section summaries, and any analysis gaps.
- No commit or publication occurs.
- The draft artifact includes required architecture sections and labels observed
  facts separately from inferred relationships.
- Inferred relationships include confidence levels.

## Scenario 2: Verify Sphinx documentation integration

Review the generated draft and proposed documentation location.

Expected outcome:

- Proposed output path is inside the existing documentation tree.
- Proposed navigation update fits the current documentation hierarchy.
- Existing documentation style/templates are reused where available.
- Existing manual architecture documentation is not overwritten by generation.

## Scenario 3: Preserve manual edits during regeneration

Create or simulate existing approved architecture documentation, then run
architecture generation again.

Expected outcome:

- Regeneration creates a new draft artifact.
- Approved manual content remains unchanged.
- Any conflicting regenerated content is presented for review.
- Overwrite is blocked unless explicitly confirmed during approval.

## Scenario 4: Approve a draft

Submit an approval request using the generated `draft_id`.

Expected outcome:

- Approval applies or prepares the reviewed architecture document at the
  requested documentation path.
- Existing manual content is replaced only when overwrite confirmation is true.
- The response includes the approved output path and branch.

## Scenario 5: Validate failure and partial-result behavior

Run generation against a repository with missing entry points, ambiguous
dependencies, or incomplete documentation structure.

Expected outcome:

- The workflow returns a clear failure or partial-result status.
- The draft includes visible caveats for incomplete or ambiguous analysis.
- Logs and artifacts do not expose tokens or secrets.

## Validation Commands

```sh
uv run pytest
uv run ruff check .
uv run sphinx-build -b html docs docs/_build/html
```

## Related Design Artifacts

- [data-model.md](./data-model.md)
- [contracts/architecture-docs-api.yaml](./contracts/architecture-docs-api.yaml)

## Implementation Validation Notes

Recorded after implementing and testing the feature:

- `uv run pytest`, `uv run ruff check src tests`, and
  `uv run sphinx-build -E -W -b html docs docs/_build/html` all pass.
- Scenarios 1-5 above are covered by automated tests in
  `tests/test_architecture_services.py`, `tests/test_router.py`,
  `tests/test_sphinx_template.py`, `tests/test_doc_services.py`,
  `tests/test_git_utils.py`, and `tests/test_admin_router.py`.
- Generated architecture drafts reuse existing reStructuredText conventions
  (headings, `.. note::`, `.. warning::`, `.. code-block::`) rather than the
  `docs/scaffold/` sample templates, since those templates are for the initial
  docs scaffold, not for an individual generated page. This is a deliberate
  scoping decision, not a deviation from a firm requirement.
- A repository with no recognizable entry point or top-level structure now
  returns `status: partial` with a visible `AnalysisGap` per the affected
  section, matching Scenario 5.

## Secret and Token Leakage Review (T060)

- Draft artifacts (`architecture_draft_<id>.rst`/`.json`) and diagram files
  never include the request token; only repo path, branch, sections, gaps,
  and paths are recorded.
- `services/architecture_services.py` and `services/sphinx_services.py` log
  provider/repo/branch context but never log the token.
- The admin dashboard's stored `request_payload` excludes the `token` field
  before writing run history for `/generate`, `/publish-pages`,
  `/suggest-python-docstrings-pr`, `/generate-architecture-docs`, and
  `/approve-architecture-docs`, since that payload is rendered back to the
  browser on the run detail page.
- Admin retries rehydrate the token from the encrypted repository configuration
  only for the queued execution payload; the persisted retry run payload remains
  token-free.
- Application startup scrubs any existing run-history `request_payload` JSON
  that still contains a legacy plaintext `token` field.
