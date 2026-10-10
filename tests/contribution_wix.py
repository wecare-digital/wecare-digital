"""A stateful Cart V2 fake that knows about variant pricing, for the Phase-2 contribution tests.

Why a second fake rather than reusing `RecordingWix` from
`tests/test_checkout_cart_v2_authority.py`: that one replays ONE canned response for every call,
which is right for the money assertions it was written for and useless here. Phase 2's assertions
are about what happens to the cart BETWEEN calls -- a stale delivery address being abandoned, a
three-line diff being reconciled in a particular order, a contribution basket skipping the delivery
gate -- so the cart has to actually change when a command is issued.

It records `(method, endpoint)` in `calls` and `(method, endpoint, body)` in `requests`, matching
`RecordingWix`'s surface, so assertions read the same way in both files.

THE CONTRIBUTION IDS ARE THE REAL ONES, IMPORTED RATHER THAN INVENTED. `blog_contribution` holds
the committed product id and the committed variant ids, and `CONTRIBUTION_CHOICES_PAISE` is
read by the handler DIRECTLY rather than through a patchable seam -- so a fixture with made-up
variant ids would be refused as `UNKNOWN_CHOICE` and prove nothing. Importing them also means the
suite exercises the constants that ship. Their literal values are pinned against
src/config/contribution.ts by
tests/test_blog_contribution.py::test_server_choices_mirror_the_frontend_contract.
"""

from __future__ import annotations

import copy
import pathlib
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/shared"))

from lambda_utils import wix_ecom  # noqa: E402
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

#: The visible, in-stock variants of each product. A registry rather than a chain of conditionals,
#: because a product whose GET answers somebody else's variant id makes `resolved_catalog_lines`
#: raise "choose an available product option" -- a 502 that reads as a catalogue outage rather than
#: as a broken fixture. The contribution carries whatever the live allow-list declares -- one
#: variant since 2026-10-10.
VARIANTS: Dict[str, List[str]] = {CONTRIBUTION_ID: list(CONTRIBUTION_VARIANTS),
                                  KIOSK_ID: [KIOSK_VARIANT], OTHER_ID: [OTHER_VARIANT]}

STORES_APP_ID = "215238eb-22a5-4c36-9e7b-e7c08025e04e"

#: `productType` per product. EVERY product is PHYSICAL, including the contribution, because that
#: is what the live catalogue holds: a Wix digital product with no downloadable file attached is
#: not purchasable, so the owner created `Contribute` as PHYSICAL.
#:
#: THIS IS THE FIXTURE VALUE THAT USED TO HIDE A DEFECT. It read `DIGITAL` for the contribution,
#: which agreed with a server that decided "no delivery address needed" from `productType` -- so
#: the suite was green and the real product would have demanded an address for a donation. Tests
#: that care drive BOTH types through the `product_type` constructor argument and assert the
#: delivery skip is identical either way, which is what proves the skip comes from identity.
PRODUCT_TYPE = {CONTRIBUTION_ID: "PHYSICAL", KIOSK_ID: "PHYSICAL", OTHER_ID: "PHYSICAL"}


def unit_rupees(product_id: str, variant_id: str) -> int:
    """The unit price Wix would quote for one line. Per-VARIANT for the contribution."""
    product_id = str(product_id)
    if product_id == CONTRIBUTION_ID:
        # Integer division of an integer paise figure. No float anywhere in the fixture either --
        # a fake that priced in rupees-as-float could make a real paise bug invisible.
        return CONTRIBUTION_CHOICES[str(variant_id)] // 100
    return UNIT_RUPEES[product_id]


def _money(rupees: int) -> Dict[str, str]:
    return {"amount": f"{rupees}.00", "convertedAmount": f"{rupees}.00"}


class ContributionWix:
    """A Wix Cart V2 transport whose cart has state.

    `lines` is the live cart, as `[{productId, variantId, quantity}]`. `delivery_address` is what
    `deliveryInfo.address` holds, which is the field no Cart V2 call can clear and which the
    stale-delivery abandon exists for.
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
        #: Cart ids Wix answers 404 for, as the migrated site does for a cart minted against the
        #: old one. The failure is built by `wix_ecom.http_error`, the SAME constructor the real
        #: transport uses, so `.status` is present exactly as it is in production -- a fake that
        #: raised a bare `WixEcomError` would make the 404 recovery untestable by construction.
        self.gone_cart_ids = {str(value).lower() for value in (gone_cart_ids or ())}
        #: Product ids whose `GET /stores/v3/products/{id}` answers 404: a line whose item really
        #: is off the catalogue, which must still surface as "no longer available".
        self.gone_product_ids = {str(value).lower() for value in (gone_product_ids or ())}
        self.lines = [dict(line) for line in (lines or [])]
        self.delivery_address = copy.deepcopy(delivery_address) if delivery_address else None
        self.delivery_method: Optional[Dict[str, Any]] = (
            {"id": "11111111-2222-3333-4444-555555555555", "title": "Standard delivery"}
            if delivery_address else None)
        self.product_type = dict(product_type or PRODUCT_TYPE)
        self.variants = {key: list(value) for key, value in VARIANTS.items()}
        self.tax_rupees = tax_rupees
        self.discount_rupees = discount_rupees
        self.delivery_rupees = delivery_rupees
        self.fees_rupees = fees_rupees
        self.coupons = coupons or []
        self.gift_cards = gift_cards or []
        self.in_stock = in_stock
        self.confirmed_delta = confirmed_delta
        self.line_status = line_status
        #: EXTRA variants beyond the ones a product really has, for the "too many to guess" case.
        #: Zero by default now rather than one, because the registry above already carries the
        #: correct count per product.
        self.variant_count = variant_count
        self.require_delivery_on_calculate = require_delivery_on_calculate
        #: What `summary.deliverySummary` offers, as `[{"code", "appId", "title", "priceRupees"}]`.
        #: One option by default, matching the live site measured 2026-10-04: Wix resolves ONE
        #: applicable method for a cart plus address and reports it here even before any method is
        #: selected. `[]` is the delivery-region gap. Wix reports a single resolved method rather
        #: than a menu, so anything past the first entry is a shape this fake supports and the
        #: provider does not currently produce.
        self.offered_delivery_options = (
            [dict(option) for option in offered_delivery_options]
            if offered_delivery_options is not None
            else [{"code": "11111111-2222-3333-4444-555555555555",
                   "appId": "45c44b27-ca7b-4891-8c0d-1747d588b835",
                   "title": "Standard delivery", "priceRupees": delivery_rupees}])
        self.revision = 4
        self.cart_id = CART_ID
        #: True when this fake stands for a cart that ALREADY existed before the request -- the
        #: thing a seeded `CUSTOMERCART#` pointer names. A create against one must therefore mint
        #: a different id, which is what makes an abandon observable.
        self._pre_existing = bool(self.lines) or self.delivery_address is not None
        self.created_carts: List[str] = []
        self.calls: List[tuple] = []
        self.requests: List[tuple] = []
        #: `("quantity"|"add"|"remove", key_or_line_id, quantity)` in the order Wix saw them.
        self.commands: List[tuple] = []
        self._next_line = 1
        self._line_ids: Dict[tuple, str] = {}
        for line in self.lines:
            self._line_id(line, mint=True)

    # ── cart bookkeeping ────────────────────────────────────────────────────────

    def _key(self, line: Dict[str, Any]) -> tuple:
        return (str(line["productId"]).lower(), str(line["variantId"]).lower())

    def _line_id(self, line: Dict[str, Any], *, mint: bool = False) -> str:
        key = self._key(line)
        if key not in self._line_ids:
            if not mint:
                raise AssertionError(f"no line for {key}")
            self._line_ids[key] = f"00000000-0000-0000-0000-{self._next_line:012d}"
            self._next_line += 1
        return self._line_ids[key]

    def _find(self, line_id: str) -> Dict[str, Any]:
        for line in self.lines:
            if self._line_ids.get(self._key(line)) == line_id:
                return line
        raise AssertionError(f"unknown lineItemId {line_id}")

    def line_count(self) -> int:
        return len(self.lines)

    # ── response builders ───────────────────────────────────────────────────────

    def _name(self, line: Dict[str, Any]) -> str:
        if str(line["productId"]) == CONTRIBUTION_ID:
            return "Contribute \u20b9" + str(
                CONTRIBUTION_CHOICES[str(line["variantId"])] // 100)
        return "Kiosk"

    def _cart_body(self) -> Dict[str, Any]:
        items = []
        for line in self.lines:
            unit = unit_rupees(line["productId"], line["variantId"])
            quantity = int(line["quantity"])
            confirmed = quantity + self.confirmed_delta
            name = self._name(line)
            items.append({
                "id": self._line_id(line),
                "name": {"original": name, "translated": name},
                "quantityInfo": {"requestedQuantity": quantity,
                                 "confirmedQuantity": confirmed, "fixedQuantity": False},
                "pricing": {"unitPrice": _money(unit),
                            "totalPrice": _money(unit * quantity),
                            "priceUndetermined": False},
                "status": self.line_status,
                "paymentConfig": {"paymentOption": "FULL_PAYMENT_ONLINE"},
                "source": {"catalogReference": {
                    "catalogItemId": line["productId"], "appId": STORES_APP_ID,
                    "options": {"variantId": line["variantId"]}}},
            })
        delivery: Dict[str, Any] = {"weightUnit": "KG"}
        if self.delivery_address:
            delivery["address"] = copy.deepcopy(self.delivery_address)
        if self.delivery_method:
            delivery["method"] = copy.deepcopy(self.delivery_method)
        return {
            "id": self.cart_id, "revision": self.revision, "lineItems": items,
            "coupons": copy.deepcopy(self.coupons),
            "businessInfo": {"currencyCode": "INR"},
            "customerInfo": {"currencyCode": "INR"},
            "paymentInfo": {"currencyCode": "INR",
                            "giftCards": copy.deepcopy(self.gift_cards)},
            "deliveryInfo": delivery, "taxInfo": {}, "orderPlaced": False,
            "purchaseFlowId": "33333333-4444-5555-6666-777777777777",
            "demo": False,
        }

    def _subtotal_rupees(self) -> int:
        return sum(unit_rupees(line["productId"], line["variantId"]) * int(line["quantity"])
                   for line in self.lines)

    def _summary(self, cart: Dict[str, Any]) -> Dict[str, Any]:
        subtotal = self._subtotal_rupees()
        total = (subtotal - self.discount_rupees + self.delivery_rupees
                 + self.fees_rupees + self.tax_rupees)
        lines = [{"lineItemId": item["id"],
                  "quantity": item["quantityInfo"]["confirmedQuantity"],
                  "unitPrice": item["pricing"]["unitPrice"],
                  "totalPrice": item["pricing"]["totalPrice"]}
                 for item in cart["lineItems"]]
        payment: Dict[str, Any] = {
            "giftCards": copy.deepcopy(self.gift_cards), "memberships": [],
            "subscriptionCharges": [], "requiresPaymentAfterGiftCard": True,
            "totalAfterGiftCards": _money(total), "payNow": _money(total),
            "payLater": _money(0), "payAfterFreeTrial": _money(0)}
        violations = []
        if self.require_delivery_on_calculate and not self.delivery_method:
            violations = [{"scope": "OTHER", "code": "MISSING_DELIVERY_METHOD",
                           "severity": "ERROR"}]
        # `summary.deliverySummary` -- the field a live probe on 2026-10-04 confirmed as the one
        # that names the delivery option Wix offers for the address on the cart. Present whether
        # or not a method has been SELECTED, which is exactly the state `prepare_delivery` reads
        # it in. Absent entirely when nothing is offered, as the live pre-address cart shows.
        delivery_summary = None
        if self.offered_delivery_options:
            offered = self.offered_delivery_options[0]
            delivery_summary = {
                "method": {"code": offered["code"], "appId": offered.get("appId", ""),
                           "title": {"original": offered.get("title", ""),
                                     "translated": offered.get("title", "")},
                           "pickup": False},
                "price": _money(offered.get("priceRupees", 0)),
            }
        return {
            "cartId": cart["id"], "cartRevision": cart["revision"],
            "calculationId": "calc-1", "lineItems": lines,
            **({"deliverySummary": delivery_summary} if delivery_summary else {}),
            "priceSummary": {
                "subtotal": _money(subtotal), "discount": _money(self.discount_rupees),
                "delivery": _money(self.delivery_rupees),
                "additionalFees": _money(self.fees_rupees),
                "tax": _money(self.tax_rupees), "total": _money(total)},
            "paymentSummary": payment,
            "priceVerificationToken": "token-1", "calculationErrors": {},
            "spiViolations": [], "violations": violations,
        }

    # ── transport ───────────────────────────────────────────────────────────────

    def __call__(self, endpoint, method="GET", body=None):
        method = method.upper()
        self.calls.append((method, endpoint))
        self.requests.append((method, endpoint, copy.deepcopy(body)))

        # A cart Wix no longer has. Checked before every other branch so it covers the GET the
        # stale-delivery read, the basket backstop and the reconcile diff all share.
        #
        # Scoped to the GET, matching the live evidence (`GET /ecom/v2/carts/{id}` -> 404) and
        # matching where `CartV2` draws the distinction. A fake that 404'd the whole cart
        # namespace would be modelling "Wix carts are down", which is a different failure.
        if method == "GET" and endpoint.startswith("/ecom/v2/carts/"):
            addressed = endpoint[len("/ecom/v2/carts/"):].split("/")[0].split("?")[0]
            if addressed.lower() in self.gone_cart_ids:
                raise wix_ecom.http_error(method, endpoint, 404)

        if endpoint.startswith("/stores/v3/products/"):
            product_id = endpoint.rsplit("/", 1)[-1]
            if product_id.lower() in self.gone_product_ids:
                raise wix_ecom.http_error(method, endpoint, 404)
            variants = [{"id": variant_id, "visible": True,
                         "inventoryStatus": {"inStock": self.in_stock}}
                        for variant_id in self.variants.get(product_id, [OTHER_VARIANT])]
            for extra in range(self.variant_count):
                variants.append({"id": f"ffffffff-0000-4000-8000-{extra:012d}",
                                 "visible": True,
                                 "inventoryStatus": {"inStock": self.in_stock}})
            return {"product": {
                "id": product_id, "visible": True,
                "productType": self.product_type.get(product_id, "PHYSICAL"),
                "variantsInfo": {"variants": variants}}}

        if endpoint == "/ecom/v2/carts" and method == "POST":
            # A create REPLACES the cart contents with the requested basket, which is what
            # `CustomerCart.ensure` relies on: the replacement cart is created already holding it.
            #
            # A create always mints a DIFFERENT cart id from the one in hand, because that is the
            # property the stale-delivery abandon depends on -- a replacement that reused the id
            # would make "the address is gone" indistinguishable from "the cart was mutated".
            self.cart_id = (REPLACEMENT_CART_ID
                            if (self.created_carts or self._pre_existing) else CART_ID)
            self.created_carts.append(self.cart_id)
            # `CartV2.create` sends `{"catalogItems": [catalog_item(...)]}`, so the reference is
            # nested exactly as a request line nests it.
            self.lines = []
            self._line_ids, self._next_line = {}, 1
            for item in ((body or {}).get("catalogItems") or []):
                line = {"productId": item["catalogReference"]["catalogItemId"],
                        "variantId": item["catalogReference"]["options"]["variantId"],
                        "quantity": item["quantity"]}
                # WIX MERGES IDENTICAL CATALOGUE REFERENCES INTO ONE CART LINE, and modelling that
                # matters rather than being a convenience: a cart with two lines sharing one
                # `(catalogItemId, variantId)` key would be rejected by `calculate` itself
                # (`len(expected_quantities) != len(items)`), so a fake that kept them separate
                # would make a legitimate request look like a contract violation.
                existing = next((held for held in self.lines
                                 if self._key(held) == self._key(line)), None)
                if existing is not None:
                    existing["quantity"] += line["quantity"]
                    continue
                self.lines.append(line)
                self._line_id(line, mint=True)
            # A fresh cart carries no delivery address. That is the whole point of the abandon.
            self.delivery_address, self.delivery_method = None, None
            self.revision += 1
            return {"cart": self._cart_body()}

        if endpoint.endswith("/calculate") and method == "POST":
            cart = self._cart_body()
            return {"cart": cart, "summary": self._summary(cart)}

        if endpoint.endswith("/add-line-items"):
            for item in ((body or {}).get("catalogItems") or []):
                reference = item["catalogReference"]
                line = {"productId": reference["catalogItemId"],
                        "variantId": reference["options"]["variantId"],
                        "quantity": item["quantity"]}
                existing = next((held for held in self.lines
                                 if self._key(held) == self._key(line)), None)
                if existing is not None:
                    existing["quantity"] += line["quantity"]
                else:
                    self.lines.append(line)
                    self._line_id(line, mint=True)
                self.commands.append(("add", self._key(line), item["quantity"]))
            self.revision += 1
            return {"cart": self._cart_body()}

        if endpoint.endswith("/update-line-items"):
            for item in ((body or {}).get("lineItems") or []):
                line = self._find(item["lineItemId"])
                quantity = int(item["quantity"]["newQuantity"])
                line["quantity"] = quantity
                self.commands.append(("quantity", self._key(line), quantity))
            self.revision += 1
            return {"cart": self._cart_body()}

        if endpoint.endswith("/remove-line-items"):
            for line_id in ((body or {}).get("lineItemIds") or []):
                line = self._find(line_id)
                self.commands.append(("remove", self._key(line), 0))
                self._line_ids.pop(self._key(line), None)
                self.lines.remove(line)
            self.revision += 1
            # Wix's behaviour when the LAST line is removed is unverified, which is why the
            # reconcile never removes first. Modelled here as still returning a cart, so a test
            # that accidentally empties the cart fails on the line count rather than on a raise.
            return {"cart": self._cart_body()}

        if endpoint.endswith("/set-delivery-method"):
            # `{"deliveryMethod": {"code": ...}}`, the body Wix actually accepts -- measured
            # 2026-10-04. The previous spelling read `deliveryOptionId`, a field name the provider
            # answers with HTTP 400, and the `or` default hid that: the fake selected a method no
            # matter what it was sent, so a request shape the live API rejects passed here.
            code = (((body or {}).get("deliveryMethod") or {}).get("code") or "")
            if not code:
                raise AssertionError(
                    "set-delivery-method needs {'deliveryMethod': {'code': ...}}; "
                    f"got {sorted((body or {}))}")
            self.delivery_method = {"id": code, "title": "Standard delivery"}
            self.revision += 1
            return {"cart": self._cart_body()}

        if method == "PATCH":
            address = (((body or {}).get("cart") or {}).get("deliveryInfo") or {}).get("address")
            if address:
                self.delivery_address = copy.deepcopy(address)
            self.revision += 1
            return {"cart": self._cart_body()}

        # GET of the cart, and anything else that just wants the cart back.
        return {"cart": self._cart_body()}

    def paths(self) -> List[str]:
        return [path for _method, path in self.calls]

    def wrote(self) -> List[tuple]:
        """Every call that is not a read. A GET creates nothing and leaves nothing behind."""
        return [(method, path) for method, path in self.calls if method != "GET"]


def register_product(fake: "ContributionWix", product_id: str, variant_id: str, *,
                     unit_rupees: int = 10, product_type: str = "PHYSICAL") -> None:
    """Teach one fake about an extra catalogue product, so a multi-line diff can be driven.

    Writes `UNIT_RUPEES` globally (it is read at response-build time and a per-instance copy would
    have to be threaded through `_summary`) and the variant and type per instance.
    """
    UNIT_RUPEES.setdefault(product_id, unit_rupees)
    fake.variants[product_id] = [variant_id]
    fake.product_type[product_id] = product_type


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
