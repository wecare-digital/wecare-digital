"""The missing third of plan / approval / receipt.

`plans.py` can already describe exactly what an APPLY would do and give that intent
a stable hash. `receipts.py` can already record that it happened. What did not exist
was anything in between - a human saying yes to *this* intent - which is why
`governance.py` holds every APPLY tool at `enabled=False` and says so plainly:

    There is deliberately no flag, because the approval, plan-hash and receipt
    machinery that would make an APPLY safe does not exist yet - a flag added now
    would be a switch nobody could safely throw, and the first person to find it
    would throw it.

This module is that machinery. It does NOT enable anything. After this, an APPLY is
refused for two independent reasons rather than one: the catalog still disables it,
AND there is no approval. Both have to change, separately and deliberately.

The properties that make an approval worth having
------------------------------------------------
Each of these exists because its absence has a specific failure:

* **Bound to one exact intent.** An approval carries a `plan_hash`, which covers the
  tool, the catalog version and the canonical arguments. Approving "send this text to
  that number" cannot authorise a different number - change any argument and the
  hash changes and the approval no longer matches. An approval scoped to a *tool*
  would be a standing licence to send.

* **Single use.** Consumed atomically at apply time. Without this, one approval is a
  replay token: the same send could be applied twice, or a thousand times, and the
  receipt trail would show a thousand legitimate-looking applies against one yes.

* **Short lived.** An approval expires. "Yes, message this customer about their
  order" is not an answer that stays true tomorrow, and an approval store without
  expiry accumulates live authorisations nobody remembers granting.

* **Not grantable by the agent.** `grant()` takes an explicit operator identity and
  the calling route must be Admin-gated. A model must never be able to reach the
  approve path; if it could, the plan/approve split would be theatre. There is no
  code path here that derives an approver from a model's own output.

* **Fails closed, everywhere.** A store that errors, a hash that does not match, a
  clock that cannot be read - all of them refuse. This is the opposite of the audit
  sink's original choice, and deliberately so: a failed audit loses a record, a
  failed authorisation check sends a message to a customer.

Storage is injectable
---------------------
The default store is in-memory, which is correct for tests and useless in
production - a Lambda's memory does not survive the request that created the
approval, so an in-memory store can never satisfy an apply from a later invocation.
That is a deliberate fail-safe rather than an oversight: with no real store
configured, nothing can ever be applied. `DynamoApprovalStore` is the production
implementation and needs a table; until that table exists and is wired, the answer
to every apply is no.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

from . import governance as gov
from . import plans as plan_module

# How long an approval stays usable. Short on purpose: this is a window in which a
# specific message may be sent, not a licence.
DEFAULT_TTL_SECONDS = int(os.environ.get("AGENT_APPROVAL_TTL_SECONDS", "900"))

# An approval must name a human. The model's own identity is never acceptable, and
# these are the values that have shown up in this codebase as "no real user".
_REJECTED_APPROVERS = frozenset({
    "", "agent", "assistant", "model", "bedrock", "system", "none", "null",
    "anonymous", "unknown",
})


class ApprovalRejected(PermissionError):
    """The approval was refused. Carries a reason safe to show a model."""

    def __init__(self, reason: str, *, plan_hash: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.plan_hash = plan_hash

    def as_result(self) -> Dict[str, Any]:
        """The refusal, shaped like `ToolRefused.as_result`.

        Carries no key a caller could read as a completed side effect - no
        `messageId`, no `sentAt`, no `invoiceId`. That is the direct lesson of the
        placeholder `createInvoice` that returned success and wrote nothing.
        """
        return {
            "success": False,
            "refused": True,
            "reason": self.reason,
            "planHash": self.plan_hash,
        }


@dataclass(frozen=True)
class Approval:
    plan_hash: str
    tool: str
    catalog_version: str
    approved_by: str
    approved_at: int
    expires_at: int
    # Set when consumed, so a second attempt can say "already used" rather than
    # "not found" - two very different things for whoever is reading the log.
    consumed_at: Optional[int] = None

    def is_expired(self, now: Optional[int] = None) -> bool:
        return int(now if now is not None else time.time()) >= self.expires_at

    def is_consumed(self) -> bool:
        return self.consumed_at is not None


class ApprovalStore(Protocol):
    """Minimal contract. Deliberately not a general key-value interface."""

    def put(self, approval: Approval) -> None: ...

    def get(self, plan_hash: str) -> Optional[Approval]: ...

    def consume(self, plan_hash: str, now: int) -> Optional[Approval]:
        """Atomically mark used and return it, or None if not consumable."""
        ...


@dataclass
class InMemoryApprovalStore:
    """For tests, and a fail-safe default in production.

    A Lambda's memory does not outlive the invocation, so in production this store
    can never hold an approval long enough to satisfy a later apply. That means an
    unconfigured deployment refuses everything, which is the right direction for a
    default.
    """

    _rows: Dict[str, Approval] = field(default_factory=dict)

    def put(self, approval: Approval) -> None:
        self._rows[approval.plan_hash] = approval

    def get(self, plan_hash: str) -> Optional[Approval]:
        return self._rows.get(plan_hash)

    def consume(self, plan_hash: str, now: int) -> Optional[Approval]:
        current = self._rows.get(plan_hash)
        if current is None or current.is_consumed() or current.is_expired(now):
            return None
        used = Approval(
            plan_hash=current.plan_hash, tool=current.tool,
            catalog_version=current.catalog_version,
            approved_by=current.approved_by, approved_at=current.approved_at,
            expires_at=current.expires_at, consumed_at=now,
        )
        self._rows[plan_hash] = used
        return used


APPROVALS_TABLE = os.environ.get(
    "AGENT_APPROVALS_TABLE", "stack-wecare-digital-AgentApprovalsTable")


class DynamoApprovalStore:
    """The production store. Single-use is enforced by DynamoDB, not by Python.

    `consume` is a single `update_item` with a condition expression: it sets
    `consumedAt` only if the attribute does not already exist and the row has not
    expired. That is the whole reason this class exists rather than a read-then-write
    in the application - a read-then-write loses the race, and losing that race means
    one approval spending twice, which is exactly the property single-use is for.

    `ConditionalCheckFailedException` is therefore not an error to log and swallow;
    it is the correct answer, and it becomes `None` so the caller refuses.

    TTL is set as `expiresTtl` for DynamoDB to reap, AND checked in the condition.
    DynamoDB's TTL deletion is asynchronous and documented as taking up to 48 hours,
    so relying on it alone would leave an expired approval spendable for two days.
    The TTL attribute is housekeeping; the condition is the control.
    """

    def __init__(self, table_name: Optional[str] = None, client: Any = None) -> None:
        self._table_name = table_name or APPROVALS_TABLE
        self._client = client
        self._table = None

    def _get_table(self):
        if self._table is None:
            import boto3  # imported lazily so tests never need AWS config
            resource = self._client or boto3.resource(
                "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            self._table = resource.Table(self._table_name)
        return self._table

    @staticmethod
    def _to_row(approval: Approval) -> Dict[str, Any]:
        row = {
            "planHash": approval.plan_hash,
            "tool": approval.tool,
            "catalogVersion": approval.catalog_version,
            "approvedBy": approval.approved_by,
            "approvedAt": approval.approved_at,
            "expiresAt": approval.expires_at,
            # Reaped by DynamoDB eventually; the condition below is what actually
            # enforces expiry.
            "expiresTtl": approval.expires_at,
        }
        if approval.consumed_at is not None:
            row["consumedAt"] = approval.consumed_at
        return row

    @staticmethod
    def _from_row(row: Dict[str, Any]) -> Approval:
        consumed = row.get("consumedAt")
        return Approval(
            plan_hash=str(row["planHash"]),
            tool=str(row.get("tool", "")),
            catalog_version=str(row.get("catalogVersion", "")),
            approved_by=str(row.get("approvedBy", "")),
            approved_at=int(row.get("approvedAt", 0)),
            expires_at=int(row.get("expiresAt", 0)),
            consumed_at=int(consumed) if consumed is not None else None,
        )

    def put(self, approval: Approval) -> None:
        self._get_table().put_item(Item=self._to_row(approval))

    def get(self, plan_hash: str) -> Optional[Approval]:
        got = self._get_table().get_item(Key={"planHash": plan_hash})
        row = got.get("Item")
        return self._from_row(row) if row else None

    def consume(self, plan_hash: str, now: int) -> Optional[Approval]:
        """Atomic single-use. Returns None when somebody else already spent it."""
        from botocore.exceptions import ClientError

        try:
            updated = self._get_table().update_item(
                Key={"planHash": plan_hash},
                UpdateExpression="SET consumedAt = :now",
                # attribute_not_exists is the single-use guarantee; expiresAt keeps a
                # lapsed approval unspendable regardless of TTL reaping lag.
                ConditionExpression=(
                    "attribute_not_exists(consumedAt) AND expiresAt > :now"),
                ExpressionAttributeValues={":now": now},
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") \
                    == "ConditionalCheckFailedException":
                # Already consumed, expired, or absent. The correct answer is no.
                return None
            raise
        row = updated.get("Attributes")
        return self._from_row(row) if row else None


_store: ApprovalStore = InMemoryApprovalStore()


def use_dynamo_store(table_name: Optional[str] = None) -> None:
    """Switch to the production store. Call once, at handler import time."""
    set_store(DynamoApprovalStore(table_name))


def set_store(store: ApprovalStore) -> None:
    """Install the production store. Called once, at wiring time."""
    global _store
    _store = store


def get_store() -> ApprovalStore:
    return _store


def _normalise_approver(approved_by: str) -> str:
    """Reject anything that is not plausibly a person.

    Not cosmetic. An approval whose approver is 'agent' records the model approving
    its own send, which is precisely the arrangement this module exists to prevent.
    """
    name = str(approved_by or "").strip()
    if name.lower() in _REJECTED_APPROVERS:
        raise ApprovalRejected(
            "an approval must name the operator who gave it; the agent cannot "
            "approve its own actions")
    return name


def grant(plan: plan_module.Plan, *, approved_by: str,
          ttl_seconds: Optional[int] = None,
          now: Optional[int] = None) -> Approval:
    """Record a human's yes to one exact plan.

    The CALLER is responsible for having authenticated that human - this function
    cannot verify a request it never sees. Any route exposing it must be Admin
    gated, which since 2026-09-24 also requires the Admin to have a second factor
    enrolled.

    The plan is re-validated here rather than trusted, because a plan that arrived
    over the wire may have been altered after it was built: `assert_plan_applicable`
    recomputes the hash from the contents and refuses a mismatch.
    """
    approver = _normalise_approver(approved_by)

    entry = gov.resolve(plan.tool)
    if entry.tool_class != gov.CLASS_APPLY:
        raise ApprovalRejected(
            f"{entry.name} is a {entry.tool_class} tool; there is nothing to "
            f"approve because it has no apply step")

    if plan.catalog_version != gov.CATALOG_VERSION:
        raise ApprovalRejected(
            f"plan was built against catalog version {plan.catalog_version}, "
            f"current is {gov.CATALOG_VERSION}; rebuild it before approving",
            plan_hash=plan.plan_hash)

    expected = plan_module.plan_hash(plan.tool, plan.catalog_version, plan.arguments)
    if expected != plan.plan_hash:
        raise ApprovalRejected(
            "plan hash does not match its own contents; it was altered after being "
            "built and must not be approved", plan_hash=plan.plan_hash)

    stamp = int(now if now is not None else time.time())
    ttl = int(ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS)
    if ttl <= 0:
        raise ApprovalRejected("an approval with no lifetime cannot be used")

    approval = Approval(
        plan_hash=plan.plan_hash,
        tool=plan.tool,
        catalog_version=plan.catalog_version,
        approved_by=approver,
        approved_at=stamp,
        expires_at=stamp + ttl,
    )
    _store.put(approval)
    return approval


def check(plan: plan_module.Plan, *, now: Optional[int] = None) -> Approval:
    """The approval for this plan, or raise. Does NOT consume it.

    For showing an operator what is pending. `consume` is what an apply must call,
    because only that is single-use.
    """
    stamp = int(now if now is not None else time.time())
    try:
        found = _store.get(plan.plan_hash)
    except Exception as exc:  # noqa: BLE001 - a broken store must refuse, not pass
        raise ApprovalRejected(
            f"the approval store could not be read, so this cannot be applied: "
            f"{type(exc).__name__}", plan_hash=plan.plan_hash) from exc

    if found is None:
        raise ApprovalRejected(
            "no operator has approved this exact action. Draft it, show it to a "
            "person, and apply only what they approve.",
            plan_hash=plan.plan_hash)
    if found.tool != plan.tool:
        # Cannot happen with a correct store, and if it does the store is not
        # trustworthy enough to authorise a send.
        raise ApprovalRejected(
            "the stored approval is for a different tool", plan_hash=plan.plan_hash)
    if found.is_consumed():
        raise ApprovalRejected(
            "this approval has already been used. Approvals are single use, so a "
            "repeat needs a new one.", plan_hash=plan.plan_hash)
    if found.is_expired(stamp):
        raise ApprovalRejected(
            "this approval has expired. Re-approve it rather than applying a stale "
            "decision.", plan_hash=plan.plan_hash)
    return found


def consume(plan: plan_module.Plan, *, now: Optional[int] = None) -> Approval:
    """Spend the approval for this plan. The gate an apply must pass.

    `check` first so the refusal says *why*, then an atomic consume so two
    concurrent applies cannot both win. A store returning None from `consume` after
    `check` passed means somebody else took it in between - which is exactly the
    race single-use exists to lose safely.
    """
    stamp = int(now if now is not None else time.time())
    check(plan, now=stamp)
    try:
        used = _store.consume(plan.plan_hash, stamp)
    except Exception as exc:  # noqa: BLE001
        raise ApprovalRejected(
            f"the approval could not be consumed, so nothing was applied: "
            f"{type(exc).__name__}", plan_hash=plan.plan_hash) from exc
    if used is None:
        raise ApprovalRejected(
            "this approval was used by another request a moment ago. Nothing was "
            "applied twice.", plan_hash=plan.plan_hash)
    return used


def assert_may_apply(plan: plan_module.Plan, *,
                     now: Optional[int] = None) -> Approval:
    """Both gates, in the order that gives the most useful refusal.

    Catalog enablement first, via `plans.assert_plan_applicable`, because "this tool
    is switched off entirely" is a different conversation from "nobody approved
    this", and reporting the approval problem to somebody whose tool is disabled
    sends them hunting the wrong thing.

    Then the approval, consumed. Two independent reasons to refuse, and both must
    change - separately and deliberately - before an apply can happen.
    """
    plan_module.assert_plan_applicable(plan)
    return consume(plan, now=now)


def describe(approval: Approval) -> Dict[str, Any]:
    """An approval in a form safe to show a model or write to a log.

    The plan's ARGUMENTS are deliberately absent: they may contain a phone number
    and a message body, and `plans.describe_plan` already has the redaction rules
    for those. Duplicating them here would be a second place to get it wrong.
    """
    return {
        "planHash": approval.plan_hash,
        "tool": approval.tool,
        "catalogVersion": approval.catalog_version,
        "approvedBy": approval.approved_by,
        "approvedAt": approval.approved_at,
        "expiresAt": approval.expires_at,
        "consumed": approval.is_consumed(),
    }
