"""Bounded JSON credential caching; errors never contain provider secret values."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Sequence


class SecretAccessError(RuntimeError):
    """A required runtime credential could not be established."""


class JsonSecretCache:
    def __init__(self, *, ttl_seconds: float = 120, clock: Callable[[], float] = time.monotonic):
        if not 0 < ttl_seconds <= 300:
            raise ValueError("secret cache TTL must be between zero and 300 seconds")
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[tuple[int, str, str, str], tuple[float, dict[str, Any]]] = {}

    def read(self, client: Any, secret_id: str, *, required: Sequence[str],
             stage: str = "AWSCURRENT", generation: str = "") -> dict[str, Any]:
        if not secret_id or not required or stage not in {"AWSCURRENT", "AWSPENDING"}:
            raise SecretAccessError("invalid credential specification")
        key = (id(client), secret_id, stage, generation)
        now = self._clock()
        cached = self._entries.get(key)
        if cached is None or now >= cached[0]:
            try:
                response = client.get_secret_value(SecretId=secret_id, VersionStage=stage)
                parsed = json.loads(response["SecretString"])
            except Exception:
                raise SecretAccessError("required credential lookup failed") from None
            if not isinstance(parsed, dict):
                raise SecretAccessError("credential must be a JSON object")
            # Discard obsolete generations/stages rather than accumulate old credential copies.
            self._entries = {k: v for k, v in self._entries.items()
                             if k[:2] != key[:2] and now < v[0]}
            cached = (now + self._ttl, parsed)
        if any(not isinstance(cached[1].get(k), str) or not cached[1][k].strip()
               for k in required):
            raise SecretAccessError("required credential fields are missing")
        self._entries[key] = cached
        return {k: cached[1][k].strip() for k in required}

    def clear(self) -> None:
        self._entries.clear()
