doc_services
============

.. py:module:: doc_services


Attributes
----------

.. autoapisummary::

   doc_services.logger


Functions
---------

.. autoapisummary::

   doc_services.analyze_repo


Module Contents
---------------

.. py:data:: logger

.. py:function:: analyze_repo(provider, repo_url, token, branch)

   Analyze a repository for Python files missing docstring.

   Description:
       This function fetches the repository tree, detects the tech stack, and checks each file
       for missing or present docstring. It returns lists of files and items missing docstring and those with docstring.

   :param provider: The git provider name (e.g., 'github', 'gitlab').
   :type provider: str
   :param repo_url: The URL of the repository.
   :type repo_url: str
   :param token: The authentication token for accessing the repository.
   :type token: str
   :param branch: The branch name to analyze.
   :type branch: str

   :returns:     - files_missing_docstring (list): List of dicts for files/items missing docstring.
                 - file_present_docstring (list): List of dicts for files/items with docstring.
   :rtype: tuple


