from datetime import datetime

project = "Auto Doc"
author = "Digital Metabolic Twin Centre"
copyright = f"{datetime.now().year}, {author}"

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'autoapi.extension',
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["custom-wide.css"]
html_favicon = "_static/img/favicon.ico"
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 4,
}


html_show_sphinx = False

autoapi_dirs = ['../autoapi_include']
autoapi_add_toctree_entry = False
