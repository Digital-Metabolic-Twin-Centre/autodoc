Architecture
============

Processing flow
---------------

Auto Docs follows a straightforward pipeline:

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
