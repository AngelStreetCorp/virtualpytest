"""Pseudonymisation of player names for published datasets.

Every Riot ID (game name) in the roster is replaced by "player-" + the first 12 hex digits of SHA-256(salt | name), in every
string of every output table and in meta.json. The salt is a secret kept outside the repository (--salt-file); without it
the mapping cannot be reproduced. Champion names are not personal data and are kept.
"""
import hashlib


def pseudonym(name, salt):
    return "player-" + hashlib.sha256((salt + "|" + name).encode("utf-8")).hexdigest()[:12]


def scrub(obj, names, salt):
    """Return obj with every occurrence of a roster name in a string replaced by its pseudonym (lists and dicts recursively)."""
    ordered = sorted({n for n in names if n}, key=len, reverse=True)   # longest first, so a short name inside a longer one is not split
    replace = {n: pseudonym(n, salt) for n in ordered}

    def walk(x):
        if isinstance(x, str):
            for n in ordered:
                x = x.replace(n, replace[n])
            return x
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        return x

    return walk(obj)
