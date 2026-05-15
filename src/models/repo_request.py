from typing import Optional

from pydantic import BaseModel, Field


class RepoRequest(BaseModel):
    """
    Represents a request for repository information.

        Args:
            provider (str): The repository provider, either 'github' or 'gitlab'.
            repo_url (str): The URL of the repository.
            token (str): Authentication token for accessing the repository.
            branch (str): The branch of the repository to access.
            target_folders (list[str], optional): List of target folders, defaults to an empty list.
            model (Optional[str], optional): Optional model name.
            reuse_doc (bool, optional): Flag to indicate if the document should be reused, defaults
            to False.

        Returns:
            None: This class does not return a value.

    """

    provider: str  # "github" or "gitlab"
    repo_url: str
    token: str
    branch: str
    target_folders: list[str] = Field(default_factory=list)
    model: Optional[str] = None
    reuse_doc: bool = False
    docstring_threshold: float = Field(default=0.50, ge=0.0, le=1.0)


class PublishPagesRequest(BaseModel):
    """
    Represents a request to publish pages to a repository.

        Args:
            repo_url (str): The URL of the repository.
            token (str): The authentication token.
            branch (str): The branch to publish to.

        Returns:
            None

    """

    repo_url: str
    token: str
    branch: str
    low_content_min_lines: int = Field(default=4, ge=0)


class DocstringPullRequestRequest(BaseModel):
    """
    Represents a request for a pull request to add Python docstrings.

        Args:
            provider (str): The name of the provider (default is 'github').
            repo_url (str): The URL of the repository.
            token (str): Authentication token for the repository.
            base_branch (str): The base branch for the pull request.
            suggestion_branch (Optional[str]): The branch for suggested changes (default is None).
            title (str): Title of the pull request (default is 'Add suggested Python docstrings').
            max_docstrings (int): Maximum number of docstrings to add (default is 50).

        Returns:
            None

    """

    provider: str = "github"
    repo_url: str
    token: str
    base_branch: str
    suggestion_branch: Optional[str] = None
    title: str = "Add suggested docstrings"
    max_docstrings: int = 50
