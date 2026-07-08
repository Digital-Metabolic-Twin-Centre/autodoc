from typing import Optional

from pydantic import BaseModel, Field, field_validator

from utils.output_paths import validate_architecture_output_path


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
    low_content_min_lines: int = Field(default=4, ge=0)


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


class ArchitectureGenerationRequest(BaseModel):
    """
    Represents a request to analyze a repository and produce a reviewable
    architecture documentation draft. Generation never commits or publishes.

        Args:
            provider (str): The repository provider, either 'github' or 'gitlab'.
            repo_url (str): The URL of the repository.
            token (str): Authentication token used for repository read access.
            branch (str): The branch of the repository to analyze.
            target_folders (list[str], optional): Optional folder filters, defaults to empty.
            output_path (str, optional): Preferred documentation path for the approved page.
            include_diagrams (bool, optional): Whether diagrams should be generated when
            evidence is sufficient, defaults to True.
            reuse_existing_docs (bool, optional): Whether existing architecture docs should be
            used as context for regeneration, defaults to True.
            model (Optional[str], optional): Optional generation model override.

        Returns:
            None: This class does not return a value.

    """

    provider: str
    repo_url: str
    token: str
    branch: str
    target_folders: list[str] = Field(default_factory=list)
    output_path: str = "docs/project/architecture.rst"
    include_diagrams: bool = True
    reuse_existing_docs: bool = True
    model: Optional[str] = None

    @field_validator("output_path")
    @classmethod
    def _validate_output_path(cls, value: str) -> str:
        """
        Validate an architecture output path value.

        Args:
            value (str): Output path to validate.

        Returns:
            str: Validated architecture output path.

        """
        return validate_architecture_output_path(value)


class ArchitectureApprovalRequest(BaseModel):
    """
    Represents explicit maintainer approval to apply a generated architecture draft
    to the target repository documentation workflow.

        Args:
            provider (str): The repository provider, either 'github' or 'gitlab'.
            repo_url (str): The URL of the repository.
            token (str): Authentication token used for repository write access.
            branch (str): The branch receiving the approved documentation update.
            draft_id (str): Identifier for the generated architecture draft artifact.
            output_path (str): Documentation path to update.
            overwrite_existing (bool): Whether approved manual edits may be replaced.
            approval_note (Optional[str], optional): Optional reviewer note.

        Returns:
            None: This class does not return a value.

    """

    provider: str
    repo_url: str
    token: str
    branch: str
    draft_id: str
    output_path: str
    overwrite_existing: bool
    approval_note: Optional[str] = None

    @field_validator("output_path")
    @classmethod
    def _validate_output_path(cls, value: str) -> str:
        """
        Validate an architecture documentation output path.

        Args:
            value (str): Output path to validate.

        Returns:
            str: Validated output path.

        """
        return validate_architecture_output_path(value)
