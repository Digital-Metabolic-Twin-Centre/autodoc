from datetime import datetime

project = "Auto Doc"
author = "Digital Metabolic Twin Centre"
copyright = f"{datetime.now().year}, {author}"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "autoapi.extension",
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

autoapi_dirs = ["../autoapi_include"]
autoapi_add_toctree_entry = False

# Configure AutoAPI to handle import errors gracefully
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
]


def autoapi_skip_member(app, what, name, obj, skip, options):
    """Skip members that cause import errors during parsing."""
    return skip


def setup(app):
    """Setup Sphinx extension to handle AutoAPI import errors."""
    app.connect("autoapi-skip-member", autoapi_skip_member)

    # Patch AutoAPI's astroid utilities to handle TooManyLevelsError gracefully
    try:
        from autoapi import _astroid_utils
        from astroid.exceptions import TooManyLevelsError

        original_get_full_import_name = _astroid_utils.get_full_import_name

        def safe_get_full_import_name(module_node, level):
            """Safely get full import name, handling TooManyLevelsError."""
            try:
                return original_get_full_import_name(module_node, level)
            except TooManyLevelsError:
                # Preserve a string result so downstream AutoAPI parsing does not
                # crash on string operations such as rsplit().
                partial_name = None
                if isinstance(level, str):
                    partial_name = level
                elif hasattr(module_node, "names"):
                    for import_name, imported_as in module_node.names:
                        partial_name = imported_as or import_name
                        if partial_name:
                            break

                module_name = getattr(module_node, "modname", "") or ""
                if module_name and partial_name:
                    return f"{module_name}.{partial_name}"
                return partial_name or module_name or "__autoapi_unresolved__"

        _astroid_utils.get_full_import_name = safe_get_full_import_name
    except (ImportError, AttributeError):
        pass
