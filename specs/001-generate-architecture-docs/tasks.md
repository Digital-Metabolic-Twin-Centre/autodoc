# Tasks: Architecture Documentation Generation

**Input**: Design documents from `specs/001-generate-architecture-docs/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/architecture-docs-api.yaml, quickstart.md

**Tests**: Required by the project constitution for changed analysis, generation, scaffolding, admin, provider, publishing, and artifact-path behavior.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add shared files and contract fixtures needed by all architecture documentation stories.

- [ ] T001 Create architecture service module scaffold in `src/services/architecture_services.py`
- [ ] T002 [P] Create architecture service test module in `tests/test_architecture_services.py`
- [ ] T003 [P] Create architecture contract fixture from `specs/001-generate-architecture-docs/contracts/architecture-docs-api.yaml` in `tests/fixtures/architecture_docs_api.yaml`
- [ ] T004 [P] Create architecture sample repository fixture layout in `tests/fixtures/architecture_repo/README.md`
- [ ] T005 [P] Create Sphinx architecture template fixture in `tests/fixtures/docs_template/project/architecture.rst`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared request/response models, artifact conventions, and service boundaries before user-story work begins.

**Checkpoint**: No user story implementation starts until these tasks are complete.

- [ ] T006 Add `ArchitectureGenerationRequest` and `ArchitectureApprovalRequest` Pydantic models in `src/models/repo_request.py`
- [ ] T007 Add architecture workflow result fields to `WorkflowRunResult` in `src/services/workflow_service.py`
- [ ] T008 Implement draft id and architecture artifact path helpers in `src/services/architecture_services.py`
- [ ] T009 Add architecture artifact path tests in `tests/test_output_paths.py`
- [ ] T010 Add safe architecture output path validation in `src/services/architecture_services.py`
- [ ] T011 Add safe architecture output path validation tests in `tests/test_architecture_services.py`
- [ ] T012 Add architecture endpoint names to admin job dispatch mapping in `src/admin/jobs.py`
- [ ] T013 Add admin job dispatch tests for architecture endpoints in `tests/test_admin_jobs.py`

---

## Phase 3: User Story 1 - Generate Integrated Architecture Draft (Priority: P1) MVP

**Goal**: A maintainer can generate a reviewable architecture draft that fits the existing documentation workflow and does not commit or publish automatically.

**Independent Test**: Submit an architecture generation request for a representative repository and verify the response includes a draft artifact with required sections, proposed docs location, Sphinx navigation context, and no commit or publication.

### Tests for User Story 1

- [ ] T014 [P] [US1] Add contract tests for `POST /generate-architecture-docs` request/response in `tests/test_router.py`
- [ ] T015 [P] [US1] Add architecture draft generation unit tests for required sections in `tests/test_architecture_services.py`
- [ ] T016 [P] [US1] Add Sphinx hierarchy/template integration tests in `tests/test_sphinx_template.py`
- [ ] T017 [P] [US1] Add workflow no-commit generation and provider read/access failure tests in `tests/test_doc_services.py`

### Implementation for User Story 1

- [ ] T018 [US1] Implement repository structure scanning for entry points, packages, modules, and dependency evidence in `src/services/architecture_services.py`
- [ ] T019 [US1] Implement architecture section assembly for overview, entry points, services, routers, modules, dependencies, data flow, jobs, models, configuration, environment variables, authentication, endpoints, diagrams, repository structure, and technology stack in `src/services/architecture_services.py`
- [ ] T020 [US1] Implement Sphinx architecture draft rendering with existing documentation style conventions in `src/services/architecture_services.py`
- [ ] T021 [US1] Add Sphinx documentation placement and navigation proposal helpers in `src/services/sphinx_services.py`
- [ ] T022 [US1] Add `execute_architecture_generation_request` orchestration without repository mutation in `src/services/workflow_service.py`
- [ ] T023 [US1] Add `POST /generate-architecture-docs` endpoint and error handling in `src/router/router.py`
- [ ] T024 [US1] Add admin dashboard architecture generation form and run summary fields in `src/templates/admin/dashboard.html`
- [ ] T025 [US1] Wire admin architecture generation request handling in `src/admin/router.py`

**Checkpoint**: User Story 1 works independently: architecture draft generation returns reviewable artifacts and performs no commit/publish.

---

## Phase 4: User Story 2 - Review Evidence and Confidence (Priority: P2)

**Goal**: A maintainer can distinguish observed facts, inferred relationships, confidence levels, and analysis gaps in the generated draft.

**Independent Test**: Generate a draft from a repository with clear and ambiguous relationships and verify observed/inferred labels, confidence levels, and gap caveats appear in response metadata and draft content.

### Tests for User Story 2

- [ ] T026 [P] [US2] Add confidence classification tests for observed and inferred findings in `tests/test_architecture_services.py`
- [ ] T027 [P] [US2] Add analysis gap rendering tests for missing entry points, ambiguous dependencies, incomplete auth/data flow, and too-large repository partial-result handling in `tests/test_architecture_services.py`
- [ ] T028 [P] [US2] Add response metadata tests for sections and gaps in `tests/test_router.py`

### Implementation for User Story 2

- [ ] T029 [US2] Implement `ArchitectureFinding`, `ArchitectureSection`, and `AnalysisGap` data structures in `src/services/architecture_services.py`
- [ ] T030 [US2] Implement observed versus inferred classification and evidence path recording in `src/services/architecture_services.py`
- [ ] T031 [US2] Implement confidence level assignment using `high`, `medium`, `low`, and `not_applicable` values for inferred findings in `src/services/architecture_services.py`
- [ ] T032 [US2] Implement reviewer-visible gap detection, too-large repository partial-result reporting, and caveat rendering in `src/services/architecture_services.py`
- [ ] T033 [US2] Include sections, confidence levels, and gaps in architecture generation response payloads in `src/services/workflow_service.py`
- [ ] T034 [US2] Render confidence and gap summaries in the admin run detail area in `src/templates/admin/dashboard.html`

**Checkpoint**: User Story 2 works independently on top of US1: generated drafts expose evidence quality and uncertainty clearly.

---

## Phase 5: User Story 3 - Protect Manual Documentation During Regeneration (Priority: P3)

**Goal**: Regeneration preserves existing approved manual architecture documentation unless the maintainer explicitly confirms overwrite or update.

**Independent Test**: Generate a draft, simulate approved manual edits, regenerate, and verify the existing documentation remains unchanged while a reviewable update draft is produced.

### Tests for User Story 3

- [ ] T035 [P] [US3] Add regeneration preservation tests for existing architecture docs in `tests/test_architecture_services.py`
- [ ] T036 [P] [US3] Add Sphinx navigation conflict detection tests in `tests/test_sphinx_template.py`
- [ ] T037 [P] [US3] Add provider write-protection regression tests for generation in `tests/test_git_utils.py`

### Implementation for User Story 3

- [ ] T038 [US3] Implement existing architecture document discovery and manual-content detection in `src/services/architecture_services.py`
- [ ] T039 [US3] Implement regeneration comparison and superseded draft metadata in `src/services/architecture_services.py`
- [ ] T040 [US3] Implement navigation conflict detection for existing Sphinx docs in `src/services/sphinx_services.py`
- [ ] T041 [US3] Add overwrite-required status and conflict metadata to architecture generation responses in `src/services/workflow_service.py`
- [ ] T042 [US3] Display regeneration conflicts and manual-edit warnings in `src/templates/admin/dashboard.html`

**Checkpoint**: User Story 3 works independently on top of US1: regeneration creates reviewable updates without overwriting manual edits.

---

## Phase 6: User Story 4 - Approve Architecture Documentation for Publication (Priority: P4)

**Goal**: A maintainer can explicitly approve a generated architecture draft so the reviewed content becomes eligible for commit or publication.

**Independent Test**: Approve a generated draft and verify only the approved draft is applied to the requested documentation path, with overwrite protection enforced.

### Tests for User Story 4

- [ ] T043 [P] [US4] Add contract tests for `POST /approve-architecture-docs` request/response in `tests/test_router.py`
- [ ] T044 [P] [US4] Add approval gating and overwrite confirmation tests in `tests/test_architecture_services.py`
- [ ] T045 [P] [US4] Add provider approval write tests with mocked GitHub/GitLab helpers in `tests/test_git_utils.py`
- [ ] T046 [P] [US4] Add admin approval workflow tests in `tests/test_admin_router.py`

### Implementation for User Story 4

- [ ] T047 [US4] Implement draft lookup, approval validation, and overwrite confirmation checks in `src/services/architecture_services.py`
- [ ] T048 [US4] Implement approved architecture document application and navigation update through provider helpers in `src/services/sphinx_services.py`
- [ ] T049 [US4] Add `execute_architecture_approval_request` orchestration in `src/services/workflow_service.py`
- [ ] T050 [US4] Add `POST /approve-architecture-docs` endpoint and conflict/error handling in `src/router/router.py`
- [ ] T051 [US4] Add admin dashboard approve/reject controls for architecture drafts in `src/templates/admin/dashboard.html`
- [ ] T052 [US4] Wire admin approval and rejection actions in `src/admin/router.py`

**Checkpoint**: User Story 4 works independently on top of US1: approved drafts can be applied while unapproved drafts remain uncommitted and unpublished.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, documentation, and quality gates across all user stories.

- [ ] T053 [P] Update public README endpoint and workflow documentation in `README.md`
- [ ] T054 [P] Update project documentation overview for architecture docs workflow in `docs/project/overview.rst`
- [ ] T055 [P] Add architecture feature notes to generated API reference narrative in `docs/api_reference.rst`
- [ ] T056 Run quickstart validation commands, perform checklist-based new-developer readability review, and record any deviations in `specs/001-generate-architecture-docs/quickstart.md`
- [ ] T057 Run full regression suite with `uv run pytest` and fix failures in `tests/`
- [ ] T058 Run linting with `uv run ruff check src tests` and fix issues in `src/` and `tests/`
- [ ] T059 Run Sphinx validation with `uv run sphinx-build -E -W -b html docs docs/_build/html` and fix documentation build issues in `docs/`
- [ ] T060 Review generated artifacts and logs for token leakage and document findings in `specs/001-generate-architecture-docs/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup; blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; MVP scope.
- **User Story 2 (Phase 4)**: Depends on US1 draft generation artifacts.
- **User Story 3 (Phase 5)**: Depends on US1 draft generation artifacts.
- **User Story 4 (Phase 6)**: Depends on US1 draft ids and artifacts; benefits from US3 overwrite checks.
- **Polish (Phase 7)**: Depends on selected user stories being complete.

### User Story Dependencies

- **US1 Generate integrated architecture draft**: Required MVP and foundation for all later stories.
- **US2 Review evidence and confidence**: Depends on US1 because it enriches generated drafts.
- **US3 Protect manual documentation during regeneration**: Depends on US1 because it compares regenerated drafts with existing docs.
- **US4 Approve architecture documentation for publication**: Depends on US1 and should follow US3 overwrite protection before release.

### Within Each User Story

- Tests must be written and fail before implementation.
- Request/model changes before service orchestration.
- Service logic before router/admin integration.
- Draft artifact behavior before approval behavior.
- Story checkpoint must pass before moving to the next priority.

## Parallel Opportunities

- T002, T003, T004, and T005 can run in parallel after T001.
- T009, T011, and T013 can run in parallel once their corresponding foundational code tasks are understood.
- US1 tests T014, T015, T016, and T017 can run in parallel.
- US2 tests T026, T027, and T028 can run in parallel.
- US3 tests T035, T036, and T037 can run in parallel.
- US4 tests T043, T044, T045, and T046 can run in parallel.
- Documentation updates T053, T054, and T055 can run in parallel after stories are implemented.

## Parallel Example: User Story 1

```bash
Task: "T014 [P] [US1] Add contract tests for POST /generate-architecture-docs request/response in tests/test_router.py"
Task: "T015 [P] [US1] Add architecture draft generation unit tests for required sections in tests/test_architecture_services.py"
Task: "T016 [P] [US1] Add Sphinx hierarchy/template integration tests in tests/test_sphinx_template.py"
Task: "T017 [P] [US1] Add workflow no-commit generation and provider read/access failure tests in tests/test_doc_services.py"
```

## Parallel Example: User Story 2

```bash
Task: "T026 [P] [US2] Add confidence classification tests for observed and inferred findings in tests/test_architecture_services.py"
Task: "T027 [P] [US2] Add analysis gap rendering tests for missing entry points, ambiguous dependencies, incomplete auth/data flow, and too-large repository partial-result handling in tests/test_architecture_services.py"
Task: "T028 [P] [US2] Add response metadata tests for sections and gaps in tests/test_router.py"
```

## Parallel Example: User Story 3

```bash
Task: "T035 [P] [US3] Add regeneration preservation tests for existing architecture docs in tests/test_architecture_services.py"
Task: "T036 [P] [US3] Add Sphinx navigation conflict detection tests in tests/test_sphinx_template.py"
Task: "T037 [P] [US3] Add provider write-protection regression tests for generation in tests/test_git_utils.py"
```

## Parallel Example: User Story 4

```bash
Task: "T043 [P] [US4] Add contract tests for POST /approve-architecture-docs request/response in tests/test_router.py"
Task: "T044 [P] [US4] Add approval gating and overwrite confirmation tests in tests/test_architecture_services.py"
Task: "T045 [P] [US4] Add provider approval write tests with mocked GitHub/GitLab helpers in tests/test_git_utils.py"
Task: "T046 [P] [US4] Add admin approval workflow tests in tests/test_admin_router.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational prerequisites.
3. Complete Phase 3: User Story 1.
4. Stop and validate that generation creates a reviewable architecture draft with no commit or publication.

### Incremental Delivery

1. US1 delivers reviewable integrated draft generation.
2. US2 adds confidence, evidence, and gap transparency.
3. US3 adds safe regeneration and manual-edit preservation.
4. US4 adds explicit approval to apply reviewed docs.
5. Polish validates docs, tests, linting, Sphinx build, and secret handling.

### Team Parallel Strategy

After Phase 2, one developer can implement US1 service logic while another prepares US1 contract/router tests. After US1 stabilizes, US2 and US3 can proceed mostly in parallel because they enrich different parts of the draft lifecycle. US4 should wait until overwrite protection expectations from US3 are clear.

## Notes

- [P] tasks are parallelizable because they touch different files or independent test surfaces.
- Every user-story task includes a story label for traceability.
- Tests are included because the constitution requires regression protection for this feature.
- Keep generated architecture artifacts reviewable and repo-scoped throughout implementation.
