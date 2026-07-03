# Data Model: Architecture Documentation Generation

## ArchitectureGenerationRequest

Represents a request to analyze a repository and create a reviewable
architecture documentation draft.

**Fields**:
- `provider`: repository provider, constrained to supported providers.
- `repo_url`: target repository URL.
- `token`: access token used for repository read access; never persisted in
  generated artifacts or logs.
- `branch`: branch to analyze.
- `target_folders`: optional folder filters for scoped analysis.
- `output_path`: preferred documentation path for the approved architecture page.
- `include_diagrams`: whether diagrams should be generated when evidence is
  sufficient.
- `reuse_existing_docs`: whether existing architecture docs should be used as
  context for regeneration.
- `model`: optional generation model name, following existing model override
  behavior.

**Validation rules**:
- `provider`, `repo_url`, `token`, and `branch` are required.
- `output_path` must stay within the documentation tree when provided.
- `target_folders` must be normalized and cannot escape the repository root.

## ArchitectureApprovalRequest

Represents explicit maintainer approval to apply a generated architecture draft
to the target repository documentation workflow.

**Fields**:
- `provider`: repository provider.
- `repo_url`: target repository URL.
- `token`: access token used for repository write access.
- `branch`: branch receiving the approved documentation update.
- `draft_id`: identifier for the generated architecture draft artifact.
- `output_path`: documentation path to update.
- `overwrite_existing`: whether approved manual edits may be replaced.
- `approval_note`: optional reviewer note recorded with the approval.

**Validation rules**:
- `draft_id`, `provider`, `repo_url`, `token`, `branch`, and `output_path` are
  required.
- `overwrite_existing` must be true before replacing existing approved manual
  architecture content.

## AnalysisRun

Represents a single repository architecture analysis attempt.

**Fields**:
- `run_id`: unique run identifier.
- `provider`, `repo_url`, `branch`: analyzed source target.
- `status`: queued, running, success, partial, failed, cancelled.
- `artifact_dir`: repo-scoped artifact directory.
- `log_path`: secret-safe run log path.
- `draft_id`: generated draft identifier when available.
- `analysis_summary_path`: structured summary artifact path.
- `started_at`, `completed_at`, `duration_seconds`.
- `error_message`: safe failure message when applicable.

**Relationships**:
- One AnalysisRun creates zero or one ArchitectureDraft.
- One AnalysisRun records many ArchitectureSections, Findings, and Gaps through
  the draft artifacts.

## ArchitectureDraft

Represents the generated reviewable documentation artifact.

**Fields**:
- `draft_id`: stable id for approval.
- `run_id`: source analysis run.
- `status`: draft, approved, rejected, superseded.
- `draft_path`: generated document artifact path.
- `proposed_output_path`: suggested target documentation path.
- `navigation_update`: proposed documentation navigation change.
- `diagram_paths`: generated diagram artifact paths.
- `created_at`, `reviewed_at`.

**Relationships**:
- Contains many ArchitectureSections.
- Receives zero or more ReviewDecisions.

## ArchitectureSection

Represents one required section in the architecture draft.

**Fields**:
- `section_name`: project overview, entry points, services, routers, modules and
  packages, internal dependencies, external dependencies, data flow, background
  jobs, database models, configuration, environment variables, authentication
  flow, API endpoints, sequence diagrams, architecture diagrams, repository
  structure, or technology stack.
- `status`: populated, partial, unavailable.
- `summary`: reviewer-facing section content.
- `confidence_level`: high, medium, low, or not applicable.
- `evidence_count`: number of supporting findings.

**Relationships**:
- Has many ArchitectureFindings.
- Has zero or more AnalysisGaps.

## ArchitectureFinding

Represents an observed fact or inferred architecture relationship.

**Fields**:
- `finding_type`: service, router, module, dependency, data_flow, job, model,
  config, environment_variable, auth_flow, endpoint, entry_point, technology.
- `name`: human-readable finding name.
- `classification`: observed or inferred.
- `confidence_level`: required for inferred findings.
- `evidence_paths`: source or documentation paths supporting the finding.
- `description`: reviewer-facing explanation.

**Validation rules**:
- Inferred findings must include a confidence level and explanation.
- Observed findings must include at least one evidence path where feasible.

## AnalysisGap

Represents incomplete or ambiguous architecture analysis.

**Fields**:
- `section_name`: affected architecture section.
- `gap_type`: missing, ambiguous, inaccessible, unsupported, too_large.
- `description`: reviewer-facing caveat.
- `recommended_review_action`: suggested maintainer action.

## ReviewDecision

Represents maintainer review of a generated architecture draft.

**Fields**:
- `decision`: approved, rejected, changes_requested, overwrite_confirmed.
- `reviewer`: maintainer identifier when available.
- `reviewed_at`: decision timestamp.
- `approval_note`: optional note.
- `applied_commit`: commit id or URL when approval mutates the repository.

## State Transitions

```text
AnalysisRun: queued -> running -> success | partial | failed | cancelled
ArchitectureDraft: draft -> approved | rejected | superseded
ReviewDecision: changes_requested -> approved | rejected
Regeneration: draft -> superseded when a newer draft replaces an unapproved draft
```
