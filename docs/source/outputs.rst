Outputs and Reports
===================

.. raw:: html

   <section class="callout-band">
     <p class="eyebrow">Artifacts</p>
     <p>
       Auto Docs writes outputs that support review, debugging, and documentation publishing.
       These files are part of the operational value of the system, not just side effects.
     </p>
   </section>

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

.. raw:: html

   <section class="card-grid">
     <article class="card">
       <p class="eyebrow">Review</p>
       <h3>Use CSV output to inspect coverage</h3>
       <p>See where docstrings are present, where they are missing, and which lines need editorial attention.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Suggest</p>
       <h3>Keep generated text separate</h3>
       <p>The suggested docstring output gives teams a reviewable artifact rather than silently rewriting source files.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Publish</p>
       <h3>Trace the full docs build path</h3>
       <p>Logs and generated site assets make it easier to debug failures and validate publishing behavior in CI.</p>
     </article>
   </section>
