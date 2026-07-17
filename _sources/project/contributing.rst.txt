How to Contribute
=================

Contributions to Auto Doc should keep the project focused on reliable,
reviewable documentation automation. The safest changes are small, tested, and
clearly connected to repository analysis, docstring suggestions, Sphinx
generation, publishing, or the admin workflow.

Set Up the Project
------------------

Start from a local checkout and install the development dependencies:

.. code-block:: bash

   git clone <repository-url>
   cd autodoc
   uv venv
   source .venv/bin/activate
   uv sync --group dev --no-install-project

Create a ``.env`` file for local development. At minimum, configure the admin
settings:

.. code-block:: text

   ADMIN_PASSWORD=choose-a-strong-password
   ADMIN_SECRET_KEY=choose-a-long-random-secret

Add an OpenAI key or configure a local AI CLI provider if your change needs to
exercise docstring generation.

Development Workflow
--------------------

1. Create a feature branch from the current main branch.
2. Make a focused change with matching tests or documentation updates.
3. Run the relevant checks locally.
4. Review generated files before committing, especially Sphinx output, logs, and
   AutoAPI artifacts.
5. Open a pull request with a short summary, testing notes, and any known
   limitations.

Run the Application Locally
---------------------------

Use this command while developing API or admin dashboard changes:

.. code-block:: bash

   uv run uvicorn main:app --app-dir src --reload

The local service runs at ``http://localhost:8000``. The admin dashboard is
available at ``http://localhost:8000/admin`` and the FastAPI OpenAPI interface is
available at ``http://localhost:8000/docs``.

Run Tests and Checks
--------------------

Run the automated test suite:

.. code-block:: bash

   uv run pytest

Run linting:

.. code-block:: bash

   uv run ruff check .

If your change affects documentation rendering, rebuild the Sphinx preview:

.. code-block:: bash

   env UV_CACHE_DIR=/tmp/uv-cache uv run --group docs sphinx-build -b html docs docs/_build/html-preview

Then open ``docs/_build/html-preview/index.html`` and inspect the affected
pages.

Documentation Guidelines
------------------------

- Keep documentation aligned with the current application behavior.
- Prefer concrete commands and paths over vague setup notes.
- Update Sphinx pages when API behavior, environment variables, publishing
  behavior, or developer workflow changes.
- Avoid committing generated logs or temporary run artifacts unless they are
  intentional fixtures.

Code Guidelines
---------------

- Keep changes small and easy to review.
- Follow the existing project structure under ``src/``.
- Add tests when behavior changes or when fixing a bug.
- Preserve the review-first workflow for generated documentation.
- Handle repository, publishing, and AI-provider failures with clear errors and
  useful logs.

Pull Request Checklist
----------------------

- The change has been tested locally.
- Relevant documentation has been updated.
- New behavior is covered by tests where practical.
- Generated artifacts have been reviewed before commit.
- The pull request explains what changed, why it changed, and how it was
  verified.
