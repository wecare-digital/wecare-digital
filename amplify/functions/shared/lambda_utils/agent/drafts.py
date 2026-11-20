"""Where a plan waits between being drafted and being approved.

The gap this closes
-------------------
`plans.describe_plan` deliberately hands back MASKED arguments: `...0044` instead of
a phone number, `<omitted 140 chars>` instead of a message body. That is right - the
description is rendered in a dashboard and written to an audit trail.

But it means the browser never holds the real arguments, so a client cannot submit
them back to be approved. Two ways out, and only one of them is acceptable:

* Send the full arguments to the client and have it echo them back on approve. This
  undoes the redaction, puts a customer's phone number and message body in a
  browser, and lets a client submit arguments that differ from the ones it displayed.
* Keep the plan on the server and let the client refer to it by hash. The client
  approves an identifier; the server already knows what that identifier means.

This module is the second one. An approval request therefore carries a hash and
nothing else that matters, and `approvals.grant` still re-derives and re-checks the
hash from the stored contents, so a tampered row cannot authorise a different send.

Why the same table
------------------
Drafts live in the approvals table under a `draft#` key prefix. A plan hash is hex,
so it can never collide with a prefixed key, and `DynamoApprovalStore` reads the bare
hash - the two record types cannot see each other. One table means one TTL config,
one PITR setting and one thing to look at during an incident, which is the same
argument `receipts.py` makes for writing through the existing audit sink instead of
standing up a second trail.

What is stored, and the cost of storing it
------------------------------------------
A draft holds the FULL canonical arguments, because that is the only form from which
the hash can be recomputed - and recomputing it is the check that makes the whole
arrangement trustworthy. So this table holds customer data at rest: a recipient and
a message body, with point-in-time recovery on.

That is a real cost, not a detail to skip past. It is bounded three ways: the TTL is
short (an approval window is minutes, not days), only APPLY tools are ever drafted,
and nothing reads a draft except the approve path. The alternative - not storing
them - makes it impossible for an operator to approve a specific send at all, which
is worse than the exposure.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from . import plans as plan_module

# A draft is a thing a person is about to look at, not a record. Long enough for an
# operator to read a plan and decide; short enough that customer content does not
# accumulate. Deliberately longer than the approval TTL, so the draft does not
# vanish out from under an approval that is still valid.
DEFAULT_DRAFT_TTL_SECONDS = int(
    os.environ.get("AGENT_DRAFT_TTL_SECONDS", "3600"))

KEY_PREFIX = "draft#"

TABLE = os.environ.get(
    "AGENT_APPROVALS_TABLE", "stack-wecare-digital-AgentApprovalsTable")


class DraftMissing(LookupError):
    """No draft for this hash. Fails closed: nothing can be approved."""


class DraftCorrupt(ValueError):
    """The stored draft does not hash to its own key.

    Either the row was altered or the canonicalisation changed underneath it. Both
    mean the draft cannot be trusted to say what a person agreed to, so it is refused
    rather than repaired.
    """


def _key(plan_hash: str) -> str:
    return f"{KEY_PREFIX}{plan_hash}"


class InMemoryDraftStore:
    """For tests, and a fail-safe default.

    A Lambda's memory does not outlive the invocation, so in production this store
    holds nothing by the time an approve request arrives and every approval refuses.
    That is the correct direction for an unconfigured deployment.
    """

    def __init__(self) -> None:
        self._rows: Dict[str, Dict[str, Any]] = {}

    def put(self, row: Dict[str, Any]) -> None:
        self._rows[str(row["planHash"])] = dict(row)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        row = self._rows.get(key)
        return dict(row) if row else None


class DynamoDraftStore:
    """The production store."""

    def __init__(self, table_name: Optional[str] = None, client: Any = None) -> None:
        self._table_name = table_name or TABLE
        self._client = client
        self._table = None

    def _get_table(self):
        if self._table is None:
            import boto3  # lazily, so tests need no AWS config
            resource = self._client or boto3.resource(
                "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            self._table = resource.Table(self._table_name)
        return self._table

    def put(self, row: Dict[str, Any]) -> None:
        self._get_table().put_item(Item=row)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        got = self._get_table().get_item(Key={"planHash": key})
        return got.get("Item")


_store: Any = InMemoryDraftStore()


def use_dynamo_store(table_name: Optional[str] = None) -> None:
    _set_store(DynamoDraftStore(table_name))


def _set_store(store: Any) -> None:
    global _store
    _store = store


def set_store(store: Any) -> None:
    _set_store(store)


def get_store() -> Any:
    return _store


def _to_row(plan: "plan_module.Plan", ttl_seconds: int,
            now: int) -> Dict[str, Any]:
    return {
        "planHash": _key(plan.plan_hash),
        "recordType": "draft",
        "tool": plan.tool,
        "toolClass": plan.tool_class,
        "catalogVersion": plan.catalog_version,
        # Canonical form, so the hash recomputes byte for byte. `canonical_arguments`
        # stringifies scalars, which also keeps floats out of DynamoDB - it rejects
        # them, and a silent Decimal conversion here would change the hash.
        "arguments": plan_module.canonical_arguments(plan.arguments),
        "createdAt": plan.created_at,
        "expiresTtl": now + ttl_seconds,
    }


def record(plan: "plan_module.Plan", *, ttl_seconds: Optional[int] = None,
           now: Optional[int] = None) -> str:
    """Save a drafted plan so it can later be approved by hash. Returns the hash."""
    stamp = int(now if now is not None else time.time())
    ttl = int(ttl_seconds if ttl_seconds is not None
              else DEFAULT_DRAFT_TTL_SECONDS)
    if ttl <= 0:
        raise ValueError("a draft with no lifetime could never be approved")
    _store.put(_to_row(plan, ttl, stamp))
    return plan.plan_hash


def load(plan_hash: str) -> "plan_module.Plan":
    """The drafted plan for this hash, re-derived and re-verified.

    The plan is REBUILT through `plans.build_plan` rather than reassembled field by
    field from the row. That matters: rebuilding runs the current governance and
    canonicalisation rules, so a draft made before a tool was reclassified cannot be
    approved as though nothing changed. The hash is then compared against the key,
    which catches both an altered row and a catalog that moved underneath it.
    """
    wanted = str(plan_hash or "").strip()
    if not wanted:
        raise DraftMissing("no plan hash supplied")

    row = _store.get(_key(wanted))
    if not row:
        raise DraftMissing(
            "no drafted plan with that hash. Draft it again and look at it before "
            "approving.")

    rebuilt = plan_module.build_plan(str(row.get("tool") or ""),
                                     row.get("arguments") or {})
    if rebuilt.plan_hash != wanted:
        raise DraftCorrupt(
            "the stored plan does not hash to the value it was filed under, so it "
            "cannot be shown to have been approved as drafted")
    return rebuilt
