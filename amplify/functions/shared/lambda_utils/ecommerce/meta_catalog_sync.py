"""ProductsTable -> Meta catalogue projection: the retailer-id contract, item shape and diff.

PHASE W, FEAT-001. Design decisions D2, D3 and D4 of
`.agents/tasks/phase-w-whatsapp-commerce-20261006/plan.md`; the measurements behind them are in
that task's `findings.md` section 1.

PURE, AND THAT IS THE POINT
---------------------------
No boto3 client, no network, no environment read, no clock. Every input arrives as an argument,
exactly like `initiation.py` and `finalization.py`. So the whole of "what would we send to Meta,
and what would change" is decidable offline against the committed storefront snapshot
`src/content/catalog-snapshot.json` (generated from ProductsTable by
`scripts/build-catalog-snapshot.py`), which is how `tests/test_meta_catalog_sync.py` pins the
item count without a credential. The Lambda in `ecommerce/meta-catalog-sync/` is the only thing
that reads ProductsTable for this projection or talks to Meta, and it ships with both gates
closed.

ONE DIRECTION ONLY: PRODUCTSTABLE -> META
-----------------------------------------
The AWS ProductsTable is the single source of truth for products, variants, prices and
availability. Meta is a VIEW. Nothing here reads a Meta value back into the catalogue, and
nothing here deletes a Meta item - see `diff` for why a vanished variant becomes
`availability: out of stock` instead.

THE RETAILER ID IS THE JOIN, AND IT IS NOT A NEW IDEA
-----------------------------------------------------
`<RETAILER_PREFIX>:<productId>:<variantId>` carries exactly the `catalogReference` pair
(`catalogItemId` plus `options.variantId`) that `src/lib/cart.ts` `toLineItems()` sends and
`checkout/handler.py` `_native_quote` prices. So an order that arrives from WhatsApp carrying
`product_retailer_id` resolves to the same ProductsTable line as an order placed on the website,
with no mapping table to keep in step. 88 characters against Meta's 100-character limit.

MONEY IS INTEGER PAISE AND THERE IS NO FLOAT IN THIS FILE
---------------------------------------------------------
`tests/test_meta_catalog_sync.py` walks this module's AST and fails on a float literal or a
`float()` call. A displayed price is composed from the integer by SLICING THE DIGITS
(`price_text`), not by dividing, so there is no point at which a binary fraction could enter. Any
stored number that arrives as a decimal string goes through `Decimal(str(value))`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

#: The retailer-id namespace. New Meta catalogue items are branded with WECARE.DIGITAL.
#: Existing live items and in-flight WhatsApp carts may still carry the historical `wix:`
#: namespace, so inbound parsing remains backward-compatible during migration. New writes MUST
#: use only `WECARE.DIGITAL:`.
#:
#: The migration is deliberately non-deleting: an approved sync creates the new
#: `WECARE.DIGITAL:` items and retires matching legacy `wix:` items by marking them out of
#: stock. Once the live Meta catalogue and all in-flight carts no longer contain legacy ids,
#: `"wix"` can be removed from `LEGACY_RETAILER_PREFIXES`.
#:
#: Known namespaces mark an item as OURS. An item whose retailer id carries none of them was
#: created independently (for example by the Meta catalog builder) and this sync reports it as
#: foreign and never touches it.
RETAILER_PREFIX = "WECARE.DIGITAL"

#: Prefixes accepted on READ. Values are lowercase because `parse_retailer_id` normalises input
#: before comparison; `retailer_id` still writes the branded `RETAILER_PREFIX` exactly.
LEGACY_RETAILER_PREFIXES = (RETAILER_PREFIX.lower(), "wix")

#: Meta's documented ceiling for `retailer_id`. A pair of UUIDs plus the prefix is 88, so this is
#: headroom rather than a constraint - but it is asserted rather than assumed, because a change to
#: the catalogue's id format would otherwise fail at Meta instead of here.
RETAILER_ID_MAX_LENGTH = 100

#: ProductsTable product ids and variant ids (the variant `sku`) are canonical lowercase UUIDs.
#: Anchored, so a value carrying a colon cannot smuggle an extra segment past `parse_retailer_id`.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: Meta's availability vocabulary, which is not ours. Two literals in one place so no caller
#: spells them by hand.
IN_STOCK = "in stock"
OUT_OF_STOCK = "out of stock"

#: The currency this catalogue sells in. Compared EXPLICITLY, never inferred from an amount.
CURRENCY = "INR"

# Service payment vehicles have dedicated public routes and no /shop/<slug>/ page.
# Stable identities mirror src/config/services.ts; prices come from ProductsTable like any other.
SERVICE_PRODUCT_ID = "df976a0a-f582-4535-b2e1-d532f348bd27"
SERVICE_PATH_BY_VARIANT = {
    "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b": "/submit-request/",
    "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b": "/request-amendment/",
    "db166bc8-a763-41ec-9f65-0f718f18155a": "/drop-docs/",
    "dcff995e-448c-493a-9259-f6a82ccdc2b4": "/vault/",
    # Added 2026-10-10 with the fifth service variant. A SERVICE VARIANT WITHOUT A ROUTE IS NOT A
    # COSMETIC GAP: `desired_items` omits `url` entirely for one, and `_batch_requests` in the
    # handler reads `item["url"]` to build Meta's `link` - so a routeless variant takes the whole
    # sync down with a KeyError rather than publishing a linkless item. The page this names is
    # src/pages/request-pickup.tsx, and this map is what decides the address it answers on.
    "8ee7e325-d772-4452-a993-5c79e927d42b": "/request-pickup/",
}

SERVICE_ARTWORK_BY_VARIANT = {
    "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b":
        "https://wecare.digital/get/o/stream/media/m/wd-catalog-live/submit-request-4096.png",
    "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b":
        "https://wecare.digital/get/o/stream/media/m/wd-catalog-live/request-amendment-4096.png",
    "db166bc8-a763-41ec-9f65-0f718f18155a":
        "https://wecare.digital/get/o/stream/media/m/wd-catalog-live/drop-docs-4096.png",
    "dcff995e-448c-493a-9259-f6a82ccdc2b4":
        "https://wecare.digital/get/o/stream/media/m/wd-catalog-live/vault-4096.png",
    "8ee7e325-d772-4452-a993-5c79e927d42b":
        "https://wecare.digital/get/o/stream/media/m/wd-catalog-live/request-pickup-4096.png",
}

# Customer-facing service copy is variant-specific; the shared product description
# contains operational details for several services and is not catalog copy.
SERVICE_COPY_BY_VARIANT = {
    "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b":
        ("Submit Request", "Get help with your existing order."),
    "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b":
        ("Request Amendment", "Request a change to your existing order."),
    "db166bc8-a763-41ec-9f65-0f718f18155a":
        ("Drop Docs", "Upload documents for your order."),
    "dcff995e-448c-493a-9259-f6a82ccdc2b4":
        ("Vault", "Access and download your documents."),
    "8ee7e325-d772-4452-a993-5c79e927d42b":
        # "Arrange", not "book": a collection depends on a courier agreeing to it, which is the
        # same claim /request-pickup/ makes. This wording is stack's and is kept as it stands.
        ("Request Pickup", "Arrange pickup of documents for your order."),
}

#: THE ONLY FIELDS THAT MAY REACH META, as an explicit allowlist rather than "whatever is in the
#: dict". An item also carries `product_name`, which is a grouping label for `blockers` and for
#: logs; projecting through `meta_payload` is what guarantees it cannot be sent as a product
#: attribute Meta does not have.
META_ITEM_FIELDS = (
    "retailer_id",
    "item_group_id",
    "name",
    "description",
    "availability",
    "price",
    "currency",
    "image_url",
    "url",
)

#: The fields a diff compares to decide "has this item changed". `item_group_id` is deliberately
#: absent: it is derived from the retailer id, so it cannot differ without the id differing, and
#: including it would make every comparison depend on a value Meta may normalise.
COMPARED_FIELDS = ("name", "description", "availability", "price", "currency", "image_url", "url")

# ─────────────────────────────────────────────────────────────────────────────────────────────
# Named catalogue rows.
#
# There is no product deny-list here. Whether a row reaches Meta is decided by the catalogue's own
# flags: `metaEnabled` in the Lambda's ProductsTable read (`_native_products` skips a row whose flag
# is False) and `visible` in `is_syncable`. Two rows are named below: the contribution vehicle,
# which is deliberately NOT special-cased, and the ₹1 test product, the one exception, excluded by
# slug for the reason its docstring gives.
# ─────────────────────────────────────────────────────────────────────────────────────────────

#: The contribution vehicle. Deliberately NOT special-cased here, although `/shop/` keeps it out of
#: its GRID (`shop.ts` `isContributionRow`) because the place to choose a contribution is the block
#: at the foot of a blog post: it is a real, sellable product reached by direct cart reference, so
#: whether the WhatsApp catalogue carries it is decided by its own catalogue flags like any other
#: row. Its variants remain subject to checkout's own variant allow-list and quantity-1 rule.
CONTRIBUTION_PRODUCT_ID = "8514c405-3971-4786-ad0d-15406ca23407"
CONTRIBUTION_CTA_URL = "https://wa.me/message/BYFLCAAMSZBXD1"

#: The ₹1 test product - a catalogue test row that is not this storefront and must never reach a
#: customer-facing WhatsApp catalogue, whatever its visibility flags say (it is also hidden from
#: /shop/ by `isTestProductRow` in shop.ts). Excluded BY SLUG ONLY (`1-test-product`),
#: deliberately NOT by id: the projection unit tests reuse this product's real id as a throwaway
#: fixture under neutral slugs ("x", "imageless", "wecaredigital-services"), and those fixtures
#: must stay syncable. The real row carries slug `1-test-product`, which the id-reuse fixtures
#: never do, so a slug gate drops exactly the real row and nothing else. It stays in ProductsTable
#: and in the committed snapshot (the generator owns that artifact); this keeps it out of the Meta
#: projection.
TEST_PRODUCT_SLUGS: Tuple[str, ...] = ("1-test-product",)

_TEST_PRODUCT_SLUGS = frozenset(TEST_PRODUCT_SLUGS)

#: Stripped from `descriptionHtml`. The catalogue stores the description as HTML; Meta wants plain
#: text.
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class RetailerIdError(ValueError):
    """A product/variant pair cannot be expressed as a retailer id. Refuse rather than truncate."""


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The retailer-id contract
# ─────────────────────────────────────────────────────────────────────────────────────────────


def retailer_id(product_id: Any, variant_id: Any) -> str:
    """`<RETAILER_PREFIX>:<productId>:<variantId>` with canonical lowercase UUIDs.

    REFUSES RATHER THAN NORMALISES ANYTHING BUT CASE. A retailer id is the join key between a
    WhatsApp order line and a ProductsTable line, so a value that is nearly right is worse than no
    value: it would create a Meta item nothing can resolve, and the resolution failure would show
    up at order time as "we cannot price this line" rather than here.

    Lowercasing is safe and necessary: the catalogue stores canonical lowercase UUIDs, and Meta's
    retailer id is case-sensitive, so one upper-case character anywhere in the pipeline would fork
    the item.
    """
    product = str(product_id or "").strip().lower()
    variant = str(variant_id or "").strip().lower()
    if not _UUID_RE.match(product):
        raise RetailerIdError("product id is not a catalogue UUID")
    if not _UUID_RE.match(variant):
        raise RetailerIdError("variant id is not a catalogue UUID")
    value = f"{RETAILER_PREFIX}:{product}:{variant}"
    if len(value) > RETAILER_ID_MAX_LENGTH:
        # Unreachable with today's UUIDs (88 characters), and asserted anyway so an id format
        # change fails here with a readable reason instead of at Meta with a 400.
        raise RetailerIdError(
            f"retailer id is {len(value)} characters, over Meta's {RETAILER_ID_MAX_LENGTH}")
    return value


def parse_retailer_id(value: Any) -> Optional[Tuple[str, str]]:
    """`(productId, variantId)` for one of ours, `None` for anything else.

    `None` IS THE SAFE ANSWER AND IT IS WHAT MAKES `foreign` WORK. Every id this returns `None`
    for is reported and never modified, so the set of things this sync can touch is exactly the
    set it can parse. That covers three cases on purpose:

    - a hand-made SKU from the catalog builder (`WD-PARTNER-UP`) - not ours, leave it;
    - an id carrying the prefix but not two UUIDs - ours in intention, broken in fact, and
      modifying it blind could overwrite an item we cannot identify;
    - an id with extra colon-separated segments - `_UUID_RE` is anchored, so it cannot pass.
    """
    text = str(value or "").strip().lower()
    parts = text.split(":")
    if len(parts) != 3:
        return None
    prefix, product, variant = parts
    if prefix not in LEGACY_RETAILER_PREFIXES:
        return None
    if not _UUID_RE.match(product) or not _UUID_RE.match(variant):
        return None
    return product, variant


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Which catalogue rows become Meta items
# ─────────────────────────────────────────────────────────────────────────────────────────────


def is_syncable(product: Mapping[str, Any]) -> bool:
    """Should this catalogue row (native ProductsTable projection or snapshot row) reach Meta?

    Two exclusions and no more:

    1. the ₹1 test product, BY SLUG ONLY (`1-test-product`, compared `.strip().lower()`) - not by
       id, unlike `isTestProductRow` in `src/content/shop.ts`, because the projection unit tests
       reuse its id as a fixture under neutral slugs that must stay syncable;
    2. `visible is False` - identity against `False`, not truthiness, so an ABSENT `visible` key
       means visible. Treating absence as hidden would empty the catalogue on a shape change.

    The Meta channel flag (`metaEnabled`) is applied before this, in the Lambda's ProductsTable
    read, so it is not repeated here.
    """
    if not isinstance(product, Mapping):
        return False
    slug = str(product.get("slug") or "").strip().lower()
    if slug in _TEST_PRODUCT_SLUGS:
        return False
    if product.get("visible") is False:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Money: integer paise in, a display string out, no float at any point
# ─────────────────────────────────────────────────────────────────────────────────────────────


def paise_from_major(value: Any) -> int:
    """A decimal-string amount in major units (`"1199.00"`) -> integer paise.

    `Decimal(str(value))`, never float, and a value that is not an exact whole number of paise is
    REFUSED rather than rounded: a fractional paise in a catalogue price is a data error, and
    rounding it here would plant a one-paise mismatch for the checkout comparison to fail closed
    on later.
    """
    try:
        rupees = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as error:
        raise ValueError(f"not a decimal amount: {value!r}") from error
    paise = rupees * 100
    if paise != paise.to_integral_value():
        raise ValueError(f"amount {value!r} is not a whole number of paise")
    whole = int(paise)
    if whole <= 0:
        raise ValueError(f"amount {value!r} is not positive")
    return whole


def price_text(paise: Any) -> str:
    """Integer paise -> `"1199.00"`, BY SLICING THE DIGITS.

        price_text(119900) -> '1199.00'
        price_text(100)    -> '1.00'
        price_text(5)      -> '0.05'

    No division and no float, so there is no rounding decision to get wrong and nothing a binary
    fraction can enter through. `rjust(3, "0")` is what makes a sub-rupee amount work: `"5"`
    becomes `"005"` and slices to `"0.05"`.
    """
    whole = int(paise)
    if whole <= 0:
        raise ValueError("a catalogue price must be positive")
    digits = str(whole).rjust(3, "0")
    return f"{digits[:-2]}.{digits[-2:]}"


def _normalized_price(value: Any) -> str:
    """Any price rendering -> the canonical `"1199.00"`, or `""` when it is not a price.

    Meta's `/{catalog_id}/products` read can return a price as a formatted string
    (`"₹1,199.00"`), so comparing Meta's rendering against ours directly would report an update on
    every single item forever. This strips everything that is not a digit or a decimal point and
    re-composes through `paise_from_major` + `price_text`, so the comparison is between two
    amounts rather than between two formats.

    EXACTLY WHAT META RETURNS HERE IS UNVERIFIED - no read has been made against either catalogue
    (findings section 1 records this as an open item). `""` for an unparseable value means such an
    item is treated as changed, which is the harmless direction while both gates are closed.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned or cleaned.count(".") > 1:
        return ""
    try:
        return price_text(paise_from_major(cleaned))
    except (ValueError, ArithmeticError):
        return ""


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The desired catalogue
# ─────────────────────────────────────────────────────────────────────────────────────────────


def _plain_text(html: Any) -> str:
    return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", str(html or ""))).strip()


def _description(product: Mapping[str, Any], name: str) -> str:
    """The catalogue description as plain text, or the name-based tagline `/shop/` falls back to.

    Borrowed from `shop.ts` `fallbackTagline` on purpose, so the two channels describe an
    uncopywritten product with the same sentence rather than two slightly different ones. It
    invents no claim - it states the product's own name.
    """
    text = _plain_text(product.get("descriptionHtml"))
    if text:
        return text
    return f"{name} from WECARE.DIGITAL." if name else "A product from WECARE.DIGITAL."


def _image_url(product: Mapping[str, Any]) -> str:
    """The row's public image URL, or `""`.

    `image` is the key the Lambda's ProductsTable read emits (the first `imageRefs` entry), the
    storefront snapshot carries and `shop.ts` reads; `imageUrl` is accepted too, for a row shaped
    that way. An imageless row returns `""`, which is what `blockers` reports. Nothing here
    invents a placeholder: an item with a made-up image would pass Meta commerce review under
    false pretences.
    """
    for key in ("image", "imageUrl"):
        value = str(product.get(key) or "").strip()
        if value:
            return value
    return ""


def _variant_price_paise(product: Mapping[str, Any], variant: Mapping[str, Any],
                         *, require_variant_price: bool) -> int:
    """The variant's own price in paise, falling back to the product's when permitted.

    THE FALLBACK IS AN OFFLINE-ONLY CONVENIENCE AND THE LIVE PATH REFUSES IT. The Lambda's
    ProductsTable read gives every priced variant its own `pricePaise`, straight from the
    variant's integer `priceMinor`. The committed storefront snapshot carries no per-variant price
    (its variant rows are `id`, `label` and `inStock`), and a row can still arrive without one - a
    variant with no `priceMinor`, or a hand-built fixture. For a product whose variants are priced
    differently (the Request services product, for one) the product-level `price` is a single
    figure and would be wrong for most variants.

    That is why `require_variant_price=True` - which the Lambda always passes - raises instead.
    The permissive default exists so the diff can be computed against the committed snapshot in a
    test with no credential, and the strict mode is what guarantees a wrong price can never be
    sent even if the gates were ever opened.
    """
    for key in ("pricePaise", "price_paise"):
        if key in variant:
            return int(variant[key])
    for key in ("price", "actualPrice"):
        if variant.get(key) not in (None, ""):
            return paise_from_major(variant.get(key))
    if require_variant_price:
        raise ValueError(
            "variant carries no price; the catalogue must supply one before a Meta write")
    return paise_from_major(product.get("price"))


def desired_items(products: Iterable[Mapping[str, Any]], *,
                  require_variant_price: bool = False) -> List[Dict[str, Any]]:
    """The Meta catalogue this product catalogue implies: ONE ITEM PER VARIANT.

    One item per variant rather than per product, because a variant is what a customer buys and
    what `catalogReference.options.variantId` names. `item_group_id = productId` groups them, so
    Meta can present `Merchandise` once with ten options rather than ten unrelated items. (Whether
    WhatsApp actually renders a variant picker for a grouped item is UNVERIFIED; at worst each
    variant shows as its own item, which still orders correctly - findings section 1.)

    `name` carries the variant label only when the product HAS more than one variant, so
    single-variant products read as `Kiosk` rather than `Kiosk - Standard`, and
    `Merchandise - Men's / XL` stays distinguishable in a list of ten.

    `image_url` is present as a KEY only when the source row has one, so an imageless product has
    no `image_url` at all rather than an empty string that would read as "cleared" on an update.

    A product with no variants is skipped rather than guessed at: there is no variant id to join
    on, so no retailer id can be formed, so no order could ever resolve back.
    """
    items: List[Dict[str, Any]] = []
    for product in products or []:
        if not is_syncable(product):
            continue
        product_id = str(product.get("id") or "").strip().lower()
        product_name = str(product.get("name") or "").strip()
        variants = [v for v in (product.get("variants") or []) if isinstance(v, Mapping)]
        if not variants:
            continue
        multi = len(variants) > 1
        for variant in variants:
            label = str(variant.get("label") or "").strip()
            name = f"{product_name} - {label}" if multi and label else product_name
            description = _description(product, product_name)
            if product_id == SERVICE_PRODUCT_ID:
                name, description = SERVICE_COPY_BY_VARIANT.get(
                    str(variant.get("id") or "").strip().lower(), (name, description))
            item: Dict[str, Any] = {
                "retailer_id": retailer_id(product_id, variant.get("id")),
                "item_group_id": product_id,
                "name": name,
                "description": description,
                # Identity against `False`, like `is_syncable`: an absent `inStock` means in
                # stock, because defaulting a row read without the field to out of stock would
                # hide the whole catalogue on a shape change.
                "availability": OUT_OF_STOCK if variant.get("inStock") is False else IN_STOCK,
                "price": price_text(_variant_price_paise(
                    product, variant, require_variant_price=require_variant_price)),
                # Compared explicitly, never inferred from the amount. A catalogue row that is not
                # INR is a configuration error this catalogue has no handling for, and `currency` is
                # one of `COMPARED_FIELDS` so it would surface as a permanent update rather than
                # a silent mis-sale.
                "currency": str(product.get("currency") or CURRENCY).strip().upper(),
                # NOT a Meta field. The grouping label `blockers` and the log line read; it cannot
                # reach Meta because `meta_payload` projects through `META_ITEM_FIELDS`.
                "product_name": product_name,
            }
            # Prefer the variant's linked image and fall back to the product image. The
            # 2026-10-11 snapshot carries linked artwork for all five Request variants, so this
            # preserves their distinct catalogue images while still handling ordinary one-image
            # products without inventing a placeholder.
            variant_id = str(variant.get("id") or "").strip().lower()
            image = (
                SERVICE_ARTWORK_BY_VARIANT.get(variant_id, "")
                if product_id == SERVICE_PRODUCT_ID
                else ""
            ) or _image_url(variant) or _image_url(product)
            if image:
                item["image_url"] = image
            # Same public route as `shopProductPath` in src/content/shop.ts: the row's
            # `canonicalPath` when it has one, else /shop/<slug>/. Both come from ProductsTable.
            slug = str(product.get("slug") or "").strip()
            service_path = SERVICE_PATH_BY_VARIANT.get(str(variant.get("id") or ""))
            if product_id == SERVICE_PRODUCT_ID and service_path:
                item["url"] = f"https://wecare.digital{service_path}"
            elif product_id == CONTRIBUTION_PRODUCT_ID:
                item["url"] = CONTRIBUTION_CTA_URL
            elif product_id != SERVICE_PRODUCT_ID:
                canonical_path = str(product.get("canonicalPath") or "").strip()
                if canonical_path.startswith("/") and "://" not in canonical_path:
                    item["url"] = "https://wecare.digital" + canonical_path
                elif slug and re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
                    item["url"] = f"https://wecare.digital/shop/{slug}/"
            items.append(item)
    return items


def meta_payload(item: Mapping[str, Any]) -> Dict[str, Any]:
    """An item projected onto the fields Meta accepts, and nothing else.

    An allowlist rather than a blocklist, so adding an internal field to an item can never widen
    what is transmitted. `product_name` is the field this exists to drop.
    """
    return {key: item[key] for key in META_ITEM_FIELDS if key in item}


def blockers(desired: Sequence[Mapping[str, Any]]) -> List[str]:
    """The products that cannot pass Meta commerce review, because they have no image.

    Meta rejects an imageless item, so publishing one is a review failure rather than a listing.
    The current state is MEASURED rather than assumed: `tests/test_meta_catalog_sync.py` pins it
    against the native ProductsTable read (every syncable product carries an image today). A
    missing image is reported rather than worked around - nothing here invents a placeholder.

    REPORTED PER PRODUCT, NOT PER ITEM, and deduplicated on `item_group_id`, so a multi-variant
    product with a missing image is named once rather than once per Meta item.
    """
    names: Dict[str, str] = {}
    for item in desired or []:
        if str(item.get("image_url") or "").strip():
            continue
        group = str(item.get("item_group_id") or "")
        names.setdefault(group, str(item.get("product_name") or item.get("name") or ""))
    return sorted(names.values())


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The diff
# ─────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SyncPlan:
    """What would change, in four buckets. There is no fifth bucket, and no `delete`.

    `create` / `update` carry full items; `update` and `retire` additionally carry `meta_id` when
    the existing Meta item reported an `id`, so a caller can address the item without re-querying.
    `foreign` carries retailer ids only - they are reported, never read into and never written.
    """

    create: List[Dict[str, Any]] = field(default_factory=list)
    update: List[Dict[str, Any]] = field(default_factory=list)
    retire: List[Dict[str, Any]] = field(default_factory=list)
    foreign: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Nothing to do. `foreign` does NOT count: it is a report, not an action."""
        return not (self.create or self.update or self.retire)

    def counts(self) -> Dict[str, int]:
        return {"create": len(self.create), "update": len(self.update),
                "retire": len(self.retire), "foreign": len(self.foreign)}

    def fingerprint(self) -> str:
        """A stable hash of the plan, so two log lines can be compared without diffing them.

        Sorted keys and sorted buckets, so an ordering change in either source does not look like
        a changed plan.
        """
        payload = {
            "create": sorted(json.dumps(meta_payload(i), sort_keys=True) for i in self.create),
            "update": sorted(json.dumps(meta_payload(i), sort_keys=True) for i in self.update),
            "retire": sorted(json.dumps(
                {k: v for k, v in i.items() if k in META_ITEM_FIELDS}, sort_keys=True)
                for i in self.retire),
            "foreign": sorted(self.foreign),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


def _comparable(item: Mapping[str, Any]) -> Dict[str, str]:
    """The compared fields, normalised, so a formatting difference is not a change."""
    out: Dict[str, str] = {}
    for key in COMPARED_FIELDS:
        value = item.get(key)
        if key == "price":
            out[key] = _normalized_price(value)
        else:
            out[key] = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    return out


def diff(desired: Sequence[Mapping[str, Any]],
         existing: Sequence[Mapping[str, Any]]) -> SyncPlan:
    """What it would take to make the Meta catalogue match ProductsTable. Computes only.

    A VANISHED VARIANT IS RETIRED, NEVER DELETED. `retire` sets `availability: out of stock`
    and nothing else. A delete would break an in-flight WhatsApp cart: the customer's cart holds a
    `product_retailer_id`, and if the item is gone the hand-off cannot resolve the line at all,
    which fails at checkout rather than at browse time. Out of stock is a state the whole pipeline
    already handles. There is no code path in this module that can produce a delete, which is a
    structural guarantee rather than a convention.

    A FOREIGN ITEM IS REPORTED AND LEFT ALONE. `parse_retailer_id` returning `None` is the test -
    see its docstring for the three cases that land here. The Meta catalogue is also edited by
    hand through `catalog-builder.tsx`, and a sync that tidied up what it did not recognise would
    delete someone's work.
    """
    by_retailer: Dict[str, Mapping[str, Any]] = {}
    foreign: List[str] = []
    for row in existing or []:
        if not isinstance(row, Mapping):
            continue
        raw = str(row.get("retailer_id") or "").strip()
        if parse_retailer_id(raw) is None:
            if raw:
                foreign.append(raw)
            continue
        by_retailer[raw.lower()] = row

    create: List[Dict[str, Any]] = []
    update: List[Dict[str, Any]] = []
    seen: set = set()

    for item in desired or []:
        key = str(item.get("retailer_id") or "").strip().lower()
        if not key:
            continue
        seen.add(key)
        current = by_retailer.get(key)
        if current is None:
            create.append(dict(item))
            continue
        if _comparable(current) != _comparable(item):
            changed = dict(item)
            meta_id = str(current.get("id") or "").strip()
            if meta_id:
                changed["meta_id"] = meta_id
            update.append(changed)

    retire: List[Dict[str, Any]] = []
    for key, row in by_retailer.items():
        if key in seen:
            continue
        if str(row.get("availability") or "").strip().lower() == OUT_OF_STOCK:
            # Already retired. Re-sending it would be a write that changes nothing, and a plan
            # that is never empty is a plan nobody reads.
            continue
        entry: Dict[str, Any] = {"retailer_id": str(row.get("retailer_id") or "").strip(),
                                 "availability": OUT_OF_STOCK,
                                 "product_name": str(row.get("name") or "")}
        meta_id = str(row.get("id") or "").strip()
        if meta_id:
            entry["meta_id"] = meta_id
        retire.append(entry)

    return SyncPlan(create=create, update=update, retire=retire, foreign=sorted(foreign))


__all__ = [
    "RETAILER_PREFIX",
    "LEGACY_RETAILER_PREFIXES",
    "RETAILER_ID_MAX_LENGTH",
    "IN_STOCK",
    "OUT_OF_STOCK",
    "CURRENCY",
    "META_ITEM_FIELDS",
    "COMPARED_FIELDS",
    "CONTRIBUTION_PRODUCT_ID",
    "RetailerIdError",
    "SyncPlan",
    "retailer_id",
    "parse_retailer_id",
    "is_syncable",
    "paise_from_major",
    "price_text",
    "desired_items",
    "meta_payload",
    "blockers",
    "diff",
]
