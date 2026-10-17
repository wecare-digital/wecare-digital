"""A native catalogue descriptor + line builders for the Phase-2 contribution/service tests.

The checkout handler prices every basket off ProductsTable through `_native_quote`. What the
contribution and service tests need is the real catalogue identifiers (imported from
blog_contribution, never invented), the small `catalogReference` line builders the browser's
basket shape uses, and a lightweight `NativeCatalog` descriptor that carries a
product -> variant -> price registry for `contribution_env.make_env` to build a native
`_native_product_reader` from.

Nothing here reaches AWS, the network or a credential. All catalog identifiers in this helper are synthetic and exist only in tests. Production
contribution configuration is intentionally empty until the fresh SKU-first item is created.
"""

from __future__ import annotations

import copy
import pathlib
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/shared"))

#: Synthetic contribution identity used only by tests. Production contribution mappings are empty
#: until the fresh SKU-first Contribute item is created.
CONTRIBUTION_ID = "77777777-7777-4777-8777-777777777777"
CONTRIBUTION_VARIANT = "7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a"
CONTRIBUTION_CHOICES = {CONTRIBUTION_VARIANT: 25000}
CONTRIBUTION_VARIANTS = (CONTRIBUTION_VARIANT,)

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


class NativeCatalog:
    """A native catalogue descriptor. It carries a product -> variant -> price registry that
    `contribution_env.make_env` turns into a `_native_product_reader`.

    The native supply engine prices from the per-variant catalogue only (GST-inclusive, free
    shipping), so a basket prices at its line total. The per-line service price guard is
    asserted at the pure-unit layer (`service_requests.native_service_line_paise`).
    """

    def __init__(self, *, product_type: Optional[Dict[str, str]] = None,
                 in_stock: bool = True):
        self.product_type = dict(product_type or PRODUCT_TYPE)
        #: product_id -> [variant ids]. A copy so a test can teach it the services product.
        self.variants = {key: list(value) for key, value in VARIANTS.items()}
        self.in_stock = in_stock

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


def register_product(descriptor: "NativeCatalog", product_id: str, variant_id: str, *,
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
    return {"catalogReference": {"catalogItemId": CONTRIBUTION_ID,
                                 "options": {"variantId": variant}},
            "quantity": quantity}


def contribution_paise(variant: str = CONTRIBUTION_VARIANT) -> int:
    """What a contribution on `variant` must collect, in integer paise."""
    return CONTRIBUTION_CHOICES[variant]


def kiosk_line(quantity: int = 1) -> Dict[str, Any]:
    return {"catalogReference": {"catalogItemId": KIOSK_ID,
                                 "options": {"variantId": KIOSK_VARIANT}},
            "quantity": quantity}


def other_line(quantity: int = 1) -> Dict[str, Any]:
    return {"catalogReference": {"catalogItemId": OTHER_ID,
                                 "options": {"variantId": OTHER_VARIANT}},
            "quantity": quantity}


def saved(product_id: str, variant_id: str, quantity: int) -> Dict[str, Any]:
    return {"productId": product_id, "variantId": variant_id, "quantity": quantity}
