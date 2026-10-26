"""
Explain a missing IR keymap.

DEVICE{i}_IR_TYPE is typed by hand and used as a file name (`<ir_type>.json`), so a
spelling such as `appletv` instead of `apple_tv` used to fail with only a path in the
journal and "Failed to connect to remote controller" in the UI. This builds one line
that names the variable, the folder, the keymaps that do exist and the closest match.
"""

import difflib
import os


def missing_keymap_message(config_dir: str, ir_type: str) -> str:
    available = sorted(
        name[:-5] for name in os.listdir(config_dir)
        if name.endswith('.json') and name != 'template.json'
    ) if os.path.isdir(config_dir) else []

    message = (f"IR keymap '{ir_type}.json' not found in {os.path.basename(config_dir)}/ "
               f"(check DEVICE<n>_IR_TYPE={ir_type}). Available: {', '.join(available) or 'none'}")

    close = difflib.get_close_matches(ir_type.lower(), available, n=1, cutoff=0.6)
    if close:
        message += f". Did you mean '{close[0]}'?"
    return message
