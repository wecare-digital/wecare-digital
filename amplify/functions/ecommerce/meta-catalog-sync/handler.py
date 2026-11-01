"""`wecare-meta-catalog-sync` - project the AWS ProductsTable onto the Meta Commerce catalog.

PHASE W, FEAT-001. Plan decision D3 in
`.agents/tasks/phase-w-whatsapp-commerce-20261006/plan.md`; the retailer-id contract, the item
shape and the diff all live in `lambda_utils/ecommerce/meta_catalog_sync.py`, which is pure. This
file is wiring: AWS catalog in, Meta in, a plan out, and two gates in front of the only write.

OWNER-AUTHORIZED PRODUCT-SCOPED PUBLICATION
--------------------------------------------
ProductsTable is the publication authority. Only rows with metaEnabled=true enter the desired
catalog, and active rows are always projected as available; stock quantities and retired stock
flags do not control Meta availability. Dry-run plus exact-plan approval protect every write.
Foreign retailer ids remain outside the owned reconciliation set.

THE TRIGGER CARRIES NO INFORMATION THIS FUNCTION USES
-----------------------------------------------------
It accepts ProductsTable DynamoDB stream events and the scheduled EventBridge backstop, and treats
both as signals to re-read the authoritative AWS catalogue. Stream record identity is correlation
only; the full ProductsTable is re-read so a partial event can never produce a partial Meta plan.

THE TOKEN IS READ LAZILY, AT REQUEST TIME, INSIDE THE FUNCTION
--------------------------------------------------------------
`wecare/meta-system-user-token`, by reference, in `_read_secret` - never at module scope. A
module-scope read is cached for the life of a warm sandbox, so a rotation would keep using the old
value until every sandbox recycled; that is the defect fixed in `payments/razorpay-webhook` on
2026-09-19. The value is never logged and never reduced to a logged boolean: CodeQL's
`py/clear-text-logging-sensitive-data` tracks taint across function boundaries and has already
failed this build twice on exactly that shape.

AUTHORIZATION
-------------
There is none, because there is no public surface: no HTTP API route, no function URL. The only
callers are the webhook's role (one `lambda:InvokeFunction` grant, added by
`scripts/provision_meta_catalog_sync.py` to the WEBHOOK's role) and an EventBridge schedule. Its
own role grants exactly one secret read and CloudWatch Logs; `wecare-digital-lambda-role` is not
touched.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence

from lambda_utils import shared_tables
from lambda_utils.ecommerce import meta_catalog_sync as catalog
from lambda_utils.ecommerce import request_service_contracts
from lambda_utils.logging import get_logger
from lambda_utils.meta_version import graph_url

logger = get_logger(__name__)

#: Secret NAME, never a value.
META_TOKEN_SECRET = os.environ.get("META_TOKEN_SECRET", "wecare/meta-system-user-token")

#: Meta allows one WhatsApp Business Account per product catalog. The primary published `:live`
#: alias owns WABA1; the unqualified function (and optional `:waba2` alias) owns WABA2. Keep
#: target identity independent of the legacy META_CATALOG_ID / META_TOKEN_FIELD variables so a
#: code deploy cannot accidentally publish WABA2's mutable $LATEST configuration onto WABA1.
WABA1_TOKEN_FIELD = os.environ.get("META_TOKEN_FIELD_WABA1", "access_token")
WABA2_TOKEN_FIELD = os.environ.get("META_TOKEN_FIELD_WABA2", "access_token_waba2")
WABA1_CATALOG_ID = os.environ.get("META_CATALOG_ID_WABA1", "1457045652952851")
WABA2_CATALOG_ID = os.environ.get("META_CATALOG_ID_WABA2", "1317472650427643")

#: Backward-compatible names for tests and old operational tooling that import these constants.
META_TOKEN_FIELD = WABA1_TOKEN_FIELD
META_CATALOG_ID = WABA1_CATALOG_ID


def _target_config(context) -> tuple[str, str]:
    """Return (catalog_id, token_field) from the Lambda invocation target.

    Production routing is qualifier-based and therefore immutable with the published code:
    - `:live` (or any numbered published version) -> WABA1
    - unqualified function / `:waba2` -> WABA2

    A missing invocation ARN is a unit-test/manual-call shape, so retain the legacy environment
    overrides there for backward compatibility without allowing those mutable variables to steer
    a real Lambda invocation.
    """
    arn = str(getattr(context, "invoked_function_arn", "") or "")
    if not arn:
        return (
            os.environ.get("META_CATALOG_ID", WABA1_CATALOG_ID),
            os.environ.get("META_TOKEN_FIELD", WABA1_TOKEN_FIELD),
        )
    parts = arn.split(":")
    qualifier = parts[7] if len(parts) > 7 else ""
    if qualifier in ("", "waba2"):
        return WABA2_CATALOG_ID, WABA2_TOKEN_FIELD
    return WABA1_CATALOG_ID, WABA1_TOKEN_FIELD

#: The same `fields` set `catalog-management._list_products` asks for, plus nothing. Asking for
#: less would make the diff report a change on a field we never read.
META_PRODUCT_FIELDS = ("id,name,retailer_id,price,currency,availability,image_url,url,"
                       "description")
META_PAGE_LIMIT = "100"

#: AWS-native product authority.
PRODUCTS_TABLE = shared_tables.products_table_name()

#: A cursor that never empties would otherwise spin until the Lambda timed out. Same guard, and
#: the same value, as both existing cursor loops.
MAX_PAGES = 50

GRAPH_TIMEOUT_SECONDS = 15

#: Meta's batch endpoint and the `"1199.00 INR"` price form it wants are UNVERIFIED against the
#: live API - no write has ever been made from this repository (findings section 1 lists it as an
#: open item). They are only reachable with both gates open, which is why an unverified shape is
#: acceptable here and would not be if the function shipped enabled.
META_BATCH_PATH = "items_batch"
META_BATCH_CHUNK = 100

#: Durable owner-approval records share the existing authorization table, but use a namespaced
#: key (`META_CATALOG_SYNC#<catalogId>#<planHash>`) so they can never collide with agent tool-plan
#: approvals or with the other WhatsApp catalog's approval for the same plan. Rows intentionally omit the
#: table's expiresTtl attribute: a catalog decision is an audit record, not a 15-minute bearer
#: approval. Exact current-plan binding still makes any ProductsTable/Meta drift invalidate the
#: approval.
CATALOG_APPROVALS_TABLE = os.environ.get(
    "META_CATALOG_APPROVALS_TABLE", "stack-wecare-digital-AgentApprovalsTable")
CATALOG_APPROVAL_KEY_PREFIX = "META_CATALOG_SYNC#"
CATALOG_APPROVAL_RECORD_TYPE = "META_CATALOG_SYNC"


def _approval_key(plan_hash: str, catalog_id: str) -> str:
    """One approval row per (catalog, exact plan).

    Both catalogs are built from the same ProductsTable, so one product change gives WABA1 and
    WABA2 the SAME plan and the same fingerprint. Keyed by the plan alone, the second catalog's
    proposal found the first catalog's row and could never be approved (its catalogId condition
    failed), and a readback on one catalog rewrote the other's status. Rows written before the key
    carried the catalog stay as history; nothing reads them.
    """
    return (CATALOG_APPROVAL_KEY_PREFIX + str(catalog_id or "").strip() + "#"
            + str(plan_hash or "").strip().lower())


def _public_approval(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "planHash": str(row.get("exactPlanHash") or ""),
        "status": str(row.get("status") or ""),
        "catalogId": str(row.get("catalogId") or ""),
        "proposedAt": int(row.get("proposedAt") or 0),
        "approvedAt": int(row.get("approvedAt") or 0),
        "approvedBy": str(row.get("approvedBy") or ""),
        "applyStartedAt": int(row.get("applyStartedAt") or 0),
        "appliedAt": int(row.get("appliedAt") or 0),
        "verifiedAt": int(row.get("verifiedAt") or 0),
        "batchHandles": list(row.get("batchHandles") or []),
        "counts": dict(row.get("counts") or {}),
        "blocked": list(row.get("blocked") or []),
        "lastReadbackPlanHash": str(row.get("lastReadbackPlanHash") or ""),
        "lastReadbackCounts": dict(row.get("lastReadbackCounts") or {}),
    }


class _DynamoCatalogApprovalStore:
    """Exact-plan proposal/approval/apply audit trail on the existing approvals table."""

    def __init__(self, table_name: str = CATALOG_APPROVALS_TABLE, table: Any = None) -> None:
        self.table_name = table_name
        self._table = table

    def _get_table(self):
        if self._table is None:
            import boto3
            self._table = boto3.resource(
                "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")
            ).Table(self.table_name)
        return self._table

    def get(self, plan_hash: str, catalog_id: str) -> Optional[Dict[str, Any]]:
        row = self._get_table().get_item(
            Key={"planHash": _approval_key(plan_hash, catalog_id)}, ConsistentRead=True
        ).get("Item")
        if (row and row.get("recordType") == CATALOG_APPROVAL_RECORD_TYPE
                and str(row.get("catalogId") or "") == str(catalog_id or "")):
            return dict(row)
        return None

    def propose(self, *, plan_hash: str, catalog_id: str, counts: Mapping[str, Any],
                blocked: Sequence[str], desired_items: Sequence[Mapping[str, Any]],
                proposed_by: str = "") -> Dict[str, Any]:
        from botocore.exceptions import ClientError
        now = int(time.time())
        item = {
            "planHash": _approval_key(plan_hash, catalog_id),
            "recordType": CATALOG_APPROVAL_RECORD_TYPE,
            "exactPlanHash": plan_hash.lower(),
            "catalogId": catalog_id,
            "status": "PROPOSED",
            "counts": dict(counts),
            "blocked": list(blocked),
            "desiredItems": [dict(x) for x in desired_items],
            "proposedAt": now,
            "proposedBy": str(proposed_by or ""),
        }
        try:
            self._get_table().put_item(
                Item=item, ConditionExpression="attribute_not_exists(planHash)")
            return item
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self.get(plan_hash, catalog_id)
            if existing is None:
                raise
            return existing

    def approve(self, *, plan_hash: str, catalog_id: str, approved_by: str) -> Optional[Dict[str, Any]]:
        from botocore.exceptions import ClientError
        now = int(time.time())
        try:
            result = self._get_table().update_item(
                Key={"planHash": _approval_key(plan_hash, catalog_id)},
                UpdateExpression=(
                    "SET #st=:approved, approvedBy=:by, approvedAt=:now, updatedAt=:now"
                ),
                ConditionExpression=(
                    "recordType=:type AND exactPlanHash=:hash AND catalogId=:catalog "
                    "AND (#st=:proposed OR #st=:approved)"
                ),
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":approved": "APPROVED", ":proposed": "PROPOSED",
                    ":by": approved_by, ":now": now, ":type": CATALOG_APPROVAL_RECORD_TYPE,
                    ":hash": plan_hash.lower(), ":catalog": catalog_id,
                },
                ReturnValues="ALL_NEW",
            )
            return dict(result.get("Attributes") or {})
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise

    def claim_apply(self, *, plan_hash: str, catalog_id: str) -> Optional[Dict[str, Any]]:
        from botocore.exceptions import ClientError
        now = int(time.time())
        try:
            result = self._get_table().update_item(
                Key={"planHash": _approval_key(plan_hash, catalog_id)},
                UpdateExpression="SET #st=:applying, applyStartedAt=:now, updatedAt=:now",
                ConditionExpression=(
                    "recordType=:type AND exactPlanHash=:hash AND catalogId=:catalog "
                    "AND #st=:approved"
                ),
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":applying": "APPLYING", ":approved": "APPROVED", ":now": now,
                    ":type": CATALOG_APPROVAL_RECORD_TYPE, ":hash": plan_hash.lower(),
                    ":catalog": catalog_id,
                },
                ReturnValues="ALL_NEW",
            )
            return dict(result.get("Attributes") or {})
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise

    def finish_apply(self, *, plan_hash: str, catalog_id: str,
                     outcome: Mapping[str, Any]) -> Dict[str, Any]:
        now = int(time.time())
        ok = bool(outcome.get("ok"))
        status = "APPLY_SUBMITTED" if ok else "APPLY_FAILED"
        result = self._get_table().update_item(
            Key={"planHash": _approval_key(plan_hash, catalog_id)},
            UpdateExpression=(
                "SET #st=:status, appliedAt=:now, updatedAt=:now, "
                "batchHandles=:handles, appliedCount=:count"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":status": status, ":now": now,
                ":handles": list(outcome.get("batchHandles") or []),
                ":count": int(outcome.get("applied") or 0),
            },
            ReturnValues="ALL_NEW",
        )
        return dict(result.get("Attributes") or {})

    def record_readback(self, *, plan_hash: str, catalog_id: str, current_plan_hash: str,
                        counts: Mapping[str, Any], verified: bool) -> Dict[str, Any]:
        now = int(time.time())
        status = "APPLIED" if verified else "APPLY_SUBMITTED"
        result = self._get_table().update_item(
            Key={"planHash": _approval_key(plan_hash, catalog_id)},
            UpdateExpression=(
                "SET #st=:status, updatedAt=:now, lastReadbackAt=:now, "
                "lastReadbackPlanHash=:current, lastReadbackCounts=:counts"
                + (", verifiedAt=:now" if verified else "")
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":status": status, ":now": now, ":current": current_plan_hash,
                ":counts": dict(counts),
            },
            ReturnValues="ALL_NEW",
        )
        return dict(result.get("Attributes") or {})


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The read failure
# ─────────────────────────────────────────────────────────────────────────────────────────────


class MetaCatalogReadError(RuntimeError):
    """The Meta catalogue read failed. Carries the Graph status structurally, never a body.

    THE STATUS HAS TO BE READABLE WITHOUT PARSING THE MESSAGE, which is the whole reason this
    class exists so transport failures carry structured status. A 403 means
    "ask the owner to re-grant the asset", a 429 means "back off and retry", and a log line
    carrying only `errorType` makes those indistinguishable from a 500 or a DNS failure.

    `status` is the integer HTTP status when the Graph call reached HTTP; `errorKind` is the
    transport exception's class name when it did not, and a transport failure has no status.
    Both default to `None` so a reader never has to guess which arm produced the failure.

    The Graph response BODY is never carried here and is never logged: it echoes the request, and
    this request's one header is a credential (`_graph_request` records that at its `HTTPError`
    arm). Only the status and a class name leave this object.

    Subclasses `RuntimeError`, so `type(error).__name__` in the handler's `except` arm stays a
    reliable localiser and becomes MORE specific than the bare `RuntimeError` it replaces.
    """

    status: Optional[int] = None
    errorKind: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The gates
# ─────────────────────────────────────────────────────────────────────────────────────────────

_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})


def _enabled() -> bool:
    """`META_CATALOG_SYNC_ENABLED` must say true. Absent, empty or anything else is OFF.

    Read at request time, not at import, so the value a deploy set is the value in force rather
    than whatever a warm sandbox started with.
    """
    return os.environ.get("META_CATALOG_SYNC_ENABLED", "").strip().lower() in _TRUE


def _safe_auto_apply_enabled() -> bool:
    return os.environ.get("META_CATALOG_AUTO_APPLY_SAFE", "").strip().lower() in _TRUE


def _safe_auto_apply_max_changes() -> int:
    raw = os.environ.get("META_CATALOG_AUTO_APPLY_MAX_CHANGES", "50").strip()
    try:
        value = int(raw)
    except ValueError:
        return 0
    return value if 0 < value <= 1000 else 0


def _safe_auto_apply(plan, blocked: Sequence[str], trigger: Mapping[str, str]) -> bool:
    """True only for bounded non-destructive background catalogue changes."""
    if not _safe_auto_apply_enabled():
        return False
    if trigger.get("source") not in {"ddb-stream", "schedule"}:
        return False
    counts = plan.counts()
    total = int(counts.get("create", 0)) + int(counts.get("update", 0))
    return (
        not blocked
        and int(counts.get("retire", 0)) == 0
        and int(counts.get("foreign", 0)) == 0
        and total > 0
        and total <= _safe_auto_apply_max_changes()
    )


def _dry_run() -> bool:
    """`META_CATALOG_SYNC_DRY_RUN` must say false EXPLICITLY to switch dry run off.

    Asymmetric with `_enabled` on purpose. A typo (`META_CATALOG_SYNC_DRY_RUN=flase`) leaves dry
    run ON, which is the direction a mistake should fall in when the alternative is writing to a
    customer-visible catalogue.
    """
    return os.environ.get("META_CATALOG_SYNC_DRY_RUN", "").strip().lower() not in _FALSE


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The credential
# ─────────────────────────────────────────────────────────────────────────────────────────────


def _read_secret(secret_id: str) -> Mapping[str, Any]:
    """Read a JSON secret by id, AT REQUEST TIME. No cache, and never raises.

    Lazy and uncached for the reason recorded in the module docstring: a module-scope or
    process-cached read survives a rotation. `boto3` is imported INSIDE, so importing this handler
    costs no AWS client - `tests/test_meta_catalog_sync_handler.py` asserts the import succeeds
    with a `boto3.client` factory that raises.

    `{}` on any failure. A sync that cannot read its token must do nothing, which is what an empty
    secret produces: no token, so the Meta read is skipped and the function reports a refusal
    rather than crashing into a retry.

    Nothing here logs the result, not even its shape or its truthiness.
    """
    try:
        import boto3
        client = boto3.client("secretsmanager",
                              region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return json.loads(client.get_secret_value(SecretId=secret_id)["SecretString"])
    except Exception as error:  # noqa: BLE001 - a read failure is a refusal, never a 500
        # The secret NAME and the exception TYPE. Never the value, and never a message that could
        # carry one.
        logger.error(json.dumps({
            "event": "meta_catalog_secret_read_failed",
            "secretId": secret_id,
            "errorType": type(error).__name__,
        }))
        return {}


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Meta
# ─────────────────────────────────────────────────────────────────────────────────────────────


def _graph_request(path: str, *, method: str = "GET",
                   params: Optional[Mapping[str, str]] = None,
                   payload: Optional[Mapping[str, Any]] = None,
                   token: str = "", app_secret: str = "") -> Dict[str, Any]:
    """One Graph call. Returns `{"error": ...}` rather than raising, like `catalog-management`.

    `appsecret_proof` is attached when the secret carries an `app_secret`, matching
    `catalog-management._graph_api` - an app configured to require the proof rejects every call
    without it. The proof is an HMAC OF the token, so it is as sensitive as the token: it is put
    in the query string and never logged.

    The URL is built through `graph_url`, so the Graph version comes from
    `lambda_utils.meta_version` and is not a literal here (`tests/test_meta_version.py` enforces
    both halves of that).
    """
    url = graph_url(*[segment for segment in path.split("/") if segment])
    query = dict(params or {})
    if app_secret and token:
        query["appsecret_proof"] = hmac.new(
            app_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=GRAPH_TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        # The STATUS only. A Graph error body echoes the request, and this request's one header is
        # a credential.
        return {"error": {"status": int(error.code)}}
    except Exception as error:  # noqa: BLE001
        return {"error": {"type": type(error).__name__}}


def _existing_items(requester, *, token: str, app_secret: str,
                    catalog_id: str) -> List[Dict[str, Any]]:
    """Read the complete Meta catalog or fail closed.

    Graph may legitimately return {"data": []} for an empty catalog. A missing
    or malformed data array, bad cursor, empty page that still advertises a
    next page, or exhausted page budget is *not* evidence of emptiness. Returning
    a partial list here would offer to create duplicates or retire valid items.
    """
    items: List[Dict[str, Any]] = []
    after = ""
    seen_cursors: set[str] = set()

    def _unreliable(reason: str) -> None:
        error = MetaCatalogReadError("the Meta catalogue read was incomplete")
        # Structured internal diagnostic, never response body, token or URL.
        error.errorKind = reason
        raise error

    for _ in range(MAX_PAGES):
        params = {"fields": META_PRODUCT_FIELDS, "limit": META_PAGE_LIMIT}
        if after:
            params["after"] = after
        result = requester(f"{catalog_id}/products", method="GET", params=params,
                           token=token, app_secret=app_secret)
        if not isinstance(result, Mapping):
            _unreliable("InvalidGraphRoot")
        if "error" in result:
            # Only transport status/type: Graph errors can contain secrets.
            details = result["error"] if isinstance(result["error"], Mapping) else {}
            failure = MetaCatalogReadError("the Meta catalogue could not be read")
            failure.status = details.get("status")
            failure.errorKind = details.get("type")
            raise failure

        page = result.get("data")
        if not isinstance(page, list):
            _unreliable("InvalidProductsData")
        if any(not isinstance(row, Mapping) for row in page):
            _unreliable("InvalidProductRow")
        paging = result.get("paging") or {}
        if not isinstance(paging, Mapping):
            _unreliable("InvalidPaging")
        cursors = paging.get("cursors") or {}
        if not isinstance(cursors, Mapping):
            _unreliable("InvalidCursors")
        raw_after = cursors.get("after") or ""
        if not isinstance(raw_after, str):
            _unreliable("InvalidAfterCursor")
        advertised_next = paging.get("next") or ""
        if not isinstance(advertised_next, str):
            _unreliable("InvalidNextPage")

        items.extend(page)
        if not page:
            if advertised_next:
                _unreliable("EmptyPageHasNext")
            return items
        if not raw_after:
            if advertised_next:
                _unreliable("MissingAfterCursor")
            return items
        if raw_after in seen_cursors:
            _unreliable("RepeatedAfterCursor")
        seen_cursors.add(raw_after)
        after = raw_after

    _unreliable("CatalogPageLimitExceeded")
    return items  # Unreachable; explicit for static type checkers.



# ─────────────────────────────────────────────────────────────────────────────────────────────
# AWS-native catalogue source (CATALOG_SOURCE=aws)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _native_products(scanner=None) -> List[Dict[str, Any]]:
    """Read the AWS ProductsTable and project onto the slim catalog shape consumed by `catalog.desired_items(..., require_variant_price=True)` and the entire
    diff/approval/dry-run pipeline downstream are byte-for-byte source-agnostic.

    `scanner` is injected for tests (a callable returning the list of ProductsTable
    items); production resolves a DynamoDB scan lazily. The catalogue is small, so a
    scan is acceptable here, matching `scripts/build-catalog-snapshot.py`.

    Per-variant `pricePaise` is emitted as integer paise directly from the native
    `priceMinor`, which is exactly what `require_variant_price=True` needs — so a
    native product with priced variants is accepted, and one missing a variant price
    is refused before any Meta write.
    """
    from decimal import Decimal

    def _default_scan() -> List[Mapping[str, Any]]:
        import boto3
        table = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")
        ).Table(PRODUCTS_TABLE)
        items: List[Mapping[str, Any]] = []
        kwargs: Dict[str, Any] = {}
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    def _paise(value: Any) -> int:
        if isinstance(value, Decimal):
            value = int(value)
        return int(value or 0)

    def _major(paise: int) -> str:
        return f"{Decimal(paise) / Decimal(100):.2f}"

    raw = (scanner or _default_scan)()
    rows: List[Dict[str, Any]] = []
    for item in raw:
        if str(item.get("status") or "active") == "archived":
            continue
        # Request services use ProductsTable for SKU/price authority and native ORDER_DETAILS
        # payment, but are not customer-browsable Meta catalogue products. This structural
        # exclusion wins even if a stale/admin-written row has metaEnabled=true.
        product_id = str(item.get("id") or "").strip().lower()
        if product_id in request_service_contracts.REQUEST_SERVICE_PRODUCT_IDS:
            continue
        # Meta publication is explicit and fail-closed. Only rows deliberately marked
        # metaEnabled=true may enter the desired Meta catalogue. Missing, false, null, or
        # malformed values all remain out until an Admin explicitly enables the product.
        if item.get("metaEnabled") is not True:
            continue
        price_minor = _paise(item.get("priceMinor"))
        variants = []
        for v in item.get("variants", []) or []:
            variant: Dict[str, Any] = {
                "id": str(v.get("sku") or v.get("id") or ""),
                "label": str(v.get("label") or ""),
                "inStock": True,
            }
            # A priced variant carries pricePaise; an unpriced one omits it, so
            # desired_items(require_variant_price=True) refuses it rather than guessing a price.
            vp = v.get("priceMinor")
            if vp is not None:
                variant["pricePaise"] = _paise(vp)
            variants.append(variant)
        row: Dict[str, Any] = {
            "id": str(item.get("id") or ""),
            "name": str(item.get("title") or item.get("name") or ""),
            "slug": str(item.get("slug") or ""),
            # `or "active"` defaults an absent status to visible — valid ONLY because `item`
            # comes from the ProductsTable scanner (our catalogue authority), where a missing
            # status is a legacy-row default, not an error. This invariant must not migrate to
            # a Meta source: Meta is a publishing destination, never a second master, so a
            # status read off a Meta GET response must fail closed (unknown/missing -> NOT
            # visible), never inherit this permissive default.
            "visible": str(item.get("status") or "active") == "active",
            "price": _major(price_minor),
            "currency": str(item.get("currency") or catalog.CURRENCY),
            "descriptionHtml": str(item.get("descriptionHtml") or item.get("tagline") or ""),
            "mediaCount": len(item.get("imageRefs") or []),
            "variants": variants,
            "choiceImages": {},
            "canonicalPath": str(item.get("canonicalPath") or ""),
        }
        images = item.get("imageRefs") or []
        if images:
            row["image"] = str(images[0])
        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The write, which nothing in this repository enables
# ─────────────────────────────────────────────────────────────────────────────────────────────


def _batch_requests(plan: catalog.SyncPlan) -> List[Dict[str, Any]]:
    """The plan as Meta `items_batch` requests. UPDATE for everything, including a create.

    `items_batch`'s `UPDATE` method is an upsert keyed on `retailer_id`, so one method covers
    create and update and there is no ordering hazard between them. There is NO `DELETE` method
    anywhere in this function: a retired item is an `UPDATE` setting `availability` to out of
    stock, because deleting it would break an in-flight WhatsApp cart that already holds its
    retailer id. `meta_catalog_sync.diff` cannot produce a delete either, so that guarantee is
    structural at both layers.
    """
    requests: List[Dict[str, Any]] = []
    for item in list(plan.create) + list(plan.update):
        # items_batch takes feed fields, unlike /products and the catalog read API.
        data = catalog.meta_payload(item)
        data["id"] = data.pop("retailer_id")
        data["title"] = data.pop("name")
        if "image_url" in data:
            data["image_link"] = data.pop("image_url")
        data["link"] = data.pop("url")
        data["price"] = f'{data["price"]} {data.pop("currency")}'
        requests.append({"method": "UPDATE",
                         "retailer_id": item["retailer_id"],
                         "data": data})
    for item in plan.retire:
        requests.append({"method": "UPDATE",
                         "retailer_id": item["retailer_id"],
                         "data": {"id": item["retailer_id"], "availability": catalog.OUT_OF_STOCK}})
    return requests


def _apply(plan: catalog.SyncPlan, requester, *, token: str, app_secret: str,
           catalog_id: str) -> Dict[str, Any]:
    """Send the plan. REACHABLE ONLY WITH BOTH GATES OPEN, and no code here opens them.

    Chunked, because `items_batch` bounds a batch and a single 24-item catalogue would never hit
    it today - the chunking is for the day the catalogue is not 24 items, not for today.
    """
    requests = _batch_requests(plan)
    sent = 0
    handles = []
    for start in range(0, len(requests), META_BATCH_CHUNK):
        chunk = requests[start:start + META_BATCH_CHUNK]
        result = requester(f"{catalog_id}/{META_BATCH_PATH}", method="POST",
                           payload={"item_type": "PRODUCT_ITEM", "allow_upsert": True,
                                    "requests": chunk}, token=token, app_secret=app_secret)
        if "error" in result:
            logger.error(json.dumps({"event": "meta_catalog_batch_rejected",
                                     "catalogId": catalog_id,
                                     "sent": sent,
                                     "chunk": len(chunk)}))
            return {"applied": sent, "ok": False}
        if result.get("validation_errors"):
            return {"applied": sent, "ok": False, "validationErrors": result["validation_errors"],
                    "responseFields": sorted(result.keys()), "validationStatus": result.get("validation_status")}
        if not result.get("handles"):
            return {"applied": sent, "ok": False, "responseFields": sorted(result.keys()), "validationStatus": result.get("validation_status")}
        handles.extend(result.get("handles") or [])
        sent += len(chunk)
    return {"applied": sent, "ok": True, "batchHandles": handles}


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The handler
# ─────────────────────────────────────────────────────────────────────────────────────────────


def _trigger(event: Any) -> Dict[str, str]:
    """What invoked us, for the log line only. Never used to narrow the read.

    Covers three envelopes, treated IDENTICALLY downstream (a full catalogue re-read):
      1. the ProductsTable DynamoDB stream. `entityId` is the changed item's `id` key,
         for correlation only.
      2. an EventBridge scheduled event (the backstop cron).
      3. anything else -> `unknown`, which still triggers the same full re-read rather than
         refusing: an unrecognised envelope must never become a missed sync.
    """
    if not isinstance(event, Mapping):
        return {"source": "unknown", "entityId": ""}
    records = event.get("Records")
    if isinstance(records, list) and records:
        first = records[0] if isinstance(records[0], Mapping) else {}
        if str(first.get("eventSource") or "") == "aws:dynamodb":
            keys = (((first.get("dynamodb") or {}) if isinstance(first.get("dynamodb"), Mapping)
                     else {}).get("Keys") or {})
            entity = ""
            id_key = keys.get("id") if isinstance(keys, Mapping) else None
            if isinstance(id_key, Mapping):
                entity = str(id_key.get("S") or "")
            return {"source": "ddb-stream", "entityId": entity}
    if event.get("source") == "aws.events" or event.get("detail-type"):
        return {"source": "schedule", "entityId": ""}
    return {"source": str(event.get("source") or "unknown"),
            "entityId": str(event.get("entityId") or "")}


def handler(event, context, *, graph_requester=None,
            secret_reader=None, approval_store=None):  # noqa: ARG001 - Lambda signature
    """Compute the AWS ProductsTable -> Meta plan and write only if both gates are open.

    The catalogue is read from ProductsTable only (`_native_products`), and the only API outside
    AWS that this handler calls is Meta Graph. Injection points resolve inside the function so
    monkeypatches remain effective.
    """
    reader = secret_reader or _read_secret
    graph = graph_requester or _graph_request

    trigger = _trigger(event)
    catalog_id, token_field = _target_config(context)
    enabled = _enabled()
    dry_run = _dry_run()

    secret = reader(META_TOKEN_SECRET) or {}
    token = str(secret.get(token_field) or "").strip()
    app_secret = str(secret.get("app_secret") or "").strip()
    if not token:
        # A fact about the secret ENTRY, which is a name - not about the credential. No boolean
        # derived from the value is logged either; "the configured field is empty" is reported by
        # naming the field, not by reporting what was in it.
        logger.error(json.dumps({"event": "meta_catalog_sync_unconfigured",
                                 "secretId": META_TOKEN_SECRET,
                                 "field": token_field}))
        return {"ok": False, "reason": "unconfigured", "enabled": enabled,
                "dryRun": True, "catalogId": catalog_id, "applied": 0}

    if isinstance(event, Mapping) and isinstance(event.get("batchHandle"), str):
        status = graph(f"{catalog_id}/check_batch_request_status", method="GET",
                       params={"handle": event["batchHandle"]}, token=token, app_secret=app_secret)
        return {"readOnly": True, "batchStatus": status}

    try:
        # ProductsTable is the sole catalogue authority. Everything downstream
        # (desired_items, diff, approval, dry-run, Meta write) remains unchanged.
        products = _native_products()
        desired = catalog.desired_items(products, require_variant_price=True)
        existing = _existing_items(graph, token=token, app_secret=app_secret,
                                   catalog_id=catalog_id)
        # A scoped rollout must not publish or retire unrelated catalog variants.
        allowed = {value.strip().lower() for value in
                   os.environ.get("META_CATALOG_SYNC_VARIANT_IDS", "").split(",") if value.strip()}
        if allowed:
            def _variant_in_scope(item):
                parsed = catalog.parse_retailer_id(item.get("retailer_id"))
                return bool(parsed and str(parsed[1]).lower() in allowed)
            desired = [item for item in desired if _variant_in_scope(item)]
            existing = [item for item in existing
                        if not catalog.parse_retailer_id(item.get("retailer_id"))
                        or _variant_in_scope(item)]
    except Exception as error:  # noqa: BLE001 - a read failure must not become a write attempt
        # The STATUS and the exception class name, and nothing more. `getattr` rather than an
        # isinstance branch because non-Graph read failures carry neither.
        logger.error(json.dumps({"event": "meta_catalog_sync_read_failed",
                                 "errorType": type(error).__name__,
                                 "graphStatus": getattr(error, "status", None),
                                 "graphErrorKind": getattr(error, "errorKind", None),
                                 "catalogId": catalog_id,
                                 "source": trigger["source"]}))
        return {"ok": False, "reason": "read_failed", "enabled": enabled,
                "dryRun": True, "catalogId": catalog_id, "applied": 0}

    plan = catalog.diff(desired, existing)
    blocked = catalog.blockers(desired)
    counts = plan.counts()
    plan_hash = plan.fingerprint()
    desired_public = [catalog.meta_payload(item) for item in desired]
    existing_public = [catalog.meta_payload(item) for item in existing]
    action = str(event.get("catalogAction") or "") if isinstance(event, Mapping) else ""
    store = approval_store or _DynamoCatalogApprovalStore()

    approval_row = None
    approval_store_ready = True
    if action or (isinstance(event, Mapping) and event.get("inspect") is True):
        try:
            approval_row = store.get(plan_hash, catalog_id)
        except Exception as error:  # fail closed for approval-dependent operations
            approval_store_ready = False
            logger.error(json.dumps({
                "event": "meta_catalog_approval_store_failed",
                "operation": action or "inspect",
                "errorType": type(error).__name__,
            }))
            if action:
                return {"ok": False, "reason": "approval_store_unavailable",
                        "enabled": enabled, "dryRun": True, "catalogId": catalog_id,
                        "planHash": plan_hash, "applied": 0}

    approved = bool(approval_row and approval_row.get("status") in (
        "APPROVED", "APPLYING", "APPLY_SUBMITTED", "APPLIED"))

    if isinstance(event, Mapping) and event.get("inspect") is True:
        # Private IAM-protected readback. Never enters the write path, even when
        # synchronization is enabled. Only public product fields are returned.
        return {"ok": True, "reason": "read_only_inspect", "enabled": enabled, "dryRun": True,
                "readOnly": True,
                "catalogId": catalog_id, "counts": counts, "blocked": blocked,
                "planHash": plan_hash, "approved": approved,
                "approvalStoreReady": approval_store_ready,
                "approval": _public_approval(approval_row),
                "desiredItems": desired_public, "existingItems": existing_public,
                "applied": 0}

    if action == "propose":
        if blocked:
            return {"ok": False, "reason": "blocked", "catalogId": catalog_id,
                    "counts": counts, "blocked": blocked, "planHash": plan_hash,
                    "approved": False, "applied": 0}
        row = store.propose(
            plan_hash=plan_hash, catalog_id=catalog_id, counts=counts, blocked=blocked,
            desired_items=desired_public, proposed_by=str(event.get("proposedBy") or ""))
        return {"ok": True, "readOnly": False, "catalogId": catalog_id,
                "counts": counts, "blocked": blocked, "planHash": plan_hash,
                "approval": _public_approval(row), "applied": 0}

    if action == "status":
        requested = str(event.get("planHash") or plan_hash).strip().lower()
        row = store.get(requested, catalog_id)
        return {"ok": True, "readOnly": True, "catalogId": catalog_id,
                "currentPlanHash": plan_hash, "requestedPlanHash": requested,
                "currentPlanMatches": hmac.compare_digest(requested, plan_hash.lower()),
                "approval": _public_approval(row), "applied": 0}

    if action == "approve":
        requested = str(event.get("planHash") or "").strip().lower()
        approved_by = str(event.get("approvedBy") or "").strip()
        if not requested or not hmac.compare_digest(requested, plan_hash.lower()):
            return {"ok": False, "reason": "plan_changed", "catalogId": catalog_id,
                    "currentPlanHash": plan_hash, "requestedPlanHash": requested, "applied": 0}
        if blocked:
            return {"ok": False, "reason": "blocked", "catalogId": catalog_id,
                    "blocked": blocked, "planHash": plan_hash, "applied": 0}
        if not approved_by:
            return {"ok": False, "reason": "approver_required", "catalogId": catalog_id,
                    "planHash": plan_hash, "applied": 0}
        row = store.approve(
            plan_hash=plan_hash, catalog_id=catalog_id, approved_by=approved_by)
        if not row:
            return {"ok": False, "reason": "proposal_required", "catalogId": catalog_id,
                    "planHash": plan_hash, "applied": 0}
        return {"ok": True, "catalogId": catalog_id, "planHash": plan_hash,
                "approved": True, "approval": _public_approval(row), "applied": 0}

    if action == "readback":
        requested = str(event.get("planHash") or "").strip().lower()
        row = store.get(requested, catalog_id)
        if not requested or not row:
            return {"ok": False, "reason": "approval_not_found", "catalogId": catalog_id,
                    "currentPlanHash": plan_hash, "requestedPlanHash": requested, "applied": 0}
        verified = (
            not blocked and counts.get("create", 0) == 0
            and counts.get("update", 0) == 0 and counts.get("retire", 0) == 0
        )
        updated = store.record_readback(
            plan_hash=requested, catalog_id=catalog_id, current_plan_hash=plan_hash, counts=counts,
            verified=verified)
        return {"ok": True, "readOnly": True, "catalogId": catalog_id,
                "currentPlanHash": plan_hash, "requestedPlanHash": requested,
                "verified": verified, "counts": counts, "blocked": blocked,
                "approval": _public_approval(updated), "applied": 0}

    # ONE structured line, and every field in it is a public catalogue identifier or a count.
    # Product ids, retailer ids and catalog ids are public commerce identifiers; there is no
    # personal data on this path at all, so nothing is masked and nothing needs to be.
    logger.info(json.dumps({
        "event": "meta_catalog_sync_planned",
        "catalogId": catalog_id,
        "source": trigger["source"],
        "entityId": trigger["entityId"],
        "enabled": enabled,
        "dryRun": dry_run,
        "desired": len(desired),
        "existing": len(existing),
        "create": counts["create"],
        "update": counts["update"],
        "retire": counts["retire"],
        "foreign": counts["foreign"],
        "blocked": len(blocked),
        "blockedProducts": blocked,
        "foreignRetailerIds": plan.foreign,
        "planHash": plan_hash,
        "approved": approved,
    }))

    if not enabled or dry_run:
        # RETURNS BEFORE ANY WRITE REQUEST IS CONSTRUCTED. `_batch_requests` is not called, so
        # there is no payload in memory to send by accident. An explicit Apply action gets a
        # refusal rather than a dry-run "ok", so the workspace cannot mistake a closed gate for
        # a successful catalog mutation.
        if action == "apply":
            return {"ok": False, "reason": "release_gates_closed",
                    "enabled": enabled, "dryRun": True, "catalogId": catalog_id,
                    "counts": counts, "blocked": blocked, "planHash": plan_hash,
                    "approved": approved, "approval": _public_approval(approval_row), "applied": 0}
        # This non-apply arm covers two situations - the gate is shut, or the gate is open and
        # the run is a rehearsal - so the reason is DERIVED from `enabled` rather than written as
        # a literal (F-1: every applied:0 arm states its reason). Live configuration is
        # `ENABLED=false, DRY_RUN=true`, so the next invocation lands here and reports `disabled`.
        return {"ok": True, "reason": "disabled" if not enabled else "dry_run",
                "enabled": enabled, "dryRun": True, "catalogId": catalog_id,
                "counts": counts, "blocked": blocked, "planHash": plan_hash,
                "approved": approved, "approval": _public_approval(approval_row), "applied": 0}

    if plan.is_empty:
        return {"ok": True, "reason": "nothing_to_apply", "enabled": True, "dryRun": False,
                "catalogId": catalog_id, "counts": counts, "blocked": blocked,
                "planHash": plan_hash, "approved": approved,
                "approval": _public_approval(approval_row), "applied": 0}

    if blocked:
        return {"ok": False, "reason": "blocked", "enabled": True, "dryRun": False,
                "catalogId": catalog_id, "counts": counts, "blocked": blocked,
                "planHash": plan_hash, "approved": approved, "applied": 0}

    if not action and desired and not existing:
        # A catalog that suddenly reads zero after having products must never
        # enter bounded auto-apply, even if that feature is enabled later.
        # A real empty catalog may be recovered only by the explicit,
        # separately approved exact-plan manual procedure.
        return {"ok": False, "reason": "empty_provider_inventory_requires_review",
                "enabled": enabled, "dryRun": False, "catalogId": catalog_id,
                "counts": counts, "blocked": blocked, "planHash": plan_hash,
                "approved": approved, "autoApplied": False, "applied": 0}

    if not action and _safe_auto_apply(plan, blocked, trigger):
        outcome = _apply(plan, graph, token=token, app_secret=app_secret, catalog_id=catalog_id)
        return {"ok": outcome["ok"], "reason": "safe_auto_apply",
                "enabled": True, "dryRun": False, "catalogId": catalog_id,
                "counts": counts, "blocked": blocked, "planHash": plan_hash,
                "approved": False, "autoApplied": True,
                "applied": outcome["applied"], "batchHandles": outcome.get("batchHandles", []),
                "validationErrors": outcome.get("validationErrors", []),
                "responseFields": outcome.get("responseFields", []),
                "validationStatus": outcome.get("validationStatus")}

    if not action and (
        int(counts.get("retire", 0)) > 0
        or int(counts.get("foreign", 0)) > 0
        or (
            int(counts.get("create", 0)) + int(counts.get("update", 0))
            > _safe_auto_apply_max_changes()
        )
    ):
        return {"ok": False, "reason": "approval_required_for_destructive_or_unusual_plan",
                "enabled": True, "dryRun": False, "catalogId": catalog_id,
                "counts": counts, "blocked": blocked, "planHash": plan_hash,
                "approved": approved, "autoApplied": False, "applied": 0}

    # A schedule/webhook is never an APPLY command unless it qualifies for the bounded
    # safe-auto-apply policy above. Destructive/unusual plans stay owner-approved.
    # a write still requires a separately authenticated admin action bound to the exact approved
    # plan. This prevents "approval exists" from becoming "background job may spend it whenever".
    if action != "apply":
        return {"ok": False, "reason": "explicit_apply_required", "enabled": True,
                "dryRun": False, "catalogId": catalog_id, "counts": counts,
                "blocked": blocked, "planHash": plan_hash, "approved": approved, "applied": 0}

    requested = str(event.get("planHash") or "").strip().lower()
    if not requested or not hmac.compare_digest(requested, plan_hash.lower()):
        return {"ok": False, "reason": "plan_changed", "enabled": True, "dryRun": False,
                "catalogId": catalog_id, "currentPlanHash": plan_hash,
                "requestedPlanHash": requested, "applied": 0}

    claimed = store.claim_apply(plan_hash=plan_hash, catalog_id=catalog_id)
    if not claimed:
        return {"ok": False, "reason": "approval_required", "enabled": True,
                "dryRun": False, "catalogId": catalog_id, "counts": counts,
                "blocked": blocked, "planHash": plan_hash, "approved": False, "applied": 0}

    outcome = _apply(plan, graph, token=token, app_secret=app_secret, catalog_id=catalog_id)
    finished = store.finish_apply(plan_hash=plan_hash, catalog_id=catalog_id, outcome=outcome)
    return {"ok": outcome["ok"], "enabled": True, "dryRun": False, "catalogId": catalog_id,
            "counts": counts, "blocked": blocked, "planHash": plan_hash,
            "approved": True, "approval": _public_approval(finished),
            "applied": outcome["applied"], "batchHandles": outcome.get("batchHandles", []),
            "validationErrors": outcome.get("validationErrors", []),
            "responseFields": outcome.get("responseFields", []),
            "validationStatus": outcome.get("validationStatus")}
