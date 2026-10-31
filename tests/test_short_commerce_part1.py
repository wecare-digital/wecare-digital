"""Source-bound website checkout contracts. No AWS, provider or customer traffic."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CART = (ROOT / "src/lib/cart.ts").read_text(encoding="utf-8")
PAGE = (ROOT / "src/components/cart/CartPage.tsx").read_text(encoding="utf-8")
CHECKOUT = (ROOT / "src/pages/checkout/index.tsx").read_text(encoding="utf-8")
CART_COMPAT = (ROOT / "src/pages/cart.tsx").read_text(encoding="utf-8")
WHATSAPP = (ROOT / "src/pages/checkout/whatsapp.tsx").read_text(encoding="utf-8")
HANDLER = (ROOT / "amplify/functions/ecommerce/checkout/handler.py").read_text(encoding="utf-8")
ORDER = (ROOT / "src/components/orders/OrdersPage.tsx").read_text(encoding="utf-8")
INVOICE = (ROOT / "src/lib/customerInvoice.ts").read_text(encoding="utf-8")
STATUS_PAGE = (ROOT / "src/pages/checkout/status.tsx").read_text(encoding="utf-8")
SERVICE = (ROOT / "src/lib/serviceEntry.ts").read_text(encoding="utf-8")


def between(source, begin, end):
    assert begin in source and end in source
    return source.split(begin, 1)[1].split(end, 1)[0]


def test_canonical_checkout_is_not_a_redirect_and_cart_is_compatible():
    assert "import CartPage" in CHECKOUT and "export default CartPage" in CHECKOUT
    assert "window.location.replace" in CART_COMPAT
    assert "/checkout/" in CART_COMPAT
    assert "basketTokenFromUrl" in CART_COMPAT
    assert "export const CHECKOUT_PATH = '/checkout/';" in SERVICE
    assert "href=\"/checkout/\"" in STATUS_PAGE


def test_full_website_cart_preserves_all_lines_and_selected_quantities():
    writer = between(CART, "export function addItem (", "export function availableVariantsForItem")
    assert "writeCart( result )" in writer
    assert "[ ...current, selected ]" in writer
    lines = between(CART, "export function toLineItems (", "/* ── Phase O-1 services:")
    assert "quantity: item.quantity" in lines
    assert "catalogReference:" in lines
    assert "formattedPrice" not in lines
    assert "amountPaise" not in lines


def test_quote_is_read_only_and_does_not_create_payment_attempt():
    quote = between(HANDLER, "def _website_quote(", "def _website_prepare(")
    assert 'action == "quote"' in HANDLER
    assert "_website_snapshot(identity, line_items" in quote
    assert "_website_invoice_lines(snapshot)" in quote
    assert "_order_charges(spec, items" in quote
    for forbidden in ("_reserve_website_attempt(", "create_order(", "prepare_checkout(",
                      "new_payment_attempt_id(", "_send_order_details("):
        assert forbidden not in quote
    assert '"QUOTE_READY"' in quote
    assert "return _hardened(cors_response(" not in quote or "_hardened(cors_response(code, data, origin))" in quote


def test_website_allows_full_basket_but_native_policy_stays_separate():
    website = between(HANDLER, "def _website_prepare(", "def _load_attempt_via(")
    assert "short_purchase.one_unit_lines(line_items)" not in website
    native = between(HANDLER, "def _create(", "def _status(")
    assert "short_purchase.one_unit_lines" in native
    assert "/checkout/whatsapp/" in PAGE
    assert "no payment or message" in WHATSAPP.lower()
    assert "fetch(" not in WHATSAPP and "Razorpay" not in WHATSAPP


def test_payment_matches_reviewed_quote_before_opening_razorpay():
    assert "parseCheckoutQuote( body )" in PAGE
    assert "options.amountPaise !== expectedTotalPaise" in PAGE
    # Prior live Lambda falls back to a CREATE for unknown actions. Never post
    # action:quote before the version-pinned backend is activated.
    assert "NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED" in PAGE
    assert "if ( !WEBSITE_FULL_CART_QUOTE_ENABLED )" in PAGE
    assert "return { kind: 'QUOTE_CHANGED' };" in PAGE
    assert "const expectedTotalPaise = quote.charges.totalPaise" in PAGE
    assert "quoteFor !== basketFingerprint( lineItems )" in PAGE
    assert "disabled={ busy || !quoteReady }" in PAGE
    assert "action: 'prepare'" in PAGE
    assert "proceed( 'whatsapp' )" not in PAGE
    assert "SHORT_COMMERCE_ONE_PRODUCT_MESSAGE" not in PAGE


def test_no_paid_order_claim_before_server_capture():
    assert "VERIFIED_PAID" in PAGE
    assert "clearCart();" in PAGE
    assert "goToCheckoutStatus(" in PAGE
    assert "isPaid( status )" in STATUS_PAGE
    assert "settlePaidCheckout( attemptId )" in STATUS_PAGE
    assert "Do not pay again." in STATUS_PAGE


def test_authenticated_order_table_and_real_invoice_download():
    assert '<table className="ord-table">' in ORDER
    assert "order.orderNumber" in ORDER
    assert '<OrderActionIcon name="download" />' in ORDER
    assert "downloadInvoice( order )" in ORDER
    assert 'const MY_INVOICE_URL = ' in ORDER
    assert "format: 'png'" in ORDER
    assert "isSignedInvoiceUrl" in ORDER
    assert "X-Amz-Signature" in ORDER
    assert "featureFlags.invoiceDownload" in ORDER
    assert "OrderDetail" not in ORDER
    assert "invoiceNumber" not in ORDER
    assert "charges.supplyGstPaise" not in ORDER
    assert "format: 'png'" in INVOICE
    assert "isSignedInvoiceUrl" in INVOICE
    assert "X-Amz-Signature" in INVOICE


def _isolated_checkout_dispatch():
    """Run actual checkout routing without importing AWS or any payment clients."""
    import ast
    from types import SimpleNamespace

    parsed = ast.parse(HANDLER)
    nodes = [node for node in parsed.body if
             isinstance(node, ast.FunctionDef) and node.name in ("_action", "handler")]
    assert len(nodes) == 2
    calls = []
    def _create_stub(*_args, **_kwargs):
        calls.append("create")
        return {"statusCode": 201, "body": {"outcome": "created"}}
    def _quote_stub(*_args, **_kwargs):
        calls.append("quote")
        return {"statusCode": 200, "body": {"status": "QUOTE_READY"}}

    namespace = {
        "Dict": dict, "Any": object,
        "extract_origin": lambda event: "",
        "options_response": lambda origin: {"statusCode": 200},
        "cors_response": lambda status, body, origin: {"statusCode": status, "body": body},
        "customer_auth": SimpleNamespace(
            require_customer=lambda event: (object(), None),
            CustomerNotAuthorized=type("CustomerNotAuthorized", (Exception,), {}),
            denied_response=lambda event: {"statusCode": 401}),
        "_body": lambda event: event.get("body", {}),
        "_hardened": lambda response: response,
        "_create": _create_stub,
        "_website_quote": _quote_stub,
        "_website_prepare": lambda *_: {"statusCode": 200, "body": "prepare"},
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "checkout_handler", "exec"), namespace)
    return namespace, calls


def test_explicit_unknown_checkout_action_cannot_create_a_payment():
    namespace, calls = _isolated_checkout_dispatch()
    event = {"requestContext": {"http": {"method": "POST"}},
             "rawPath": "/ecommerce/prepare-checkout",
             "body": {"action": "new-read-only-probe", "lineItems": [{"quantity": 1}]}}
    response = namespace["handler"](event, None)
    assert response == {"statusCode": 400, "body": {"error": "UNKNOWN_CHECKOUT_ACTION"}}
    assert calls == []
    assert namespace["_action"](event, event["body"]) == "unsupported"


def test_quote_stays_a_distinct_read_only_dispatch_and_explicit_create_still_works():
    namespace, calls = _isolated_checkout_dispatch()
    event = {"requestContext": {"http": {"method": "POST"}},
             "rawPath": "/ecommerce/prepare-checkout",
             "body": {"action": "quote", "lineItems": [{"quantity": 1}]}}
    assert namespace["handler"](event, None)["body"]["status"] == "QUOTE_READY"
    assert calls == ["quote"]
    event["body"]["action"] = "create"
    assert namespace["handler"](event, None)["statusCode"] == 201
    assert calls == ["quote", "create"]
    # Existing older clients without an explicit action still map to the intended path.
    event["body"].pop("action")
    assert namespace["_action"](event, event["body"]) == "prepare"


def test_retired_order_detail_read_never_returns_gst_or_creates_payment():
    """Old app clients must not retrieve an itemized receipt or trigger checkout."""
    namespace, calls = _isolated_checkout_dispatch()
    event = {"requestContext": {"http": {"method": "POST"}},
             "rawPath": "/ecommerce/checkout/status",
             "body": {"action": "order", "orderNumber": "WD-ORD-K5VB57VG"}}
    response = namespace["handler"](event, None)
    assert response["statusCode"] == 410
    assert response["body"] == {"error": "ORDER_DETAILS_RETIRED"}
    assert "invoiceNumber" not in str(response)
    assert "items" not in str(response)
    assert "charges" not in str(response)
    assert "delivery" not in str(response)
    assert calls == []
    assert namespace["_action"](event, event["body"]) == "order"
