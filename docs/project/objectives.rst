Objectives
==========

1. Build a FastAPI-based service that can inspect repositories hosted on GitHub
   and GitLab and gather enough structural information to support automated
   documentation workflows.
2. Detect missing or weak documentation across supported codebases and generate
   high-quality docstring suggestions using OpenAI for Python, JavaScript,
   TypeScript, and MATLAB projects.
3. Automate Sphinx documentation scaffolding so a repository can be turned into
   a structured documentation site with minimal manual setup.
4. Support a review-first publishing workflow in which generated documentation
   can be checked, refined, and then published as HTML to GitHub Pages.
5. Improve developer productivity and documentation consistency by combining
   code analysis, AI-assisted writing, and documentation deployment in a single
   service.

Success criteria
----------------

- The service can successfully Analyse a target GitHub or GitLab repository and
  identify documentation coverage for supported source files.
- The system produces useful docstring suggestions that are clear, relevant, and
  suitable for developer review before adoption.
- Auto Doc generates a working Sphinx documentation scaffold that can be built
  locally and extended by the team.
- The reviewed documentation site can be published successfully to GitHub Pages
  as static HTML.
- The overall workflow reduces the amount of manual effort needed to document
  and publish technical project information.
