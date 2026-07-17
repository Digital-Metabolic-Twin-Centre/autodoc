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
