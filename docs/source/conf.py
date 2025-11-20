import os
import sys
import datetime

# Add project root to path so AutoAPI can discover modules
sys.path.insert(0, os.path.abspath('../../src'))
sys.path.insert(0, os.path.abspath('../..'))

project = 'Auto Docs'
author = 'IMDhub Team'
year = datetime.datetime.now().year
copyright = f'{year}, IMDhub'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'autoapi.extension',
    'sphinx.ext.viewcode',
]

templates_path = ['_templates']
exclude_patterns = []

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

autoapi_type = 'python'
autoapi_dirs = ['../../src']

autoapi_keep_files = True
autoapi_generate_api_docs = True
