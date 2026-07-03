Architecture Documentation Workflow
===================================

This project provides a review-first architecture documentation workflow for
target repositories. The service analyses repository structure, packages,
routers, services, dependencies, background jobs, configuration, and API entry
points before generating a draft page for maintainer review.

The generated architecture draft stays in the existing Sphinx hierarchy until
an explicit approval step writes the reviewed content into the docs tree.

