import pathlib
import re
import sys

if len(sys.argv) < 2:
    sys.exit(1)

conf_py = sys.argv[1]

conf_path = pathlib.Path(conf_py)
if conf_path.exists():
    text = conf_path.read_text(encoding='utf-8')
    # Ensure autoapi.extension is in extensions
    ext_match = re.search(r'extensions\s*=\s*(\[[^\]]*\])', text)
    if ext_match:
        extensions = ext_match.group(1)
        if 'autoapi.extension' not in extensions:
            new_ext = extensions[:-1] + " 'autoapi.extension',]"
            text = text.replace(extensions, new_ext)
    else:
        text += "\nextensions = ['autoapi.extension']\n"
    # Set autoapi_dirs
    if not re.search(r'autoapi_dirs\s*=', text):
        text += "\nautoapi_dirs = ['../../autoapi_include']\n"
    conf_path.write_text(text, encoding='utf-8')