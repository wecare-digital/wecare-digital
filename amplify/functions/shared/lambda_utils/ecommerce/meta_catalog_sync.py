"""Wix -> Meta catalogue projection: the retailer-id contract, the item shape and the diff.

PHASE W, FEAT-001. Design decisions D2, D3 and D4 of
`.agents/tasks/phase-w-whatsapp-commerce-20261006/plan.md`; the measurements behind them are in
that task's `findings.md` section 1.

PURE, AND THAT IS THE POINT
---------------------------
No boto3 client, no network, no environment read, no clock. Every input arrives as an argument,
exactly like `initiation.py` and `finalization.py`. So the whole of "what would we send to Meta,
and what would change" is decidable offline against the committed snapshot
`src/content/wix-catalog.json`, which is how `tests/test_meta_catalog_sync.py` pins the 24-item
result without a credential. The Lambda in `ecommerce/meta-catalog-sync/` is the only thing that
talks to Wix or Meta, and it ships with both gates closed.

ONE DIRECTION ONLY: WIX -> META
-------------------------------
Wix is the single source of truth for products, variants, prices and availability. Meta is a
VIEW. Nothing here reads a Meta value back into Wix, and nothing here deletes a Meta item - see
`diff` for why a vanished Wix variant becomes `availability: out of stock` instead.

THE RETAILER ID IS THE JOIN, AND IT IS NOT A NEW IDEA
-----------------------------------------------------
`wix:<productId>:<variantId>` is exactly the `catalogReference` pair (`catalogItemId` plus
`options.variantId`) that `src/lib/cart.ts` `toLineItems()` and `checkout/handler.py`
`_v2_catalog_items` already use. So an order that arrives from WhatsApp carrying
`product_retailer_id` resolves to the same Wix line as an order placed on the website, with no
mapping table to keep in step. 77 characters against Meta's 100-character limit.

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

#: The namespace that marks an item as OURS. An item whose retailer id lacks it was created by
#: hand in the Meta catalog builder (`catalog-builder.tsx` free-types a SKU, e.g. `WD-PARTNER-UP`)
#: and this sync must report it and never touch it. See `diff`'s `foreign` bucket.
RETAILER_PREFIX = "wix"

#: Meta's documented ceiling for `retailer_id`. A pair of UUIDs plus the prefix is 77, so this is
#: headroom rather than a constraint - but it is asserted rather than assumed, because a Wix id
#: format change would otherwise fail at Meta instead of here.
RETAILER_ID_MAX_LENGTH = 100

#: Wix product and variant ids are canonical lowercase UUIDs. Anchored, so a value carrying a
#: colon cannot smuggle an extra segment past `parse_retailer_id`.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: Meta's availability vocabulary, which is not ours. Two literals in one place so no caller
#: spells them by hand.
IN_STOCK = "in stock"
OUT_OF_STOCK = "out of stock"

#: The currency this catalogue sells in. Compared EXPLICITLY, never inferred from an amount.
CURRENCY = "INR"

# Service payment vehicles have dedicated public routes and no /shop/<slug>/ page.
# Stable identities mirror src/config/services.ts; prices remain entirely Wix-owned.
SERVICE_PRODUCT_ID = "df976a0a-f582-4535-b2e1-d532f348bd27"
SERVICE_PATH_BY_VARIANT = {
    "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b": "/submit-request/",
    "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b": "/request-amendment/",
    "db166bc8-a763-41ec-9f65-0f718f18155a": "/drop-docs/",
    "dcff995e-448c-493a-9259-f6a82ccdc2b4": "/vault/",
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
# The exclusion lists.
#
# COPIED FROM `src/content/shop.ts:186-209`, VERBATIM AND DELIBERATELY NOT SHARED.
# `tests/test_meta_catalog_exclusion_parity.py` extracts both arrays from `shop.ts` by regex and
# asserts set equality with the copies below, so drift is a test failure rather than a silent
# divergence between the two channels.
#
# WHY A TEST RATHER THAN ONE SHARED JSON FILE (plan decision D4): `shop.ts` is concurrently owned
# by the phase-o1 and ui-native-replace worktrees. Moving the list into a file both sides import
# would mean editing their file; a parity test catches the same drift at the same cost and touches
# nothing they own.
#
# These twelve are the Wix store template's own demo products. They are `visible: true` real
# catalogue rows, so `scripts/fetch-wix-catalog.js` collects them, and `/shop/` filters them out
# rather than deleting anything from Wix. The Meta catalogue must agree with `/shop/`: publishing
# a template's sample data to a customer-visible WhatsApp catalogue would offer Baseball Caps for
# sale.
# ─────────────────────────────────────────────────────────────────────────────────────────────

WIX_TEMPLATE_SAMPLE_PRODUCT_IDS: Tuple[str, ...] = (
    "618dcfe4-8d85-40a9-87c6-0dea57abe644",  # Baseball Cap
    "af654225-662f-42e5-ac51-fbebc88f63ed",  # Ceramic Flower Vase
    "df8ae122-9a06-4fa2-96bb-4b058db5959f",  # Crew T-Shirt
    "f68519fb-2095-4dfc-8684-ec55d60c2adc",  # Essential Oil Diffuser
    "96ff5295-1660-40d1-89e4-d1f1a34309be",  # Foaming Facial Cleanser
    "ca71fee6-1fc9-4a57-8fa7-967c8edcaabb",  # Hydrating Eye Serum - Pre Order
    "99684dfe-d36a-4869-858a-dba67af9b993",  # Knitted Golf Sweater
    "fedfcb20-1ad2-405b-950b-e65112bb6222",  # Minimalist Tote Bag
    "d86d7bea-fe19-4654-a597-bfe8dd449407",  # Round Eyeglasses
    "42941ee7-1707-4b5d-a7d7-41e12da6ab9e",  # Solid Wood Chair
    "1190303d-1fb5-40ca-bb60-2d5c1af3ae97",  # Stainless Steel Water Bottle
    "d2dc8bef-0a26-414a-b1dc-7bbba867bc6a",  # Textured Loop Earrings
)

#: The same twelve by slug, so the exclusion survives a product being re-created in Wix with a new
#: id. Checked SECOND, because the id is the identity the catalogue keys on and cannot be edited in
#: the Wix dashboard while the slug can - the same ordering `isTemplateSampleRow` uses.
WIX_TEMPLATE_SAMPLE_SLUGS: Tuple[str, ...] = (
    "baseball-cap", "ceramic-flower-vase", "crew-t-shirt", "essential-oil-diffuser",
    "foaming-facial-cleanser", "hydrating-eye-serum", "knitted-golf-sweater",
    "minimalist-tote-bag", "round-eyeglasses", "solid-wood-chair",
    "stainless-steel-water-bottle", "textured-loop-earrings",
)

#: The contribution vehicle, and it is INCLUDED here while `/shop/` excludes it. That difference is
#: deliberate, not an oversight: `shop.ts` `isContributionRow` keeps it out of the `/shop/` GRID
#: because the place to choose a contribution is the block at the foot of a blog post - but it is a
#: real, sellable product reached by direct cart reference, and the owner's catalogue list names
#: it. Its three variants remain subject to checkout's own variant allow-list and quantity-1 rule.
CONTRIBUTION_PRODUCT_ID = "8514c405-3971-4786-ad0d-15406ca23407"

_SAMPLE_IDS = frozenset(WIX_TEMPLATE_SAMPLE_PRODUCT_IDS)
_SAMPLE_SLUGS = frozenset(WIX_TEMPLATE_SAMPLE_SLUGS)

#: Stripped from `descriptionHtml`. Wix stores description as HTML; Meta wants plain text.
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class RetailerIdError(ValueError):
    """A product/variant pair cannot be expressed as a retailer id. Refuse rather than truncate."""


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The retailer-id contract
# ─────────────────────────────────────────────────────────────────────────────────────────────


def retailer_id(product_id: Any, variant_id: Any) -> str:
    """`wix:<productId>:<variantId>`, lowercased. Raises on anything that is not two UUIDs.

    REFUSES RATHER THAN NORMALISES ANYTHING BUT CASE. A retailer id is the join key between a
    WhatsApp order line and a Wix catalogue line, so a value that is nearly right is worse than no
    value: it would create a Meta item nothing can resolve, and the resolution failure would show
    up at order time as "we cannot price this line" rather than here.

    Lowercasing is safe and necessary: Wix emits canonical lowercase UUIDs, and Meta's retailer id
    is case-sensitive, so one upper-case character anywhere in the pipeline would fork the item.
    """
    product = str(product_id or "").strip().lower()
    variant = str(variant_id or "").strip().lower()
    if not _UUID_RE.match(product):
        raise RetailerIdError("product id is not a Wix UUID")
    if not _UUID_RE.match(variant):
        raise RetailerIdError("variant id is not a Wix UUID")
    value = f"{RETAILER_PREFIX}:{product}:{variant}"
    if len(value) > RETAILER_ID_MAX_LENGTH:
        # Unreachable with today's UUIDs (77 characters), and asserted anyway so a Wix id format
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
    if not text.startswith(f"{RETAILER_PREFIX}:"):
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    _, product, variant = parts
    if not _UUID_RE.match(product) or not _UUID_RE.match(variant):
        return None
    return product, variant


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Which Wix rows become Meta items
# ─────────────────────────────────────────────────────────────────────────────────────────────


def is_syncable(product: Mapping[str, Any]) -> bool:
    """Should this Wix snapshot row be projected into the Meta catalogue?

    Two exclusions and no more. Id first, slug second, both `.strip().lower()`, mirroring
    `isTemplateSampleRow` in `src/content/shop.ts`:

    1. a Wix template sample row - see the list above;
    2. `visible is False` - identity against `False`, not truthiness, so an ABSENT `visible` key
       means visible. Wix omits the field on some reads and treating absence as hidden would empty
       the catalogue on a shape change.
    """
    if not isinstance(product, Mapping):
        return False
    identifier = str(product.get("id") or "").strip().lower()
    slug = str(product.get("slug") or "").strip().lower()
    if identifier in _SAMPLE_IDS or slug in _SAMPLE_SLUGS:
        return False
    if product.get("visible") is False:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────────────────────
# Money: integer paise in, a display string out, no float at any point
# ─────────────────────────────────────────────────────────────────────────────────────────────


def paise_from_major(value: Any) -> int:
    """A Wix decimal-string amount in major units (`"1199.00"`) -> integer paise.

    `Decimal(str(value))`, never float, and a value that is not an exact whole number of paise is
    REFUSED rather than rounded - the same rule `lambda_utils/wix_ecom.to_paise` applies, for the
    same reason: a fractional paise in a catalogue price is a data error, and rounding it here
    would plant a one-paise mismatch for the checkout comparison to fail closed on later.
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
    """Wix's description as plain text, or the same name-based tagline `/shop/` falls back to.

    Borrowed from `shop.ts` `fallbackTagline` on purpose, so the two channels describe an
    uncopywritten product with the same sentence rather than two slightly different ones. It
    invents no claim - it states the product's own name.
    """
    text = _plain_text(product.get("descriptionHtml"))
    if text:
        return text
    return f"{name} from WECARE.DIGITAL." if name else "A product from WECARE.DIGITAL."


def _image_url(product: Mapping[str, Any]) -> str:
    """The product's public image URL, or `""`.

    `image` is the key `scripts/fetch-wix-catalog.js` emits and `shop.ts` reads; `imageUrl` is
    accepted too because the live Catalog V3 read the Lambda performs names it that way. EVERY ONE
    of the ten real products carries `mediaCount: 0` in the committed snapshot, so in practice this
    returns `""` for all of them today - which is what `blockers` reports. Nothing here invents a
    placeholder: an item with a made-up image would pass Meta commerce review under false pretences.
    """
    for key in ("image", "imageUrl"):
        value = str(product.get(key) or "").strip()
        if value:
            return value
    return ""


def _variant_price_paise(product: Mapping[str, Any], variant: Mapping[str, Any],
                         *, require_variant_price: bool) -> int:
    """The variant's own price in paise, falling back to the product's when permitted.

    THE FALLBACK IS AN OFFLINE-ONLY CONVENIENCE AND THE LIVE PATH REFUSES IT.
    `src/content/wix-catalog.json`'s variant rows carry `id`, `label` and `inStock` and no price at
    all - per-variant price needs `/stores/v3/products/query-variants`, which
    `scripts/fetch-wix-catalog.js:107` documents and the snapshot generator does not call. So for a
    product with a price RANGE (Contribute is 100-500, WECARE.DIGITAL Services 49-350) the
    product-level `price` is the minimum and would be wrong for most variants.

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
            "variant carries no price; query-variants must supply one before a Meta write")
    return paise_from_major(product.get("price"))


def desired_items(products: Iterable[Mapping[str, Any]], *,
                  require_variant_price: bool = False) -> List[Dict[str, Any]]:
    """The Meta catalogue this Wix catalogue implies: ONE ITEM PER WIX VARIANT.

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
            item: Dict[str, Any] = {
                "retailer_id": retailer_id(product_id, variant.get("id")),
                "item_group_id": product_id,
                "name": name,
                "description": _description(product, product_name),
                # Identity against `False`, like `is_syncable`: an absent `inStock` means in
                # stock, because Wix omits the field on some reads and defaulting to out of stock
                # would hide the whole catalogue on a shape change.
                "availability": OUT_OF_STOCK if variant.get("inStock") is False else IN_STOCK,
                "price": price_text(_variant_price_paise(
                    product, variant, require_variant_price=require_variant_price)),
                # Compared explicitly, never inferred from the amount. A Wix row that is not INR
                # is a configuration error this catalogue has no handling for, and `currency` is
                # one of `COMPARED_FIELDS` so it would surface as a permanent update rather than
                # a silent mis-sale.
                "currency": str(product.get("currency") or CURRENCY).strip().upper(),
                # NOT a Meta field. The grouping label `blockers` and the log line read; it cannot
                # reach Meta because `meta_payload` projects through `META_ITEM_FIELDS`.
                "product_name": product_name,
            }
            # Wix resolves option-choice media onto each read-only variant. Prefer it
            # so Submit Request and Vault do not inherit the same service artwork.
            image = _image_url(variant) or _image_url(product)
            if image:
                item["image_url"] = image
            # Same public route as scripts/fetch-wix-catalog.js and shopProductHref.
            # Wix supplies the slug; its editorless storefront domain stays internal.
            slug = str(product.get("slug") or "").strip()
            service_path = SERVICE_PATH_BY_VARIANT.get(str(variant.get("id") or ""))
            if product_id == SERVICE_PRODUCT_ID and service_path:
                item["url"] = f"https://wecare.digital{service_path}"
            elif product_id != SERVICE_PRODUCT_ID and slug and re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
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
    MEASURED against the committed snapshot: all ten real products carry `mediaCount: 0`, so today
    every real item is blocked and this returns all ten names. That is the honest state of the
    catalogue and it is reported rather than worked around - nothing here invents a placeholder
    image.

    REPORTED PER PRODUCT, NOT PER ITEM, and deduplicated on `item_group_id`: media belongs to the
    Wix product and all its variants share it, so ten lines name the ten things the owner has to
    fix while twenty-four would name the same ten twice over.
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
    """What it would take to make the Meta catalogue match Wix. Computes; never calls anything.

    A VANISHED WIX VARIANT IS RETIRED, NEVER DELETED. `retire` sets `availability: out of stock`
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
    "RETAILER_ID_MAX_LENGTH",
    "IN_STOCK",
    "OUT_OF_STOCK",
    "CURRENCY",
    "META_ITEM_FIELDS",
    "COMPARED_FIELDS",
    "WIX_TEMPLATE_SAMPLE_PRODUCT_IDS",
    "WIX_TEMPLATE_SAMPLE_SLUGS",
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
