"""One rule for every value that enters a trace or crosses a link.

Values must be plain JSON: dicts with string keys, lists, strings, ints,
finite floats, booleans and ``None``. Anything that would come back from a
JSON round trip as something else (a tuple as a list, an int key as a
string, a str subclass as a plain str) is rejected rather than silently
converted, so what an endpoint sends, what the trace records and what a
checker reads are always the same value.
"""

from __future__ import annotations

import json
from typing import Any


def plain_json_copy(value: Any) -> Any:
    """Return a deep copy of ``value`` via JSON, or raise ``ValueError``."""
    try:
        copy = json.loads(json.dumps(value, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"not JSON-serialisable: {exc}") from exc
    if not _same(copy, value):
        raise ValueError(
            "would change in a JSON round trip (use lists not tuples, string keys, "
            "and plain str/int/float/bool values, not subclasses such as enums)"
        )
    return copy


def _same(a: Any, b: Any) -> bool:
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b
