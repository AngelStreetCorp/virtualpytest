"""Public URL of the VirtualPyTest server these scripts talk to (TASK-92).

Resolution order: VPT_SERVER_URL, then SERVER_PUBLIC_URL (environment, else the
repo-root .env). No hostname fallback: if neither is set the script exits and
names both variables.
"""
import os
import sys
from pathlib import Path


def server_public_url() -> str:
    for key in ("VPT_SERVER_URL", "SERVER_PUBLIC_URL"):
        value = os.environ.get(key)
        if value:
            return value.rstrip("/")
    try:
        from dotenv import dotenv_values
        env = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
        value = env.get("SERVER_PUBLIC_URL")
        if value:
            return value.rstrip("/")
    except ImportError:
        pass
    sys.exit("error: server URL not set. Set VPT_SERVER_URL or SERVER_PUBLIC_URL "
             "(environment or repo-root .env), e.g. https://<server>.angelstreet.io")
