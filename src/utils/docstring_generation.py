import json
import os
import textwrap
import time
from typing import Optional

import openai
from dotenv import load_dotenv
from tqdm import tqdm

from config.log_config import get_logger

logger = get_logger(__name__)
load_dotenv()


def configure_openai(api_key: str = None):
    """
    Configure OpenAI API with the provided API key.

    Args:
        api_key (str, optional): OpenAI API key. If None, reads from environment.
    """
    if api_key is None:
        api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OpenAI API key not provided. Set OPENAI_API_KEY environment "
            "variable or pass api_key parameter."
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


def create_openai_docstring_prompt(code: str, language: str = "python") -> str:
    """
    Create a prompt for ChatGPT to generate a concise docstring.

    Args:
        code (str): The code block to analyze.
        language (str): Programming language of the code.

    Returns:
        str: Formatted prompt for docstring generation.
    """
    prompt = f"""
Generate a concise docstring for the following {language} code.
The docstring should be 4-5 lines maximum and include:

1. A brief description (1-2 lines maximum)
2. Args section with parameter types and descriptions
3. Returns section with return type and description

Follow {language} docstring conventions. Be concise and clear.

Return the response as a JSON object with this structure:
{{
    "docstring": "the generated docstring content"
}}

Code to analyze:
```{language}
{code}
```

Generate only the JSON response without any additional text or markdown formatting.
"""
    return prompt


def generate_docstring_with_openai(
    code: str, language: str = "python", api_key: str = None, model: str = "gpt-4o-mini"
) -> Optional[str]:
    """
    Generate a concise docstring for the given code using OpenAI ChatGPT.

    Args:
        code (str): The code block for which to generate docstring.
        language (str): Programming language of the code (default: "python").
        api_key (str, optional): OpenAI API key.
        model (str): OpenAI model name.

    Returns:
        str: Generated docstring or None if generation fails.
    """
    try:
        configure_openai(api_key)
        prompt = create_openai_docstring_prompt(code, language)
        response = openai.chat.completions.create(
            model=model,
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
            response_text = response.choices[0].message.content.strip()
            response_text = _clean_json_block(response_text)
            response_json = json.loads(response_text)
            return response_json.get("docstring", "")
        else:
            logger.warning("No response from OpenAI API")
            return None
    except Exception as e:
        logger.error(f"Error generating docstring with OpenAI: {e}")
        return None


def generate_docstrings_for_code_blocks_openai(
    code_blocks_data: list, language: str = "python", model: str = "gpt-3.5-turbo"
) -> list:
    """
    Generate docstrings for multiple code blocks using OpenAI ChatGPT.

    Args:
        code_blocks_data (list): List of dictionaries containing code block information.
        language (str): Programming language of the code blocks.
        model (str): OpenAI model name.

    Returns:
        list: Updated list with generated docstrings.
    """
    for block in code_blocks_data:
        block["generated_docstring"] = "N/A"

    for i in tqdm(range(len(code_blocks_data)), desc="Generating docstrings (OpenAI)"):
        code_block = code_blocks_data[i].get("code", "")
        function_name = code_blocks_data[i].get("function_name", f"Block_{i}")

        if not code_block.strip():
            logger.warning(f"Skipping empty code block for {function_name}")
            continue

        try:
            docstring = generate_docstring_with_openai(code_block, language, model=model)
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


def format_docstring_for_language(docstring: str, language: str) -> str:
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

    if language.lower() == "python":
        # Python triple-quote format
        lines = []
        for line in docstring.split("\n"):
            stripped = line.rstrip()
            if not stripped:
                lines.append("")
                continue
            leading_spaces = stripped[: len(stripped) - len(stripped.lstrip())]
            lines.extend(
                textwrap.wrap(stripped, width=96, subsequent_indent=leading_spaces) or [""]
            )
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
    cleaned = docstring.strip()
    quote_pairs = (('"""', '"""'), ("'''", "'''"), ("/**", "*/"))
    for opening, closing in quote_pairs:
        if cleaned.startswith(opening) and cleaned.endswith(closing):
            return cleaned[len(opening) : -len(closing)].strip()
    return cleaned
