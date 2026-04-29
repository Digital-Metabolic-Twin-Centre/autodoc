import json
import os
from pathlib import Path

import pandas as pd

from config.log_config import get_logger
from utils.code_block_extraction import GenericCodeBlockExtractor
from utils.docstring_generation import (
    format_docstring_for_language,
    generate_docstring_with_openai,
)
from utils.docstring_validation import (
    analyze_docstring_in_blocks,
    analyze_docstring_in_module,
)
from utils.git_utils import (
    RepositoryAccessError,
    extract_repo_path,
    fetch_content_from_github,
    fetch_content_from_gitlab,
    fetch_repo_tree,
)
from utils.output_paths import bind_repo_run_log_dir, build_repo_output_dir, build_repo_output_file
from utils.output_paths import clear_repo_output_history, find_latest_repo_run_dir

logger = get_logger(__name__)

__all__ = [
    "RepoAnalysisError",
    "analyze_repo",
    "_normalize_target_folders",
    "_file_matches_target_folders",
]


class RepoAnalysisError(RuntimeError):
    """Raised when repository analysis cannot proceed or yields no usable files."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _normalize_target_folders(target_folders):
    normalized_folders = []
    for folder in target_folders or []:
        normalized = str(folder).strip().strip("/")
        if normalized:
            normalized_folders.append(normalized)
    return normalized_folders


def _file_matches_target_folders(file_path, target_folders):
    if not target_folders:
        return True
    normalized_path = file_path.strip("/")
    return any(
        normalized_path == target_folder or normalized_path.startswith(f"{target_folder}/")
        for target_folder in target_folders
    )


def _suggestion_key(
    file_path: str,
    function_name: str,
    block_type: str,
    line_number: int,
    language: str,
):
    return (file_path, function_name, block_type, line_number, language)


def _suggestion_fuzzy_key(
    file_path: str,
    function_name: str,
    block_type: str,
    language: str,
):
    return (file_path, function_name, block_type, language)


def _load_reusable_suggestions(repo_path: str, provider: str, branch: str) -> dict:
    latest_run_dir = find_latest_repo_run_dir(repo_path, provider)
    if not latest_run_dir:
        return {}
    repo_run_dirs = sorted(
        [
            os.path.join(os.path.dirname(latest_run_dir), entry)
            for entry in os.listdir(os.path.dirname(latest_run_dir))
            if entry.startswith("app_")
        ],
        reverse=True,
    )
    for run_dir in repo_run_dirs:
        suggestions_path = os.path.join(run_dir, "suggested_docstrings.json")
        if not os.path.exists(suggestions_path):
            continue
        with open(suggestions_path, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
        if payload.get("repo_path") != repo_path or payload.get("branch") != branch:
            continue
        suggestions = {"exact": {}, "fuzzy": {}}
        for suggestion in payload.get("suggestions", []):
            exact_key = _suggestion_key(
                suggestion.get("file_path", ""),
                suggestion.get("function_name", ""),
                suggestion.get("block_type", ""),
                suggestion.get("line_number", 0),
                suggestion.get("language", ""),
            )
            fuzzy_key = _suggestion_fuzzy_key(
                suggestion.get("file_path", ""),
                suggestion.get("function_name", ""),
                suggestion.get("block_type", ""),
                suggestion.get("language", ""),
            )
            generated_docstring = suggestion.get("generated_docstring")
            suggestions["exact"][exact_key] = generated_docstring
            suggestions["fuzzy"].setdefault(fuzzy_key, generated_docstring)
        return suggestions
    return {"exact": {}, "fuzzy": {}}


def _write_suggested_docstring_report(suggested_file: str, suggestions: list[dict]) -> None:
    Path(suggested_file).parent.mkdir(parents=True, exist_ok=True)
    with open(suggested_file, "w", encoding="utf-8") as file_handle:
        for suggestion in suggestions:
            file_handle.write(
                "\n# File: "
                f"{suggestion.get('file_name', '')}, Path: {suggestion.get('file_path', '')}, "
                f"Function: {suggestion.get('function_name', '')}, "
                f"Line: {suggestion.get('line_number', 0)}\n"
            )
            file_handle.write(
                f"{format_docstring_for_language(suggestion['generated_docstring'], suggestion['language'])}\n"
            )
            file_handle.write(f"{'-' * 100}\n")


def analyze_repo(
    provider,
    repo_url,
    token,
    branch,
    target_folders=None,
    model=None,
    reuse_doc=False,
):
    """
    Analyze a repository for source files missing docstring.

    Description:
        This function fetches the repository tree, detects the tech stack, and checks each file
        for missing or present docstring. It returns lists of files and items
        missing docstring and those with docstring.

    Args:
        provider (str): The git provider name (e.g., 'github', 'gitlab').
        repo_url (str): The URL of the repository.
        token (str): The authentication token for accessing the repository.
        branch (str): The branch name to analyze.
        target_folders (list[str] | None): Optional repository folders to limit analysis to.
        model (str | None): Optional OpenAI model override for generated docstrings.

    Returns:
        tuple:
            - files_missing_docstring (list): List of dicts for files/items missing docstring.
            - file_present_docstring (list): List of dicts for files/items with docstring.
    """
    block_analysis_list = []
    normalized_target_folders = _normalize_target_folders(target_folders)
    supported_files_found = 0
    supported_files_in_scope = 0
    unreadable_supported_files = 0
    logger.info(f"Analyzing repo: provider={provider}, url={repo_url}, branch={branch}")
    if normalized_target_folders:
        logger.info("Limiting analysis to target folders: %s", normalized_target_folders)

    # Extract repo path from URL
    repo_path = extract_repo_path(repo_url, provider)
    logger.info(f"Extracted repo path: {repo_path}")
    existing_suggestions = {"exact": {}, "fuzzy": {}}
    if reuse_doc:
        existing_suggestions = _load_reusable_suggestions(repo_path, provider, branch)
    else:
        clear_repo_output_history(repo_path, provider)

    # Keep each repository analysis isolated under logs/<provider>/<repo>/app_<timestamp>/.
    bind_repo_run_log_dir(repo_path, provider)
    output_dir = build_repo_output_dir(repo_path, provider)
    suggested_file = build_repo_output_file(repo_path, provider, "suggested_docstring.txt")
    suggested_json_file = build_repo_output_file(repo_path, provider, "suggested_docstrings.json")
    block_analysis_file = build_repo_output_file(repo_path, provider, "block_analysis.csv")
    if not reuse_doc and os.path.exists(suggested_file):
        os.remove(suggested_file)
        logger.debug(f"Deleted {suggested_file}")
    if not reuse_doc and os.path.exists(suggested_json_file):
        os.remove(suggested_json_file)
        logger.debug(f"Deleted {suggested_json_file}")
    if not reuse_doc and os.path.exists(block_analysis_file):
        os.remove(block_analysis_file)
        logger.debug(f"Deleted {block_analysis_file}")

    # Fetch repo tree
    try:
        file_list = fetch_repo_tree(repo_path, token, branch=branch, provider=provider.lower())
        logger.info(f"Fetched repo tree, {len(file_list)} files found.")
    except RepositoryAccessError as exc:
        logger.error("Repository access failed: %s", exc)
        raise RepoAnalysisError(str(exc), status_code=exc.status_code or 404) from exc
    except Exception as e:
        logger.error(f"Error fetching repo tree: {e}")
        raise
    # tech = detect_tech_stack(file_list)

    # Determine file type key for provider
    file_type_key = "blob" if provider.lower() == "gitlab" else "file"

    for file in file_list:
        # To make sure item is a file not a directory
        if file.get("type", "") != file_type_key:
            continue
        file_name = file.get("name", "")
        language = None
        if file_name.endswith((".py", ".pyw")):
            language = "python"
        elif file_name.endswith((".js", ".jsx")):
            language = "javascript"
        elif file_name.endswith((".ts", ".tsx")):
            language = "typescript"
        elif file_name.endswith((".m", ".mat")):
            language = "matlab"
        # File type not supported
        else:
            logger.warning(
                f"File {file_name} is not supported for docstring validation. Skipping..."
            )
            continue
        supported_files_found += 1
        file_path = file.get("path", "")
        if not _file_matches_target_folders(file_path, normalized_target_folders):
            logger.debug(
                "Skipping %s because it is outside the requested target folders.",
                file_path,
            )
            continue
        supported_files_in_scope += 1

        # fetch content based on provider
        if provider.lower() == "github":
            content = fetch_content_from_github(repo_path, branch, file_path, token)
        elif provider.lower() == "gitlab":
            content = fetch_content_from_gitlab(repo_path, branch, file_path, token)
        else:
            content = ""
        if content is None or content == "":
            logger.warning(f"Empty file {file_name}. Cannot validate docstring.")
            unreadable_supported_files += 1
            continue

        # Create a code blocks in the file to analyze
        extractor = GenericCodeBlockExtractor(content, file_name)
        code_blocks = extractor.code_block_extractor()
        # If no code blocks found, check for module-level docstring
        if not code_blocks:
            logger.warning(
                f"No code blocks found in {file_name}. Checking for module-level docstring..."
            )
            module_docstring = analyze_docstring_in_module(content, language)
            if module_docstring:
                block_analysis = {
                    "file_name": file_name,
                    "file_path": file_path,
                    "total_blocks": 1,
                    "blocks_with_docstring": 1,
                    "blocks_without_docstring": 0,
                    "docstring_analysis": [
                        {
                            "function_name": f"Module: {file_name}",
                            "block_type": "module",
                            "docstring_content": module_docstring,
                            "missing_docstring": False,
                            "block_number": 1,
                            "language": language,
                            "line_number": 1,
                        }
                    ],
                }
            else:
                # No module docstring found either
                block_analysis = {
                    "file_name": file_name,
                    "file_path": file_path,
                    "total_blocks": 1,
                    "blocks_with_docstring": 0,
                    "blocks_without_docstring": 1,
                    "docstring_analysis": [
                        {
                            "function_name": f"Module: {file_name}",
                            "block_type": "module",
                            "docstring_content": None,
                            "missing_docstring": True,
                            "block_number": 1,
                            "language": language,
                            "line_number": 1,
                        }
                    ],
                }
                suggestion_key = _suggestion_key(
                    file_path,
                    f"Module: {file_name}",
                    "module",
                    1,
                    language,
                )
                fuzzy_suggestion_key = _suggestion_fuzzy_key(
                    file_path,
                    f"Module: {file_name}",
                    "module",
                    language,
                )
                generated_docstring = existing_suggestions["exact"].get(suggestion_key)
                docstring_source = None
                if generated_docstring:
                    docstring_source = "exact-cache"
                if not generated_docstring:
                    generated_docstring = existing_suggestions["fuzzy"].get(fuzzy_suggestion_key)
                    if generated_docstring:
                        docstring_source = "fuzzy-cache"
                if not generated_docstring:
                    generated_docstring = generate_docstring_with_openai(
                        content,
                        language,
                        model=model,
                    )
                    if generated_docstring:
                        docstring_source = "openai"

                if generated_docstring:
                    block_analysis["docstring_analysis"][0]["generated_docstring"] = (
                        generated_docstring
                    )
                    if docstring_source == "openai":
                        logger.info("Generated Docstring:")
                    elif docstring_source == "exact-cache":
                        logger.info("Reused cached docstring (exact match):")
                    else:
                        logger.info("Reused cached docstring (line number changed):")
                    logger.info(format_docstring_for_language(generated_docstring, language))
                    suggested_file = os.path.join(output_dir, "suggested_docstring.txt")
                    doc_info = block_analysis["docstring_analysis"][0]
                    with open(suggested_file, "a") as f:
                        f.write(
                            "\n# File: "
                            f"{file_name}, Path: {file_path}, Function: "
                            f"{doc_info['function_name']}, Line: {doc_info['line_number']}\n"
                        )
                        f.write(f"{format_docstring_for_language(generated_docstring, language)}\n")
                        f.write(f"{'-' * 100}\n")
                else:
                    logger.warning("Docstring generation failed.")

            block_analysis_list.append(block_analysis)
            continue

        logger.info(f"Analyzing {file_name} with {len(code_blocks)} code blocks.")
        block_analysis = analyze_docstring_in_blocks(
            code_blocks,
            file_name=file_name,
            file_path=file_path,
            language=language,
            suggested_file=suggested_file,
            model=model,
            existing_suggestions=existing_suggestions,
        )
        block_analysis_list.append(block_analysis)

    # save details in csv
    output_path = os.path.join(output_dir, "block_analysis.csv")

    # save details in csv
    flattened_data = []

    for block_analysis in block_analysis_list:
        # Extract main keys
        file_name = block_analysis.get("file_name", "")
        file_path = block_analysis.get("file_path", "")

        # Extract nested dictionary data from docstring_analysis
        docstring_analysis = block_analysis.get("docstring_analysis", [])
        for analysis in docstring_analysis:
            row = {
                "file_name": file_name,
                "file_path": file_path,
                "function_name": analysis.get("function_name", ""),
                "block_type": analysis.get("block_type", ""),
                "missing_docstring": analysis.get("missing_docstring", True),
                "language": analysis.get("language", ""),
                "line_number": analysis.get("line_number", 0),
            }
            flattened_data.append(row)

    # Create DataFrame with proper columns (empty if no data)
    columns = [
        "file_name",
        "file_path",
        "function_name",
        "block_type",
        "missing_docstring",
        "language",
        "line_number",
    ]
    df = pd.DataFrame(flattened_data, columns=columns)
    df.to_csv(output_path, index=False)

    suggestions = []
    for block_analysis in block_analysis_list:
        file_path = block_analysis.get("file_path", "")
        for analysis in block_analysis.get("docstring_analysis", []):
            generated_docstring = analysis.get("generated_docstring")
            if not generated_docstring:
                continue
            suggestions.append(
                {
                    "file_path": file_path,
                    "file_name": block_analysis.get("file_name", ""),
                    "function_name": analysis.get("function_name", ""),
                    "block_type": analysis.get("block_type", ""),
                    "line_number": analysis.get("line_number", 0),
                    "language": analysis.get("language", ""),
                    "generated_docstring": generated_docstring,
                }
            )

    _write_suggested_docstring_report(suggested_file, suggestions)

    with open(suggested_json_file, "w", encoding="utf-8") as file_handle:
        json.dump(
            {
                "provider": provider.lower(),
                "repo_path": repo_path,
                "branch": branch,
                "suggestions": suggestions,
            },
            file_handle,
            indent=2,
        )

    if not block_analysis_list:
        logger.warning("No files with docstring analysis found.")
        if supported_files_found == 0:
            raise RepoAnalysisError(
                "Repository was reachable, but no supported source files were found. "
                "Auto-Doc currently analyzes .py, .pyw, .js, .jsx, .ts, .tsx, .m, and .mat files.",
                status_code=404,
            )
        if normalized_target_folders and supported_files_in_scope == 0:
            raise RepoAnalysisError(
                "Repository was reachable, but none of the supported source files matched "
                f"target_folders={normalized_target_folders}.",
                status_code=404,
            )
        if supported_files_in_scope > 0 and unreadable_supported_files == supported_files_in_scope:
            raise RepoAnalysisError(
                "Repository tree was found, but Auto-Doc could not read any matching source file "
                f"contents on branch '{branch}'. Check that the branch exists and that the token "
                "can read file contents for this repository or fork.",
                status_code=403,
            )
        raise RepoAnalysisError(
            "Repository was reachable, but Auto-Doc could not extract any analyzable code blocks "
            f"from the supported files on branch '{branch}'.",
            status_code=422,
        )
    return output_path, block_analysis_list
