Project Overview
================

Auto Doc is a FastAPI-based documentation automation service for teams working
with GitHub and GitLab repositories. It analyses a target repository, identifies
missing or weak documentation, generates reviewable docstring suggestions, and
scaffolds a Sphinx documentation site that can be built locally or published as
static HTML.

The project is designed to reduce the repetitive work involved in moving from an
under-documented codebase to a navigable documentation site. Rather than treating
documentation as a one-off manual task, Auto Doc brings repository analysis,
AI-assisted writing, Sphinx generation, review artifacts, and publishing support
into a single workflow.

Project Context
---------------

- **Project title:** Auto Doc
- **Project type:** Automated documentation generator and publishing workflow
- **Primary audience:** Developers, research software teams, and maintainers who
  need to improve documentation coverage across active repositories.
- **Supported repository providers:** GitHub and GitLab
- **Supported source languages:** Python, JavaScript, TypeScript, and MATLAB
  source files (``.m``/``.matlab``)
- **Documentation output:** Sphinx documentation with AutoAPI support and
  publishable HTML

Problem Statement
-----------------

Many software projects accumulate useful code faster than they accumulate useful
documentation. Existing functions, modules, services, and workflows may be hard
to understand because docstrings are missing, architecture notes are scattered,
or publishing a documentation site requires too much manual setup.

Auto Doc addresses this by inspecting repository structure, measuring
documentation coverage, suggesting missing docstrings for supported source
files, and preparing a Sphinx site that teams can review before publishing.

Core Workflow
-------------

1. A user selects a target repository and branch through the API or admin
   dashboard.
2. Auto Doc clones and analyses the repository, scanning supported source files
   for documentation coverage.
3. The system generates reviewable documentation artifacts, including docstring
   suggestions and Sphinx scaffold files.
4. Developers review and refine the generated output before adoption.
5. Reviewed documentation can be built as HTML and published to GitHub Pages.

Key Capabilities
----------------

- Repository analysis for GitHub and GitLab projects.
- Documentation coverage checks at module, class, and function level.
- AI-assisted docstring suggestions using OpenAI, Codex CLI, or Claude CLI,
  with Python-only insertion pull requests for GitHub repositories.
- Reuse of previous suggestion artifacts when appropriate.
- Sphinx scaffold generation with AutoAPI integration.
- Review-first publishing to GitHub Pages.
- Runtime logs and generated artifacts for traceability.
- Admin dashboard support for saved repositories, workflow triggers, run
  history, and generated outputs.

Technology Summary
------------------

Auto Doc is built with FastAPI, Sphinx, AutoAPI, Jinja2, HTMX, SQLite,
SQLAlchemy, Docker, and ``uv``. AI-generated suggestions can be provided through
the OpenAI API or authenticated local CLI providers such as Codex CLI and Claude
CLI.
