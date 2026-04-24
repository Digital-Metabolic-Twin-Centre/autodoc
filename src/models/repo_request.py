from pydantic import BaseModel


class RepoRequest(BaseModel):
    provider: str  # "github" or "gitlab"
    repo_url: str
    token: str
    branch: str


class PublishPagesRequest(BaseModel):
    repo_url: str
    token: str
    branch: str


class DocstringPullRequestRequest(BaseModel):
    provider: str = "github"
    repo_url: str
    token: str
    base_branch: str
    suggestion_branch: str = "autodocs/python-docstring-suggestions"
    title: str = "Add suggested Python docstrings"
    max_docstrings: int = 50
