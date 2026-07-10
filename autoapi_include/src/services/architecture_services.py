import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from config.log_config import get_logger
from services.doc_services import (
    _file_matches_target_folders,
    _normalize_target_folders,
)
from services.sphinx_services import (
    apply_approved_architecture_document,
    propose_architecture_navigation,
    update_sphinx_navigation_for_architecture,
)
from utils.git_utils import (
    RepositoryAccessError,
    clone_repository,
    extract_repo_path,
    fetch_content_from_github,
    fetch_content_from_gitlab,
    read_file_content_from_local,
)
from utils.output_paths import (
    bind_repo_run_log_dir,
    build_repo_output_dir,
    build_repo_output_file,
    find_latest_repo_run_dir,
    validate_architecture_output_path,
)

logger = get_logger(__name__)

__all__ = [
    "ArchitectureAnalysisError",
    "ArchitectureApprovalError",
    "ArchitectureOverwriteRequiredError",
    "ArchitectureFinding",
    "ArchitectureSection",
    "AnalysisGap",
    "SECTION_NAMES",
    "MANUAL_EDIT_MARKER",
    "generate_draft_id",
    "architecture_draft_paths",
    "generate_architecture_draft",
    "find_architecture_draft",
    "apply_architecture_approval",
    "is_autodoc_generated_content",
]

SECTION_NAMES = [
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
]

MAX_FILES_FOR_FULL_ANALYSIS = 3000
MAX_LISTED_EXTERNAL_DEPENDENCIES = 60
MAX_LISTED_INTERNAL_EDGES = 80
MANUAL_EDIT_MARKER = ".. AUTODOC ARCHITECTURE DRAFT"

IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
}
ENTRY_POINT_FILENAMES = {
    "main.py",
    "manage.py",
    "app.py",
    "wsgi.py",
    "asgi.py",
    "__main__.py",
    "index.js",
    "server.js",
    "app.js",
    "index.ts",
    "server.ts",
}
DEPENDENCY_FILES = {
    "requirements.txt": "Python (pip)",
    "pyproject.toml": "Python (uv/poetry)",
    "Pipfile": "Python (pipenv)",
    "package.json": "Node.js",
    "go.mod": "Go",
    "Gemfile": "Ruby",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java/Kotlin (Gradle)",
    "Cargo.toml": "Rust",
}
CONFIG_FILENAMES = {
    "config.py",
    "settings.py",
    ".env",
    ".env.example",
    ".env.sample",
    "config.yaml",
    "config.yml",
    "docker-compose.yml",
    "Dockerfile",
}
SEGMENT_HINTS = {
    "services": "services",
    "service": "services",
    "routers": "routers",
    "router": "routers",
    "routes": "routers",
    "models": "database models",
    "jobs": "background jobs",
    "tasks": "background jobs",
    "workers": "background jobs",
}
SOURCE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rb": "Ruby",
    ".java": "Java",
}
SCANNABLE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}

ROUTER_PATTERN = re.compile(r"APIRouter\(|Blueprint\(|express\.Router\(")
ENDPOINT_PATTERN = re.compile(
    r"@(?:router|app)\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']"
)
MODEL_BASE_HINTS = ("Base)", "models.Model", "db.Model", "Base,")
JOB_PATTERN = re.compile(r"@(?:celery_app\.task|shared_task|task)\(|class\s+\w*Job\b")
AUTH_PATTERN = re.compile(
    r"\b(jwt|oauth|authenticate|login_required|require_admin|authorization)\b",
    re.IGNORECASE,
)
ENV_VAR_PATTERN = re.compile(r"os\.(?:getenv|environ\.get)\(\s*[\"']([A-Z0-9_]+)[\"']")
IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.MULTILINE
)


class ArchitectureAnalysisError(RuntimeError):
    """Raised when architecture analysis cannot proceed or yields no usable evidence."""

    def __init__(self, message: str, status_code: int = 422):
        """
        Initialize a conflict error with the provided message.

        Args:
            message (str): Human-readable error message.
        Returns:
            None: This initializer does not return a value.

        """
        super().__init__(message)
        self.status_code = status_code


class ArchitectureApprovalError(RuntimeError):
    """Raised when an architecture draft cannot be approved."""

    def __init__(self, message: str, status_code: int = 422):
        """
        Initialize an error with a message and HTTP-style status code.
        Args:
            message (str): Error message to display.
            status_code (int): Status code associated with the error. Defaults to 422.
        Returns:
            None: Constructor does not return a value.

        """
        super().__init__(message)
        self.status_code = status_code


class ArchitectureOverwriteRequiredError(ArchitectureApprovalError):
    """Raised when approval would overwrite existing manual content without confirmation."""

    def __init__(self, message: str):
        """
        Initialize the exception with a message and HTTP status code.
        Args:
            message (str): Error message. status_code (int): HTTP status code, defaulting to 422.
        Returns:
            None: This initializer returns nothing.

        """
        super().__init__(message, status_code=409)


@dataclass
class ArchitectureFinding:
    """An observed fact or inferred architecture relationship."""

    finding_type: str
    name: str
    classification: str  # "observed" | "inferred"
    description: str
    evidence_paths: list[str] = field(default_factory=list)
    confidence_level: str | None = None

    def to_dict(self) -> dict:
        """
        Convert the documentation gap to a dictionary.
        Args:
            self (DocumentationGap): Instance containing gap details.
        Returns:
            dict: Serialized gap fields for review.

        """
        return {
            "finding_type": self.finding_type,
            "name": self.name,
            "classification": self.classification,
            "description": self.description,
            "evidence_paths": self.evidence_paths,
            "confidence_level": self.confidence_level,
        }


@dataclass
class AnalysisGap:
    """Incomplete or ambiguous architecture analysis for a section."""

    section_name: str
    gap_type: str  # missing | ambiguous | inaccessible | unsupported | too_large
    description: str
    recommended_review_action: str = ""

    def to_dict(self) -> dict:
        """
        Return a dictionary representation of the finding.

        Returns:
            dict: Serialized finding fields, including type, name, classification, evidence paths,
            and confidence level.

        """
        return {
            "section_name": self.section_name,
            "gap_type": self.gap_type,
            "description": self.description,
            "recommended_review_action": self.recommended_review_action,
        }


@dataclass
class ArchitectureSection:
    """One required section of the architecture draft."""

    section_name: str
    status: str  # populated | partial | unavailable
    summary: str
    findings: list[ArchitectureFinding] = field(default_factory=list)
    confidence_level: str = "not_applicable"
    gaps: list[AnalysisGap] = field(default_factory=list)

    @property
    def observed_count(self) -> int:
        """
        Return the number of findings classified as observed.

        Returns:
            int: Count of findings with classification set to "observed".

        """
        return sum(
            1 for finding in self.findings if finding.classification == "observed"
        )

    @property
    def inferred_count(self) -> int:
        """
        Return the number of findings classified as inferred.

        Args:
            None.
        Returns:
            int: Count of findings with classification set to "inferred".

        """
        return sum(
            1 for finding in self.findings if finding.classification == "inferred"
        )

    def to_summary_dict(self) -> dict:
        """
        Return a compact summary representation of this section.

        Returns:
            dict: Mapping containing section name, status, confidence level, and observation counts.

        """
        return {
            "section_name": self.section_name,
            "status": self.status,
            "confidence_level": self.confidence_level,
            "observed_count": self.observed_count,
            "inferred_count": self.inferred_count,
        }


def generate_draft_id() -> str:
    """Generates a unique, sortable architecture draft id."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"arch_{timestamp}_{uuid4().hex[:8]}"


def architecture_draft_paths(
    repo_path: str, provider: str, draft_id: str
) -> tuple[str, str]:
    """Returns the (rst_path, json_metadata_path) artifact locations for a draft id."""
    rst_path = build_repo_output_file(
        repo_path, provider, f"architecture_draft_{draft_id}.rst"
    )
    json_path = build_repo_output_file(
        repo_path, provider, f"architecture_draft_{draft_id}.json"
    )
    return rst_path, json_path


def is_autodoc_generated_content(content: str) -> bool:
    """Returns True when content was previously written by an approved Auto Doc draft."""
    return MANUAL_EDIT_MARKER in (content or "")


def fetch_existing_output_content(
    repo_path: str,
    branch: str,
    output_path: str,
    token: str,
    provider: str,
) -> str | None:
    """Fetches the current content at the proposed architecture output path, if any."""
    normalized_provider = provider.lower()
    if normalized_provider == "github":
        return fetch_content_from_github(repo_path, branch, output_path, token)
    if normalized_provider == "gitlab":
        return fetch_content_from_gitlab(repo_path, branch, output_path, token)
    return None


def _project_name_from_repo_path(repo_path: str) -> str:
    """
    Derive a display project name from a repository path.
    Args:
        repo_path (str): Repository path or URL-like path to parse.
    Returns:
        str: Title-cased project name, or "Project" if unavailable.

    """
    repo_name = repo_path.rstrip("/").split("/")[-1]
    name = repo_name.replace("-", " ").replace("_", " ").strip()
    return name.title() if name else "Project"


def _iter_source_files(root_dir: str, target_folders: list[str]) -> list[str]:
    """
    Return sorted relative source file paths under the given root.

    Args:
        root_dir (str): Directory tree to scan.
        target_folders (list[str]): Optional folder filters for included files.
    Returns:
        list[str]: Sorted relative file paths using forward slashes.

    """
    normalized_targets = _normalize_target_folders(target_folders)
    collected: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRECTORIES]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root_dir).replace(os.sep, "/")
            if normalized_targets and not _file_matches_target_folders(
                rel_path, normalized_targets
            ):
                continue
            collected.append(rel_path)
    return sorted(collected)


def _scan_repository(root_dir: str, target_folders: list[str]) -> dict:
    """Walks a cloned repository and collects architecture evidence via static heuristics."""
    all_paths = _iter_source_files(root_dir, target_folders)
    truncated = len(all_paths) > MAX_FILES_FOR_FULL_ANALYSIS
    scan_paths = all_paths[:MAX_FILES_FOR_FULL_ANALYSIS] if truncated else all_paths

    top_level_packages = {
        name
        for name in os.listdir(root_dir)
        if os.path.isdir(os.path.join(root_dir, name))
        and name not in IGNORED_DIRECTORIES
    }

    evidence = {
        "total_files": len(all_paths),
        "scanned_files": len(scan_paths),
        "truncated": truncated,
        "entry_points": [],
        "dependency_files": [],
        "config_files": [],
        "packages": set(),
        "services": [],
        "routers": [],
        "endpoints": [],
        "models": [],
        "jobs": [],
        "auth_files": [],
        "env_vars": {},
        "internal_imports": set(),
        "language_counts": {},
        "top_level_entries": set(),
    }

    for rel_path in scan_paths:
        segments = rel_path.split("/")
        evidence["top_level_entries"].add(segments[0])
        filename = segments[-1]
        _, ext = os.path.splitext(filename)
        if ext in SOURCE_EXTENSIONS:
            language = SOURCE_EXTENSIONS[ext]
            evidence["language_counts"][language] = (
                evidence["language_counts"].get(language, 0) + 1
            )

        if filename in ENTRY_POINT_FILENAMES:
            evidence["entry_points"].append(rel_path)
        if filename in DEPENDENCY_FILES:
            evidence["dependency_files"].append(rel_path)
        if filename in CONFIG_FILENAMES:
            evidence["config_files"].append(rel_path)
        if filename == "__init__.py" and len(segments) > 1:
            evidence["packages"].add("/".join(segments[:-1]))

        for segment in segments[:-1]:
            hint = SEGMENT_HINTS.get(segment.lower())
            if hint == "services" and rel_path not in evidence["services"]:
                evidence["services"].append(rel_path)
            elif hint == "routers" and rel_path not in evidence["routers"]:
                evidence["routers"].append(rel_path)
            elif hint == "database models" and rel_path not in evidence["models"]:
                evidence["models"].append(rel_path)
            elif hint == "background jobs" and rel_path not in evidence["jobs"]:
                evidence["jobs"].append(rel_path)

        if ext not in SCANNABLE_EXTENSIONS:
            continue
        content = read_file_content_from_local(root_dir, rel_path)
        if not content:
            continue
        if ROUTER_PATTERN.search(content) and rel_path not in evidence["routers"]:
            evidence["routers"].append(rel_path)
        for method, path in ENDPOINT_PATTERN.findall(content):
            evidence["endpoints"].append(
                {"method": method.upper(), "path": path, "file": rel_path}
            )
        if (
            any(hint in content for hint in MODEL_BASE_HINTS)
            and rel_path not in evidence["models"]
        ):
            evidence["models"].append(rel_path)
        if JOB_PATTERN.search(content) and rel_path not in evidence["jobs"]:
            evidence["jobs"].append(rel_path)
        if AUTH_PATTERN.search(content) and rel_path not in evidence["auth_files"]:
            evidence["auth_files"].append(rel_path)
        for var_name in ENV_VAR_PATTERN.findall(content):
            evidence["env_vars"].setdefault(var_name, []).append(rel_path)
        if ext == ".py":
            module_guess = rel_path[:-3].replace("/", ".")
            for imported in IMPORT_PATTERN.findall(content):
                top_module = imported.split(".")[0]
                package_roots = {pkg.split("/")[0] for pkg in evidence["packages"]}
                if top_module in top_level_packages or top_module in package_roots:
                    evidence["internal_imports"].add((module_guess, top_module))

    evidence["packages"] = sorted(evidence["packages"])
    evidence["top_level_entries"] = sorted(evidence["top_level_entries"])
    return evidence


def _finding(
    finding_type: str,
    name: str,
    classification: str,
    description: str,
    evidence_paths: list[str] | None = None,
    confidence_level: str | None = None,
) -> ArchitectureFinding:
    """
    Create an ArchitectureFinding with normalized optional fields.
    Args: finding_type (str), name (str), classification (str), description (str), evidence_paths
    (list[str] | None), confidence_level (str | None): Finding metadata and optional
    evidence/confidence.
    Returns: ArchitectureFinding: The constructed finding with confidence only for inferred
    classifications.
    """
    return ArchitectureFinding(
        finding_type=finding_type,
        name=name,
        classification=classification,
        description=description,
        evidence_paths=evidence_paths or [],
        confidence_level=confidence_level if classification == "inferred" else None,
    )


def _confidence_from_count(count: int) -> str:
    """
    Return a confidence label based on an occurrence count.

    Args:
        count (int): Number of occurrences to classify.
    Returns:
        str: Confidence level: "high", "medium", or "low".

    """
    if count >= 5:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


def _paths_section(
    section_name: str,
    paths: list[str],
    finding_type: str,
    gap_recommendation: str,
) -> tuple[ArchitectureSection, AnalysisGap | None]:
    """
    Build an architecture section from detected file paths, reporting a gap when none exist.
    Args: section_name (str): Section label; paths (list[str]): candidate paths; finding_type (str):
    finding category; gap_recommendation (str): review guidance for missing evidence.
    Returns: tuple[ArchitectureSection, AnalysisGap | None]: Generated section and optional gap for
    missing paths.
    """
    unique_paths = sorted(set(paths))
    if not unique_paths:
        gap = AnalysisGap(
            section_name=section_name,
            gap_type="missing",
            description=f"No {section_name} evidence was found in the analyzed files.",
            recommended_review_action=gap_recommendation,
        )
        section = ArchitectureSection(
            section_name=section_name,
            status="unavailable",
            summary=f"No {section_name} evidence found.",
            findings=[],
            confidence_level="not_applicable",
            gaps=[gap],
        )
        return section, gap

    findings = [
        _finding(
            finding_type,
            path,
            "observed",
            f"File path matched {section_name} detection heuristics.",
            [path],
        )
        for path in unique_paths
    ]
    preview = ", ".join(unique_paths[:8]) + (", ..." if len(unique_paths) > 8 else "")
    section = ArchitectureSection(
        section_name=section_name,
        status="populated",
        summary=f"Found {len(findings)} {section_name} file(s): {preview}",
        findings=findings,
        confidence_level="not_applicable",
        gaps=[],
    )
    return section, None


def _parse_external_dependencies(
    root_dir: str, dependency_files: list[str]
) -> list[tuple[str, str, str]]:
    """Extracts (name, source_file, manager_label) tuples from common manifest formats."""
    results: list[tuple[str, str, str]] = []
    for rel_path in dependency_files:
        filename = os.path.basename(rel_path)
        manager_label = DEPENDENCY_FILES.get(filename, filename)
        content = read_file_content_from_local(root_dir, rel_path)
        if not content:
            continue
        if filename == "requirements.txt":
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                    continue
                name = re.split(r"[<>=!~\[; ]", stripped, maxsplit=1)[0].strip()
                if name:
                    results.append((name, rel_path, manager_label))
        elif filename == "package.json":
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
            for dependency_group in ("dependencies", "devDependencies"):
                for name in (payload.get(dependency_group) or {}).keys():
                    results.append((name, rel_path, manager_label))
        elif filename == "pyproject.toml":
            for match in re.finditer(
                r'^\s*"([A-Za-z0-9_.\-]+)(?:[<>=!~ ].*)?"\s*,?\s*$',
                content,
                flags=re.MULTILINE,
            ):
                results.append((match.group(1), rel_path, manager_label))
    return results


def _build_sections(
    evidence: dict, include_diagrams: bool
) -> tuple[list[ArchitectureSection], list[AnalysisGap], dict]:
    """
    Build architecture report sections, analysis gaps, and optional diagram content from repository
    evidence.

    Args:
        evidence (dict): Collected repository signals used to populate sections and gaps.
        include_diagrams (bool): Whether to generate architecture and sequence diagram content.
    Returns:
        tuple[list[ArchitectureSection], list[AnalysisGap], dict]: Sections, gaps, and diagram
        content by diagram type.

    """
    sections: list[ArchitectureSection] = []
    gaps: list[AnalysisGap] = []
    diagram_content: dict[str, str] = {}

    # project overview
    overview_gap = None
    if evidence["truncated"]:
        overview_gap = AnalysisGap(
            "project overview",
            "too_large",
            f"Repository has {evidence['total_files']} files; analysis was limited to the first "
            f"{evidence['scanned_files']} files for this run.",
            "Narrow analysis with target_folders, or accept the partial result and review manually.",
        )
        gaps.append(overview_gap)
    overview_summary = (
        f"Scanned {evidence['scanned_files']} of {evidence['total_files']} files across "
        f"{len(evidence['top_level_entries'])} top-level entries."
    )
    overview_findings = [
        _finding("technology", "repository scan", "observed", overview_summary, [])
    ]
    sections.append(
        ArchitectureSection(
            "project overview",
            "partial" if evidence["truncated"] else "populated",
            overview_summary,
            overview_findings,
            "not_applicable",
            [overview_gap] if overview_gap else [],
        )
    )

    # entry points
    entry_section, entry_gap = _paths_section(
        "entry points",
        evidence["entry_points"],
        "entry_point",
        "Add a documented entry point file (e.g. main.py) or note the process start command manually.",
    )
    sections.append(entry_section)
    if entry_gap:
        gaps.append(entry_gap)

    # services
    services_section, services_gap = _paths_section(
        "services",
        evidence["services"],
        "service",
        "Organize service logic under a services/ directory or document service boundaries manually.",
    )
    sections.append(services_section)
    if services_gap:
        gaps.append(services_gap)

    # routers
    routers_section, routers_gap = _paths_section(
        "routers",
        evidence["routers"],
        "router",
        "Add router/blueprint definitions or document HTTP entry points manually.",
    )
    sections.append(routers_section)
    if routers_gap:
        gaps.append(routers_gap)

    # modules and packages
    packages_section, packages_gap = _paths_section(
        "modules and packages",
        evidence["packages"],
        "module",
        "Confirm module boundaries manually; no __init__.py packages were detected.",
    )
    sections.append(packages_section)
    if packages_gap:
        gaps.append(packages_gap)

    # internal dependencies (inferred)
    internal_edges = sorted(evidence["internal_imports"])
    if internal_edges:
        confidence = _confidence_from_count(len(internal_edges))
        listed_edges = internal_edges[:MAX_LISTED_INTERNAL_EDGES]
        findings = [
            _finding(
                "module",
                f"{source} -> {target}",
                "inferred",
                "Inferred from an import statement; relationship direction assumes standard import semantics.",
                [source.replace(".", "/") + ".py"],
                confidence_level=confidence,
            )
            for source, target in listed_edges
        ]
        internal_gap = None
        status = "populated"
        if len(internal_edges) > MAX_LISTED_INTERNAL_EDGES:
            status = "partial"
            internal_gap = AnalysisGap(
                "internal dependencies",
                "too_large",
                f"{len(internal_edges)} import edges detected; only the first {MAX_LISTED_INTERNAL_EDGES} are listed.",
                "Review the repository's import graph directly for the complete picture.",
            )
            gaps.append(internal_gap)
        sections.append(
            ArchitectureSection(
                "internal dependencies",
                status,
                f"Inferred {len(internal_edges)} internal import relationship(s).",
                findings,
                confidence,
                [internal_gap] if internal_gap else [],
            )
        )
    else:
        internal_gap = AnalysisGap(
            "internal dependencies",
            "ambiguous",
            "No internal import relationships could be inferred between local packages.",
            "Confirm module boundaries manually; the heuristic import scan found no local package edges.",
        )
        gaps.append(internal_gap)
        sections.append(
            ArchitectureSection(
                "internal dependencies",
                "unavailable",
                "No internal dependency evidence found.",
                [],
                "not_applicable",
                [internal_gap],
            )
        )

    # external dependencies
    external_deps = evidence.get("_external_deps")
    if external_deps is None:
        external_deps = []
    if external_deps:
        listed = external_deps[:MAX_LISTED_EXTERNAL_DEPENDENCIES]
        findings = [
            _finding(
                "dependency",
                name,
                "observed",
                f"Declared in {manager_label} manifest.",
                [source_file],
            )
            for name, source_file, manager_label in listed
        ]
        status = "populated"
        external_gap = None
        if len(external_deps) > MAX_LISTED_EXTERNAL_DEPENDENCIES:
            status = "partial"
            external_gap = AnalysisGap(
                "external dependencies",
                "too_large",
                f"{len(external_deps)} dependencies declared; only the first "
                f"{MAX_LISTED_EXTERNAL_DEPENDENCIES} are listed.",
                "Review the manifest files directly for the complete dependency list.",
            )
            gaps.append(external_gap)
        sections.append(
            ArchitectureSection(
                "external dependencies",
                status,
                f"Found {len(external_deps)} external dependency declaration(s).",
                findings,
                "not_applicable",
                [external_gap] if external_gap else [],
            )
        )
    elif evidence["dependency_files"]:
        findings = [
            _finding(
                "dependency",
                os.path.basename(path),
                "observed",
                "Manifest file present but dependency names were not parsed for this manifest format.",
                [path],
            )
            for path in evidence["dependency_files"]
        ]
        sections.append(
            ArchitectureSection(
                "external dependencies",
                "partial",
                "Dependency manifest found but names were not parsed for this manifest format.",
                findings,
                "not_applicable",
                [],
            )
        )
    else:
        external_gap = AnalysisGap(
            "external dependencies",
            "missing",
            "No dependency manifest files were found.",
            "Add a manifest (requirements.txt, package.json, etc.) or document dependencies manually.",
        )
        gaps.append(external_gap)
        sections.append(
            ArchitectureSection(
                "external dependencies",
                "unavailable",
                "No external dependency evidence found.",
                [],
                "not_applicable",
                [external_gap],
            )
        )

    # data flow (inferred)
    flow_stages = []
    if evidence["endpoints"]:
        flow_stages.append("API endpoint")
    if evidence["routers"]:
        flow_stages.append("router")
    if evidence["services"]:
        flow_stages.append("service")
    if evidence["models"]:
        flow_stages.append("database model")

    if len(flow_stages) >= 2:
        confidence = _confidence_from_count(len(flow_stages) * 2)
        flow_description = " -> ".join(flow_stages)
        findings = [
            _finding(
                "data_flow",
                flow_description,
                "inferred",
                "Inferred from the presence of endpoint, router, service, and model evidence; "
                "exact call paths were not traced.",
                [],
                confidence_level=confidence,
            )
        ]
        sections.append(
            ArchitectureSection(
                "data flow",
                "populated",
                f"Inferred a likely request flow: {flow_description}.",
                findings,
                confidence,
                [],
            )
        )
    else:
        data_flow_gap = AnalysisGap(
            "data flow",
            "ambiguous",
            "Not enough layered evidence (endpoints/routers/services/models) was found to infer a request flow.",
            "Document the request/data flow manually.",
        )
        gaps.append(data_flow_gap)
        sections.append(
            ArchitectureSection(
                "data flow",
                "unavailable",
                "No data flow evidence found.",
                [],
                "not_applicable",
                [data_flow_gap],
            )
        )

    # background jobs
    jobs_section, jobs_gap = _paths_section(
        "background jobs",
        evidence["jobs"],
        "job",
        "Document background/async jobs manually if a scheduler is used outside common patterns.",
    )
    sections.append(jobs_section)
    if jobs_gap:
        gaps.append(jobs_gap)

    # database models
    models_section, models_gap = _paths_section(
        "database models",
        evidence["models"],
        "model",
        "Document data models manually if the project uses a non-standard ORM pattern.",
    )
    sections.append(models_section)
    if models_gap:
        gaps.append(models_gap)

    # configuration
    config_section, config_gap = _paths_section(
        "configuration",
        evidence["config_files"],
        "config",
        "Document configuration sources manually.",
    )
    sections.append(config_section)
    if config_gap:
        gaps.append(config_gap)

    # environment variables
    if evidence["env_vars"]:
        env_findings = [
            _finding(
                "environment_variable",
                var_name,
                "observed",
                "Referenced via os.getenv/os.environ.get in source.",
                sorted(set(paths)),
            )
            for var_name, paths in sorted(evidence["env_vars"].items())
        ]
        sections.append(
            ArchitectureSection(
                "environment variables",
                "populated",
                f"Found {len(env_findings)} environment variable reference(s).",
                env_findings,
                "not_applicable",
                [],
            )
        )
    else:
        env_gap = AnalysisGap(
            "environment variables",
            "missing",
            "No os.getenv/os.environ.get references were found.",
            "Document required environment variables manually, or confirm the project reads config elsewhere.",
        )
        gaps.append(env_gap)
        sections.append(
            ArchitectureSection(
                "environment variables",
                "unavailable",
                "No environment variable evidence found.",
                [],
                "not_applicable",
                [env_gap],
            )
        )

    # authentication flow
    auth_section, auth_gap = _paths_section(
        "authentication flow",
        evidence["auth_files"],
        "auth_flow",
        "Document the authentication flow manually; no auth-related keywords were detected.",
    )
    sections.append(auth_section)
    if auth_gap:
        gaps.append(auth_gap)

    # API endpoints
    if evidence["endpoints"]:
        endpoint_findings = [
            _finding(
                "endpoint",
                f"{item['method']} {item['path']}",
                "observed",
                "Matched a router/app decorator in source.",
                [item["file"]],
            )
            for item in evidence["endpoints"]
        ]
        sections.append(
            ArchitectureSection(
                "API endpoints",
                "populated",
                f"Found {len(endpoint_findings)} endpoint(s).",
                endpoint_findings,
                "not_applicable",
                [],
            )
        )
    else:
        endpoints_gap = AnalysisGap(
            "API endpoints",
            "missing",
            "No HTTP route decorators were found.",
            "Document API endpoints manually if the project exposes HTTP routes via a non-standard framework.",
        )
        gaps.append(endpoints_gap)
        sections.append(
            ArchitectureSection(
                "API endpoints",
                "unavailable",
                "No API endpoint evidence found.",
                [],
                "not_applicable",
                [endpoints_gap],
            )
        )

    # sequence + architecture diagrams
    if include_diagrams and len(flow_stages) >= 2:
        confidence = _confidence_from_count(len(flow_stages) * 2)
        diagram_content["architecture"] = " -> ".join(
            stage.replace(" ", "_") for stage in flow_stages
        )
        diagram_content["sequence"] = "\n".join(
            f"{flow_stages[index]} -> {flow_stages[index + 1]}: call"
            for index in range(len(flow_stages) - 1)
        )
        sections.append(
            ArchitectureSection(
                "architecture diagrams",
                "populated",
                "Architecture diagram rendered from layered evidence.",
                [
                    _finding(
                        "technology",
                        "architecture diagram",
                        "inferred",
                        "Rendered from layered endpoint/router/service/model evidence.",
                        [],
                        confidence_level=confidence,
                    )
                ],
                confidence,
                [],
            )
        )
        sections.append(
            ArchitectureSection(
                "sequence diagrams",
                "populated",
                "Sequence diagram rendered from layered evidence.",
                [
                    _finding(
                        "technology",
                        "sequence diagram",
                        "inferred",
                        "Rendered from layered endpoint/router/service/model evidence.",
                        [],
                        confidence_level=confidence,
                    )
                ],
                confidence,
                [],
            )
        )
    else:
        if not include_diagrams:
            reason = "Diagram generation was disabled for this request."
            gap_type = "unsupported"
        else:
            reason = (
                "Not enough layered evidence was found to generate a reliable diagram."
            )
            gap_type = "ambiguous"
        for diagram_section_name in ("architecture diagrams", "sequence diagrams"):
            diagram_gap = AnalysisGap(
                diagram_section_name,
                gap_type,
                reason,
                "Enable diagram generation and ensure endpoint/router/service/model evidence exists, "
                "or add a diagram manually.",
            )
            gaps.append(diagram_gap)
            sections.append(
                ArchitectureSection(
                    diagram_section_name,
                    "unavailable",
                    reason,
                    [],
                    "not_applicable",
                    [diagram_gap],
                )
            )

    # repository structure
    if evidence["top_level_entries"]:
        structure_findings = [
            _finding(
                "module", entry, "observed", "Top-level repository entry.", [entry]
            )
            for entry in evidence["top_level_entries"]
        ]
        sections.append(
            ArchitectureSection(
                "repository structure",
                "populated",
                f"Repository has {len(structure_findings)} top-level entries.",
                structure_findings,
                "not_applicable",
                [],
            )
        )
    else:
        structure_gap = AnalysisGap(
            "repository structure",
            "inaccessible",
            "No top-level repository entries could be listed.",
            "Confirm the repository clone succeeded and contains files.",
        )
        gaps.append(structure_gap)
        sections.append(
            ArchitectureSection(
                "repository structure",
                "unavailable",
                "No repository structure evidence found.",
                [],
                "not_applicable",
                [structure_gap],
            )
        )

    # technology stack
    tech_findings = []
    for language, count in sorted(
        evidence["language_counts"].items(), key=lambda item: -item[1]
    ):
        tech_findings.append(
            _finding(
                "technology",
                f"{language} ({count} file(s))",
                "observed",
                "Counted from scanned file extensions.",
                [],
            )
        )
    for rel_path in evidence["dependency_files"]:
        manager_label = DEPENDENCY_FILES.get(
            os.path.basename(rel_path), os.path.basename(rel_path)
        )
        tech_findings.append(
            _finding(
                "technology",
                manager_label,
                "observed",
                "Detected from dependency manifest file.",
                [rel_path],
            )
        )
    if tech_findings:
        sections.append(
            ArchitectureSection(
                "technology stack",
                "populated",
                f"Identified {len(tech_findings)} technology signal(s).",
                tech_findings,
                "not_applicable",
                [],
            )
        )
    else:
        tech_gap = AnalysisGap(
            "technology stack",
            "missing",
            "No recognizable source file extensions or dependency manifests were found.",
            "Document the technology stack manually.",
        )
        gaps.append(tech_gap)
        sections.append(
            ArchitectureSection(
                "technology stack",
                "unavailable",
                "No technology stack evidence found.",
                [],
                "not_applicable",
                [tech_gap],
            )
        )

    return sections, gaps, diagram_content


def _confidence_label(level: str) -> str:
    """
    Return a human-readable label for a confidence level.

    Args:
        level (str): Confidence level key to translate.
    Returns:
        str: Display label, or the original level if unknown.

    """
    return {
        "high": "High confidence",
        "medium": "Medium confidence",
        "low": "Low confidence",
        "not_applicable": "N/A",
    }.get(level, level)


def render_architecture_draft_rst(
    project_name: str,
    sections: list[ArchitectureSection],
    diagram_content: dict,
) -> str:
    """Renders the architecture draft as reStructuredText matching the docs style conventions."""
    title = f"{project_name} Architecture (Draft)"
    lines = [
        title,
        "=" * len(title),
        "",
        ".. note::",
        "   This page is an automatically generated draft. It has not been approved",
        "   for publication. Review each section before approving.",
        "",
    ]
    for section in sections:
        heading = section.section_name.title()
        lines.append(heading)
        lines.append("-" * len(heading))
        lines.append("")
        lines.append(
            f"Status: {section.status} | Confidence: {_confidence_label(section.confidence_level)}"
        )
        lines.append("")
        lines.append(section.summary)
        lines.append("")
        for finding in section.findings:
            if finding.classification == "observed":
                marker = "Observed"
            else:
                marker = f"Inferred ({_confidence_label(finding.confidence_level or 'not_applicable')})"
            evidence = (
                f" [{', '.join(finding.evidence_paths)}]"
                if finding.evidence_paths
                else ""
            )
            lines.append(
                f"- **{finding.name}** -- {marker}: {finding.description}{evidence}"
            )
        if section.findings:
            lines.append("")
        for gap in section.gaps:
            lines.append(f".. warning:: {gap.description} ({gap.gap_type})")
            if gap.recommended_review_action:
                lines.append(f"   Recommended action: {gap.recommended_review_action}")
            lines.append("")
        if section.section_name == "architecture diagrams" and diagram_content.get(
            "architecture"
        ):
            lines.append(".. code-block:: text")
            lines.append("")
            for diagram_line in diagram_content["architecture"].splitlines():
                lines.append(f"   {diagram_line}")
            lines.append("")
        if section.section_name == "sequence diagrams" and diagram_content.get(
            "sequence"
        ):
            lines.append(".. code-block:: text")
            lines.append("")
            for diagram_line in diagram_content["sequence"].splitlines():
                lines.append(f"   {diagram_line}")
            lines.append("")
    return "\n".join(lines) + "\n"


def _approved_architecture_content(draft_content: str) -> str:
    """
    Convert a reviewed architecture draft into publishable approved content.
    """
    content = re.sub(
        r"^(?P<title>.+?) Architecture \(Draft\)\n=+\n",
        "Architecture\n============\n",
        draft_content,
        count=1,
        flags=re.MULTILINE,
    )
    content = re.sub(
        (
            r"\n?\.\. note::\n"
            r"   This page is an automatically generated draft\. It has not been approved\n"
            r"   for publication\. Review each section before approving\.\n\n"
        ),
        "\n",
        content,
        count=1,
    )
    return content.lstrip()


def generate_architecture_draft(
    provider: str,
    repo_url: str,
    token: str,
    branch: str,
    target_folders: list[str] | None,
    output_path: str,
    include_diagrams: bool,
    reuse_existing_docs: bool,
    progress_callback=None,
) -> dict:
    """
    Analyzes a repository and produces a reviewable architecture documentation draft.

    Generation is read-only: it never commits, writes, or publishes to the target repository.
    """
    if not repo_url or not token or not branch or not provider:
        raise ValueError(
            "Missing required parameters: repo_url, token, branch, or provider."
        )

    normalized_output_path = validate_architecture_output_path(output_path)
    repo_path = extract_repo_path(repo_url, provider)
    logger.info(
        "Analyzing architecture for repo: provider=%s, url=%s, branch=%s",
        provider,
        repo_url,
        branch,
    )

    bind_repo_run_log_dir(repo_path, provider)
    artifact_dir = build_repo_output_dir(repo_path, provider)

    if progress_callback is not None:
        progress_callback(20.0, "Cloning repository for architecture analysis")

    try:
        with clone_repository(repo_url, token, branch, provider) as temp_dir:
            evidence = _scan_repository(temp_dir, target_folders or [])
            evidence["_external_deps"] = _parse_external_dependencies(
                temp_dir, evidence["dependency_files"]
            )
    except RepositoryAccessError as exc:
        raise ArchitectureAnalysisError(
            str(exc), status_code=exc.status_code or 404
        ) from exc

    if evidence["total_files"] == 0:
        raise ArchitectureAnalysisError(
            f"Repository was reachable, but no files were found to analyze on branch '{branch}'.",
            status_code=404,
        )

    if progress_callback is not None:
        progress_callback(50.0, "Assembling architecture sections")

    sections, gaps, diagram_content = _build_sections(evidence, include_diagrams)

    existing_doc_is_manual = False
    if reuse_existing_docs:
        existing_content = fetch_existing_output_content(
            repo_path, branch, normalized_output_path, token, provider
        )
        if existing_content is not None:
            existing_doc_is_manual = not is_autodoc_generated_content(existing_content)
            if existing_doc_is_manual:
                manual_gap = AnalysisGap(
                    "project overview",
                    "ambiguous",
                    f"An existing document was found at '{normalized_output_path}' that does not look "
                    "autogenerated. Regeneration will not overwrite it without explicit approval.",
                    "Review the existing document before approving an overwrite.",
                )
                gaps.append(manual_gap)
                sections[0].gaps.append(manual_gap)

    project_name = _project_name_from_repo_path(repo_path)
    draft_content = render_architecture_draft_rst(
        project_name, sections, diagram_content
    )

    draft_id = generate_draft_id()
    draft_rst_path, draft_json_path = architecture_draft_paths(
        repo_path, provider, draft_id
    )
    with open(draft_rst_path, "w", encoding="utf-8") as handle:
        handle.write(draft_content)

    diagram_paths = []
    for diagram_name, diagram_text in diagram_content.items():
        diagram_filename = f"architecture_diagram_{draft_id}_{diagram_name}.txt"
        diagram_path = build_repo_output_file(repo_path, provider, diagram_filename)
        with open(diagram_path, "w", encoding="utf-8") as handle:
            handle.write(diagram_text)
        diagram_paths.append(diagram_path)

    navigation_update = propose_architecture_navigation(
        repo_path, branch, token, provider, normalized_output_path
    )

    overall_status = "success"
    if evidence["truncated"] or navigation_update.get("conflict"):
        overall_status = "partial"
    critical_sections = {"entry points", "repository structure"}
    if any(
        section.status == "unavailable"
        for section in sections
        if section.section_name in critical_sections
    ):
        overall_status = "partial"

    sections_summary = [section.to_summary_dict() for section in sections]
    gaps_payload = [gap.to_dict() for gap in gaps]

    metadata = {
        "draft_id": draft_id,
        "status": "draft",
        "generation_status": overall_status,
        "repo_path": repo_path,
        "provider": provider.lower(),
        "branch": branch,
        "draft_path": draft_rst_path,
        "proposed_output_path": normalized_output_path,
        "navigation_update": navigation_update,
        "diagram_paths": diagram_paths,
        "existing_doc_is_manual": existing_doc_is_manual,
        "sections_summary": sections_summary,
        "gaps": gaps_payload,
        "created_at": datetime.now(UTC).isoformat(),
        "reviewed_at": None,
        "approval_note": None,
    }
    with open(draft_json_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)

    if progress_callback is not None:
        progress_callback(90.0, "Architecture draft ready for review")

    return {
        "status": overall_status,
        "draft_id": draft_id,
        "draft_path": draft_rst_path,
        "proposed_output_path": normalized_output_path,
        "sections_summary": sections_summary,
        "gaps": gaps_payload,
        "diagram_paths": diagram_paths,
        "artifact_dir": artifact_dir,
        "navigation_update": navigation_update,
    }


def find_architecture_draft(
    repo_path: str, provider: str, draft_id: str
) -> dict | None:
    """Searches this repository's run artifact history for a generated draft's metadata."""
    latest_run_dir = find_latest_repo_run_dir(repo_path, provider)
    if not latest_run_dir:
        return None
    repo_base = os.path.dirname(latest_run_dir)
    run_dirs = sorted(
        (
            os.path.join(repo_base, entry)
            for entry in os.listdir(repo_base)
            if entry.startswith("app_")
        ),
        reverse=True,
    )
    for run_dir in run_dirs:
        draft_json_path = os.path.join(run_dir, f"architecture_draft_{draft_id}.json")
        if os.path.exists(draft_json_path):
            with open(draft_json_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
            metadata["_metadata_path"] = draft_json_path
            return metadata
    return None


def apply_architecture_approval(
    provider: str,
    repo_url: str,
    token: str,
    branch: str,
    draft_id: str,
    output_path: str,
    overwrite_existing: bool,
    approval_note: str | None = None,
) -> dict:
    """
    Applies an approved architecture draft to the target repository documentation tree.

    Raises ArchitectureOverwriteRequiredError when existing manual content would be replaced
    without explicit overwrite confirmation.
    """
    normalized_output_path = validate_architecture_output_path(output_path)
    repo_path = extract_repo_path(repo_url, provider)

    draft_metadata = find_architecture_draft(repo_path, provider, draft_id)
    if draft_metadata is None:
        raise ArchitectureApprovalError(
            f"Architecture draft '{draft_id}' was not found for this repository."
        )
    if draft_metadata.get("status") != "draft":
        raise ArchitectureApprovalError(
            f"Architecture draft '{draft_id}' is '{draft_metadata.get('status')}' and cannot be approved again."
        )

    draft_path = draft_metadata["draft_path"]
    if not os.path.exists(draft_path):
        raise ArchitectureApprovalError(
            f"Architecture draft content for '{draft_id}' is no longer available."
        )
    with open(draft_path, "r", encoding="utf-8") as handle:
        draft_content = handle.read()

    existing_content = fetch_existing_output_content(
        repo_path, branch, normalized_output_path, token, provider
    )
    if (
        existing_content is not None
        and not is_autodoc_generated_content(existing_content)
        and not overwrite_existing
    ):
        raise ArchitectureOverwriteRequiredError(
            f"Existing manual content was found at '{normalized_output_path}'. "
            "Set overwrite_existing=true to replace it."
        )

    approved_at = datetime.now(UTC)
    marker_line = f"{MANUAL_EDIT_MARKER} (approved {approved_at.isoformat()})\n\n"
    final_content = marker_line + _approved_architecture_content(draft_content)
    if approval_note:
        final_content += f"\n.. Reviewer note: {approval_note}\n"

    written = apply_approved_architecture_document(
        repo_path, branch, token, provider, normalized_output_path, final_content
    )
    if not written:
        raise ArchitectureApprovalError(
            f"Writing the approved architecture document to '{normalized_output_path}' failed. "
            "Check that the token has write access to this branch.",
            status_code=403,
        )

    navigation_update = draft_metadata.get("navigation_update") or {}
    navigation_applied = update_sphinx_navigation_for_architecture(
        repo_path, branch, token, provider, navigation_update
    )
    if not navigation_applied:
        logger.warning(
            "Architecture doc approved for draft '%s' but navigation update failed.",
            draft_id,
        )

    draft_metadata["status"] = "approved"
    draft_metadata["reviewed_at"] = approved_at.isoformat()
    draft_metadata["approval_note"] = approval_note
    metadata_path = draft_metadata.pop("_metadata_path")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(draft_metadata, handle, indent=2)

    return {
        "status": "approved",
        "output_path": normalized_output_path,
        "commit_url": None,
        "navigation_applied": navigation_applied,
    }
