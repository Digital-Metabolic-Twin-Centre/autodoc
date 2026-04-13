API Guide
=========

Root endpoint
-------------

``GET /``

Returns a simple welcome message and confirms the service is running.

Generate endpoint
-----------------

``POST /generate``

This endpoint analyzes a repository, writes docstring analysis outputs, and attempts
to prepare Sphinx documentation setup for the target repository.

Request body
------------

The request model includes:

- ``provider``: ``github`` or ``gitlab``
- ``repo_url``: repository URL or provider path such as ``owner/repo``
- ``token``: access token for reading the target repository
- ``branch``: branch to inspect and update

Example request
---------------

.. code-block:: json

   {
     "provider": "github",
     "repo_url": "owner/repository",
     "token": "your-access-token",
     "branch": "main"
   }

Successful response
-------------------

The endpoint returns:

- ``status``
- ``sphinx_setup_created``
- ``Docstring_analysis``

Error conditions
----------------

Common response failures include:

- ``400`` for missing required request fields
- ``403`` for repository write or branch protection issues
- ``404`` when no analyzable files are found
- ``422`` for validation-related failures
- ``500`` for unexpected runtime errors
