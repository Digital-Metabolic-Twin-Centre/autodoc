import textwrap

from services.docstring_pr_services import patch_python_docstrings


def fake_generator(code: str, language: str) -> str:
    return "Generated documentation."


def quoted_generator(code: str, language: str) -> str:
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
