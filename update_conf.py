import ast
import pathlib
import re
import sys

REQUIRED_EXTENSIONS = ("autoapi.extension", "sphinx.ext.napoleon")
AUTOAPI_DIRS_LINE = "autoapi_dirs = ['../autoapi_include']"
AUTOAPI_ADD_TOCTREE_LINE = "autoapi_add_toctree_entry = False"


def _format_extension_block(extensions: list[str]) -> str:
    lines = ["extensions = ["]
    for extension in extensions:
        lines.append(f"    {extension!r},")
    lines.append("]")
    return "\n".join(lines)


def _replace_extensions_block(text: str) -> str:
    module = ast.parse(text)
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "extensions":
                    current_value = ast.literal_eval(node.value)
                    if not isinstance(current_value, list):
                        raise ValueError(
                            "docs/conf.py must define 'extensions' as a Python list."
                        )
                    merged = list(current_value)
                    for extension in REQUIRED_EXTENSIONS:
                        if extension not in merged:
                            merged.append(extension)
                    replacement = _format_extension_block(merged)
                    lines = text.splitlines(keepends=True)
                    start = node.lineno - 1
                    end = node.end_lineno
                    updated = lines[:start] + [replacement + "\n"] + lines[end:]
                    return "".join(updated)
    return text.rstrip() + "\n\n" + _format_extension_block(list(REQUIRED_EXTENSIONS)) + "\n"


def update_conf(conf_py: str) -> None:
    conf_path = pathlib.Path(conf_py)
    if not conf_path.exists():
        return

    original_text = conf_path.read_text(encoding="utf-8")
    text = _replace_extensions_block(original_text)
    if not re.search(r"^\s*autoapi_dirs\s*=", text, flags=re.MULTILINE):
        text = text.rstrip() + f"\n\n{AUTOAPI_DIRS_LINE}\n"
    if not re.search(r"^\s*autoapi_add_toctree_entry\s*=", text, flags=re.MULTILINE):
        text = text.rstrip() + f"\n{AUTOAPI_ADD_TOCTREE_LINE}\n"

    try:
        ast.parse(text)
    except SyntaxError as exc:
        raise ValueError(
            f"Updated docs/conf.py would be invalid Python: {exc.msg} (line {exc.lineno})."
        ) from exc

    conf_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    update_conf(sys.argv[1])
