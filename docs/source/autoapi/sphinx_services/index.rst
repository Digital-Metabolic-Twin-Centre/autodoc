sphinx_services
===============

.. py:module:: sphinx_services


Attributes
----------

.. autoapisummary::

   sphinx_services.logger


Functions
---------

.. autoapisummary::

   sphinx_services.create_sphinx_setup
   sphinx_services.trigger_gitlab_pipeline


Module Contents
---------------

.. py:data:: logger

.. py:function:: create_sphinx_setup(provider, repo_url, token, branch, docstring_analysis_file)

.. py:function:: trigger_gitlab_pipeline(repo_url: str, branch: str, token: str, variables: dict = None) -> bool

   Triggers a GitLab pipeline for the given project and branch.

   :param repo_url: The GitLab project path (e.g., 'namespace/project').
   :type repo_url: str
   :param branch: The branch to trigger the pipeline on.
   :type branch: str
   :param token: GitLab private token.
   :type token: str
   :param variables: Pipeline variables.
   :type variables: dict, optional

   :returns: True if the pipeline was triggered successfully, False otherwise.
   :rtype: bool


