generate_yml_content
====================

.. py:module:: generate_yml_content


Functions
---------

.. autoapisummary::

   generate_yml_content.generate_gitlab_ci_file


Module Contents
---------------

.. py:function:: generate_gitlab_ci_file() -> bool

   Generates a .gitlab-ci.yml file in the specified remote GitLab repository.

   :param repo_path: Repository path (e.g., 'user/repo').
   :type repo_path: str
   :param access_token: GitLab private token.
   :type access_token: str
   :param branch: Branch name. Defaults to "main".
   :type branch: str, optional

   :returns: True if the file was created successfully, False otherwise.
   :rtype: bool


