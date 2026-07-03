from pathlib import Path

import pytest

from models.repo_request import ArchitectureApprovalRequest, ArchitectureGenerationRequest
from services.architecture_services import (
    ARCHITECTURE_OUTPUT_DEFAULT,
    approve_architecture_draft,
    build_architecture_artifact_paths,
    generate_architecture_draft,
    validate_architecture_output_path,
)
from utils.git_utils import RepositoryAccessError


def test_validate_architecture_output_path_accepts_default():
    assert validate_architecture_output_path(None) == ARCHITECTURE_OUTPUT_DEFAULT


def test_validate_architecture_output_path_rejects_escape():
    with pytest.raises(ValueError, match="cannot escape"):
        validate_architecture_output_path("docs/../architecture.rst")


def test_build_architecture_artifact_paths_uses_repo_scoped_log_dir():
    paths = build_architecture_artifact_paths("octo-org/example-repo", "github")

    assert "logs/github/octo-org__example-repo/app_" in paths["artifact_dir"]
    assert paths["draft_path"].endswith(".rst")
    assert paths["summary_path"].endswith(".json")


def test_generate_architecture_draft_builds_required_sections(monkeypatch, tmp_path):
    tree = [
        {"path": "src/main.py", "type": "blob"},
        {"path": "src/router/router.py", "type": "blob"},
        {"path": "src/services/workflow_service.py", "type": "blob"},
        {"path": "src/admin/models.py", "type": "blob"},
        {"path": "src/config/config.py", "type": "blob"},
        {"path": "src/admin/security.py", "type": "blob"},
        {"path": "docs/conf.py", "type": "blob"},
    ]

    monkeypatch.setattr("services.architecture_services.fetch_repo_tree", lambda *args, **kwargs: tree)

    def fake_fetch_content(repo_path, branch, file_path, token):
        if file_path.endswith("router.py"):
            return (
                "from fastapi import APIRouter\n"
                "import os\n"
                "router = APIRouter()\n"
                "@router.get('/health')\n"
                "def health():\n"
                "    return os.getenv('ARCH_TOKEN')\n"
            )
        if file_path.endswith("config.py"):
            return "import os\nvalue = os.getenv('ARCH_TOKEN')\n"
        if file_path.endswith("models.py"):
            return "from sqlalchemy import Column\n"
        if file_path.endswith("main.py"):
            return "from fastapi import FastAPI\n"
        if file_path.endswith("security.py"):
            return "from fastapi import Depends\n"
        return "project = 'Example'\n"

    monkeypatch.setattr("services.architecture_services.fetch_content_from_github", fake_fetch_content)
    monkeypatch.setattr("services.architecture_services.fetch_content_from_gitlab", lambda *args, **kwargs: None)
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path / "logs"))

    result = generate_architecture_draft(
        ArchitectureGenerationRequest(
            provider="github",
            repo_url="octo-org/example-repo",
            token="secret",
            branch="main",
        )
    )

    section_names = [section.section_name for section in result.sections]
    assert "Project overview" in section_names
    assert "Application entry points" in section_names
    assert "Services" in section_names
    assert "Routers" in section_names
    assert "API endpoints" in section_names
    assert Path(result.draft_path).exists()
    assert Path(result.analysis_summary_path).exists()
    assert result.approval_required is True
    assert "high" in result.confidence_summary


def test_generate_architecture_draft_reports_partial_analysis(monkeypatch, tmp_path):
    tree = [
        {"path": "src/router/router.py", "type": "blob"},
        {"path": "src/services/workflow_service.py", "type": "blob"},
    ]

    monkeypatch.setattr("services.architecture_services.ARCHITECTURE_PARTIAL_REPO_THRESHOLD", 1)
    monkeypatch.setattr("services.architecture_services.fetch_repo_tree", lambda *args, **kwargs: tree)
    monkeypatch.setattr(
        "services.architecture_services.fetch_content_from_github",
        lambda *args,
        **kwargs: "from fastapi import APIRouter\nrouter = APIRouter()\n@router.get('/x')\ndef x():\n    return 1\n",
    )
    monkeypatch.setattr("services.architecture_services.fetch_content_from_gitlab", lambda *args, **kwargs: None)
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path / "logs"))

    result = generate_architecture_draft(
        ArchitectureGenerationRequest(
            provider="github",
            repo_url="octo-org/example-repo",
            token="secret",
            branch="main",
        )
    )

    assert result.status == "partial"
    assert any(gap.gap_type == "missing" and gap.section_name == "Application entry points" for gap in result.gaps)
    assert any(gap.gap_type == "too_large" for gap in result.gaps)


def test_approve_architecture_draft_requires_overwrite_confirmation(monkeypatch, tmp_path):
    repo_dir = tmp_path / "repo"
    docs_dir = repo_dir / "docs" / "project"
    docs_dir.mkdir(parents=True)
    (repo_dir / "docs" / "index.rst").write_text("Project\n=======\n", encoding="utf-8")
    (docs_dir / "architecture.rst").write_text("Manual architecture notes\n", encoding="utf-8")
    draft_dir = tmp_path / "logs" / "github" / "repo__architecture"
    draft_dir.mkdir(parents=True)
    draft_path = draft_dir / "repo__architecture__20260703-120000.rst"
    draft_path.write_text("Architecture Documentation Draft\n", encoding="utf-8")

    monkeypatch.setattr(
        "services.architecture_services.load_architecture_summary",
        lambda *args, **kwargs: {"approval_required": True, "draft_path": str(draft_path)},
    )

    with pytest.raises(ValueError, match="overwrite confirmation"):
        approve_architecture_draft(
            ArchitectureApprovalRequest(
                provider="github",
                repo_url=str(repo_dir),
                token="secret",
                branch="main",
                draft_id="repo__architecture__20260703-120000",
                output_path="docs/project/architecture.rst",
                overwrite_existing=False,
            )
        )


def test_generate_architecture_draft_preserves_existing_manual_docs(monkeypatch, tmp_path):
    repo_dir = tmp_path / "repo"
    docs_dir = repo_dir / "docs" / "project"
    docs_dir.mkdir(parents=True)
    architecture_doc = docs_dir / "architecture.rst"
    architecture_doc.write_text("Manual architecture notes\n", encoding="utf-8")

    tree = [
        {"path": "src/main.py", "type": "blob"},
        {"path": "src/router/router.py", "type": "blob"},
    ]

    monkeypatch.setattr("services.architecture_services.fetch_repo_tree", lambda *args, **kwargs: tree)
    monkeypatch.setattr(
        "services.architecture_services.fetch_content_from_github",
        lambda *args, **kwargs: "from fastapi import APIRouter\nrouter = APIRouter()\n",
    )
    monkeypatch.setattr("services.architecture_services.fetch_content_from_gitlab", lambda *args, **kwargs: None)
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path / "logs"))

    result = generate_architecture_draft(
        ArchitectureGenerationRequest(
            provider="github",
            repo_url=str(repo_dir),
            token="secret",
            branch="main",
        )
    )

    assert result.manual_docs_detected is True
    assert result.overwrite_required is True
    assert architecture_doc.read_text(encoding="utf-8") == "Manual architecture notes\n"


def test_generate_architecture_draft_propagates_repository_access_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.architecture_services.fetch_repo_tree",
        lambda *args, **kwargs: (_ for _ in ()).throw(RepositoryAccessError("denied", 403)),
    )
    monkeypatch.setattr("services.architecture_services.fetch_content_from_github", lambda *args, **kwargs: None)
    monkeypatch.setattr("services.architecture_services.fetch_content_from_gitlab", lambda *args, **kwargs: None)
    monkeypatch.setattr("utils.output_paths.LOG_DIR", str(tmp_path / "logs"))

    with pytest.raises(RepositoryAccessError):
        generate_architecture_draft(
            ArchitectureGenerationRequest(
                provider="github",
                repo_url="octo-org/example-repo",
                token="secret",
                branch="main",
            )
        )
