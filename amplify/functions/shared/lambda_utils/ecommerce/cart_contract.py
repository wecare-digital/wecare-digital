"""Provider-neutral cart contract: the vocabulary and pure helpers a cart surface needs.

The native cart paths — `service_requests`, `customer_cart`, the checkout handler's catch arms —
share this vocabulary (the `CartContractError` family) and these pure utilities (`identifier`,
`catalog_item`, `cheapest_delivery_option`, `delivery_address`). Nothing here performs I/O.

A cart line is identified by its ProductsTable product id and variant id, carried in the
`catalogReference` shape (`catalogItemId` + `options.variantId`) the website cart sends.
"""
from uuid import UUID

from .money import Money

_COUNTRY_LENGTH = 2

#: Every address field a cart surface will forward, and nothing else. An allowlist, so an
#: unrecognised key fails before a call rather than after it.
ADDRESS_FIELDS = ("country", "subdivision", "city", "postalCode",
                  "streetAddress", "addressLine", "addressLine2")

#: The minimum that makes an address a DESTINATION rather than a region. `subdivision` is the
#: Indian place-of-supply, so an address without it would price with the wrong CGST/SGST-vs-IGST
#: split.
REQUIRED_ADDRESS_FIELDS = ("country", "subdivision", "city", "postalCode")


class CartContractError(ValueError):
    """A cart is not safe to offer for payment."""


class CartItemUnavailable(CartContractError):
    """A line item is out of stock, partially available, or gone from the catalogue.

    Carries `.items` so the caller can tell the customer WHICH item and WHY. Surfaced as a
    violation rather than silently dropping the line and pricing what is left.
    """

    def __init__(self, message, items=None):
        super().__init__(message)
        self.items = list(items or ())


class CartGone(CartContractError):
    """The CART RESOURCE itself is absent (e.g. the stored pointer is stale/expired).

    Distinct from `CartItemUnavailable`: the pointer we hold is worthless, so the recovery is to
    DISCARD it and create a fresh cart from the current line items — not to ask the customer to
    remove an item. `.cart_id` carries the dead id for logging (a resource id, not PII).
    """

    def __init__(self, message, cart_id=""):
        super().__init__(message)
        self.cart_id = str(cart_id or "")


class CartQuantityReduced(CartContractError):
    """Fewer units were confirmed than requested, so the cart no longer means what was asked.

    A reduced quantity on a priced cart is a wrong amount for the wrong goods — a correctness
    failure, never a warning. Carries `.items` with the requested and confirmed figures so the
    customer can re-confirm deliberately.
    """

    def __init__(self, message, items=None):
        super().__init__(message)
        self.items = list(items or ())


def identifier(value):
    """A lowercased UUID string, or raise. The identity a cart/catalog line keys on."""
    if not isinstance(value, str) or str(UUID(value)) != value.lower():
        raise ValueError("invalid cart/catalog identifier")
    return value.lower()


def catalog_item(item):
    """Validate a `{productId, variantId, quantity}` line into a `catalogReference` shape.

    Nothing financial is accepted — a caller cannot smuggle a price or currency through a line.
    """
    if not isinstance(item, dict) or set(item) != {"productId", "variantId", "quantity"}:
        raise ValueError("only productId, variantId and quantity are accepted")
    quantity = item["quantity"]
    if type(quantity) is not int or not 1 <= quantity <= 100000:
        raise ValueError("quantity must be a positive integer")
    return {"catalogReference": {
        "catalogItemId": identifier(item["productId"]),
        "options": {"variantId": identifier(item["variantId"])}}, "quantity": quantity}


def cheapest_delivery_option(options):
    """The option to select when nobody chose one: lowest price, ties to the first.

    A DECISION about someone's money, named so it can be tested on its own. `None` for an empty
    list, so the caller decides what "no option offered" means rather than inheriting a default.
    """
    ordered = sorted(options or [],
                     key=lambda option: (option.get("pricePaise") is None,
                                         option.get("pricePaise") or 0))
    return ordered[0] if ordered else None


def delivery_address(address):
    """Validate a delivery address, or raise. Nothing financial is accepted."""
    if not isinstance(address, dict) or not address:
        raise ValueError("a delivery address object is required")
    unknown = set(address) - set(ADDRESS_FIELDS)
    if unknown:
        raise ValueError("unsupported delivery address fields")
    country = address.get("country")
    if (not isinstance(country, str) or len(country) != _COUNTRY_LENGTH
            or not country.isalpha() or country != country.upper()):
        raise ValueError("country must be an uppercase ISO 3166-1 alpha-2 code")
    out = {}
    for field in ADDRESS_FIELDS:
        if field not in address:
            continue
        value = address[field]
        if field == "streetAddress":
            if not isinstance(value, dict) or not value or not all(
                    isinstance(part, str) and part.strip() for part in value.values()):
                raise ValueError("streetAddress must be an object of non-empty strings")
            out[field] = dict(value)
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        out[field] = value.strip()
    missing = [field for field in REQUIRED_ADDRESS_FIELDS if field not in out]
    if missing:
        raise ValueError(f"delivery address is missing {', '.join(missing)}")
    if not (out.get("addressLine") or out.get("streetAddress")):
        raise ValueError("delivery address needs a street line")
    return out


def available_delivery_options(summary):
    """Delivery options a price `summary` offers, cheapest first.

    `[{"id", "title", "pricePaise"}]`, or `[]`. `pricePaise` is integer paise via `Money.from_decimal_string`
    (never a float) and `None` when no parseable amount was sent — unknown rather than zero, so a
    missing price cannot silently read as free. An unpriced option sorts LAST. Stable sort, so the
    source order survives a tie.
    """
    delivery = (summary or {}).get("deliverySummary") or {}
    method = delivery.get("method") or {}
    code = str(method.get("code") or "").strip()
    if not code:
        return []
    try:
        price = Money.from_decimal_string((delivery.get("price") or {}).get("amount")).paise
    except ValueError:
        price = None
    title = method.get("title")
    if isinstance(title, dict):
        title = title.get("original") or title.get("translated") or ""
    return [{"id": code, "title": str(title or ""), "pricePaise": price}]
