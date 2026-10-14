"""DEPRECATED SHIM — re-exports from `india_address`.

The India GST place-of-supply logic that used to live here was never Wix-specific:
`india_subdivision`, `gst_state_code`, `UnmappableAddress` and the subdivision table
are load-bearing for the AWS-native checkout pricing. They moved to the neutrally
named `india_address` as part of the Wix code removal. This module stays as a thin
re-export so existing imports keep working during the removal; drop it once every
`from ... import wix_address` is repointed to `india_address`.

`to_wix_address` is the only genuinely Wix-shaped symbol and is re-exported too, for
the dead Cart V2 delivery path, until that path is removed.
"""
from __future__ import annotations

from lambda_utils.ecommerce.india_address import (  # noqa: F401
    INDIA_ALIASES,
    INDIA_SUBDIVISIONS,
    UnmappableAddress,
    gst_state_code,
    india_subdivision,
    to_wix_address,
)

__all__ = [
    "INDIA_SUBDIVISIONS",
    "INDIA_ALIASES",
    "UnmappableAddress",
    "india_subdivision",
    "to_wix_address",
    "gst_state_code",
]
