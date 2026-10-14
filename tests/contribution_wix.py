"""A native catalog descriptor + line builders for the Phase-2 contribution/service tests.

HISTORY: this module used to be a stateful Wix Cart V2 transport fake (it imported wix_ecom and
synthesised 404s through wix_ecom.http_error). The checkout handler is AWS-native now — it prices
every basket off ProductsTable through `_native_quote`, with no Wix cart and no Wix transport — so
the transport fake was retired. What survives is the part the live native tests still need: the
real catalogue identifiers (imported from blog_contribution, never invented) and the small
`catalogReference` line builders, plus a lightweight `ContributionWix` descriptor that carries a
product → variant → price registry for `contribution_env.make_env` to build a native
`_native_product_reader` from.

The descriptor keeps empty `.calls`/`.requests`/`.commands` lists so a native test asserting "no
Wix call was made" (`wix.calls == []`) reads true by construction — there is no transport to call.

Nothing here reaches AWS, the network, a credential, or wix_ecom. The contribution ids are the
real ones (blog_contribution), pinned against src/config/contribution.ts by
tests/test_blog_contribution.py::test_server_choices_mirror_the_frontend_contract.
"""

from __future__ import annotations

import copy
import pathlib
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/shared"))

from lambda_utils.ecommerce.blog_contribution import (  # noqa: E402
    CONTRIBUTION_CHOICES_PAISE, CONTRIBUTION_PRODUCT_IDS)

#: The live `Contribute` product, and a kiosk to stand beside it. Fixed GUIDs rather than random
#: ones, so a failure message names the same ids every run.
CONTRIBUTION_ID = sorted(CONTRIBUTION_PRODUCT_IDS)[0]

#: `{variant id: paise}` for the live choices, cheapest first, so a test can say "the low one"
#: without re-typing a GUID. DERIVED from the shipped allow-list rather than listed, which is why
#: the 2026-10-10 reduction to a single Rs.250 variant needed no edit here.
CONTRIBUTION_CHOICES = dict(sorted(CONTRIBUTION_CHOICES_PAISE.items(), key=lambda kv: kv[1]))
CONTRIBUTION_VARIANTS = tuple(CONTRIBUTION_CHOICES)
#: The default choice a helper reaches for: the cheapest, which is the only one today (Rs.250).
CONTRIBUTION_VARIANT = CONTRIBUTION_VARIANTS[0]

KIOSK_ID = "00d4c72b-f694-441a-a192-e16f4b192440"
KIOSK_VARIANT = "9f1c0e8a-1111-4222-8333-444455556666"
OTHER_ID = "2b3c4d5e-0000-4000-8000-000000000002"
OTHER_VARIANT = "2b3c4d5e-0000-4000-8000-000000000092"

CART_ID = "7c7f0f44-aaaa-4bbb-8ccc-dddddddddddd"
REPLACEMENT_CART_ID = "7c7f0f44-aaaa-4bbb-8ccc-eeeeeeeeeeee"

#: Unit prices in rupees, for products whose price does NOT vary by variant. The contribution is
#: absent on purpose: its price is per-VARIANT, which is the whole mechanism, and a per-product
#: entry would let a test pass while pricing every choice the same.
UNIT_RUPEES = {KIOSK_ID: 24999, OTHER_ID: 150}

#: The variants of each product the native product reader should resolve. The contribution carries
#: whatever the live allow-list declares — one variant since 2026-10-10.
VARIANTS: Dict[str, List[str]] = {CONTRIBUTION_ID: list(CONTRIBUTION_VARIANTS),
                                  KIOSK_ID: [KIOSK_VARIANT], OTHER_ID: [OTHER_VARIANT]}

STORES_APP_ID = "215238eb-22a5-4c36-9e7b-e7c08025e04e"

#: `productType` per product. EVERY product is PHYSICAL, including the contribution, because that
#: is what the live catalogue holds. Native shipping is free, so a PHYSICAL contribution still
#: prices at exactly its variant figure.
PRODUCT_TYPE = {CONTRIBUTION_ID: "PHYSICAL", KIOSK_ID: "PHYSICAL", OTHER_ID: "PHYSICAL"}


def unit_paise(product_id: str, variant_id: str) -> int:
    """The authoritative per-unit price in integer paise. Per-VARIANT for the contribution."""
    product_id = str(product_id)
    if product_id == CONTRIBUTION_ID:
        return CONTRIBUTION_CHOICES[str(variant_id)]
    return UNIT_RUPEES[product_id] * 100


class ContributionWix:
    """A native catalogue descriptor (NOT a transport). It carries a product → variant → price
    registry that `contribution_env.make_env` turns into a `_native_product_reader`, and empty
    `calls`/`requests`/`commands` lists so "no Wix call" assertions hold by construction.

    Pricing knobs (`tax_rupees`, `discount_rupees`, `delivery_rupees`, `fees_rupees`) are retained
    on the signature so existing callers keep their shape, but the native supply engine prices from
    the per-variant catalogue only (GST-inclusive, free shipping): adjustments a Wix cart used to
    compute no longer apply, and a basket that would have carried delivery/tax/fees simply prices
    at its line total. The services tests that asserted a delivery/tax/fee REFUSAL now assert that
    at the pure-unit layer (`service_requests.assert_service_line_price`), which is unchanged.
    """

    def __init__(self, *, lines: Optional[List[Dict[str, Any]]] = None,
                 delivery_address: Optional[Dict[str, Any]] = None,
                 product_type: Optional[Dict[str, str]] = None,
                 tax_rupees: int = 0, discount_rupees: int = 0,
                 delivery_rupees: int = 0, fees_rupees: int = 0,
                 coupons: Optional[list] = None, gift_cards: Optional[list] = None,
                 in_stock: bool = True, confirmed_delta: int = 0,
                 line_status: str = "IN_STOCK", variant_count: int = 0,
                 require_delivery_on_calculate: bool = False,
                 offered_delivery_options: Optional[List[Dict[str, Any]]] = None,
                 gone_cart_ids: Optional[List[str]] = None,
                 gone_product_ids: Optional[List[str]] = None):
        self.lines = [dict(line) for line in (lines or [])]
        self.delivery_address = copy.deepcopy(delivery_address) if delivery_address else None
        self.product_type = dict(product_type or PRODUCT_TYPE)
        #: product_id -> [variant ids]. A copy so a test can teach it the services product.
        self.variants = {key: list(value) for key, value in VARIANTS.items()}
        self.in_stock = in_stock
        self.tax_rupees = tax_rupees
        self.discount_rupees = discount_rupees
        self.delivery_rupees = delivery_rupees
        self.fees_rupees = fees_rupees
        self.coupons = coupons or []
        self.gift_cards = gift_cards or []
        self.cart_id = CART_ID
        #: There is no transport, so these stay empty — "no Wix call" is structural now.
        self.calls: List[tuple] = []
        self.requests: List[tuple] = []
        self.commands: List[tuple] = []
        self.created_carts: List[str] = []

    def product_rows(self) -> Dict[str, Dict[str, Any]]:
        """ProductsTable items for every product this descriptor knows, keyed by product id.

        Each row is `{id, status, variants: [{sku, priceMinor, inventory}]}`, the shape
        `native_cart._unit_price_paise` and `_native_product_reader` read. Prices come from
        `unit_paise`, so the services product's variants all price at `UNIT_RUPEES[PRODUCT]*100`
        and the contribution's variants price per-variant.
        """
        rows: Dict[str, Dict[str, Any]] = {}
        inventory = 50 if self.in_stock else 0
        for product_id, variant_ids in self.variants.items():
            rows[product_id] = {
                "id": product_id,
                "status": "active",
                "variants": [{"sku": variant_id,
                              "priceMinor": unit_paise(product_id, variant_id),
                              "inventory": inventory}
                             for variant_id in variant_ids],
            }
        return rows

    def reader(self):
        """A `product_id -> ProductsTable item | None` reader, as `_native_product_reader` returns."""
        rows = self.product_rows()

        def read(product_id):
            row = rows.get(str(product_id))
            return copy.deepcopy(row) if row is not None else None

        return read


def register_product(descriptor: "ContributionWix", product_id: str, variant_id: str, *,
                     unit_rupees: int = 10, product_type: str = "PHYSICAL") -> None:
    """Teach one descriptor about an extra catalogue product so a multi-line basket can be priced."""
    UNIT_RUPEES.setdefault(product_id, unit_rupees)
    descriptor.variants[product_id] = [variant_id]
    descriptor.product_type[product_id] = product_type


def contribution_line(variant: str = CONTRIBUTION_VARIANT, quantity: int = 1) -> Dict[str, Any]:
    """A browser `CheckoutLineItem` for one contribution. Note the TOP-LEVEL reference.

    `quantity` defaults to 1 and is a parameter only so a test can send a wrong one: a contribution
    is a fixed-price variant, so 1 is the only quantity the server accepts.
    """
    return {"catalogReference": {"appId": STORES_APP_ID, "catalogItemId": CONTRIBUTION_ID,
                                 "options": {"variantId": variant}},
            "quantity": quantity}


def contribution_paise(variant: str = CONTRIBUTION_VARIANT) -> int:
    """What a contribution on `variant` must collect, in integer paise."""
    return CONTRIBUTION_CHOICES[variant]


def kiosk_line(quantity: int = 1) -> Dict[str, Any]:
    return {"catalogReference": {"appId": STORES_APP_ID, "catalogItemId": KIOSK_ID,
                                 "options": {"variantId": KIOSK_VARIANT}},
            "quantity": quantity}


def other_line(quantity: int = 1) -> Dict[str, Any]:
    return {"catalogReference": {"appId": STORES_APP_ID, "catalogItemId": OTHER_ID,
                                 "options": {"variantId": OTHER_VARIANT}},
            "quantity": quantity}


def saved(product_id: str, variant_id: str, quantity: int) -> Dict[str, Any]:
    return {"productId": product_id, "variantId": variant_id, "quantity": quantity}
