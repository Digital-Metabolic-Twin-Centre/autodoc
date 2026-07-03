from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.log_config import get_logger
from models.repo_request import ArchitectureApprovalRequest, ArchitectureGenerationRequest
from services.sphinx_services import (
    apply_architecture_navigation_update,
    build_architecture_navigation_update,
)
from utils.git_utils import (
    RepositoryAccessError,
    create_a_file,
    extract_repo_path,
    fetch_content_from_github,
    fetch_content_from_gitlab,
    fetch_repo_tree,
    read_file_content_from_local,
)
from utils.output_paths import bind_repo_run_log_dir, build_repo_output_dir, find_latest_repo_run_dir

logger = get_logger(__name__)

ARCHITECTURE_OUTPUT_DEFAULT = "docs/project/architecture.rst"
ARCHITECTURE_CONFIDENCE_LEVELS = {"high", "medium", "low", "not_applicable"}
ARCHITECTURE_PARTIAL_REPO_THRESHOLD = 400
ARCHITECTURE_MAX_FILES = 80
ARCHITECTURE_REQUIRED_SECTIONS = [
    "Project overview",
    "Application entry points",
    "Services",
    "Routers",
    "Modules and packages",
    "Internal dependencies",
    "External dependencies",
    "Data flow",
    "Background jobs",
    "Database models",
    "Configuration",
    "Environment variables",
    "Authentication flow",
    "API endpoints",
    "Sequence diagrams",
    "Architecture diagrams",
    "Repository structure",
    "Technology stack",
]
PYTHON_ENTRYPOINT_NAMES = {
    "__main__.py",
    "app.py",
    "main.py",
    "manage.py",
    "run.py",
    "server.py",
    "wsgi.py",
    "asgi.py",
}
STD_LIBS = set(sys.stdlib_module_names)


@dataclass
class ArchitectureFinding:
    finding_type: str
    name: str
    classification: str
    confidence_level: str = "not_applicable"
    evidence_paths: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class ArchitectureSection:
    section_name: str
    status: str
    summary: str
    confidence_level: str = "not_applicable"
    evidence_count: int = 0
    findings: list[ArchitectureFinding] = field(default_factory=list)
    gaps: list["AnalysisGap"] = field(default_factory=list)


@dataclass
class AnalysisGap:
    section_name: str
    gap_type: str
    description: str
    recommended_review_action: str


@dataclass
class ArchitectureAnalysisResult:
    status: str
    draft_id: str
    draft_path: str
    proposed_output_path: str
    artifact_dir: str
    analysis_summary_path: str
    log_path: str | None
    sections: list[ArchitectureSection]
    gaps: list[AnalysisGap]
    diagram_paths: list[str]
    navigation_update: str
    confidence_summary: dict[str, int]
    approval_required: bool = True
    overwrite_required: bool = False
    manual_docs_detected: bool = False

    def to_response(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "draft_id": self.draft_id,
            "draft_path": self.draft_path,
            "proposed_output_path": self.proposed_output_path,
            "artifact_dir": self.artifact_dir,
            "analysis_summary_path": self.analysis_summary_path,
            "log_path": self.log_path,
            "sections": [
                {
                    "section_name": section.section_name,
                    "status": section.status,
                    "summary": section.summary,
                    "confidence_level": section.confidence_level,
                    "evidence_count": section.evidence_count,
                    "findings": [asdict(finding) for finding in section.findings],
                    "gaps": [asdict(gap) for gap in section.gaps],
                }
                for section in self.sections
            ],
            "gaps": [asdict(gap) for gap in self.gaps],
            "diagram_paths": self.diagram_paths,
            "navigation_update": self.navigation_update,
            "confidence_summary": self.confidence_summary,
            "approval_required": self.approval_required,
            "overwrite_required": self.overwrite_required,
            "manual_docs_detected": self.manual_docs_detected,
        }


@dataclass
class ArchitectureApprovalResult:
    status: str
    draft_id: str
    output_path: str
    branch: str
    commit_url: str | None = None
    artifact_dir: str | None = None
    navigation_update: str | None = None

    def to_response(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "draft_id": self.draft_id,
            "output_path": self.output_path,
            "branch": self.branch,
            "commit_url": self.commit_url,
            "artifact_dir": self.artifact_dir,
            "navigation_update": self.navigation_update,
        }


def _normalize_target_folders(target_folders: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for folder in target_folders or []:
        candidate = str(folder or "").strip().strip("/")
        if candidate:
            normalized.append(candidate)
    return normalized


def _matches_target_folders(file_path: str, target_folders: list[str]) -> bool:
    if not target_folders:
        return True
    normalized = file_path.strip("/")
    return any(normalized == folder or normalized.startswith(f"{folder}/") for folder in target_folders)


def _timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def build_architecture_draft_id(repo_path: str, provider: str) -> str:
    repo_key = extract_repo_path(repo_path, provider).replace("/", "__").replace(" ", "_")
    repo_key = re.sub(r"[^A-Za-z0-9._-]+", "__", repo_key).strip("_") or "repository"
    return f"{repo_key}__architecture__{_timestamp_slug()}"


def build_architecture_artifact_paths(
    repo_path: str,
    provider: str,
    draft_id: str | None = None,
    artifact_dir: str | None = None,
) -> dict[str, str]:
    repo_root = extract_repo_path(repo_path, provider)
    artifact_dir = artifact_dir or build_repo_output_dir(repo_root, provider)
    draft_name = draft_id or build_architecture_draft_id(repo_root, provider)
    return {
        "artifact_dir": artifact_dir,
        "draft_path": os.path.join(artifact_dir, f"{draft_name}.rst"),
        "summary_path": os.path.join(artifact_dir, f"{draft_name}.json"),
        "diagram_dir": os.path.join(artifact_dir, f"{draft_name}_diagrams"),
    }


def validate_architecture_output_path(output_path: str | None) -> str:
    candidate = str(output_path or ARCHITECTURE_OUTPUT_DEFAULT).replace("\\", "/").strip()
    if not candidate:
        raise ValueError("Architecture output path is required.")
    path_obj = Path(candidate)
    if path_obj.is_absolute():
        raise ValueError("Architecture output path must be relative to the repository docs tree.")
    if ".." in path_obj.parts:
        raise ValueError("Architecture output path cannot escape the docs tree.")
    normalized = path_obj.as_posix()
    if not normalized.startswith("docs/"):
        raise ValueError("Architecture output path must live under docs/.")
    return normalized


def _read_repo_content(
    provider: str,
    repo_path: str,
    branch: str,
    file_path: str,
    token: str,
) -> str | None:
    if os.path.isdir(repo_path):
        return read_file_content_from_local(repo_path, file_path)
    if provider == "github":
        return fetch_content_from_github(repo_path, branch, file_path, token)
    if provider == "gitlab":
        return fetch_content_from_gitlab(repo_path, branch, file_path, token)
    return None


def _import_root(module_name: str) -> str:
    return module_name.split(".", 1)[0].strip()


def _confidence_for_inference(evidence_count: int, files_scanned: int) -> str:
    if evidence_count >= 4:
        return "high"
    if evidence_count >= 2:
        return "medium"
    if evidence_count >= 1:
        return "low"
    if files_scanned == 0:
        return "not_applicable"
    return "low"


def _parse_python_imports(content: str) -> tuple[list[str], list[str]]:
    internal: list[str] = []
    external: list[str] = []
    try:
        parsed = ast.parse(content)
    except SyntaxError:
        return internal, external
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _import_root(alias.name)
                external.append(root)
        elif isinstance(node, ast.ImportFrom):
            if not node.module:
                continue
            root = _import_root(node.module)
            if node.level > 0:
                internal.append(root)
            else:
                external.append(root)
    return internal, external


def _detect_env_vars(content: str) -> list[str]:
    env_vars = set()
    for match in re.findall(r'os\.(?:getenv|environ\.get)\(\s*[\'"]([^\'"]+)[\'"]', content):
        env_vars.add(match)
    for match in re.findall(r'os\.environ\[\s*[\'"]([^\'"]+)[\'"]\s*\]', content):
        env_vars.add(match)
    return sorted(env_vars)


def _format_paths(paths: list[str], limit: int = 6) -> str:
    if not paths:
        return "None observed."
    visible = paths[:limit]
    suffix = "" if len(paths) <= limit else f" and {len(paths) - limit} more"
    return ", ".join(visible) + suffix


def _finding_summary(findings: list[ArchitectureFinding]) -> str:
    if not findings:
        return "No evidence was confidently identified."
    observed = [finding.name for finding in findings if finding.classification == "observed"]
    inferred = [finding.name for finding in findings if finding.classification == "inferred"]
    parts = []
    if observed:
        parts.append(f"Observed: {_format_paths(observed)}.")
    if inferred:
        parts.append(f"Inferred: {_format_paths(inferred)}.")
    return " ".join(parts)


def _section(
    section_name: str,
    findings: list[ArchitectureFinding],
    gaps: list[AnalysisGap] | None = None,
    files_scanned: int = 0,
) -> ArchitectureSection:
    evidence_count = sum(len(finding.evidence_paths) for finding in findings)
    confidence = "not_applicable"
    if findings:
        ranks = {"low": 1, "medium": 2, "high": 3, "not_applicable": 0}
        inferred_confidences = [
            finding.confidence_level
            for finding in findings
            if finding.classification == "inferred"
        ]
        if inferred_confidences:
            confidence = max(inferred_confidences, key=lambda value: ranks.get(value, 0))
        elif any(finding.classification == "observed" for finding in findings):
            confidence = "high"
        else:
            confidence = _confidence_for_inference(evidence_count, files_scanned)
    status = "populated" if findings else "unavailable"
    if gaps:
        status = "partial" if findings else "unavailable"
    return ArchitectureSection(
        section_name=section_name,
        status=status,
        summary=_finding_summary(findings),
        confidence_level=confidence,
        evidence_count=evidence_count,
        findings=findings,
        gaps=gaps or [],
    )


def _collect_repo_snapshot(
    provider: str,
    repo_url: str,
    token: str,
    branch: str,
    target_folders: list[str],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    repo_path = extract_repo_path(repo_url, provider)
    tree = fetch_repo_tree(repo_path, token, branch=branch, provider=provider)
    filtered_tree: list[dict[str, Any]] = []
    analyzed_files: list[str] = []
    skipped_files: list[str] = []
    for item in tree:
        file_path = str(item.get("path", "")).replace("\\", "/")
        if not file_path or item.get("type") != "blob":
            continue
        if not _matches_target_folders(file_path, target_folders):
            skipped_files.append(file_path)
            continue
        filtered_tree.append(item)
        analyzed_files.append(file_path)
    return filtered_tree, analyzed_files, skipped_files


def _candidate_files(analyzed_files: list[str]) -> list[str]:
    candidates = []
    for file_path in analyzed_files:
        if (
            file_path.endswith(".py")
            or file_path.endswith(".pyw")
            or file_path.endswith(
                (
                    "pyproject.toml",
                    "requirements.txt",
                    "Pipfile",
                    "package.json",
                    "Dockerfile",
                    "README.md",
                    "README.rst",
                )
            )
        ):
            candidates.append(file_path)
    return candidates[:ARCHITECTURE_MAX_FILES]


def _file_path_category(file_path: str) -> str:
    normalized = file_path.lower()
    name = os.path.basename(normalized)
    if name in PYTHON_ENTRYPOINT_NAMES or "/main.py" in normalized or normalized.endswith("/app.py"):
        return "entry_point"
    if "router" in normalized or "route" in normalized:
        return "router"
    if "service" in normalized:
        return "service"
    if "model" in normalized:
        return "model"
    if any(token in normalized for token in ("auth", "security", "login", "session")):
        return "auth"
    if any(token in normalized for token in ("job", "worker", "task", "queue")):
        return "job"
    if any(token in normalized for token in ("config", "settings")) or normalized.endswith(".env"):
        return "config"
    return "module"


def _load_findings(
    provider: str,
    repo_url: str,
    token: str,
    branch: str,
    candidate_files: list[str],
) -> tuple[
    list[ArchitectureFinding],
    list[ArchitectureFinding],
    list[ArchitectureFinding],
    list[ArchitectureFinding],
    list[ArchitectureFinding],
    list[ArchitectureFinding],
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
]:
    repo_path = extract_repo_path(repo_url, provider)
    entry_points: list[ArchitectureFinding] = []
    services: list[ArchitectureFinding] = []
    routers: list[ArchitectureFinding] = []
    modules: list[ArchitectureFinding] = []
    dependencies: list[ArchitectureFinding] = []
    external_dependencies: list[ArchitectureFinding] = []
    background_jobs: list[str] = []
    database_models: list[str] = []
    configs: list[str] = []
    env_vars: list[str] = []
    auth_files: list[str] = []
    endpoints: list[str] = []

    internal_roots = {Path(file_path).parts[0] for file_path in candidate_files if Path(file_path).parts}
    internal_roots.discard("")

    for file_path in candidate_files:
        category = _file_path_category(file_path)
        content = _read_repo_content(provider, repo_path, branch, file_path, token) or ""
        import_roots_internal, import_roots_external = (
            _parse_python_imports(content) if file_path.endswith(".py") else ([], [])
        )
        env_vars.extend(_detect_env_vars(content))

        if category == "entry_point":
            entry_points.append(
                ArchitectureFinding(
                    finding_type="entry_point",
                    name=file_path,
                    classification="observed",
                    evidence_paths=[file_path],
                    description="Entry point file detected from repository layout.",
                )
            )
        elif category == "service":
            services.append(
                ArchitectureFinding(
                    finding_type="service",
                    name=file_path,
                    classification="observed",
                    evidence_paths=[file_path],
                    description="Service module detected from the repository path.",
                )
            )
        elif category == "router":
            routers.append(
                ArchitectureFinding(
                    finding_type="router",
                    name=file_path,
                    classification="observed",
                    evidence_paths=[file_path],
                    description="Router module detected from the repository path.",
                )
            )
            endpoints.extend(_extract_route_endpoints(content, file_path))
        elif category == "model":
            database_models.append(file_path)
        elif category == "config":
            configs.append(file_path)
        elif category == "job":
            background_jobs.append(file_path)
        elif category == "auth":
            auth_files.append(file_path)

        modules.append(
            ArchitectureFinding(
                finding_type="module",
                name=file_path,
                classification="observed",
                evidence_paths=[file_path],
                description="Repository module or package file observed during analysis.",
            )
        )

        for root in import_roots_internal:
            if root in internal_roots:
                dependencies.append(
                    ArchitectureFinding(
                        finding_type="dependency",
                        name=root,
                        classification="inferred",
                        confidence_level="medium",
                        evidence_paths=[file_path],
                        description="Internal dependency inferred from a relative or in-repo import.",
                    )
                )
        for root in import_roots_external:
            if root in STD_LIBS or root in internal_roots:
                continue
            external_dependencies.append(
                ArchitectureFinding(
                    finding_type="dependency",
                    name=root,
                    classification="inferred",
                    confidence_level="medium",
                    evidence_paths=[file_path],
                    description="External dependency inferred from an import statement.",
                )
            )

    observed_env_vars = sorted(set(env_vars))
    return (
        entry_points,
        services,
        routers,
        modules,
        dependencies,
        external_dependencies,
        background_jobs,
        database_models,
        configs,
        observed_env_vars,
        auth_files,
        endpoints,
    )


def _extract_route_endpoints(content: str, file_path: str) -> list[str]:
    if not content:
        return []
    endpoints: list[str] = []
    for method, path in re.findall(r'@(?:router|app)\.(get|post|put|patch|delete)\(\s*[\'"]([^\'"]+)[\'"]', content):
        endpoints.append(f"{method.upper()} {path}")
    if not endpoints and ("FastAPI(" in content or "APIRouter(" in content):
        endpoints.append(file_path)
    return endpoints


def _diagram_text(project_name: str, sections: list[ArchitectureSection]) -> tuple[str, str]:
    generation = (
        "Generation Flow\n"
        "================\n\n"
        ".. code-block:: text\n\n"
        f"   maintainer -> API router -> workflow service -> architecture analysis -> draft artifact -> review\n"
        f"   {project_name} docs tree -> Sphinx navigation update -> approval -> publish\n"
    )
    architecture = (
        "Architecture Diagram\n"
        "====================\n\n"
        ".. code-block:: text\n\n"
        "   [API Router] -> [Workflow Service] -> [Architecture Service] -> [Draft Artifact]\n"
        "        |                |                         |                   |\n"
        "        v                v                         v                   v\n"
        "   [Admin UI]       [Sphinx Helpers]       [Evidence Summary]   [Docs Navigation]\n"
    )
    return generation, architecture


def _build_rst_draft(
    project_name: str,
    repo_path: str,
    branch: str,
    draft_id: str,
    output_path: str,
    sections: list[ArchitectureSection],
    gaps: list[AnalysisGap],
    navigation_update: str,
    diagram_paths: list[str],
    confidence_summary: dict[str, int],
    overwrite_required: bool,
    manual_docs_detected: bool,
) -> str:
    lines = [
        "Architecture Documentation Draft",
        "================================",
        "",
        f"Project: {project_name}",
        f"Repository: {repo_path}",
        f"Branch: {branch}",
        f"Draft ID: {draft_id}",
        f"Proposed output path: {output_path}",
        "",
        "Review notes",
        "------------",
        "",
        "- This is a reviewable draft. It does not commit or publish changes.",
        "- Observed facts are separated from inferred relationships in each section.",
        "- Inferred findings include confidence labels.",
        "- Confidence scale: high, medium, low, not_applicable.",
    ]
    if overwrite_required:
        lines.append("- Existing architecture documentation was detected and overwrite approval is required.")
    if manual_docs_detected:
        lines.append("- Manual architecture documentation appears to exist in the target tree.")
    lines.extend(["", "Section summary", "---------------", ""])
    for section in sections:
        lines.extend(
            [
                f"{section.section_name}",
                "~" * len(section.section_name),
                "",
                f"Status: {section.status}",
                f"Confidence: {section.confidence_level}",
                f"Evidence count: {section.evidence_count}",
                "",
                section.summary,
                "",
            ]
        )
        observed_findings = [finding for finding in section.findings if finding.classification == "observed"]
        inferred_findings = [finding for finding in section.findings if finding.classification == "inferred"]
        if observed_findings:
            lines.append("Observed findings")
            lines.append("")
            for finding in observed_findings:
                lines.append(f"- {finding.name}: {finding.description} [{_format_paths(finding.evidence_paths)}]")
            lines.append("")
        if inferred_findings:
            lines.append("Inferred findings")
            lines.append("")
            for finding in inferred_findings:
                lines.append(
                    f"- {finding.name}: {finding.description} "
                    f"(confidence: {finding.confidence_level}, evidence: {_format_paths(finding.evidence_paths)})"
                )
            lines.append("")
        if section.gaps:
            lines.append("Section gaps")
            lines.append("")
            for gap in section.gaps:
                lines.append(f"- {gap.description} ({gap.recommended_review_action})")
            lines.append("")
    if gaps:
        lines.extend(["Analysis gaps", "-------------", ""])
        for gap in gaps:
            lines.append(f"- [{gap.section_name}] {gap.description} -> {gap.recommended_review_action}")
        lines.append("")
    lines.extend(
        [
            "Confidence summary",
            "------------------",
            "",
            f"- High: {confidence_summary.get('high', 0)}",
            f"- Medium: {confidence_summary.get('medium', 0)}",
            f"- Low: {confidence_summary.get('low', 0)}",
            f"- Not applicable: {confidence_summary.get('not_applicable', 0)}",
            "",
            "Navigation proposal",
            "-------------------",
            "",
            navigation_update or "No navigation change proposed.",
            "",
            "Diagrams",
            "--------",
            "",
            _diagram_text(project_name, sections)[0],
            "",
            _diagram_text(project_name, sections)[1],
        ]
    )
    if diagram_paths:
        lines.extend(
            ["", "Diagram artifact paths", "----------------------", ""] + [f"- {path}" for path in diagram_paths]
        )
    return "\n".join(lines).strip() + "\n"


def _analysis_gaps(
    repo_file_count: int,
    entry_points: list[ArchitectureFinding],
    routers: list[ArchitectureFinding],
    services: list[ArchitectureFinding],
    auth_files: list[str],
    env_vars: list[str],
) -> list[AnalysisGap]:
    gaps: list[AnalysisGap] = []
    if not entry_points:
        gaps.append(
            AnalysisGap(
                section_name="Application entry points",
                gap_type="missing",
                description="No entry point file was identified from the repository tree.",
                recommended_review_action=(
                    "Confirm whether the application is launched from a different "
                    "script or package entry point."
                ),
            )
        )
    if not routers:
        gaps.append(
            AnalysisGap(
                section_name="Routers",
                gap_type="missing",
                description="No router file was identified during analysis.",
                recommended_review_action=(
                    "Verify whether the service exposes HTTP routes through a "
                    "different package or framework."
                ),
            )
        )
    if not services:
        gaps.append(
            AnalysisGap(
                section_name="Services",
                gap_type="ambiguous",
                description="No explicit service modules were identified from the file names.",
                recommended_review_action=(
                    "Review internal imports and folder structure for application "
                    "services or orchestrators."
                ),
            )
        )
    if not auth_files:
        gaps.append(
            AnalysisGap(
                section_name="Authentication flow",
                gap_type="missing",
                description="No dedicated authentication or security module was identified.",
                recommended_review_action=(
                    "Confirm whether authentication is handled externally or in a "
                    "non-standard module."
                ),
            )
        )
    if not env_vars:
        gaps.append(
            AnalysisGap(
                section_name="Environment variables",
                gap_type="missing",
                description="No environment variable references were detected in the scanned files.",
                recommended_review_action="Check configuration files or deployment manifests for runtime variables.",
            )
        )
    if repo_file_count > ARCHITECTURE_PARTIAL_REPO_THRESHOLD:
        gaps.append(
            AnalysisGap(
                section_name="Repository structure",
                gap_type="too_large",
                description="The repository is large enough that the analysis used a bounded file sample.",
                recommended_review_action=(
                    "Re-run analysis with a narrower target folder selection for a "
                    "more complete draft."
                ),
            )
        )
    return gaps


def _confidence_summary(sections: list[ArchitectureSection]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "not_applicable": 0}
    for section in sections:
        counts[section.confidence_level if section.confidence_level in counts else "not_applicable"] += 1
    return counts


def _existing_architecture_doc(
    provider: str,
    repo_path: str,
    branch: str,
    token: str,
    output_path: str,
) -> str | None:
    if os.path.isdir(repo_path):
        local_path = Path(repo_path) / output_path
        if local_path.exists():
            return local_path.read_text(encoding="utf-8")
        return None
    if provider == "github":
        return fetch_content_from_github(repo_path, branch, output_path, token)
    if provider == "gitlab":
        return fetch_content_from_gitlab(repo_path, branch, output_path, token)
    return None


def _manual_doc_detected(existing_doc: str | None) -> bool:
    if not existing_doc:
        return False
    markers = [
        "Architecture Documentation Draft",
        "Observed findings",
        "Inferred findings",
        "Confidence summary",
    ]
    return not any(marker in existing_doc for marker in markers)


def generate_architecture_draft(req: ArchitectureGenerationRequest) -> ArchitectureAnalysisResult:
    repo_path = extract_repo_path(req.repo_url, req.provider)
    branch = req.branch
    output_path = validate_architecture_output_path(req.output_path)
    target_folders = _normalize_target_folders(req.target_folders)
    log_file = bind_repo_run_log_dir(repo_path, req.provider)
    artifact_dir = str(Path(log_file).parent)
    draft_id = build_architecture_draft_id(repo_path, req.provider)
    artifact_paths = build_architecture_artifact_paths(
        repo_path, req.provider, draft_id=draft_id, artifact_dir=artifact_dir
    )

    try:
        repo_tree, analyzed_files, skipped_files = _collect_repo_snapshot(
            req.provider,
            req.repo_url,
            req.token,
            branch,
            target_folders,
        )
    except RepositoryAccessError:
        raise

    candidate_files = _candidate_files(analyzed_files)
    (
        entry_points,
        services,
        routers,
        modules,
        dependencies,
        external_dependencies,
        background_jobs,
        database_models,
        configs,
        env_vars,
        auth_files,
        endpoints,
    ) = _load_findings(req.provider, req.repo_url, req.token, branch, candidate_files)

    repo_file_count = len(repo_tree)
    gaps = _analysis_gaps(repo_file_count, entry_points, routers, services, auth_files, env_vars)
    if skipped_files:
        gaps.append(
            AnalysisGap(
                section_name="Repository structure",
                gap_type="unsupported",
                description=(
                    f"{len(skipped_files)} file(s) were skipped because they were "
                    "outside the selected target folders."
                ),
                recommended_review_action=(
                    "Review the target folder selection and regenerate if broader "
                    "coverage is needed."
                ),
            )
        )

    existing_doc = _existing_architecture_doc(req.provider, repo_path, branch, req.token, output_path)
    manual_docs_detected = _manual_doc_detected(existing_doc)
    overwrite_required = bool(existing_doc and existing_doc != "")

    project_name = Path(repo_path).name.replace("-", " ").replace("_", " ").title() or "Repository"
    nav_update = build_architecture_navigation_update(output_path, project_name)

    section_objects = [
        _section(
            "Project overview",
            [
                ArchitectureFinding(
                    finding_type="technology",
                    name=project_name,
                    classification="observed",
                    evidence_paths=[repo_path],
                    description="Repository name and target branch were observed from the request.",
                )
            ],
            gaps[:1],
            len(candidate_files),
        ),
        _section("Application entry points", entry_points, [], len(candidate_files)),
        _section("Services", services, [], len(candidate_files)),
        _section("Routers", routers, [], len(candidate_files)),
        _section("Modules and packages", modules, [], len(candidate_files)),
        _section("Internal dependencies", dependencies, [], len(candidate_files)),
        _section("External dependencies", external_dependencies, [], len(candidate_files)),
        _section(
            "Data flow",
            [
                ArchitectureFinding(
                    finding_type="data_flow",
                    name="Request to draft pipeline",
                    classification="inferred",
                    confidence_level="medium",
                    evidence_paths=[
                        "src/router/router.py",
                        "src/services/workflow_service.py",
                        "src/services/architecture_services.py",
                    ],
                    description=(
                        "Requests appear to move from the router through workflow "
                        "orchestration into architecture analysis and artifact "
                        "writing."
                    ),
                )
            ]
            if any([entry_points, services, routers])
            else [],
            [],
            len(candidate_files),
        ),
        _section(
            "Background jobs",
            [
                ArchitectureFinding(
                    finding_type="job",
                    name=file_path,
                    classification="observed",
                    evidence_paths=[file_path],
                    description="Background job module detected by file name.",
                )
                for file_path in background_jobs
            ],
            [],
            len(candidate_files),
        ),
        _section(
            "Database models",
            [
                ArchitectureFinding(
                    finding_type="model",
                    name=file_path,
                    classification="observed",
                    evidence_paths=[file_path],
                    description="Database model module detected by file name.",
                )
                for file_path in database_models
            ],
            [],
            len(candidate_files),
        ),
        _section(
            "Configuration",
            [
                ArchitectureFinding(
                    finding_type="config",
                    name=file_path,
                    classification="observed",
                    evidence_paths=[file_path],
                    description="Configuration source detected from the repository tree.",
                )
                for file_path in configs
            ],
            [],
            len(candidate_files),
        ),
        _section(
            "Environment variables",
            [
                ArchitectureFinding(
                    finding_type="environment_variable",
                    name=env_var,
                    classification="observed",
                    evidence_paths=["source scan"],
                    description="Environment variable reference observed in source content.",
                )
                for env_var in env_vars
            ],
            [],
            len(candidate_files),
        ),
        _section(
            "Authentication flow",
            [
                ArchitectureFinding(
                    finding_type="auth_flow",
                    name=file_path,
                    classification="observed",
                    evidence_paths=[file_path],
                    description="Authentication or session handling module detected by file name.",
                )
                for file_path in auth_files
            ],
            [],
            len(candidate_files),
        ),
        _section(
            "API endpoints",
            [
                ArchitectureFinding(
                    finding_type="endpoint",
                    name=endpoint,
                    classification="observed",
                    evidence_paths=["src/router/router.py", "src/admin/router.py"],
                    description="HTTP route detected from a route decorator.",
                )
                for endpoint in endpoints
            ],
            [],
            len(candidate_files),
        ),
        _section(
            "Sequence diagrams",
            [
                ArchitectureFinding(
                    finding_type="data_flow",
                    name="Generation sequence",
                    classification="inferred",
                    confidence_level="medium",
                    evidence_paths=["src/router/router.py", "src/services/workflow_service.py"],
                    description=(
                        "The generation sequence can be described from the router "
                        "and workflow orchestration flow."
                    ),
                )
            ],
            [],
            len(candidate_files),
        ),
        _section(
            "Architecture diagrams",
            [
                ArchitectureFinding(
                    finding_type="technology",
                    name="Draft architecture diagram",
                    classification="inferred",
                    confidence_level="low",
                    evidence_paths=["artifact generation"],
                    description="A high-level architecture diagram is generated as a review aid.",
                )
            ],
            [],
            len(candidate_files),
        ),
        _section("Repository structure", modules, gaps, len(candidate_files)),
        _section(
            "Technology stack",
            [
                ArchitectureFinding(
                    finding_type="technology",
                    name=name,
                    classification="observed",
                    evidence_paths=["imports and file names"],
                    description="Technology stack inferred from imports and repository layout.",
                )
                for name in sorted(
                    {
                        "FastAPI" if any("fastapi" in item.name.lower() for item in routers + services) else None,
                        "Sphinx" if any(file.endswith(".rst") for file in configs) else None,
                        "SQLAlchemy" if any("model" in file.lower() for file in database_models) else None,
                    }
                    - {None}
                )
            ],
            [],
            len(candidate_files),
        ),
    ]
    # Rebuild diagram artifacts after section assembly.
    diagram_text_generation, diagram_text_architecture = _diagram_text(project_name, section_objects)
    diagram_paths = [
        os.path.join(artifact_paths["diagram_dir"], "sequence_diagram.rst"),
        os.path.join(artifact_paths["diagram_dir"], "architecture_diagram.rst"),
    ]
    Path(artifact_paths["diagram_dir"]).mkdir(parents=True, exist_ok=True)
    Path(diagram_paths[0]).write_text(diagram_text_generation, encoding="utf-8")
    Path(diagram_paths[1]).write_text(diagram_text_architecture, encoding="utf-8")

    result = ArchitectureAnalysisResult(
        status="partial" if gaps else "success",
        draft_id=draft_id,
        draft_path=artifact_paths["draft_path"],
        proposed_output_path=output_path,
        artifact_dir=artifact_paths["artifact_dir"],
        analysis_summary_path=artifact_paths["summary_path"],
        log_path=os.path.join(artifact_paths["artifact_dir"], "app.log"),
        sections=section_objects,
        gaps=gaps,
        diagram_paths=diagram_paths,
        navigation_update=nav_update,
        confidence_summary=_confidence_summary(section_objects),
        approval_required=True,
        overwrite_required=overwrite_required,
        manual_docs_detected=manual_docs_detected,
    )
    Path(result.artifact_dir).mkdir(parents=True, exist_ok=True)
    Path(result.draft_path).write_text(
        _build_rst_draft(
            project_name=project_name,
            repo_path=repo_path,
            branch=branch,
            draft_id=draft_id,
            output_path=output_path,
            sections=section_objects,
            gaps=gaps,
            navigation_update=nav_update,
            diagram_paths=diagram_paths,
            confidence_summary=result.confidence_summary,
            overwrite_required=overwrite_required,
            manual_docs_detected=manual_docs_detected,
        ),
        encoding="utf-8",
    )
    Path(result.analysis_summary_path).write_text(
        json.dumps(result.to_response(), indent=2, default=str), encoding="utf-8"
    )
    return result


def load_architecture_summary(repo_path: str, provider: str, draft_id: str) -> dict[str, Any] | None:
    repo_root = extract_repo_path(repo_path, provider)
    latest_run = find_latest_repo_run_dir(repo_root, provider)
    if not latest_run:
        return None
    repo_dir = Path(latest_run).parent
    for summary_path in repo_dir.rglob(f"{draft_id}.json"):
        try:
            return json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def approve_architecture_draft(req: ArchitectureApprovalRequest) -> ArchitectureApprovalResult:
    repo_path = extract_repo_path(req.repo_url, req.provider)
    output_path = validate_architecture_output_path(req.output_path)
    draft_summary = load_architecture_summary(repo_path, req.provider, req.draft_id)
    if draft_summary is None:
        raise ValueError(f"Draft '{req.draft_id}' could not be found.")
    if draft_summary.get("approval_required") is False:
        raise ValueError("Draft has already been approved or is not in a reviewable state.")
    existing_doc = _existing_architecture_doc(req.provider, repo_path, req.branch, req.token, output_path)
    if existing_doc and not req.overwrite_existing:
        raise ValueError("Existing architecture documentation requires overwrite confirmation.")

    draft_path = Path(draft_summary.get("draft_path") or "")
    if not draft_path.exists():
        raise ValueError("Draft artifact is unavailable.")
    draft_content = draft_path.read_text(encoding="utf-8")
    project_name = Path(repo_path).name.replace("-", " ").replace("_", " ").title() or "Repository"
    navigation_update = build_architecture_navigation_update(output_path, project_name)
    if os.path.isdir(repo_path):
        destination = Path(repo_path) / output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(draft_content, encoding="utf-8")
        apply_architecture_navigation_update(repo_path, req.branch, req.token, req.provider, output_path, project_name)
        commit_url = str(destination)
    else:
        created = create_a_file(repo_path, req.branch, output_path, draft_content, req.token, req.provider)
        if not created:
            raise PermissionError("Architecture draft approval failed while writing the approved documentation.")
        apply_architecture_navigation_update(repo_path, req.branch, req.token, req.provider, output_path, project_name)
        commit_url = None
    return ArchitectureApprovalResult(
        status="approved",
        draft_id=req.draft_id,
        output_path=output_path,
        branch=req.branch,
        commit_url=commit_url,
        artifact_dir=str(draft_path.parent),
        navigation_update=navigation_update,
    )


def execute_architecture_generation_request(req: ArchitectureGenerationRequest) -> ArchitectureAnalysisResult:
    return generate_architecture_draft(req)


def execute_architecture_approval_request(req: ArchitectureApprovalRequest) -> ArchitectureApprovalResult:
    return approve_architecture_draft(req)
