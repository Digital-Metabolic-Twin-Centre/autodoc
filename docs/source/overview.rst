Overview
========

.. raw:: html

   <section class="callout-band">
     <p class="eyebrow">Purpose</p>
     <p>
       Auto Docs exists to make documentation quality visible, actionable, and publishable
       without asking engineers to build a documentation pipeline from scratch.
     </p>
   </section>

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

.. raw:: html

   <section class="card-grid">
     <article class="card">
       <p class="eyebrow">Coverage</p>
       <h3>Find missing documentation fast</h3>
       <p>Surface undocumented modules, functions, and classes before they become long-term maintenance drag.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Consistency</p>
       <h3>Standardize how technical docs are prepared</h3>
       <p>Use one pipeline for source inspection, generated suggestions, and Sphinx-ready publishing outputs.</p>
     </article>
     <article class="card">
       <p class="eyebrow">Delivery</p>
       <h3>Move from repository analysis to a public docs site</h3>
       <p>Connect repository quality signals to a documentation site that can be versioned, reviewed, and deployed.</p>
     </article>
   </section>
