"""Fail-closed helpers for Meta Graph mutation responses.

Meta mutation endpoints are not consistent about returning a success key.
The unsafe pattern is result.get("success", True) because any unexpected
response shape becomes a false success. Callers must either receive an explicit
success: true or name a concrete response field that proves the mutation.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def mutation_succeeded(result: Any, *, evidence_keys: Iterable[str] = ()) -> bool:
    """Return True only when Meta supplied explicit positive evidence.

    Error envelopes, explicit false, non-object responses, and unknown shapes all
    fail closed. evidence_keys is for endpoints whose documented success response
    returns an id/data field instead of success: true.
    """
    if not isinstance(result, Mapping):
        return False
    if result.get("error"):
        return False

    success = result.get("success")
    if success is True:
        return True
    if success is False:
        return False

    for key in evidence_keys:
        value = result.get(key)
        if value not in (None, "", [], {}):
            return True
    return False
