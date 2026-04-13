Overview
========

Auto Docs is a FastAPI-based service for improving documentation quality in software
repositories. It inspects code, detects missing docstrings, generates AI-assisted
documentation suggestions, and prepares Sphinx documentation assets for publishing.

What Auto Docs does
-------------------

- Analyzes source files from GitHub and GitLab repositories
- Detects missing or incomplete docstrings in supported languages
- Generates suggested docstrings with OpenAI-powered prompts
- Produces coverage reports and suggested text outputs
- Prepares Sphinx and CI/CD artifacts for documentation publishing

Supported source types
----------------------

- Python: ``.py``, ``.pyw``
- JavaScript: ``.js``, ``.jsx``
- TypeScript: ``.ts``, ``.tsx``
- MATLAB: ``.m``, ``.mat``

Why teams use it
----------------

Auto Docs is designed for teams that want documentation to be part of delivery, not
an afterthought. It helps reduce manual auditing, highlights gaps in code
documentation, and gives engineers a faster path to a publishable Sphinx site.

Core components
---------------

- API layer: receives repository requests and returns analysis results
- Analysis pipeline: extracts code blocks and validates docstring coverage
- Generation layer: creates suggested docstrings where coverage is missing
- Sphinx automation: prepares documentation build structure and CI workflows
