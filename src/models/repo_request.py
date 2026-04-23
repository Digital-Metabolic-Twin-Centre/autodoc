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
