from utils.git_utils import extract_repo_path, should_ignore


def test_extract_repo_path_strips_protocol_and_git_suffix():
    assert extract_repo_path("https://github.com/example/project.git") == "example/project"


def test_extract_repo_path_accepts_short_form():
    assert extract_repo_path("group/project") == "group/project"


def test_should_ignore_matches_file_and_directory_patterns():
    patterns = ["node_modules", "*.log", "dist/"]

    assert should_ignore("node_modules", patterns) is True
    assert should_ignore("server.log", patterns) is True
    assert should_ignore("dist", patterns) is True
    assert should_ignore("src", patterns) is False
