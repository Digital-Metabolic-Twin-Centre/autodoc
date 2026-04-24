import pathlib
import re
import sys


def _append_extension(extensions: str, extension: str) -> str:
    if extensions.strip() == "[]":
        return f"['{extension}']"
    return extensions[:-1].rstrip() + f", '{extension}']"


def update_conf(conf_py: str) -> None:
    conf_path = pathlib.Path(conf_py)
    if not conf_path.exists():
        return

    text = conf_path.read_text(encoding="utf-8")
    # Ensure autoapi.extension is in extensions
    ext_match = re.search(r"extensions\s*=\s*(\[[^\]]*\])", text)
    if ext_match:
        extensions = ext_match.group(1)
        if "autoapi.extension" not in extensions:
            new_ext = _append_extension(extensions, "autoapi.extension")
            text = text.replace(extensions, new_ext)
    else:
        text += "\nextensions = ['autoapi.extension']\n"
    # Set autoapi_dirs
    if not re.search(r"autoapi_dirs\s*=", text):
        text += "\nautoapi_dirs = ['../../autoapi_include']\n"
    conf_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    update_conf(sys.argv[1])
