# Research: Architecture Documentation Generation

## Decision: Reuse the existing generate/review/publish workflow

**Rationale**: The project already separates repository analysis, generated
artifacts, docstring pull requests, and publishing. Architecture documentation
must follow the same review-first model: generation creates artifacts, approval
is a separate explicit action, and publish remains downstream.

**Alternatives considered**:
- Commit architecture docs during generation: rejected because it violates the
  review-first constitution and the feature's explicit approval requirement.
- Create a separate architecture documentation system: rejected because the
  feature requires integration with the existing documentation workflow.

## Decision: Add dedicated architecture request/approval models

**Rationale**: Existing request models focus on docstring analysis, docstring
pull requests, and page publishing. Architecture generation needs explicit
fields for target folders, existing documentation behavior, output location,
confidence reporting, draft artifact id, and overwrite confirmation.

**Alternatives considered**:
- Extend `RepoRequest` with many optional architecture fields: rejected because
  it would blur docstring generation and architecture generation semantics.
- Use untyped dictionaries: rejected because the project uses Pydantic models
  for request validation.

## Decision: Store architecture drafts as repo-scoped run artifacts

**Rationale**: Existing output helpers already bind logs and artifacts to
provider/repository run directories. Draft architecture docs, analysis summaries,
gap reports, and approval metadata should live with the run so reviewers can
trace how the draft was produced.

**Alternatives considered**:
- Write draft files directly into the target repository during generation:
  rejected because this risks overwriting manual edits and implies unreviewed
  repository mutation.
- Store only database records: rejected because architecture drafts and diagrams
  are file-oriented documentation artifacts.

## Decision: Represent confidence at the section/finding level

**Rationale**: The feature requires observed facts to be distinguished from
inferred relationships and inferred content to include confidence levels.
Confidence belongs close to the evidence: an architecture section can summarize
overall confidence, while individual findings can explain observed/inferred
status and evidence paths.

**Alternatives considered**:
- Single confidence score for the full document: rejected because one weak
  inference should not reduce trust in unrelated observed sections.
- No confidence score for observed facts: accepted; observed facts need evidence
  references, while confidence levels are required for inferred relationships.

## Decision: Integrate generated docs into Sphinx navigation after approval

**Rationale**: The existing docs use `docs/index.rst` to define navigation and
project sections. Approved architecture docs should be written into the normal
docs tree, referenced from the existing toctree, and styled by the existing
theme/templates.

**Alternatives considered**:
- Generate standalone markdown outside the docs tree: rejected because it would
  not become part of the existing documentation workflow.
- Always overwrite a fixed architecture page: rejected because regeneration must
  protect approved manual edits.

## Decision: Diagrams are generated only when evidence is sufficient

**Rationale**: Architecture and sequence diagrams are useful only when they can
be traced to observed or clearly labeled inferred relationships. For ambiguous
repositories, the draft should include caveats rather than presenting uncertain
diagrams as fact.

**Alternatives considered**:
- Always generate diagrams: rejected because it would create misleading output
  for incomplete analysis.
- Never generate diagrams in the first version: rejected because diagrams are an
  explicit feature requirement and support onboarding.

## Decision: Extend admin jobs for long-running architecture analysis

**Rationale**: Repository analysis and documentation generation are already
queued in the admin dashboard. Architecture analysis can be long-running and
should expose progress, cancellation, status, and artifacts through the same
run model.

**Alternatives considered**:
- Make architecture generation synchronous only: rejected because large
  repositories can exceed normal request/response expectations.
- Create a separate worker system: rejected because the current admin job queue
  is sufficient for this feature scope.
