"""Cost configuration for the derived-SEO layer.

The derived-SEO work is deterministic: templates over source content, no model calls. The only
switch left is COST_MODE, which names how much optional background compute the layer may use.

Nothing here reads a secret, calls AWS, or logs a value. It reads environment variables that
carry names only.
"""
from __future__ import annotations

import os
from typing import Dict


#: The three cost modes. FREE is the default and the only one that needs no reasoning about
#: spend: deterministic templates, no optional background compute beyond the single
#: low-frequency freshness check.
COST_MODE_FREE = "FREE"
COST_MODE_LOW_COST = "LOW_COST"
COST_MODE_ADVANCED = "ADVANCED"
_COST_MODES = (COST_MODE_FREE, COST_MODE_LOW_COST, COST_MODE_ADVANCED)


def cost_mode() -> str:
    """The active cost mode. Unknown or unset values resolve to FREE.

    FREE is the fail-safe: an operator who fat-fingers the variable, or a deploy that forgets
    to set it, gets the cheapest posture rather than the most expensive one.
    """
    raw = str(os.environ.get("COST_MODE", "") or "").strip().upper()
    return raw if raw in _COST_MODES else COST_MODE_FREE


def snapshot() -> Dict[str, object]:
    """A log/report-safe view of the configuration: a mode string only."""
    return {"costMode": cost_mode()}
