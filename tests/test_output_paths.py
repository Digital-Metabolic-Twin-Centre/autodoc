from utils.output_paths import build_repo_output_dir, build_repo_output_file


def test_build_repo_output_dir_creates_provider_and_repo_scoped_folder():
    output_dir = build_repo_output_dir("octo-org/example-repo", "GitHub")

    assert output_dir.endswith("logs/github/octo-org__example-repo")


def test_build_repo_output_file_reuses_repo_scoped_folder():
    output_file = build_repo_output_file("group/subgroup/project", "gitlab", "block_analysis.csv")

    assert output_file.endswith("logs/gitlab/group__subgroup__project/block_analysis.csv")
