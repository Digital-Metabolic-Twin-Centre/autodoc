Getting Started
===============

Prerequisites
-------------

- Python 3.11 or newer
- ``uv`` installed locally
- An OpenAI API key for docstring generation
- A GitHub or GitLab personal access token for repository access

Install dependencies
--------------------

Create a local environment and sync development tools:

.. code-block:: bash

   uv venv
   source .venv/bin/activate
   uv sync --group dev --no-install-project

Environment variables
---------------------

Create a ``.env`` file in the project root:

.. code-block:: bash

   OPENAI_API_KEY=your-openai-api-key
   CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token

Run the service locally
-----------------------

Start the FastAPI server:

.. code-block:: bash

   uv run uvicorn main:app --app-dir src --reload

After startup:

- Application: ``http://localhost:8000``
- Interactive API docs: ``http://localhost:8000/docs``

Run local quality checks
------------------------

Before pushing changes, run:

.. code-block:: bash

   python3 prepush_check.py

This verifies linting, tests, and documentation build steps locally.
