"""Shared CLI argument helpers for script execution."""

import argparse
from typing import Any, Dict, Iterable, List, Tuple

# Flag spellings callers keep guessing (the MCP execute_script tool has a
# `userinterface_name` field, so models write `--userinterface_name`). Each one
# is rewritten to the flag the scripts actually define, with a deprecation line
# in the log, so old prompts and campaigns keep working while new ones learn.
ARG_ALIASES: Dict[str, str] = {
    '--userinterface_name': '--userinterface',
    '--user_interface': '--userinterface',
    '--node_name': '--node',
}

# Flags the launchers append to EVERY run without the script declaring them:
# the frontend, the MCP tool and campaigns add `--host <name>`, and the server
# adds `--variant <name>` (BUG-0152) even for scripts that take no variant.
# They are consumed by the executor from sys.argv, not by argparse, so they are
# tolerated here rather than rejected. Anything else unknown is a caller bug.
TOLERATED_UNKNOWN_FLAGS = frozenset({'--host', '--variant'})


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



def normalize_argv(argv: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Rewrite aliased flags to their canonical spelling.

    Returns (argv, warnings). Handles both `--flag value` and `--flag=value`.
    """
    out: List[str] = []
    warnings: List[str] = []
    for token in argv:
        flag, sep, value = token.partition('=')
        if flag in ARG_ALIASES:
            canonical = ARG_ALIASES[flag]
            warnings.append(f"'{flag}' is deprecated, using '{canonical}'")
            out.append(canonical + sep + value)
        else:
            out.append(token)
    return out, warnings


def unknown_args_message(script_name: str, unknown: List[str], parser: argparse.ArgumentParser) -> str:
    """One readable line for a run that passed flags the script does not define.

    Silently ignoring them is how `--userinterface_name youtube-web` used to fall
    back to the default interface and fail three steps later with a misleading
    "user interface not found"; failing here, with the valid list, is cheaper.
    """
    valid = sorted(a for a in parser._option_string_actions if a.startswith('--') and a != '--help')
    return (f"Unknown argument(s) for {script_name}: {' '.join(unknown)}. "
            f"Valid flags: {', '.join(valid)}")


def split_unknown_args(unknown: List[str]) -> Tuple[List[str], List[str]]:
    """Separate launcher-appended flags (tolerated) from flags nobody defines (rejected).

    argparse hands back unknown tokens in order, so `--host x` arrives as two
    tokens; a tolerated flag swallows the value that follows it, `--host=x` is one.
    """
    tolerated: List[str] = []
    rejected: List[str] = []
    skip_value = False
    for token in unknown:
        if skip_value:
            tolerated.append(token)
            skip_value = False
            continue
        flag = token.split('=', 1)[0]
        if flag in TOLERATED_UNKNOWN_FLAGS:
            tolerated.append(token)
            skip_value = '=' not in token
        else:
            rejected.append(token)
    return tolerated, rejected
