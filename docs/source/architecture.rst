Architecture
============

.. raw:: html

   <section class="callout-band">
     <p class="eyebrow">System View</p>
     <p>
       Auto Doc is structured as a thin API layer over a documentation-analysis pipeline,
       with repository utilities and Sphinx automation providing the integration points.
     </p>
   </section>

Processing flow
---------------

Auto Doc follows a straightforward pipeline:

1. Receive repository access details through the API
2. Read the repository tree from GitHub or GitLab
3. Filter supported source files
4. Extract code blocks from each file
5. Check for existing docstrings
6. Generate suggested docstrings where needed
7. Save analysis outputs locally
8. Prepare Sphinx and CI/CD artifacts for documentation publishing

Main modules
------------

- ``src/main.py``: FastAPI entry point
- ``src/router/router.py``: request handling and HTTP responses
- ``src/services/doc_services.py``: repository analysis orchestration
- ``src/services/sphinx_services.py``: Sphinx setup and CI workflow creation
- ``src/utils/code_block_extraction.py``: code block extraction logic
- ``src/utils/docstring_validation.py``: validation of existing documentation
- ``src/utils/docstring_generation.py``: OpenAI-driven docstring generation
- ``src/utils/git_utils.py``: provider integration for GitHub and GitLab

Deployment model
----------------

The service can run:

- directly with ``uvicorn`` for local development
- inside Docker for containerized execution
- with GitHub Actions and GitHub Pages for documentation publishing

Documentation model
-------------------

The published documentation site combines:

- static guides written in reStructuredText
- generated API reference pages from AutoAPI
- project styling layered on top of the Sphinx Read the Docs theme

.. raw:: html

   <section class="card-grid">
     <article class="card">
       <p class="eyebrow">Router</p>
       <h3>Entry point for orchestration</h3>
       <p>Receives requests, coordinates analysis, and returns operational outcomes through HTTP responses.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Services</p>
       <h3>Application logic and workflow control</h3>
       <p>Services handle repository inspection, coverage selection, and Sphinx setup generation for target repositories.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Utilities</p>
       <h3>Parsing, generation, and provider integration</h3>
       <p>Utility modules isolate code extraction, docstring logic, and GitHub or GitLab repository operations.</p>
     </article>
   </section>
