Project Overview
================

Summary
-------

Auto Doc is a FastAPI service that analyses GitHub and GitLab repositories,
detects missing or incomplete documentation, generates docstring suggestions
with OpenAI, scaffolds a Sphinx documentation site, and publishes reviewed HTML
to GitHub Pages. The project is designed to reduce the manual effort involved
in documenting software systems by combining repository analysis, AI-assisted
documentation generation, and automated documentation publishing in one workflow.

Scope
-----

The system supports Python, JavaScript, TypeScript, and MATLAB repositories,
making it suitable for a wide range of modern development teams. It focuses on
improving documentation quality, accelerating Sphinx setup, and helping teams
move from undocumented source code to a structured, reviewable documentation
site with less manual configuration.

Project value
-------------

Auto Doc addresses a common problem in software projects: documentation is often
incomplete, outdated, or postponed because it takes time to produce and maintain.
By automating repository inspection, highlighting documentation gaps, and
preparing a publishable documentation scaffold, Auto Doc helps teams improve
clarity, maintainability, onboarding, and long-term project knowledge sharing.

Architecture documentation workflow
------------------------------------

In addition to docstring generation, Auto Doc can analyse a repository and produce a
reviewable architecture documentation draft covering project overview, entry points,
services, routers, modules, dependencies, data flow, background jobs, database models,
configuration, environment variables, authentication flow, API endpoints, diagrams,
repository structure, and technology stack. Observed facts are distinguished from
inferred relationships, and inferred findings include a confidence level. Generation
never commits or publishes; a maintainer must explicitly approve a draft before it is
applied to the repository's documentation tree, and existing manual documentation is
preserved unless overwrite is confirmed.
