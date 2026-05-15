# GitHub Pages Deployment Branch

This branch is configured as the GitHub Pages publishing source for this repository.

- Source branch for documentation changes: `testing_and_update`
- Deployment branch served by GitHub Pages: `gh-pages`

- `/generate` analyses a target branch and writes documentation scaffold files directly to that branch
- `/suggest-python-docstrings-pr` opens a separate GitHub pull request with Python docstring insertions
- `/publish-pages` builds the reviewed Sphinx site from that branch and publishes the HTML to `gh-pages`


1. Build the Sphinx HTML locally.
2. Copy the generated static site into this branch.
3. Commit and push the updated HTML files.
