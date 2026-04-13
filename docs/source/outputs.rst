Outputs and Reports
===================

Generated local files
---------------------

During analysis, Auto Docs writes outputs into the project workspace.

Key outputs include:

- ``src/files/block_analysis.csv``: flattened analysis of detected code blocks
- ``src/files/suggested_docstring.txt``: generated docstring suggestions
- ``log/app_<timestamp>.log``: runtime logs for the service

What the reports contain
------------------------

The analysis CSV captures:

- file name
- file path
- function or module name
- block type
- missing docstring status
- detected language
- line number

How to use the outputs
----------------------

- review missing coverage in the CSV report
- inspect generated suggestions before applying them manually
- use the logs to debug repository access, parsing, and Sphinx setup steps

Publishing outputs
------------------

When the documentation pipeline succeeds, the project also produces:

- generated HTML documentation in ``docs/build/html``
- GitHub Pages deployment artifacts through GitHub Actions
- CI/CD documentation setup files for supported repository workflows
