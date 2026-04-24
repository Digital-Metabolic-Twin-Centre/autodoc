from utils.docstring_generation import format_docstring_for_language


def test_format_python_docstring_strips_triple_quote_wrapper():
    formatted = format_docstring_for_language(
        '"""Create or update a file.\n\nArgs:\n    path (str): File path."""',
        "python",
    )

    assert formatted.startswith('    """\n    Create or update a file.')
    assert '    """\n    """Create' not in formatted
    assert formatted.endswith('    """')


def test_format_python_docstring_keeps_plain_docstring_content():
    formatted = format_docstring_for_language("Create or update a file.", "python")

    assert formatted == '    """\n    Create or update a file.\n    """'
