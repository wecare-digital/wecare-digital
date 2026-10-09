"""`wecare-meta-catalog-sync` - project the Wix catalogue onto the Meta Commerce catalog.

PHASE W, FEAT-001. Plan decision D3 in
`.agents/tasks/phase-w-whatsapp-commerce-20261006/plan.md`; the retailer-id contract, the item
shape and the diff all live in `lambda_utils/ecommerce/meta_catalog_sync.py`, which is pure. This
file is wiring: Wix in, Meta in, a plan out, and two gates in front of the only thing that writes.

OWNER-AUTHORIZED SCOPED ROLLOUT, 2026-10-08
------------------------------------------
The deployed manifest enables only Submit Request and Vault, held out of stock while native
purchase QA remains pending. Absent flags still default to disabled/dry-run. The variant scope
also limits retirement, preserving unrelated and foreign items. Meta items_batch uses feed
fields; catalog reads use Graph product fields. A response without handles is not success.

THE TRIGGER CARRIES NO INFORMATION THIS FUNCTION USES
-----------------------------------------------------
It accepts an async invoke from `wecare-wix-catalog-webhook` (`{"source": "wix-webhook",
"entityId": ...}`) and a scheduled EventBridge event, and treats both identically: re-read the
whole catalogue. The entity id is logged for correlation and NEVER used to narrow the read, for
the same reason `wix-catalog-webhook` ignores it - a verified event means "the catalogue moved",
and re-reading is the right answer whatever the envelope said. So a change in Wix's event shape
can cost a log field and can never cost a missed item.

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

from lambda_utils.ecommerce import meta_catalog_sync as catalog
from lambda_utils.logging import get_logger
from lambda_utils.meta_version import graph_url

logger = get_logger(__name__)

#: Secret NAME, never a value.
META_TOKEN_SECRET = os.environ.get("META_TOKEN_SECRET", "wecare/meta-system-user-token")

#: Which field of that secret to use. `access_token` is WABA1's; `access_token_waba2` is WABA2's.
#: Configuration rather than a branch on the catalog id, so pointing this function at the other
#: WABA is two environment variables and no code change.
META_TOKEN_FIELD = os.environ.get("META_TOKEN_FIELD", "access_token")

#: The target catalog - ONE shared catalog for both WABAs, from `catalog-builder.tsx`:
#:     WABA1 2094615664435155 -> catalog 1457045652952851 (wecare_shop)
#:     WABA2 2513394156072604 -> catalog 1457045652952851 (wecare_shop)
#: So one sync run feeds both business numbers and there is no second catalog to keep in step.
#: Still configuration and not a literal in the code path, so another catalog is reachable by
#: environment variable alone.
META_CATALOG_ID = os.environ.get("META_CATALOG_ID", "1457045652952851")

#: The same `fields` set `catalog-management._list_products` asks for, plus nothing. Asking for
#: less would make the diff report a change on a field we never read.
META_PRODUCT_FIELDS = ("id,name,retailer_id,price,currency,availability,image_url,url,"
                       "description")
META_PAGE_LIMIT = "100"

#: Wix Catalog V3. The site is on V3, confirmed by Wix rather than inferred - a V1 call returns
#: HTTP 428 `CATALOG_V3_CALLING_CATALOG_V1_API` (see `scripts/fetch-wix-catalog.js`).
WIX_SEARCH_ENDPOINT = "/stores/v3/products/search"
WIX_VARIANTS_ENDPOINT = "/stores/v3/products/query-variants"

#: V3 omits description, currency, media and category info unless asked, so a search without
#: these returns products with no price currency and no description and reads as an empty
#: catalogue. Mirrors `CATALOG_PRODUCT_FIELDS` in `ecommerce/wix-store/handler.py` and `FIELDS`
#: in `scripts/fetch-wix-catalog.js`, so all three consumers ask for the same shape.
WIX_PRODUCT_FIELDS = ("URL", "CURRENCY", "MEDIA_ITEMS_INFO", "PLAIN_DESCRIPTION",
                      "DIRECT_CATEGORIES_INFO", "VARIANT_OPTION_CHOICE_NAMES", "INFO_SECTION")

WIX_PAGE_SIZE = 100
WIX_VARIANT_PAGE_SIZE = 1000

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
#: key so they can never collide with agent tool-plan approvals. Rows intentionally omit the
#: table's expiresTtl attribute: a catalog decision is an audit record, not a 15-minute bearer
#: approval. Exact current-plan binding still makes any Wix/Meta drift invalidate the approval.
CATALOG_APPROVALS_TABLE = os.environ.get(
    "META_CATALOG_APPROVALS_TABLE", "stack-wecare-digital-AgentApprovalsTable")
CATALOG_APPROVAL_KEY_PREFIX = "META_CATALOG_SYNC#"
CATALOG_APPROVAL_RECORD_TYPE = "META_CATALOG_SYNC"


def _approval_key(plan_hash: str) -> str:
    return CATALOG_APPROVAL_KEY_PREFIX + str(plan_hash or "").strip().lower()


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

    def get(self, plan_hash: str) -> Optional[Dict[str, Any]]:
        row = self._get_table().get_item(
            Key={"planHash": _approval_key(plan_hash)}, ConsistentRead=True
        ).get("Item")
        if row and row.get("recordType") == CATALOG_APPROVAL_RECORD_TYPE:
            return dict(row)
        return None

    def propose(self, *, plan_hash: str, catalog_id: str, counts: Mapping[str, Any],
                blocked: Sequence[str], desired_items: Sequence[Mapping[str, Any]],
                proposed_by: str = "") -> Dict[str, Any]:
        from botocore.exceptions import ClientError
        now = int(time.time())
        item = {
            "planHash": _approval_key(plan_hash),
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
            existing = self.get(plan_hash)
            if existing is None:
                raise
            return existing

    def approve(self, *, plan_hash: str, catalog_id: str, approved_by: str) -> Optional[Dict[str, Any]]:
        from botocore.exceptions import ClientError
        now = int(time.time())
        try:
            result = self._get_table().update_item(
                Key={"planHash": _approval_key(plan_hash)},
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
                Key={"planHash": _approval_key(plan_hash)},
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

    def finish_apply(self, *, plan_hash: str, outcome: Mapping[str, Any]) -> Dict[str, Any]:
        now = int(time.time())
        ok = bool(outcome.get("ok"))
        status = "APPLY_SUBMITTED" if ok else "APPLY_FAILED"
        result = self._get_table().update_item(
            Key={"planHash": _approval_key(plan_hash)},
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

    def record_readback(self, *, plan_hash: str, current_plan_hash: str,
                        counts: Mapping[str, Any], verified: bool) -> Dict[str, Any]:
        now = int(time.time())
        status = "APPLIED" if verified else "APPLY_SUBMITTED"
        result = self._get_table().update_item(
            Key={"planHash": _approval_key(plan_hash)},
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
    """Every item currently in the Meta catalog, by cursor paging `/{catalog_id}/products`.

    Raises `RuntimeError` on a Graph error rather than returning a short list. A PARTIAL read is
    the one failure mode that must not be tolerated here: items missing from `existing` look
    exactly like items that need creating, so a truncated read would turn into a plan that
    re-creates the whole catalogue.
    """
    items: List[Dict[str, Any]] = []
    after = ""
    for _ in range(MAX_PAGES):
        params = {"fields": META_PRODUCT_FIELDS, "limit": META_PAGE_LIMIT}
        if after:
            params["after"] = after
        result = requester(f"{catalog_id}/products", method="GET", params=params,
                           token=token, app_secret=app_secret)
        if "error" in result:
            raise RuntimeError("the Meta catalogue could not be read")
        page = result.get("data")
        if isinstance(page, list):
            items.extend(row for row in page if isinstance(row, Mapping))
        after = (((result.get("paging") or {}).get("cursors") or {}).get("after") or "")
        if not after or not page:
            break
    return items


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Wix
# ─────────────────────────────────────────────────────────────────────────────────────────────


def _wix_request(endpoint: str, body: Mapping[str, Any]) -> Dict[str, Any]:
    """One authenticated Wix call, through the existing shared eCom client.

    `lambda_utils.wix_ecom` already owns the base URL, the site-id header and the lazily-read,
    by-reference API key. Imported INSIDE so this module stays importable without an AWS client.
    """
    from lambda_utils import wix_ecom
    return wix_ecom._request(endpoint, method="POST", body=dict(body))


def _wix_products(requester) -> List[Dict[str, Any]]:
    """Read every Wix product, then hydrate per-variant prices and stock from a second endpoint.

    TWO CALLS, NOT ONE, AND THE ENVELOPES DIFFER. `/products/search` takes
    `{search: {cursorPaging}, fields}`; `/products/query-variants` takes `{fields, query}` with
    the paging INSIDE `query`. Sending one shape to the other endpoint is a 400 rather than an
    empty result - recorded in `scripts/fetch-wix-catalog.js:109-114`, which mirrors the working
    call in `ecommerce/wix-store/handler.py`.

    The second call is not optional here, and for a reason beyond the snapshot's: it is the ONLY
    source of per-variant price. `Contribute` is 100-500 and `WECARE.DIGITAL Services` 49-350, so
    a product-level price would be the minimum and wrong for most of their variants. That is why
    `desired_items` is called with `require_variant_price=True` - a variant whose price did not
    arrive refuses rather than publishing the product's.
    """
    products: List[Dict[str, Any]] = []
    cursor = ""
    for _ in range(MAX_PAGES):
        paging = {"limit": WIX_PAGE_SIZE}
        if cursor:
            paging["cursor"] = cursor
        result = requester(WIX_SEARCH_ENDPOINT,
                           {"search": {"cursorPaging": paging},
                            "fields": list(WIX_PRODUCT_FIELDS)})
        page = result.get("products") or []
        products.extend(row for row in page if isinstance(row, Mapping))
        cursor = (((result.get("pagingMetadata") or {}).get("cursors") or {}).get("next") or "")
        if not page or not cursor:
            break

    rows = [_slim_product(product) for product in products]
    identifiers = [row["id"] for row in rows if row.get("id")]
    if identifiers:
        variants = _wix_variants(requester, identifiers)
        for row in rows:
            row["variants"] = variants.get(row["id"], [])
            # The variant search index can lag behind a product update. Resolve
            # explicit option-choice artwork from the product read first.
            for variant in row["variants"]:
                images = {row["choiceImages"][key] for key in variant.get("choiceIds", [])
                          if key in row["choiceImages"]}
                if len(images) == 1:
                    variant["image"] = images.pop()
    return rows


def _slim_product(product: Mapping[str, Any]) -> Dict[str, Any]:
    """The live V3 payload reduced to the fields `meta_catalog_sync` reads.

    The same projection `scripts/fetch-wix-catalog.js` `slim()` writes into
    `src/content/wix-catalog.json`, so the pure module sees one shape whether its input came from
    the live API or from the committed snapshot - which is what lets the committed snapshot be a
    valid test fixture rather than an approximation of one.

    `price` stays the DECIMAL STRING Wix sends. No coercion to a float, here or anywhere.
    """
    price_range = product.get("actualPriceRange") or {}
    minimum = price_range.get("minValue") or {}
    media_items = (((product.get("media") or {}).get("itemsInfo") or {}).get("items") or [])
    image = ""
    for entry in media_items:
        if isinstance(entry, Mapping):
            candidate = str(((entry.get("image") or {}).get("url")
                             if isinstance(entry.get("image"), Mapping)
                             else entry.get("url")) or "").strip()
            if candidate:
                image = candidate
                break
    row: Dict[str, Any] = {
        "id": str(product.get("id") or ""),
        "name": str(product.get("name") or ""),
        "slug": str(product.get("slug") or ""),
        "visible": product.get("visible") is not False,
        "price": minimum.get("amount"),
        "currency": str(product.get("currency") or catalog.CURRENCY),
        # V3's `description` is Ricos rich-content NODES; `plainDescription` is the HTML string.
        "descriptionHtml": str(product.get("plainDescription") or ""),
        "mediaCount": len(media_items),
        "variants": [],
        "choiceImages": {},
    }
    for option in product.get("options") or []:
        for choice in (option.get("choicesSettings") or {}).get("choices") or []:
            for entry in choice.get("linkedMedia") or []:
                choice_image = str((entry.get("image") or {}).get("url")
                                   or entry.get("url") or "").strip()
                if choice_image:
                    key = f"{option.get('id')}:{choice.get('choiceId')}"
                    row["choiceImages"][key] = choice_image
                    break
    if image:
        row["image"] = image
    return row


def _wix_variants(requester, product_ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """`productId -> [{id, label, inStock, pricePaise}]` from `query-variants`.

    `pricePaise` is integer paise through `meta_catalog_sync.paise_from_major`, which uses
    `Decimal(str(value))` and refuses an amount that is not a whole number of paise. A variant
    whose price is missing or unreadable is emitted WITHOUT the key, so `desired_items` refuses it
    in strict mode rather than silently falling back to the product's price.

    `visible is False` rows are dropped, and an absent `visible` counts as visible - the same
    reading `slim()` and `is_syncable` use.
    """
    by_product: Dict[str, List[Dict[str, Any]]] = {identifier: [] for identifier in product_ids}
    cursor = ""
    for _ in range(MAX_PAGES):
        if cursor:
            query: Dict[str, Any] = {"cursorPaging": {"limit": WIX_VARIANT_PAGE_SIZE,
                                                      "cursor": cursor}}
        else:
            query = {"filter": {"productData.productId": {"$in": list(product_ids)}},
                     "cursorPaging": {"limit": WIX_VARIANT_PAGE_SIZE}}
        result = requester(WIX_VARIANTS_ENDPOINT, {"fields": ["CURRENCY"], "query": query})
        rows = result.get("variants") or []
        for row in rows:
            if not isinstance(row, Mapping) or row.get("visible") is False:
                continue
            product_id = str((row.get("productData") or {}).get("productId") or "")
            if product_id not in by_product:
                continue
            label = " / ".join(
                str((choice.get("optionChoiceNames") or {}).get("choiceName") or "")
                for choice in (row.get("optionChoices") or [])
                if isinstance(choice, Mapping)
                and (choice.get("optionChoiceNames") or {}).get("choiceName")) or "Standard"
            variant: Dict[str, Any] = {
                "id": str(row.get("variantId") or row.get("id") or ""),
                "label": label,
                "inStock": (row.get("inventoryStatus") or {}).get("inStock") is True,
                "choiceIds": [
                    f"{(choice.get('optionChoiceIds') or {}).get('optionId')}:{(choice.get('optionChoiceIds') or {}).get('choiceId')}"
                    for choice in (row.get("optionChoices") or [])
                    if isinstance(choice, Mapping)
                ],
            }
            media = row.get("media") or {}
            image = media.get("image") or {}
            image_url = str(image.get("url") or media.get("url") or "").strip()
            if image_url:
                variant["image"] = image_url
            amount = ((row.get("price") or {}).get("actualPrice") or {}).get("amount")
            try:
                variant["pricePaise"] = catalog.paise_from_major(amount)
            except (ValueError, ArithmeticError):
                pass
            by_product[product_id].append(variant)
        cursor = (((result.get("pagingMetadata") or {}).get("cursors") or {}).get("next") or "")
        if not rows or not cursor:
            break
    return by_product


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

    Covers the async invoke payload `wix-catalog-webhook` sends and an EventBridge scheduled
    event, and falls back to `unknown` for anything else rather than refusing: the correct
    response to any trigger is the same full re-read, so an unrecognised envelope must not become
    a missed sync.
    """
    if not isinstance(event, Mapping):
        return {"source": "unknown", "entityId": ""}
    if event.get("source") == "aws.events" or event.get("detail-type"):
        return {"source": "schedule", "entityId": ""}
    return {"source": str(event.get("source") or "unknown"),
            "entityId": str(event.get("entityId") or "")}


def handler(event, context, *, wix_requester=None, graph_requester=None,
            secret_reader=None, approval_store=None):  # noqa: ARG001 - Lambda signature
    """Compute the Wix -> Meta plan, log it, and write only if both gates are open.

    The three injection points default to `None` and resolve INSIDE, never as parameter defaults.
    A default argument is bound at definition time, so `reader=_read_secret` would make a patch of
    the module attribute ineffective - and in `wix-catalog-webhook` that exact mistake caused a
    test meant to simulate a missing credential to read the live one instead.
    """
    reader = secret_reader or _read_secret
    wix = wix_requester or _wix_request
    graph = graph_requester or _graph_request

    trigger = _trigger(event)
    catalog_id = os.environ.get("META_CATALOG_ID", META_CATALOG_ID)
    enabled = _enabled()
    dry_run = _dry_run()

    secret = reader(META_TOKEN_SECRET) or {}
    token = str(secret.get(META_TOKEN_FIELD) or "").strip()
    app_secret = str(secret.get("app_secret") or "").strip()
    if not token:
        # A fact about the secret ENTRY, which is a name - not about the credential. No boolean
        # derived from the value is logged either; "the configured field is empty" is reported by
        # naming the field, not by reporting what was in it.
        logger.error(json.dumps({"event": "meta_catalog_sync_unconfigured",
                                 "secretId": META_TOKEN_SECRET,
                                 "field": META_TOKEN_FIELD}))
        return {"ok": False, "reason": "unconfigured", "enabled": enabled,
                "dryRun": True, "catalogId": catalog_id, "applied": 0}

    if isinstance(event, Mapping) and isinstance(event.get("batchHandle"), str):
        status = graph(f"{catalog_id}/check_batch_request_status", method="GET",
                       params={"handle": event["batchHandle"]}, token=token, app_secret=app_secret)
        return {"readOnly": True, "batchStatus": status}

    try:
        products = _wix_products(wix)
        desired = catalog.desired_items(products, require_variant_price=True)
        existing = _existing_items(graph, token=token, app_secret=app_secret,
                                   catalog_id=catalog_id)
        # A scoped rollout must not publish or retire unrelated catalog variants.
        allowed = {value.strip().lower() for value in
                   os.environ.get("META_CATALOG_SYNC_VARIANT_IDS", "").split(",") if value.strip()}
        if allowed:
            desired = [item for item in desired
                       if (catalog.parse_retailer_id(item["retailer_id"]) or (None, None))[1] in allowed]
            existing = [item for item in existing
                        if not catalog.parse_retailer_id(item.get("retailer_id"))
                        or (catalog.parse_retailer_id(item.get("retailer_id")) or (None, None))[1] in allowed]
        if os.environ.get("META_CATALOG_SYNC_FORCE_OUT_OF_STOCK", "").lower() in _TRUE:
            for item in desired:
                item["availability"] = catalog.OUT_OF_STOCK
    except Exception as error:  # noqa: BLE001 - a read failure must not become a write attempt
        logger.error(json.dumps({"event": "meta_catalog_sync_read_failed",
                                 "errorType": type(error).__name__,
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
            approval_row = store.get(plan_hash)
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
        return {"ok": True, "enabled": enabled, "dryRun": True, "readOnly": True,
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
        row = store.get(requested)
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
        row = store.get(requested)
        if not requested or not row:
            return {"ok": False, "reason": "approval_not_found", "catalogId": catalog_id,
                    "currentPlanHash": plan_hash, "requestedPlanHash": requested, "applied": 0}
        verified = (
            not blocked and counts.get("create", 0) == 0
            and counts.get("update", 0) == 0 and counts.get("retire", 0) == 0
        )
        updated = store.record_readback(
            plan_hash=requested, current_plan_hash=plan_hash, counts=counts, verified=verified)
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
        # there is no payload in memory to send by accident.
        return {"ok": True, "enabled": enabled, "dryRun": True, "catalogId": catalog_id,
                "counts": counts, "blocked": blocked, "planHash": plan_hash,
                "approved": approved, "approval": _public_approval(approval_row), "applied": 0}

    if plan.is_empty:
        return {"ok": True, "enabled": True, "dryRun": False, "catalogId": catalog_id,
                "counts": counts, "blocked": blocked, "planHash": plan_hash,
                "approved": approved, "approval": _public_approval(approval_row), "applied": 0}

    if blocked:
        return {"ok": False, "reason": "blocked", "enabled": True, "dryRun": False,
                "catalogId": catalog_id, "counts": counts, "blocked": blocked,
                "planHash": plan_hash, "approved": approved, "applied": 0}

    # A schedule/webhook is never an APPLY command. Even if both release gates are opened later,
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
    finished = store.finish_apply(plan_hash=plan_hash, outcome=outcome)
    return {"ok": outcome["ok"], "enabled": True, "dryRun": False, "catalogId": catalog_id,
            "counts": counts, "blocked": blocked, "planHash": plan_hash,
            "approved": True, "approval": _public_approval(finished),
            "applied": outcome["applied"], "batchHandles": outcome.get("batchHandles", []),
            "validationErrors": outcome.get("validationErrors", []),
            "responseFields": outcome.get("responseFields", []),
            "validationStatus": outcome.get("validationStatus")}
