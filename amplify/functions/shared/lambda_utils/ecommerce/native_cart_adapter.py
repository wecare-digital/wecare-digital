"""Native cart adapter — presents the cart-operation interface `CustomerCart` expects, backed by
the AWS-native `native_cart` (CartTable) and `native_checkout` pricing.

WHY THIS EXISTS. `CustomerCart.execute` (the phone-keyed lock/idempotency layer the WhatsApp
claim-basket and website customer-cart routes drive) calls
`create / get / add / set_quantity / remove / calculate` on an injected adapter, each returning a
cart dict shaped `{id, revision, lineItems:[{id, quantityInfo:{confirmedQuantity}}]}`, and
`calculate` returning `{cart, amountPaise, componentsPaise, calculationId, currency}`.

This adapter satisfies that exact contract over the native store; the checkout handler builds one
per request (`_native_cart_adapter`).

SHAPE TRANSLATION. native_cart stores `{cartId, lineItems:[{productId, variantId, quantity,
unitPricePaise}]}`. The `CustomerCart` layer only reads `cart["id"]`, `cart["revision"]`, and each
line's `id` + `quantityInfo.confirmedQuantity`, so `_project` maps:
    cartId        -> id
    updatedAt     -> revision   (monotonic working-doc revision; CustomerCart stores it)
    variantId     -> lineItemId (the variant id IS the stable line identity natively; set_quantity
                                 / remove on CustomerCart pass a `lineItemId` which maps straight
                                 back to the variant)
    quantity      -> quantityInfo.confirmedQuantity (and requestedQuantity; native never silently
                                 reduces, so the two are always equal — no CartQuantityReduced)

PRICING. `calculate` prices through `native_checkout.quote_native_cart` (server-authoritative,
free shipping policy by default, GST-inclusive catalog so gst_bps=0) and returns the paise total
plus the quote components, matching what `CustomerCart` persists as the snapshot.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping

from lambda_utils.ecommerce import native_cart, native_checkout, native_shipping
from lambda_utils.ecommerce.cart_contract import CartGone

#: TTL for a priced quote snapshot the adapter hands back (mirrors QUOTE_LIFETIME downstream).
_QUOTE_TTL_SECONDS = 300


class NativeCartAdapter:
    """A `CustomerCart`-compatible adapter over native_cart + native_checkout.

    `table` is the CartTable resource; `product_reader` is `product_id -> item | None` from
    ProductsTable (the same reader the native checkout uses). `customer_id` tags created carts.
    """

    def __init__(self, table: Any, product_reader, *, customer_id: str = "",
                 shipping_policy: native_shipping.ShippingPolicy = None):
        self.table = table
        self.product_reader = product_reader
        self.customer_id = customer_id
        self.shipping_policy = shipping_policy or native_shipping.ShippingPolicy()

    # -- shape translation -----------------------------------------------------
    @staticmethod
    def _project(cart: Mapping[str, Any]) -> Dict[str, Any]:
        """native_cart row -> the cart shape CustomerCart reads."""
        lines: List[Dict[str, Any]] = []
        for ln in cart.get("lineItems", []):
            qty = int(ln["quantity"])
            lines.append({
                "id": str(ln["variantId"]),  # variant id is the stable native line identity
                "productId": str(ln["productId"]),
                "variantId": str(ln["variantId"]),
                "quantityInfo": {"requestedQuantity": qty, "confirmedQuantity": qty},
            })
        return {
            "id": str(cart["cartId"]),
            # A monotonic revision for the lock layer; the native store uses updatedAt as the
            # working-doc version. Never 0 after a mutation, so CustomerCart's revision tracking
            # advances with every write.
            "revision": int(cart.get("updatedAt") or 0),
            "lineItems": lines,
        }

    def _get_row(self, cart_id: str) -> Dict[str, Any]:
        try:
            return native_cart.get(self.table, cart_id)
        except native_cart.CartNotFound as exc:
            # The cart row is gone: the pointer is worthless, so the caller DISCARDs it and
            # creates a fresh cart.
            raise CartGone("native cart not found", cart_id=cart_id) from exc

    # -- the CustomerCart adapter contract ------------------------------------
    def create(self, items) -> Dict[str, Any]:
        cart = native_cart.create(self.table, self.product_reader, items,
                                  customer_id=self.customer_id)
        return self._project(cart)

    def get(self, cart_id: str) -> Dict[str, Any]:
        return self._project(self._get_row(cart_id))

    def add(self, cart_id: str, item: Mapping[str, Any]) -> Dict[str, Any]:
        self._get_row(cart_id)  # CartGone if missing, before the mutate
        cart = native_cart.add(self.table, self.product_reader, cart_id, item)
        return self._project(cart)

    def set_quantity(self, cart_id: str, line_item_id: str, quantity: int) -> Dict[str, Any]:
        self._get_row(cart_id)
        # CustomerCart passes a lineItemId; natively the line identity IS the variant id.
        cart = native_cart.set_quantity(self.table, cart_id, line_item_id, quantity)
        return self._project(cart)

    def remove(self, cart_id: str, line_item_id: str) -> Dict[str, Any]:
        self._get_row(cart_id)
        cart = native_cart.remove(self.table, cart_id, line_item_id)
        return self._project(cart)

    def calculate(self, cart_id: str) -> Dict[str, Any]:
        """Price the cart server-side and return the snapshot shape CustomerCart persists."""
        row = self._get_row(cart_id)
        snapshot = native_checkout.quote_native_cart(
            {"cartId": row["cartId"], "lineItems": row.get("lineItems", [])},
            product_reader=self.product_reader,
            customer_id=self.customer_id or str(row.get("customerId") or ""),
            created_at=int(row.get("updatedAt") or 0),
            ttl_seconds=_QUOTE_TTL_SECONDS,
            shipping_policy=self.shipping_policy,
            gst_bps=0,  # catalog prices are GST-inclusive today
        )
        return {
            "cart": self._project(row),
            "amountPaise": snapshot.quote.total_payable_paise,
            "currency": "INR",
            "componentsPaise": snapshot.quote.components(),
            "calculationId": snapshot.snapshot_hash,
        }
