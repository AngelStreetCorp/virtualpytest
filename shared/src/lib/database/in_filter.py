"""Chunked PostgREST ``in.(...)`` reads.

A supabase-py ``.in_(col, values)`` filter puts every value in the request URL.
Past a few KB the request fails: PostgREST's front proxy answers 414 "URI too
long" (BUG-0417), and servers that reach Supabase through the public nginx get
a 502 once the echoed ``Content-Location`` header passes its 4 KB buffer, at
~85 uuids (BUG-0416). Any read whose id list can grow with the data (all test
cases, a tree's nodes, a page of results) goes through ``chunked_in``.
"""
from typing import Any, Callable, Dict, Iterable, List

# Max values per in.() filter: 50 uuids is ~1.9 KB of query string.
IN_FILTER_CHUNK = 50

# PostgREST answers at most PGRST_DB_MAX_ROWS rows per request (1000 on our
# stacks); a chunk with more matching rows is paged with .range().
MAX_ROWS_PER_REQUEST = 1000


def chunked_in(query_fn: Callable[[List[Any]], Any], values: Iterable[Any],
               size: int = IN_FILTER_CHUNK) -> List[Dict[str, Any]]:
    """Run ``query_fn(chunk)`` once per ``size`` values, paged; return all rows.

    ``query_fn`` builds the query for one chunk (the ``.in_`` goes inside it) and
    returns the unexecuted builder. Rows come back chunk after chunk, so a global
    ``.order()`` only holds within a chunk, and ``.limit()``/``.range()`` apply per
    chunk — only use it where the caller groups rows by the chunked column.
    Each chunk is read in pages of ``MAX_ROWS_PER_REQUEST`` with ``.range()``,
    so callers must not set their own ``.limit()``/``.range()``.
    """
    values = list(values)
    rows: List[Dict[str, Any]] = []
    for start in range(0, len(values), size):
        chunk = values[start:start + size]
        offset = 0
        while True:
            page = query_fn(chunk).range(offset, offset + MAX_ROWS_PER_REQUEST - 1).execute().data or []
            rows.extend(page)
            if len(page) < MAX_ROWS_PER_REQUEST:
                break
            offset += MAX_ROWS_PER_REQUEST
    return rows
