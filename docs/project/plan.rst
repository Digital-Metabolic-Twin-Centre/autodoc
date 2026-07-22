Project Plan
============

Current implementation status
-----------------------------

The project already includes a working foundation that covers the main Auto Doc
workflow from repository analysis to documentation publishing.

Completed and active capabilities
---------------------------------

1. A FastAPI service has been implemented to coordinate repository analysis,
   documentation generation, and publishing workflows.
2. Repository access has been integrated for both GitHub and GitLab.
3. The system can scan Python, JavaScript, TypeScript, and MATLAB source files
   (``.m``/``.matlab``) and assess documentation coverage across supported
   source code blocks.
4. AI-powered docstring suggestion generation is available for missing
   documentation through OpenAI, Codex CLI, or Claude CLI, with support for reuse
   of previously generated suggestions.
5. A Sphinx documentation scaffold is generated automatically for reviewed
   repositories.
6. AutoAPI integration is supported through the ``autoapi_include/`` workflow,
   including filtering of risky files and skipped-file reporting during build
   fallback.
7. The project supports a review-first publishing flow in which documentation
   can be built and published to GitHub Pages.
8. Runtime logs and analysis artifacts are stored to support traceability and
   review of each documentation run.

Near-term refinement work
-------------------------

1. Improve the generated documentation templates so project pages are more
   structured, easier to review, and more visually consistent.
2. Strengthen documentation quality checks and evaluation across generated
   outputs.
3. Refine the publishing and scaffold workflow to reduce friction for teams
   adopting the system in real repositories.

Future development
------------------

1. Introduce Retrieval-Augmented Generation (RAG) so docstring and
   documentation suggestions can be grounded in repository-specific context,
   existing documentation, architectural notes, and previously approved
   project knowledge.
2. Extend the platform toward audit-ready documentation by generating more
   structured evidence trails, change histories, traceable outputs, and
   documentation artifacts suitable for regulated or compliance-aware
   environments.
3. Expand support for stronger documentation intelligence, including richer
   contextual recommendations, improved summarization, and more reusable
   documentation outputs across project lifecycles.

Validation approach
-------------------

1. Test the workflow against representative repositories from supported
   languages and repository providers.
2. Review the usefulness, clarity, and correctness of generated docstring
   suggestions.
3. Assess the quality of generated Sphinx pages, published HTML output, and
   supporting logs and artifacts.
4. Use developer feedback to guide improvements in usability, trust, and
   documentation completeness.

Milestones
----------

+-----------+-----------------------------------------------------------+
| Milestone | Outcome                                                   |
+===========+===========================================================+
| M1        | Core FastAPI service and repository analysis implemented  |
+-----------+-----------------------------------------------------------+
| M2        | Docstring generation and Sphinx scaffold workflow active  |
+-----------+-----------------------------------------------------------+
| M3        | Review-first publishing and reporting workflow stabilized |
+-----------+-----------------------------------------------------------+
| M4        | RAG and audit-ready documentation features planned        |
+-----------+-----------------------------------------------------------+
