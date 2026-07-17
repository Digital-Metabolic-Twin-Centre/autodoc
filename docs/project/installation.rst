Installation
============

This guide explains how to install Auto Doc and run the service locally from a
fresh checkout.

Prerequisites
-------------

Install or prepare the following before running Auto Doc:

- Python 3.11 or newer
- ``uv`` for Python environment and dependency management
- Git
- A GitHub or GitLab access token for repositories you want Auto Doc to analyse
- An OpenAI API key, or an authenticated local AI CLI such as Codex CLI or
  Claude CLI
- Docker, if you prefer to run the service in a container

Clone the Repository
--------------------

.. code-block:: bash

   git clone <repository-url>
   cd autodoc

Create the Python Environment
-----------------------------

Create a virtual environment and install the development dependencies:

.. code-block:: bash

   uv venv
   source .venv/bin/activate
   uv sync --group dev --no-install-project

The development dependency group includes the application, testing tools, and
documentation packages needed for the local workflow.

Configure Environment Variables
-------------------------------

Create a ``.env`` file in the project root. At minimum, set the admin
credentials used by the local dashboard:

.. code-block:: text

   ADMIN_PASSWORD=choose-a-strong-password
   ADMIN_SECRET_KEY=choose-a-long-random-secret

Add an AI provider configuration. Use OpenAI directly:

.. code-block:: text

   OPENAI_API_KEY=your-openai-api-key
   AUTODOC_AI_PROVIDER=openai

Or use a local CLI provider:

.. code-block:: text

   AUTODOC_AI_PROVIDER=codex
   AUTODOC_AI_CLI_PROVIDER=codex

Auto Doc also supports Claude CLI:

.. code-block:: text

   AUTODOC_AI_PROVIDER=claude
   AUTODOC_AI_CLI_PROVIDER=claude

Repository access tokens are configured through saved repository settings in
the admin dashboard. If Auto Doc needs to trigger GitLab pipelines, also set:

.. code-block:: text

   CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token

Run the Service Locally
-----------------------

Start the FastAPI service with reload enabled:

.. code-block:: bash

   uv run uvicorn main:app --app-dir src --reload

The application will be available at:

- ``http://localhost:8000`` for the app entry point
- ``http://localhost:8000/admin`` for the admin dashboard
- ``http://localhost:8000/docs`` for the FastAPI OpenAPI interface

You can also run the application directly:

.. code-block:: bash

   uv run python src/main.py

Run with Docker
---------------

To build and start Auto Doc in Docker:

.. code-block:: bash

   docker compose up --build

The Docker Compose setup exposes the service on port ``8000`` and mounts the
local ``logs/`` directory so generated run artifacts remain available on the
host machine.

Test the Sphinx Site Locally
----------------------------

To build and test the Sphinx documentation site locally, run this command from
the project root:

.. code-block:: bash

   env UV_CACHE_DIR=/tmp/uv-cache uv run --group docs sphinx-build -b html docs docs/_build/html-preview

This writes the generated HTML preview to ``docs/_build/html-preview``. Open the
site entry page in your browser:

.. code-block:: text

   docs/_build/html-preview/index.html

If you prefer to serve the generated files over a local HTTP server:

.. code-block:: bash

   uv run python -m http.server 8080 --directory docs/_build/html-preview

Then open ``http://localhost:8080``.

Basic Verification
------------------

After starting the service, confirm the local setup by opening the admin
dashboard, saving a repository configuration, and running a generate workflow
against a test branch. Generated logs and artifacts are written under
``logs/<provider>/<repository>/app_<timestamp>/``.
