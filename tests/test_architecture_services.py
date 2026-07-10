from contextlib import contextmanager
from pathlib import Path

import pytest

from services.architecture_services import (
    MANUAL_EDIT_MARKER,
    ArchitectureApprovalError,
    ArchitectureOverwriteRequiredError,
    ArchitectureSection,
    _build_sections,
    _confidence_from_count,
    _paths_section,
    apply_architecture_approval,
    architecture_draft_paths,
    find_architecture_draft,
    generate_architecture_draft,
    generate_draft_id,
    is_autodoc_generated_content,
    render_architecture_draft_rst,
)
from utils.git_utils import RepositoryAccessError

FIXTURE_REPO_DIR = str(Path(__file__).parent / "fixtures" / "architecture_repo")


@contextmanager
def _fake_clone(repo_url, token, branch, provider):
    yield FIXTURE_REPO_DIR


def _patch_no_existing_docs(monkeypatch):
    monkeypatch.setattr("services.architecture_services.clone_repository", _fake_clone)
    monkeypatch.setattr("services.architecture_services.fetch_content_from_github", lambda *a, **k: None)
    monkeypatch.setattr("services.architecture_services.fetch_content_from_gitlab", lambda *a, **k: None)
    monkeypatch.setattr("services.sphinx_services.fetch_content_from_github", lambda *a, **k: None)
    monkeypatch.setattr("services.sphinx_services.fetch_content_from_gitlab", lambda *a, **k: None)


def test_generate_draft_id_is_unique_and_sortable():
    first = generate_draft_id()
    second = generate_draft_id()

    assert first != second
    assert first.startswith("arch_")
    assert second.startswith("arch_")


def test_architecture_draft_paths_are_repo_scoped():
    rst_path, json_path = architecture_draft_paths("octo-org/example-repo", "github", "arch_123")

    assert rst_path.endswith("architecture_draft_arch_123.rst")
    assert json_path.endswith("architecture_draft_arch_123.json")
    assert "logs/github/octo-org__example-repo" in rst_path


def test_is_autodoc_generated_content_detects_marker():
    assert is_autodoc_generated_content(f"{MANUAL_EDIT_MARKER} (approved now)\n\ncontent") is True
    assert is_autodoc_generated_content("Manually written architecture notes.") is False
    assert is_autodoc_generated_content("") is False


def test_confidence_from_count_thresholds():
    assert _confidence_from_count(0) == "low"
    assert _confidence_from_count(1) == "low"
    assert _confidence_from_count(2) == "medium"
    assert _confidence_from_count(4) == "medium"
    assert _confidence_from_count(5) == "high"


def test_paths_section_returns_gap_when_empty():
    section, gap = _paths_section("services", [], "service", "Add a services directory.")

    assert section.status == "unavailable"
    assert section.confidence_level == "not_applicable"
    assert gap is not None
    assert gap.gap_type == "missing"
    assert gap.section_name == "services"


def test_paths_section_returns_observed_findings_when_populated():
    section, gap = _paths_section("services", ["src/services/a.py", "src/services/a.py"], "service", "n/a")

    assert gap is None
    assert section.status == "populated"
    assert len(section.findings) == 1
    assert section.findings[0].classification == "observed"
    assert section.observed_count == 1
    assert section.inferred_count == 0


def test_build_sections_marks_too_large_repository_as_partial():
    evidence = {
        "total_files": 5000,
        "scanned_files": 3000,
        "truncated": True,
        "entry_points": ["main.py"],
        "dependency_files": [],
        "config_files": [],
        "packages": [],
        "services": [],
        "routers": [],
        "endpoints": [],
        "models": [],
        "jobs": [],
        "auth_files": [],
        "env_vars": {},
        "internal_imports": set(),
        "language_counts": {},
        "top_level_entries": ["main.py"],
        "_external_deps": [],
    }

    sections, gaps, diagram_content = _build_sections(evidence, include_diagrams=True)

    overview = next(section for section in sections if section.section_name == "project overview")
    assert overview.status == "partial"
    assert any(gap.gap_type == "too_large" for gap in gaps)
    assert diagram_content == {}


def test_build_sections_includes_all_required_section_names():
    evidence = {
        "total_files": 0,
        "scanned_files": 0,
        "truncated": False,
        "entry_points": [],
        "dependency_files": [],
        "config_files": [],
        "packages": [],
        "services": [],
        "routers": [],
        "endpoints": [],
        "models": [],
        "jobs": [],
        "auth_files": [],
        "env_vars": {},
        "internal_imports": set(),
        "language_counts": {},
        "top_level_entries": [],
        "_external_deps": [],
    }

    sections, _gaps, _diagrams = _build_sections(evidence, include_diagrams=True)
    section_names = {section.section_name for section in sections}

    for expected in [
        "project overview",
        "entry points",
        "services",
        "routers",
        "modules and packages",
        "internal dependencies",
        "external dependencies",
        "data flow",
        "background jobs",
        "database models",
        "configuration",
        "environment variables",
        "authentication flow",
        "API endpoints",
        "sequence diagrams",
        "architecture diagrams",
        "repository structure",
        "technology stack",
    ]:
        assert expected in section_names


def test_render_architecture_draft_rst_labels_observed_and_inferred_findings():
    sections = [
        ArchitectureSection(
            section_name="entry points",
            status="populated",
            summary="Found 1 entry point.",
            findings=[],
            confidence_level="not_applicable",
        ),
    ]
    section, _ = _paths_section("services", ["main.py"], "service", "n/a")
    sections.append(section)

    rst = render_architecture_draft_rst("Example", sections, {})

    assert "Example Architecture (Draft)" in rst
    assert "Observed" in rst
    assert "This page is an automatically generated draft" in rst


def test_generate_architecture_draft_produces_reviewable_draft(monkeypatch):
    _patch_no_existing_docs(monkeypatch)

    result = generate_architecture_draft(
        provider="github",
        repo_url="octo-org/widgets",
        token="secret",
        branch="main",
        target_folders=[],
        output_path="docs/project/architecture.rst",
        include_diagrams=True,
        reuse_existing_docs=True,
    )

    assert result["status"] in {"success", "partial"}
    assert result["draft_id"].startswith("arch_")
    assert Path(result["draft_path"]).exists()
    assert result["proposed_output_path"] == "docs/project/architecture.rst"

    section_names = {section["section_name"] for section in result["sections_summary"]}
    assert "entry points" in section_names
    assert "API endpoints" in section_names

    entry_section = next(s for s in result["sections_summary"] if s["section_name"] == "entry points")
    assert entry_section["status"] == "populated"
    assert entry_section["observed_count"] >= 1

    data_flow_section = next(s for s in result["sections_summary"] if s["section_name"] == "data flow")
    assert data_flow_section["status"] == "populated"
    assert data_flow_section["confidence_level"] in {"high", "medium", "low"}

    assert result["diagram_paths"], "diagrams should be generated when layered evidence exists"


def test_generate_architecture_draft_never_writes_to_target_repo(monkeypatch):
    _patch_no_existing_docs(monkeypatch)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("generation must not write to the target repository")

    monkeypatch.setattr("services.architecture_services.apply_approved_architecture_document", _fail_if_called)

    result = generate_architecture_draft(
        provider="github",
        repo_url="octo-org/widgets",
        token="secret",
        branch="main",
        target_folders=[],
        output_path="docs/project/architecture.rst",
        include_diagrams=True,
        reuse_existing_docs=True,
    )

    assert result["draft_id"]


def test_generate_architecture_draft_raises_on_repository_access_error(monkeypatch):
    @contextmanager
    def _fake_clone_failure(repo_url, token, branch, provider):
        raise RepositoryAccessError("Repository not found.", status_code=404)
        yield  # pragma: no cover

    monkeypatch.setattr("services.architecture_services.clone_repository", _fake_clone_failure)

    with pytest.raises(Exception) as exc_info:
        generate_architecture_draft(
            provider="github",
            repo_url="octo-org/missing",
            token="secret",
            branch="main",
            target_folders=[],
            output_path="docs/project/architecture.rst",
            include_diagrams=True,
            reuse_existing_docs=True,
        )
    assert exc_info.value.status_code == 404


def test_generate_architecture_draft_rejects_output_path_outside_docs_tree(monkeypatch):
    _patch_no_existing_docs(monkeypatch)

    with pytest.raises(ValueError):
        generate_architecture_draft(
            provider="github",
            repo_url="octo-org/widgets",
            token="secret",
            branch="main",
            target_folders=[],
            output_path="../outside.rst",
            include_diagrams=True,
            reuse_existing_docs=True,
        )


def test_find_and_approve_architecture_draft_round_trip(monkeypatch):
    _patch_no_existing_docs(monkeypatch)
    written = {}

    def fake_apply_approved_architecture_document(repo_path, branch, token, provider, output_path, content):
        written["content"] = content
        return True

    monkeypatch.setattr(
        "services.architecture_services.apply_approved_architecture_document",
        fake_apply_approved_architecture_document,
    )
    monkeypatch.setattr(
        "services.architecture_services.update_sphinx_navigation_for_architecture", lambda *a, **k: True
    )

    generated = generate_architecture_draft(
        provider="github",
        repo_url="octo-org/widgets",
        token="secret",
        branch="main",
        target_folders=[],
        output_path="docs/project/architecture.rst",
        include_diagrams=True,
        reuse_existing_docs=True,
    )

    draft = find_architecture_draft("octo-org/widgets", "github", generated["draft_id"])
    assert draft is not None
    assert draft["status"] == "draft"

    approval = apply_architecture_approval(
        provider="github",
        repo_url="octo-org/widgets",
        token="secret",
        branch="main",
        draft_id=generated["draft_id"],
        output_path="docs/project/architecture.rst",
        overwrite_existing=False,
    )

    assert approval["status"] == "approved"
    assert "Architecture (Draft)" not in written["content"]
    assert "This page is an automatically generated draft" not in written["content"]
    assert "Architecture\n============\n" in written["content"]

    reapproved_draft = find_architecture_draft("octo-org/widgets", "github", generated["draft_id"])
    assert reapproved_draft["status"] == "approved"

    with pytest.raises(ArchitectureApprovalError):
        apply_architecture_approval(
            provider="github",
            repo_url="octo-org/widgets",
            token="secret",
            branch="main",
            draft_id=generated["draft_id"],
            output_path="docs/project/architecture.rst",
            overwrite_existing=False,
        )


def test_apply_architecture_approval_requires_overwrite_for_manual_content(monkeypatch):
    _patch_no_existing_docs(monkeypatch)

    generated = generate_architecture_draft(
        provider="github",
        repo_url="octo-org/widgets",
        token="secret",
        branch="main",
        target_folders=[],
        output_path="docs/project/architecture.rst",
        include_diagrams=True,
        reuse_existing_docs=True,
    )

    monkeypatch.setattr(
        "services.architecture_services.fetch_content_from_github",
        lambda *a, **k: "Hand-written architecture notes.",
    )

    with pytest.raises(ArchitectureOverwriteRequiredError):
        apply_architecture_approval(
            provider="github",
            repo_url="octo-org/widgets",
            token="secret",
            branch="main",
            draft_id=generated["draft_id"],
            output_path="docs/project/architecture.rst",
            overwrite_existing=False,
        )


def test_apply_architecture_approval_missing_draft_raises():
    with pytest.raises(ArchitectureApprovalError):
        apply_architecture_approval(
            provider="github",
            repo_url="octo-org/widgets",
            token="secret",
            branch="main",
            draft_id="arch_does_not_exist",
            output_path="docs/project/architecture.rst",
            overwrite_existing=False,
        )
