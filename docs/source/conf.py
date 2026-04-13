import datetime
import os
import sys

# Add project root to path so AutoAPI can discover modules
sys.path.insert(0, os.path.abspath("../../src"))
sys.path.insert(0, os.path.abspath("../.."))

project = "Auto Docs"
author = "Auto Doc Team"
year = datetime.datetime.now().year
copyright = f"{year}, Auto Doc Team"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "autoapi.extension",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = []

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_show_sourcelink = False
html_show_sphinx = False
html_title = "Auto Docs"
html_theme_options = {
    "collapse_navigation": True,
    "navigation_depth": 2,
    "sticky_navigation": False,
}

autoapi_type = "python"
autoapi_dirs = ["../../src"]

autoapi_keep_files = False
autoapi_generate_api_docs = True
