Auto Doc
=============================

.. raw:: html

   <section class="hero-panel">
     <div class="hero-copy">
       <p class="eyebrow">Repository Analysis and Sphinx Publishing</p>
       <h1>Turn repository structure, docstring coverage, and code context into a publishable documentation site.</h1>
       <p class="lead">
         Auto Doc reviews source trees, generates documentation suggestions, scaffolds a Sphinx site,
         and helps teams publish reviewed HTML without hand-assembling the whole docs workflow.
       </p>
     </div>
     <div class="hero-stat-grid">
       <div class="hero-stat">
         <span class="hero-stat-label">Input</span>
         <strong>GitHub and GitLab repos</strong>
       </div>
       <div class="hero-stat">
         <span class="hero-stat-label">Output</span>
         <strong>Sphinx docs and Pages HTML</strong>
       </div>
       <div class="hero-stat">
         <span class="hero-stat-label">Workflow</span>
         <strong>Generate, review, publish</strong>
       </div>
     </div>
   </section>

.. raw:: html

   <section class="feature-band">
     <article class="feature-card">
       <p class="feature-kicker">Generate</p>
       <h2>Analyze a target branch</h2>
       <p>Scan source files, measure documentation coverage, and prepare a working docs scaffold tied to the repository.</p>
     </article>
     <article class="feature-card">
       <p class="feature-kicker">Refine</p>
       <h2>Shape the documentation set</h2>
       <p>Review project pages, keep weekly progress visible, and extend the generated material into something people can actually navigate.</p>
     </article>
     <article class="feature-card">
       <p class="feature-kicker">Publish</p>
       <h2>Ship reviewed HTML</h2>
       <p>Build the Sphinx site, filter risky AutoAPI content when needed, and publish the final result to GitHub Pages.</p>
     </article>
   </section>

Project map
-----------

This homepage is organized around the real Auto Doc workflow rather than a generic template.

.. raw:: html

   <section class="map-grid">
     <article class="map-card">
       <h3>Project</h3>
       <p>Define the purpose of the repository, the documentation objectives, the implementation plan, and the final outcomes.</p>
     </article>
     <article class="map-card">
       <h3>Progress</h3>
       <p>Capture weekly movement, blockers, and decisions so the delivery story stays visible while the docs evolve.</p>
     </article>
     <article class="map-card">
       <h3>Notes</h3>
       <p>Keep local build instructions and practical maintenance details close to the documentation itself.</p>
     </article>
   </section>

Quick path
----------

1. Review the project pages to understand scope and intended outcomes.
2. Use the weekly log to track progress, blockers, and next actions.
3. Open the notes section when you need to build or maintain the Sphinx site.

.. toctree::
   :maxdepth: 1
   :caption: Project

   project/overview
   project/objectives
   project/plan
   project/results

.. toctree::
   :maxdepth: 1
   :caption: Progress

   logbook/weekly_updates

.. toctree::
   :maxdepth: 1
   :caption: Notes

   README
