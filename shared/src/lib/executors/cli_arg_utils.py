"""Shared CLI argument helpers for script execution."""

import argparse
from typing import Any


def str_to_bool(value: Any) -> bool:
    """Parse flexible boolean CLI values."""
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in ("yes", "true", "t", "y", "1", "on"):
        return True
    if lowered in ("no", "false", "f", "n", "0", "off"):
        return False
    raise argparse.ArgumentTypeError("Boolean value expected.")

