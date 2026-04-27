from typing import Optional

from pydantic import BaseModel, Field


class RepoRequest(BaseModel):
    provider: str  # "github" or "gitlab"
    repo_url: str
    token: str
    branch: str
    target_folders: list[str] = Field(default_factory=list)


class PublishPagesRequest(BaseModel):
    repo_url: str
    token: str
    branch: str


class DocstringPullRequestRequest(BaseModel):
    provider: str = "github"
    repo_url: str
    token: str
    base_branch: str
    suggestion_branch: Optional[str] = None
    title: str = "Add suggested Python docstrings"
    max_docstrings: int = 50
