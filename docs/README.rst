Documentation Notes
===================

This project includes two related setups:

- running the Auto Doc API service
- building these Sphinx documentation pages locally

Application setup
-----------------

Requirements:

- Python 3.11 or newer
- ``uv``
- an OpenAI API key, or an authenticated ``codex``/``claude`` CLI
- a GitHub or GitLab access token for the target repository
- Docker, if you want to run the service in a container

Create a virtual environment and install dependencies:

.. code-block:: bash

   uv venv
   source .venv/bin/activate
   uv sync --group dev --no-install-project

Create a ``.env`` file in the project root:

.. code-block:: text

   # Optional when using OpenAI directly.
   OPENAI_API_KEY=your-openai-api-key

   # Optional AI backend selection: openai, codex, or claude.
   AUTODOC_AI_PROVIDER=codex
   AUTODOC_AI_CLI_PROVIDER=codex
   AUTODOC_AI_MODEL=your-cli-supported-model

   # Optional, only needed if Auto Doc should trigger GitLab pipelines.
   CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token

If ``OPENAI_API_KEY`` is not set, Auto Doc uses the configured CLI provider for
docstring generation. The default fallback is ``codex``. Saved repository model
values can also use prefixes such as ``codex:your-supported-model`` or
``claude:sonnet``.
For CLI backends, leave the model unset unless you know the model name is
supported by your authenticated CLI account.

Run the application locally
---------------------------

Start the FastAPI service with auto-reload:

.. code-block:: bash

   uv run uvicorn main:app --app-dir src --reload

The service runs at ``http://localhost:8000``.
Interactive API docs are available at ``http://localhost:8000/docs``.

You can also run the app directly:

.. code-block:: bash

   uv run python src/main.py

Run with Docker
---------------

Build and start the containerised service:

.. code-block:: bash

   docker compose up --build

The compose file exposes port ``8000`` and mounts the local ``logs/`` directory into the container.

Build these docs locally
------------------------

.. code-block:: bash

   cd docs
   python -m pip install -r requirements.txt
   make clean html

Open ``docs/_build/html/index.html`` in your browser.
