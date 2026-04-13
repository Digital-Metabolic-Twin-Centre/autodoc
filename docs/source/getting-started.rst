Getting Started
===============

.. raw:: html

   <section class="callout-band">
     <p class="eyebrow">Setup Path</p>
     <p>
       The recommended local workflow uses <code>uv</code> for environment management,
       dependency sync, test execution, linting, and Sphinx builds.
     </p>
   </section>

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

.. raw:: html

   <section class="card-grid">
     <article class="card">
       <p class="eyebrow">Develop</p>
       <h3>Run the API with live reload</h3>
       <p>Use <code>uv run uvicorn main:app --app-dir src --reload</code> during local feature work.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Verify</p>
       <h3>Check quality before pushing</h3>
       <p>The pre-push script keeps lint, tests, and documentation build aligned with CI expectations.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Publish</p>
       <h3>Build the site locally first</h3>
       <p>Validate Sphinx output on your machine before relying on GitHub Actions or Pages deployment.</p>
     </article>
   </section>
