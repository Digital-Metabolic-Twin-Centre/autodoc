from utils.code_block_extraction import GenericCodeBlockExtractor


def test_python_code_block_extractor_finds_top_level_blocks():
    content = '''
def first():
    """doc"""
    return 1


class Sample:
    def method(self):
        return 2
'''.strip()

    extractor = GenericCodeBlockExtractor(content, "sample.py")

    blocks = extractor.code_block_extractor()

    assert len(blocks) == 3
    assert "def first()" in blocks[0]
    assert "class Sample:" in blocks[1]
    assert "def method(self)" in blocks[2]


def test_javascript_code_block_extractor_handles_curly_braces():
    content = """
function greet(name) {
  return `Hello ${name}`;
}
""".strip()

    extractor = GenericCodeBlockExtractor(content, "sample.js")

    blocks = extractor.code_block_extractor()

    assert len(blocks) == 1
    assert "function greet(name)" in blocks[0]


def test_matlab_source_extensions_are_detected_as_matlab():
    content = """
function result = add_one(value)
  result = value + 1;
end
""".strip()

    for file_name in ("sample.m", "sample.matlab"):
        extractor = GenericCodeBlockExtractor(content, file_name)

        assert extractor.language == "matlab"
        assert "function result = add_one(value)" in extractor.code_block_extractor()[0]


def test_unrecognized_extension_defaults_to_python():
    extractor = GenericCodeBlockExtractor("def foo():\n    pass\n", "sample.rb")

    assert extractor.language == "python"


def test_extract_single_block_returns_none_for_unhandled_language():
    extractor = GenericCodeBlockExtractor("anything", "sample.py")
    extractor.language = "unknown"

    assert extractor._extract_single_block(["anything"], 0, "anything") is None


def test_matlab_classdef_block_is_extracted():
    content = """
classdef Sample
  properties
    value
  end
end
""".strip()

    extractor = GenericCodeBlockExtractor(content, "sample.m")

    blocks = extractor.code_block_extractor()

    assert len(blocks) == 1
    assert "classdef Sample" in blocks[0]


def test_matlab_function_tracks_nested_control_flow_blocks():
    content = """
function y = foo(x)
if x > 0
    y = 1;
end
end
""".strip()

    extractor = GenericCodeBlockExtractor(content, "sample.m")

    blocks = extractor.code_block_extractor()

    assert len(blocks) == 1
    end_lines = [line for line in blocks[0].splitlines() if line.strip() == "end"]
    assert len(end_lines) == 2


def test_python_function_with_multiline_signature_is_extracted():
    content = """
def foo(a,
        b):
    return a + b
""".strip()

    extractor = GenericCodeBlockExtractor(content, "sample.py")

    blocks = extractor.code_block_extractor()

    assert len(blocks) == 1
    assert "def foo(a," in blocks[0]
    assert "b):" in blocks[0]


def test_extract_python_function_returns_none_when_signature_never_closes():
    extractor = GenericCodeBlockExtractor("def foo(a", "sample.py")

    result = extractor._extract_python_function_complete(["def foo(a"], 0)

    assert result is None


def test_python_class_with_blank_line_body_and_trailing_dedent():
    content = """
class Foo:
    def bar(self):
        pass

    def baz(self):
        pass

result = 1
""".strip()

    extractor = GenericCodeBlockExtractor(content, "sample.py")

    blocks = extractor.code_block_extractor()

    assert "class Foo:" in blocks[0]
    assert "def baz(self)" in blocks[0]


def test_javascript_block_with_opening_brace_on_next_line():
    content = """
function greet(name)
{
  return name;
}
""".strip()

    extractor = GenericCodeBlockExtractor(content, "sample.js")

    blocks = extractor.code_block_extractor()

    assert len(blocks) == 1
    assert "function greet(name)" in blocks[0]
    assert "{" in blocks[0]


def test_javascript_block_returns_none_when_declaration_is_last_line():
    extractor = GenericCodeBlockExtractor("function greet(name)", "sample.js")

    result = extractor._extract_curly_brace_block(["function greet(name)"], 0)

    assert result is None


def test_javascript_extraction_skips_unterminated_trailing_declaration():
    content = """
function foo(a, b) {
  return a + b;
}
function bar(x)
""".strip()

    extractor = GenericCodeBlockExtractor(content, "sample.js")

    blocks = extractor.code_block_extractor()

    assert len(blocks) == 1
    assert "function foo(a, b)" in blocks[0]
