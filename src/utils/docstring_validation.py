import ast
import os
import re
from typing import Optional

from utils.docstring_generation import (
    generate_docstring_with_openai,
    format_docstring_for_language,
)
from config.log_config import get_logger

logger = get_logger(__name__)


def analyze_docstring_in_blocks(
    code_blocks: list,
    file_name: str = "unknown",
    file_path: str = "unknown",
    language: str = None,
) -> dict:
    """
    Analyzes code blocks to find docstring and identify missing ones.
    Supports multiple programming languages including Python, JavaScript/TypeScript and MATLAB.

    Args:
        code_blocks (list): List of code blocks extracted from a file
        file_name (str): Name of the file being analyzed
        language (str): Programming language of the code blocks

    Returns:
        dict: Analysis results with docstring information
    """

    results = {
        "file_name": file_name,
        "file_path": file_path,
        "total_blocks": len(code_blocks),
        "blocks_with_docstring": 0,
        "blocks_without_docstring": 0,
        "docstring_analysis": [],
    }

    def analyze_python_block(clean_code: str) -> dict:
        """Analyze Python code block for docstring"""
        analysis = {
            "function_name": "unknown",
            "block_type": "unknown",
            "docstring_content": None,
            "missing_docstring": True,
        }

        try:
            tree = ast.parse(clean_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis["function_name"] = node.name
                    analysis["block_type"] = "function"
                    docstring = ast.get_docstring(node)
                    if docstring:
                        analysis["docstring_content"] = docstring
                        analysis["missing_docstring"] = False
                    break
                elif isinstance(node, ast.AsyncFunctionDef):
                    analysis["function_name"] = node.name
                    analysis["block_type"] = "async_function"
                    docstring = ast.get_docstring(node)
                    if docstring:
                        analysis["docstring_content"] = docstring
                        analysis["missing_docstring"] = False
                    break
                elif isinstance(node, ast.ClassDef):
                    analysis["function_name"] = node.name
                    analysis["block_type"] = "class"
                    docstring = ast.get_docstring(node)
                    if docstring:
                        analysis["docstring_content"] = docstring
                        analysis["missing_docstring"] = False
                    break
        except SyntaxError:
            # Fallback to regex
            return analyze_with_regex(clean_code, "python")

        return analysis

    def analyze_with_regex(clean_code: str, language: str) -> dict:
        """Analyze code block using regex patterns for different languages"""
        analysis = {
            "function_name": "unknown",
            "block_type": "unknown",
            "docstring_content": None,
            "missing_docstring": True,
        }

        # Language-specific patterns
        patterns = {
            "python": {
                "function": r"def\s+(\w+)\s*\(",
                "class": r"class\s+(\w+)\s*[\(:]",
                "docstring": [r'"""(.*?)"""', r"'''(.*?)'''"],
            },
            "javascript": {
                # Add a pattern for method calls like document.addEventListener(
                "function": r"(?:function\s+(\w+)\s*\()|(?:([\w\.]+)\s*\.\s*(\w+)\s*\()",  # updated
                "class": r"class\s+(\w+)\s*{",
                "docstring": [r"/\*\*(.*?)\*/", r"//\s*(.*?)$"],
            },
            "typescript": {
                "function": r"(?:function\s+(\w+)\s*\()|(?:([\w\.]+)\s*\.\s*(\w+)\s*\()",
                "class": r"class\s+(\w+)\s*{",
                "docstring": [r"/\*\*(.*?)\*/", r"//\s*(.*?)$"],
            },
            "matlab": {
                "function": r"function\s+(?:.*=\s*)?(\w+)\s*\(",
                "class": r"classdef\s+(\w+)",
                "docstring": [r"%\s+(.*?)(?=\n\s*(?:%|\w))", r"%{(.*?)%}"],
            },
        }

        if language not in patterns:
            return analysis

        lang_patterns = patterns[language]

        # Find function/class name
        func_match = re.search(lang_patterns["function"], clean_code, re.MULTILINE)
        class_match = re.search(lang_patterns["class"], clean_code, re.MULTILINE)

        if func_match:
            # For JavaScript/TypeScript, handle method calls like document.addEventListener(
            if language in ["javascript", "typescript"]:
                if func_match.group(3):  # e.g., document.addEventListener(
                    analysis["function_name"] = func_match.group(3)
                    analysis["block_type"] = "function"
                elif func_match.group(1):  # function foo(
                    analysis["function_name"] = func_match.group(1)
                    analysis["block_type"] = "function"
                else:
                    analysis["function_name"] = "unknown"
                    analysis["block_type"] = "function"
            else:
                groups = func_match.groups()
                analysis["function_name"] = next((g for g in groups if g), "unknown")
                analysis["block_type"] = "function"
        elif class_match:
            groups = class_match.groups()
            analysis["function_name"] = next((g for g in groups if g), "unknown")
            analysis["block_type"] = "class"

        # Look for docstring
        for docstring_pattern in lang_patterns["docstring"]:
            docstring_match = re.search(docstring_pattern, clean_code, re.DOTALL | re.MULTILINE)
            if docstring_match:
                analysis["docstring_content"] = docstring_match.group(1).strip()
                analysis["missing_docstring"] = False
                break

        return analysis

    # Analyze each code block
    for i, block in enumerate(code_blocks, 1):
        # Extract the actual code (remove header/footer comments)
        lines = block.split("\n")
        start_line_number = None
        code_lines = []

        for line in lines:
            if not line.strip().startswith("# --- Code Block"):
                code_lines.append(line)
            if "--- Code Block starts at line" in line:
                match = re.search(r"starts at line (\d+)", line)
                if match:
                    start_line_number = int(match.group(1))
                else:
                    start_line_number = 0

        clean_code = "\n".join(code_lines)
        # language = detect_language(clean_code, file_name)

        # Analyze based on detected language
        if language == "python":
            block_analysis = analyze_python_block(clean_code)
        else:
            block_analysis = analyze_with_regex(clean_code, language)

        block_analysis["block_number"] = i
        block_analysis["language"] = language
        block_analysis["line_number"] = start_line_number if start_line_number is not None else 0

        # Update counters
        if block_analysis["missing_docstring"] == False:
            results["blocks_with_docstring"] += 1
        else:
            results["blocks_without_docstring"] += 1
            generated_docstring = generate_docstring_with_openai(clean_code, language)
            if generated_docstring:
                logger.info("Generated Docstring:")
                logger.info(format_docstring_for_language(generated_docstring, language))
                # Save the generated docstring to a suggested docstring file
                output_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "files"
                )
                os.makedirs(output_dir, exist_ok=True)
                suggested_file = os.path.join(output_dir, "suggested_docstring.txt")
                # suggested_file = f"suggested_docstring"
                with open(suggested_file, "a") as f:
                    # Add a column with filename, file path, function name, and line number
                    f.write(
                        f"\n# File: {file_name}, Path: {file_path}, Function: {block_analysis['function_name']}, Line: {block_analysis['line_number']}\n"
                    )
                    f.write(f"\n{format_docstring_for_language(generated_docstring, language)}\n")
                    f.write(f"\n{'-' * 100}\n")
            else:
                logger.warning("Docstring generation failed.")

        results["docstring_analysis"].append(block_analysis)

    return results


def analyze_docstring_in_module(content: str, language: str = None) -> Optional[str]:
    """
    Extract module-level docstring from file content.

    Args:
        content (str): The file content
        language (str): The programming language

    Returns:
        str or None: The module docstring if found, None otherwise
    """
    if language == "python":
        try:
            # Parse the Python code using AST
            tree = ast.parse(content)
            # Get the first statement if it's a string literal
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                return tree.body[0].value.value.strip()
        except SyntaxError:
            # If AST parsing fails, try regex fallback
            pass

        # Fallback regex method for Python
        pattern = r'^[\s]*["\'][\"\'][\"\']([^"\']*?)[\"\'][\"\'][\"\']|^[\s]*["\']([^"\']*?)["\']'
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            docstring_content = (match.group(1) or match.group(2)).strip()

    elif language in ["javascript", "typescript"]:
        # Look for JSDoc style comments at the beginning
        pattern = r"^\s*/\*\*\s*\n(.*?)\n\s*\*/"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            # Clean up the JSDoc comment
            docstring = match.group(1)
            lines = docstring.split("\n")
            cleaned_lines = []
            for line in lines:
                line = re.sub(r"^\s*\*\s?", "", line)
                cleaned_lines.append(line)
            return "\n".join(cleaned_lines).strip()

    elif language == "matlab":
        # Look for MATLAB style comments at the beginning
        lines = content.split("\n")
        docstring_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith("%"):
                docstring_lines.append(line[1:].strip())
            elif line and not line.startswith("%"):
                break
        if docstring_lines:
            return "\n".join(docstring_lines).strip()

    return None
