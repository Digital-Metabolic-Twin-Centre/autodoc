import textwrap
from pathlib import Path

from services.docstring_pr_services import (
    PatchedPythonFile,
    _run_ruff_on_patched_files,
    _suggestion_generator,
    patch_python_docstrings,
)


def fake_generator(insertion) -> str:
    return "Generated documentation."


def quoted_generator(insertion) -> str:
    return '"""Retrieve a logger instance with the specified name."""'


def test_patch_python_docstrings_inserts_function_docstring():
    source = textwrap.dedent(
        """
        def add(left, right):
            return left + right
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=fake_generator)

    assert patched.inserted[0].name == "add"
    assert '    """Generated documentation."""' in patched.content
    assert "    return left + right" in patched.content


def test_patch_python_docstrings_preserves_existing_docstring():
    source = textwrap.dedent(
        '''
        def documented():
            """Already documented."""
            return True
        '''
    ).lstrip()

    patched = patch_python_docstrings(source, generator=fake_generator)

    assert patched.inserted == []
    assert patched.content == source


def test_patch_python_docstrings_inserts_class_and_method_docstrings():
    source = textwrap.dedent(
        """
        class Thing:
            def name(self):
                return "thing"
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=fake_generator, max_docstrings=3)

    assert len(patched.inserted) == 2
    assert '    """Generated documentation."""' in patched.content
    assert '        """Generated documentation."""' in patched.content


def test_patch_python_docstrings_strips_generated_triple_quote_wrapper():
    source = textwrap.dedent(
        """
        def get_logger(name):
            return logging.getLogger(name)
        """
    ).lstrip()

    patched = patch_python_docstrings(source, generator=quoted_generator)

    assert '    """Retrieve a logger instance with the specified name."""' in patched.content
    assert '    """\n    """Retrieve' not in patched.content


def test_patch_python_docstrings_wraps_long_generated_lines():
    source = textwrap.dedent(
        """
        def extract():
            return {}
        """
    ).lstrip()
    long_docstring = (
        "Returns:\n"
        "    dict: A dictionary containing the function code block and the ending line "
        "index, or None if not found."
    )

    patched = patch_python_docstrings(source, generator=lambda insertion: long_docstring)

    assert all(len(line) <= 100 for line in patched.content.splitlines())
    assert "        not found." in patched.content
    assert '\n    \n    """' in patched.content


def test_suggestion_generator_matches_by_name_and_kind():
    source = textwrap.dedent(
        """
        def add(left, right):
            return left + right
        """
    ).lstrip()

    patched = patch_python_docstrings(
        source,
        generator=_suggestion_generator(
            [
                {
                    "function_name": "add",
                    "block_type": "function",
                    "generated_docstring": "Add two values.",
                }
            ]
        ),
    )

    assert '    """Add two values."""' in patched.content


def test_run_ruff_on_patched_files_returns_cleaned_content(monkeypatch):
    def fake_run(command, cwd, capture_output, text, timeout):
        local_path = Path(command[-1])
        if "format" in command:
            local_path.write_text("def run():\n    return True\n", encoding="utf-8")

        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    monkeypatch.setattr("services.docstring_pr_services.subprocess.run", fake_run)

    cleaned = _run_ruff_on_patched_files(
        {"src/example.py": PatchedPythonFile(content="def run():\n return True\n", inserted=[])}
    )

    assert cleaned["src/example.py"].content == "def run():\n    return True\n"
