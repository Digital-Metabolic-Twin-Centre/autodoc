Installation Guide
==================

For the hosted Auto Doc service, use:

https://autodoc.humanmetabolism.org

Local Development
-----------------

Use the local setup only when developing or testing Auto Doc from this
repository.

.. code-block:: bash

   uv venv
   source .venv/bin/activate
   uv sync --group dev --no-install-project

Create a ``.env`` file with local admin settings and any AI provider credentials
needed for your workflow:

.. code-block:: text

   ADMIN_PASSWORD=choose-a-strong-password
   ADMIN_SECRET_KEY=choose-a-long-random-secret
   OPENAI_API_KEY=your-openai-api-key

Run Auto Doc locally:

.. code-block:: bash

   uv run uvicorn main:app --app-dir src --reload

The local app is available at ``http://localhost:8000``. The admin dashboard is
available at ``http://localhost:8000/admin``.

Preview These Docs Locally
--------------------------

Build the Sphinx HTML preview from the project root:

.. code-block:: bash

   env UV_CACHE_DIR=/tmp/uv-cache uv run --group docs sphinx-build -b html docs docs/_build/html-preview

Then open ``docs/_build/html-preview/index.html`` in your browser.
