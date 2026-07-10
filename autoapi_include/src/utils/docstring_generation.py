import json
import os
import shlex
import subprocess
import textwrap
import time
from typing import Optional

import openai
from dotenv import load_dotenv
from tqdm import tqdm

from config.log_config import get_logger

logger = get_logger(__name__)
load_dotenv()

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_CODEX_COMMAND = "codex exec --skip-git-repo-check -"
DEFAULT_CLAUDE_COMMAND = "claude -p --output-format text"
CLI_TIMEOUT_SECONDS = 120
SUPPORTED_AI_PROVIDERS = {"openai", "codex", "claude"}


def _normalize_ai_provider(provider: str | None) -> str | None:
    if not provider:
        return None
    normalized = provider.strip().lower().replace("-", "_")
    if normalized in {"openai", "openai_api", "gpt"}:
        return "openai"
    if normalized in {"codex", "codex_cli"}:
        return "codex"
    if normalized in {"claude", "claude_cli"}:
        return "claude"
    return normalized


def _split_provider_model(model: str | None) -> tuple[str | None, str | None]:
    if not model:
        return None, None
    raw_model = model.strip()
    if ":" not in raw_model:
        return None, raw_model or None
    provider, provider_model = raw_model.split(":", 1)
    normalized_provider = _normalize_ai_provider(provider)
    if normalized_provider in SUPPORTED_AI_PROVIDERS:
        return normalized_provider, provider_model.strip() or None
    return None, raw_model


def resolve_ai_provider(model: str | None = None, api_key: str | None = None) -> tuple[str, str | None]:
    """
    Resolve the AI provider and model from explicit model prefixes, environment, and API key state.

    Model values may be prefixed with ``openai:``, ``codex:``, or ``claude:``. Without a prefix,
    ``AUTODOC_AI_PROVIDER`` chooses the backend. If OpenAI is not configured, the CLI fallback is
    used so local Codex or Claude authentication can handle generation.
    """
    prefixed_provider, requested_model = _split_provider_model(model)
    configured_provider = _normalize_ai_provider(os.getenv("AUTODOC_AI_PROVIDER"))
    configured_cli_provider = _normalize_ai_provider(os.getenv("AUTODOC_AI_CLI_PROVIDER")) or "codex"
    configured_model = os.getenv("AUTODOC_AI_MODEL")
    openai_key = api_key or os.getenv("OPENAI_API_KEY")

    provider = prefixed_provider or configured_provider
    if provider is None:
        provider = "openai" if openai_key else configured_cli_provider
    if provider not in SUPPORTED_AI_PROVIDERS:
        raise ValueError(
            "Unsupported AI provider. Use 'openai', 'codex', or 'claude' "
            "via AUTODOC_AI_PROVIDER or a model prefix such as 'claude:sonnet'."
        )

    if provider == "openai":
        return provider, requested_model or configured_model or DEFAULT_OPENAI_MODEL

    if prefixed_provider:
        return provider, requested_model
    if configured_model:
        return provider, configured_model
    return provider, None


def configure_openai(api_key: str | None = None):
    """
    Configure OpenAI API with the provided API key.

    Args:
        api_key (str, optional): OpenAI API key. If None, reads from environment.
    """
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OpenAI API key not provided. Set OPENAI_API_KEY environment variable or pass api_key parameter."
        )
    openai.api_key = api_key


def _clean_json_block(response_text: str) -> str:
    """
    Clean JSON response from ChatGPT response.

    Args:
        response_text (str): Raw response text from API.

    Returns:
        str: Cleaned JSON string.
    """
    # Remove markdown code blocks if present
    if "```json" in response_text:
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        response_text = response_text[start:end].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        response_text = response_text[start:end].strip()

    return response_text.strip()


def create_docstring_prompt(code: str, language: str | None = "python") -> str:
    """
    Create a prompt for ChatGPT to generate a concise docstring.

    Args:
        code (str): The code block to Analyse.
        language (str): Programming language of the code.

    Returns:
        str: Formatted prompt for docstring generation.
    """
    selected_language = language or "python"
    prompt = f"""
Generate a concise docstring for the following {selected_language} code.
The docstring should be 4-5 lines maximum and include:

1. A brief description (1-2 lines maximum)
2. Args section with parameter types and descriptions
3. Returns section with return type and description

Follow {selected_language} docstring conventions. Be concise and clear.

Return the response as a JSON object with this structure:
{{
    "docstring": "the generated docstring content"
}}

Code to Analyse:
```{selected_language}
{code}
```

Generate only the JSON response without any additional text or markdown formatting.
"""
    return prompt


def create_openai_docstring_prompt(code: str, language: str | None = "python") -> str:
    return create_docstring_prompt(code, language)


def _extract_json_object(response_text: str) -> dict:
    cleaned = _clean_json_block(response_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _build_cli_command(provider: str, model: str | None) -> list[str]:
    if provider == "codex":
        template = os.getenv("AUTODOC_CODEX_COMMAND", DEFAULT_CODEX_COMMAND)
    elif provider == "claude":
        template = os.getenv("AUTODOC_CLAUDE_COMMAND", DEFAULT_CLAUDE_COMMAND)
    else:
        raise ValueError(f"Unsupported CLI AI provider: {provider}")

    command = shlex.split(template)
    if model:
        model_args = ["--model", model]
        if command and command[-1] == "-":
            command[-1:-1] = model_args
        else:
            command.extend(model_args)
    return command


def _generate_docstring_with_cli(provider: str, prompt: str, model: str | None = None) -> Optional[str]:
    command = _build_cli_command(provider, model)
    try:
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("AUTODOC_AI_CLI_TIMEOUT", str(CLI_TIMEOUT_SECONDS))),
        )
    except FileNotFoundError:
        logger.error("%s CLI is not installed or is not available on PATH.", provider)
        return None
    except subprocess.TimeoutExpired:
        logger.error("%s CLI timed out while generating a docstring.", provider)
        return None

    if result.returncode != 0:
        stderr = _trim_cli_error(result.stderr or "")
        logger.error("%s CLI docstring generation failed: %s", provider, stderr or "no stderr")
        return None

    try:
        response_json = _extract_json_object(result.stdout or "")
        return response_json.get("docstring", "")
    except Exception as exc:
        logger.error("Error parsing %s CLI docstring response: %s", provider, exc)
        return None


def _trim_cli_error(stderr: str, limit: int = 1200) -> str:
    """Keep CLI error logs useful without dumping full prompts or source files."""
    cleaned_lines = []
    skipping_prompt = False
    for line in stderr.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "user":
            skipping_prompt = True
            continue
        if skipping_prompt and not stripped.lower().startswith(("error", "warning")):
            continue
        if skipping_prompt:
            skipping_prompt = False
        if stripped == "--------":
            continue
        metadata_prefixes = (
            "workdir:",
            "model:",
            "provider:",
            "approval:",
            "sandbox:",
            "reasoning ",
            "session id:",
        )
        if stripped.startswith(metadata_prefixes):
            continue
        cleaned_lines.append(stripped)
    cleaned = "\n".join(cleaned_lines).strip()
    if len(cleaned) > limit:
        return f"{cleaned[:limit]}... [truncated]"
    return cleaned


def generate_docstring(
    code: str,
    language: str | None = "python",
    api_key: str | None = None,
    model: str | None = DEFAULT_OPENAI_MODEL,
) -> Optional[str]:
    """
    Generate a concise docstring for the given code using the configured AI backend.

    Args:
        code (str): The code block for which to generate docstring.
        language (str): Programming language of the code (default: "python").
        api_key (str, optional): OpenAI API key, used only for the OpenAI backend.
        model (str): Optional model name. Prefix with openai:, codex:, or claude: to select a provider.

    Returns:
        str: Generated docstring or None if generation fails.
    """
    try:
        selected_language = language or "python"
        provider, selected_model = resolve_ai_provider(model=model, api_key=api_key)
        prompt = create_docstring_prompt(code, selected_language)
        if provider in {"codex", "claude"}:
            return _generate_docstring_with_cli(provider, prompt, selected_model)

        configure_openai(api_key)
        selected_model = selected_model or DEFAULT_OPENAI_MODEL
        response = openai.chat.completions.create(
            model=selected_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant for generating code docstring.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=512,
        )
        if response and response.choices:
            response_text = (response.choices[0].message.content or "").strip()
            response_json = _extract_json_object(response_text)
            return response_json.get("docstring", "")
        else:
            logger.warning("No response from OpenAI API")
            return None
    except Exception as e:
        logger.error(f"Error generating docstring: {e}")
        return None


def generate_docstring_with_openai(
    code: str,
    language: str | None = "python",
    api_key: str | None = None,
    model: str | None = DEFAULT_OPENAI_MODEL,
) -> Optional[str]:
    """Backward-compatible wrapper for callers/tests that still use the old OpenAI-specific name."""
    return generate_docstring(code, language, api_key=api_key, model=model)


def generate_docstrings_for_code_blocks_openai(
    code_blocks_data: list, language: str = "python", model: str = DEFAULT_OPENAI_MODEL
) -> list:
    """
    Generate docstrings for multiple code blocks using the configured AI backend.

    Args:
        code_blocks_data (list): List of dictionaries containing code block information.
        language (str): Programming language of the code blocks.
        model (str): Optional AI model name or provider-prefixed model.

    Returns:
        list: Updated list with generated docstrings.
    """
    for block in code_blocks_data:
        block["generated_docstring"] = "N/A"

    for i in tqdm(range(len(code_blocks_data)), desc="Generating docstrings"):
        code_block = code_blocks_data[i].get("code", "")
        function_name = code_blocks_data[i].get("function_name", f"Block_{i}")

        if not code_block.strip():
            logger.warning(f"Skipping empty code block for {function_name}")
            continue

        try:
            docstring = generate_docstring(code_block, language, model=model)
            if docstring:
                code_blocks_data[i]["generated_docstring"] = docstring
            else:
                code_blocks_data[i]["generated_docstring"] = "Failed to generate"
            time.sleep(1.5)
        except Exception as e:
            logger.error(f"Error processing code block {i}: {function_name}")
            logger.error(f"Exception: {e}")
            code_blocks_data[i]["generated_docstring"] = f"Error: {str(e)}"

    return code_blocks_data


def format_docstring_for_language(docstring: str, language: str | None) -> str:
    """
    Format the generated docstring according to language conventions.

    Args:
        docstring (str): Raw docstring content.
        language (str): Programming language.

    Returns:
        str: Formatted docstring.
    """
    if not docstring or docstring == "N/A":
        return docstring

    docstring = _strip_docstring_wrapper(docstring)

    if language is None:
        return docstring

    if language.lower() == "python":
        # Python triple-quote format
        lines = []
        for line in docstring.split("\n"):
            stripped = line.rstrip()
            if not stripped:
                lines.append("")
                continue
            leading_spaces = stripped[: len(stripped) - len(stripped.lstrip())]
            lines.extend(textwrap.wrap(stripped, width=96, subsequent_indent=leading_spaces) or [""])
        if any(line.startswith((" ", "\t")) for line in lines):
            lines.append("")
        indented_lines = ["    " + line if line.strip() else "" for line in lines]
        return f'    """\n{chr(10).join(indented_lines)}\n    """'

    elif language.lower() in ["javascript", "typescript"]:
        # JSDoc format
        lines = docstring.split("\n")
        formatted_lines = ["    /**"] + [f"     * {line}" for line in lines] + ["     */"]
        return "\n".join(formatted_lines)

    elif language.lower() == "matlab":
        # MATLAB comment format
        lines = docstring.split("\n")
        formatted_lines = [f"% {line}" for line in lines]
        return "\n".join(formatted_lines)

    else:
        return docstring


def _strip_docstring_wrapper(docstring: str) -> str:
    """
    Remove surrounding quotes from a docstring.

    Args:
        docstring (str): The docstring to clean.

    Returns:
        str: The cleaned docstring without surrounding quotes.

    """
    cleaned = docstring.strip()
    quote_pairs = (('"""', '"""'), ("'''", "'''"), ("/**", "*/"))
    for opening, closing in quote_pairs:
        if cleaned.startswith(opening) and cleaned.endswith(closing):
            return cleaned[len(opening) : -len(closing)].strip()
    return cleaned
