from services.doc_services import _file_matches_target_folders, _normalize_target_folders


def test_normalize_target_folders_trims_whitespace_and_slashes():
    assert _normalize_target_folders([" src ", "/docs/", "nested/path//"]) == [
        "src",
        "docs",
        "nested/path",
    ]


def test_normalize_target_folders_discards_empty_values():
    assert _normalize_target_folders(["", "  ", "/"]) == []


def test_file_matches_target_folders_returns_true_when_no_targets():
    assert _file_matches_target_folders("src/main.py", []) is True


def test_file_matches_target_folders_matches_nested_paths():
    targets = ["src", "docs/guides"]

    assert _file_matches_target_folders("src/main.py", targets) is True
    assert _file_matches_target_folders("docs/guides/setup.md", targets) is True
    assert _file_matches_target_folders("docs/api/index.md", targets) is False
    assert _file_matches_target_folders("scripts/build.py", targets) is False
