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
