git_utils
=========

.. py:module:: git_utils


Attributes
----------

.. autoapisummary::

   git_utils.logger


Functions
---------

.. autoapisummary::

   git_utils.extract_repo_path
   git_utils.get_gitignore_patterns
   git_utils.should_ignore
   git_utils.fetch_content_from_github
   git_utils.fetch_content_from_gitlab
   git_utils.fetch_repo_tree
   git_utils.validate_docstring
   git_utils.create_directory_and_add_files
   git_utils.create_a_file


Module Contents
---------------

.. py:data:: logger

.. py:function:: extract_repo_path(repo_url: str, provider: str = 'github') -> str

   Extracts the repository path from a full URL.
   :param repo_url: Full repository URL (e.g., 'https://github.com/user/repo' or 'user/repo').
   :type repo_url: str
   :param provider: Git provider ("github" or "gitlab").
   :type provider: str

   :returns: Repository path (e.g., 'user/repo').
   :rtype: str


.. py:function:: get_gitignore_patterns(repo_path: str, access_token: str, branch: str = 'main', provider: str = 'github') -> List[str]

   Fetches .gitignore file from the repository and returns a list of patterns to ignore.
   :param repo_path: Repository path (e.g., 'user/repo').
   :type repo_path: str
   :param access_token: Authentication token.
   :type access_token: str
   :param branch: Branch name. Defaults to "main".
   :type branch: str, optional
   :param provider: Git provider ("github" or "gitlab"). Defaults to "github".
   :type provider: str, optional

   :returns: List of ignore patterns from .gitignore.
   :rtype: List[str]


.. py:function:: should_ignore(name: str, patterns: List[str]) -> bool

   Checks if a file or directory name matches any ignore pattern.
   :param name: File or directory name.
   :type name: str
   :param patterns: List of ignore patterns.
   :type patterns: List[str]

   :returns: True if the name should be ignored, False otherwise.
   :rtype: bool


.. py:function:: fetch_content_from_github(repo_path: str, branch: str, file_path: str, access_token: str) -> Optional[str]

   Fetches the raw content of a file from a GitHub repository.
   :param repo_path: Repository path (e.g., 'user/repo').
   :type repo_path: str
   :param branch: Branch name.
   :type branch: str
   :param file_path: Path to the file in the repository.
   :type file_path: str
   :param access_token: GitHub access token.
   :type access_token: str

   :returns: Raw file content if successful, None otherwise.
   :rtype: Optional[str]


.. py:function:: fetch_content_from_gitlab(repo_path: str, branch: str, file_path: str, private_token: str) -> Optional[str]

   Fetches the raw content of a file from a GitLab repository.
   :param repo_path: Repository path.
   :type repo_path: str
   :param branch: Branch name.
   :type branch: str
   :param file_path: Path to the file in the repository.
   :type file_path: str
   :param private_token: GitLab private token.
   :type private_token: str

   :returns: Raw file content if successful, None otherwise.
   :rtype: Optional[str]


.. py:function:: fetch_repo_tree(repo_path: str, access_token: str, branch: str = 'main', provider: str = 'github') -> List[Dict]

   Recursively fetches the file and directory tree for a given repository and branch.
   :param repo_path: Repository path.
   :type repo_path: str
   :param access_token: Authentication token.
   :type access_token: str
   :param branch: Branch name. Defaults to "main".
   :type branch: str, optional
   :param provider: Git provider ("github" or "gitlab"). Defaults to "github".
   :type provider: str, optional

   :returns: List of files and directories in the repository.
   :rtype: List[Dict]


.. py:function:: validate_docstring(tech_stack: str, repo_path: str, branch: str, file_path: str, access_token: str, provider: str = 'github') -> Optional[Tuple[bool, List[Dict[str, str]], List[Dict[str, str]]]]

   Validates the presence of docstring in a file based on its technology stack.

   :param tech_stack: Technology stack (e.g., "python").
   :type tech_stack: str
   :param repo_path: Repository path.
   :type repo_path: str
   :param branch: Branch name.
   :type branch: str
   :param file_path: Path to the file in the repository.
   :type file_path: str
   :param access_token: Authentication token.
   :type access_token: str
   :param provider: Git provider ("github" or "gitlab"). Defaults to "github".
   :type provider: str, optional

   :returns:     - bool: True if docstring is present, False otherwise.
                 - List[Dict[str, str]]: Items missing docstring.
                 - List[Dict[str, str]]: Items with docstring.
   :rtype: Optional[Tuple[bool, List[Dict[str, str]], List[Dict[str, str]]]]


.. py:function:: create_directory_and_add_files(repo_url: str, dir_path: str, file_paths: list, branch: str, token: str, provider: str = 'github') -> bool

   Creates a new directory in the remote repository and adds multiple files to it in a single commit.

   :param repo_url: Repository path (e.g., 'user/repo').
   :type repo_url: str
   :param dir_path: Directory path to create (e.g., 'autoapi_include').
   :type dir_path: str
   :param file_paths: List of file paths in the repo to copy into the new directory.
   :type file_paths: list
   :param branch: Branch name.
   :type branch: str
   :param token: Access token.
   :type token: str
   :param provider: 'github' or 'gitlab'.
   :type provider: str

   :returns: True if operation succeeded, False otherwise.
   :rtype: bool


.. py:function:: create_a_file(repo_url, branch, file_path, content, token, provider)

