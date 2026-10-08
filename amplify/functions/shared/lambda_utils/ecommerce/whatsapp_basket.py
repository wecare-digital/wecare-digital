"""The WhatsApp catalogue order, reduced to lines and quantities, so the website can price it.

WHAT THIS MODULE IS FOR
-----------------------
A customer taps "Send cart" in the WhatsApp catalogue and Meta delivers a `message.type ==
'order'`. That message is NOT an order and it is NOT a quote: it is a list of catalogue items the
customer's own client assembled, carrying prices that client happened to be showing. This module
turns it into a HAND-OFF - a phone-bound row naming variants and integer quantities and nothing
else - which the authenticated `claim-basket` action on `ecommerce/checkout` merges into the
customer's Wix cart. Pricing then happens exactly once, on the website leg, in
`checkout_pricing.compute_quote`, from a collection Wix itself calculated.

WHY `item_price` IS IGNORED ENTIRELY, WHICH IS THE WHOLE POINT OF THE MODULE
---------------------------------------------------------------------------
The path this replaces read `float(pi.get('item_price'))` and built a total from it: 18% GST added
to the goods (which Wix has already included), supply GST re-added per item, a convenience fee
logged at 2% against the 2.5% the rest of the system charges, and every `retailer_id` rewritten to
`ITEM_1..n` so a line could never be resolved back to the Wix variant it came from. Four separate
ways to produce a number that disagreed with the website's.

The fix is not a corrected second calculator. There is no total here at all:

  * `item_price` is read NOWHERE in this file. It is the customer's client's view of a price, and
    an amount a client can state is an amount a client can change.
  * No `float` appears anywhere, and a test walks this module's AST to keep it that way. Money is
    integer paise elsewhere in this repo; here it is simply absent.
  * The row this module builds has NO money field of any kind. `claimable()` and the claim action
    cannot leak a price, because there is none to leak.

So "the WhatsApp order was repriced wrongly" is not fixed by repricing it rightly - it is fixed by
there being exactly one place a payable can come from.

WHY THE RETAILER ID IS THE JOIN KEY
-----------------------------------
`meta_catalog_sync.retailer_id` publishes `wix:<productId>:<variantId>`, which is exactly the
`catalogReference` pair (`catalogItemId` plus `options.variantId`) that `cart_v2.catalog_item`
wants and that `src/lib/cart.ts` sends from the browser. So a line ordered in WhatsApp and the
same line ordered on the website resolve to one Wix cart line with no mapping table in between.
`parse_retailer_id` returning `None` is therefore the only "we cannot price this" answer this
module needs, and it is taken from that module rather than re-derived here.

PURE BY CONSTRUCTION
--------------------
No boto3, no `os.environ` read, no clock of its own - `now` is an argument. The handler that uses
this owns the table, the flag and the reply; this file owns the shape of the row and the rules for
claiming it, which is the part worth testing exhaustively.
"""
from __future__ import annotations

import re
import secrets
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import meta_catalog_sync, order_channel

#: The hand-off row's key prefix in CommerceKeys. Namespaced like every other row in that table
#: (`PAYREF#`, `ORDERNO#`, `CUSTOMERCART#`), because they share one partition key.
TOKEN_PREFIX = "WABASKET#"

#: The resolve-before-generate index: Meta's `wamid` -> the token already minted for it.
#:
#: WHY AN INDEX ROW RATHER THAN A DETERMINISTIC TOKEN. The token has to be BOTH unguessable (it
#: travels in a URL the customer opens, and it names a basket) and STABLE under replay (Meta
#: redelivers a webhook whenever our acknowledgement is lost, and a fresh token per delivery is a
#: second basket for one order). A random token is not stable; a token derived from the wamid is
#: stable but derived from a value that appears in our own logs and message store. So the token
#: stays random and the wamid gets its own index row, which is the same discipline
#: `REFERENCE#<metaReferenceId>` applies to a replayed Meta payment event: resolve before you
#: generate, so a replay lands on the row that already exists.
MESSAGE_INDEX_PREFIX = "WABASKETMSG#"

#: The claimed-channel pointer: one row per customer, naming the hand-off they most recently
#: claimed.
#:
#: WHY A POINTER EXISTS AT ALL. `checkout/handler.py::_claimed_handoff` has to answer "is this
#: prepare settling a WhatsApp basket?" from the SESSION, not from the request body - attribution a
#: browser can type is attribution a customer can forge, and `/orders` reports the word back as
#: fact. But CommerceKeys is keyed on `orderId` alone and carries no customer index, so there is no
#: way to find "this customer's claimed hand-off" by query, and a Scan is neither permitted by the
#: function's IAM nor acceptable on a checkout path. One keyed row per customer makes it a single
#: `GetItem`.
#:
#: LAST CLAIM WINS, deliberately, and the write is an unconditional put for that reason: the
#: channel describes the basket the customer is about to pay for, and that is the one they claimed
#: most recently.
CLAIM_POINTER_PREFIX = "WABASKETCLAIM#"

#: How long a claimed-channel pointer keeps answering AT MOST. Thirty days, matching
#: `customer_cart.CART_LIFETIME`, because the channel belongs to the CART: a pointer that outlived
#: the cart it describes would stamp `whatsapp` on an unrelated website order weeks later, and a
#: mislabelled order cannot be told apart from a real one afterwards. Expiry is compared in
#: application code for the same reason the hand-off's is - CommerceKeys has no TTL.
#:
#: MATCHING THAT LIFETIME IS NOT WHAT MAKES IT SAFE, and assuming it did was a measured defect: the
#: cart is consumed at payment while the pointer is not, so a website order placed days after a
#: paid WhatsApp one was still inside these thirty days and inherited `whatsapp`. The binding that
#: actually holds is `wixCartId` on the pointer, compared against the customer's current cart by
#: `active_claim`. This bound is the outer limit for a cart that is never consumed at all.
CLAIM_POINTER_LIFETIME_SECONDS = 30 * 24 * 3600

#: 24 bytes of `secrets.token_urlsafe` entropy - 32 URL-safe characters. Chosen rather than a
#: UUID because this value is pasted into a link; `token_urlsafe` needs no escaping.
TOKEN_BYTES = 24

#: An unclaimed hand-off stops being claimable after this long. Seven days: long enough that a
#: customer who sends a cart on Friday and signs in on Monday is not told their basket is gone,
#: short enough that a stale catalogue price is re-quoted rather than inherited (it is re-quoted
#: in any case - Wix prices the cart at claim time - so this bound is about intent, not money).
#:
#: ENFORCED BY THIS APPLICATION, NOT BY DYNAMODB. CommerceKeys carries no TTL by design: it holds
#: immutable financial and idempotency records, and `initiation.py`'s own docstring says so
#: outright ("No expiry on financial/idempotency records"). Enabling TTL to expire a basket would
#: arm deletion on the table that holds `PAYREF#` rows. So `expiresAt` is a field `claimable()`
#: compares, and the row stays.
HANDOFF_LIFETIME_SECONDS = 7 * 24 * 3600

#: Quantity bounds. The floor is 1 because an absent, zero or negative quantity in a cart message
#: still means the customer put the item in their cart - dropping the line would silently shorten
#: their order, and asking Meta what it meant is not an option. The ceiling is 100, which is well
#: inside `cart_v2.catalog_item`'s own 1..100000 and is a deliberate CLAMP rather than a refusal:
#: a chat basket asking for more than a hundred of one variant is far more likely a client defect
#: than an order, and clamping keeps the rest of the basket claimable. The clamp is reported on
#: the `Basket` so the handler can log that it happened.
QUANTITY_FLOOR = 1
QUANTITY_CEILING = 100

#: Wix's own cart line ceiling, mirrored so a 300-line message cannot produce a row that
#: `cart_v2.CartV2.create` would then refuse ("create requires 1 to 100 catalog items"). Lines
#: beyond this are dropped and counted, never silently merged into the ones that fit.
LINE_CEILING = 100

#: Our own numbers, digits only. A hand-off must never be built for one of these senders, and the
#: reply must never go to one: they are the business's WhatsApp and PSTN numbers, so a reply would
#: be us messaging ourselves on a path whose whole purpose is messaging a customer.
#:
#: DUPLICATED ON PURPOSE AND PINNED BY A TEST. The registry of record is
#: `lambda_utils.notifications.events.business_numbers()`, but importing it here would pull
#: `lambda_utils.notifications`, which loads boto3 at import - and this module is pure precisely
#: so it can be reasoned about without a client. `tests/test_whatsapp_basket.py` asserts the two
#: sets are equal, which is the same trade `plan.md` D4 makes for the sample-exclusion list: a
#: parity test catches drift at the same cost as sharing the list, without the coupling.
BUSINESS_SENDERS = frozenset({"919330994400", "919903300044", "918031830030"})

#: E.164, byte-identical to the pattern `customer_cart._key` enforces on a session phone. It has
#: to be the same pattern, because `claim-basket` compares this row's `phone` against
#: `normalize_phone_preserving_country(identity.phone)` by EXACT STRING EQUALITY - two different
#: notions of "valid E.164" would be two phones that are the same number and do not match.
_E164_RE = re.compile(r"\+[1-9][0-9]{7,14}")


class Basket:
    """A parsed catalogue order: resolvable Wix lines, and a count of what was dropped.

    Immutable-by-convention value object with `__slots__`, in the style of
    `notifications.events.ConnectedCallEvent`: holding one is the assertion that every line in it
    resolved through `meta_catalog_sync.parse_retailer_id`, so nothing downstream re-checks.

    `lines` is a list of `{"productId", "variantId", "quantity"}` dicts - EXACTLY the key set
    `cart_v2.catalog_item` accepts and refuses anything else for, so the claim action can pass
    them to `CustomerCart.ensure` unchanged rather than translating a third shape.
    """

    __slots__ = ("lines", "catalog_id", "message_id", "dropped", "clamped")

    def __init__(self, *, lines: Sequence[Dict[str, Any]], catalog_id: str = "",
                 message_id: str = "", dropped: int = 0, clamped: int = 0) -> None:
        self.lines: List[Dict[str, Any]] = [dict(line) for line in lines]
        self.catalog_id = catalog_id
        self.message_id = message_id
        #: Lines whose retailer id was not one of ours, plus lines past `LINE_CEILING`.
        self.dropped = int(dropped)
        #: Lines whose quantity was reduced to `QUANTITY_CEILING`.
        self.clamped = int(clamped)

    def __len__(self) -> int:
        return len(self.lines)

    def log_fields(self) -> Dict[str, Any]:
        """Counts and ids that are safe to log in full. No phone, no price, because neither is here."""
        return {"lineCount": len(self.lines), "droppedLines": self.dropped,
                "clampedLines": self.clamped, "catalogId": self.catalog_id,
                "sourceMessageId": self.message_id}


def _quantity(value: Any) -> Tuple[int, bool]:
    """`(quantity, was_clamped)`. Total: every input yields a usable integer in range.

    `int(float(...))` is deliberately NOT used, here or anywhere in this file. A quantity arriving
    as `"2.0"` is a client that should be sending an integer, and routing it through a float to
    find out is how a float gets into the one path that must not contain one. `int(str)` on a
    non-integer string raises, and the floor is the answer.
    """
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return QUANTITY_FLOOR, False
    if quantity > QUANTITY_CEILING:
        return QUANTITY_CEILING, True
    return max(quantity, QUANTITY_FLOOR), False


def parse_order_message(message: Mapping[str, Any]) -> Optional[Basket]:
    """A `Basket` for a Meta `order` message, or `None` when nothing in it is ours.

    `None` MEANS "DO NOT WRITE AND DO NOT REPLY". An all-foreign cart is a real possibility - the
    Meta catalogue can hold items this sync did not publish, and a hand-made SKU from the catalog
    builder parses to `None` by design - and the honest response is to leave it to the existing
    conversational paths rather than to hand the customer a link to an empty basket.

    Duplicate retailer ids are SUMMED, not kept as two lines, and the sum is clamped afterwards.
    Summing matches `checkout/handler.py::_require_same_basket`, which sums saved lines sharing one
    catalogue key when it compares a cart against a request; two lines for one variant would make
    that comparison disagree with this row about the same basket.
    """
    order = message.get("order") if isinstance(message, Mapping) else None
    order = order if isinstance(order, Mapping) else {}
    items = order.get("product_items")
    items = items if isinstance(items, (list, tuple)) else []

    # Insertion-ordered, so the Wix cart lists the lines in the order the customer built them.
    merged: Dict[Tuple[str, str], int] = {}
    dropped = 0
    clamped_keys: set = set()
    for item in items:
        if not isinstance(item, Mapping):
            dropped += 1
            continue
        reference = meta_catalog_sync.parse_retailer_id(item.get("product_retailer_id"))
        if reference is None:
            # Not one of ours: a catalog-builder SKU, a broken id, or an item from another
            # catalogue. Counted and reported; never guessed at.
            dropped += 1
            continue
        # `item_price` and `currency` are NOT READ. See the module docstring - this is the line
        # that used to be `float(pi.get('item_price', 0))`.
        quantity, was_clamped = _quantity(item.get("quantity"))
        if was_clamped:
            clamped_keys.add(reference)
        if reference in merged:
            merged[reference] = merged[reference] + quantity
        elif len(merged) >= LINE_CEILING:
            # Past Wix's cart ceiling. Dropped rather than merged into another line, so the row
            # never claims a quantity the customer did not ask for.
            dropped += 1
        else:
            merged[reference] = quantity

    lines: List[Dict[str, Any]] = []
    for (product_id, variant_id), quantity in merged.items():
        # Re-applied AFTER the sum, because two in-range lines for one variant can add up past the
        # ceiling. `clamped_keys` already holds anything a single line clamped, so a variant is
        # counted once however many of its lines were reduced.
        if quantity > QUANTITY_CEILING:
            quantity = QUANTITY_CEILING
            clamped_keys.add((product_id, variant_id))
        lines.append({"productId": product_id, "variantId": variant_id, "quantity": quantity})
    clamped = len(clamped_keys)

    if not lines:
        return None
    return Basket(lines=lines, catalog_id=str(order.get("catalog_id") or ""),
                  message_id=str(message.get("id") or ""), dropped=dropped, clamped=clamped)


def is_business_sender(phone: Any) -> bool:
    """Whether this sender is one of our own numbers. Digits-only comparison, so `+91...` matches."""
    digits = "".join(character for character in str(phone or "") if character.isdigit())
    return bool(digits) and digits in BUSINESS_SENDERS


def e164(phone: Any) -> str:
    """The sender as E.164, or `''` when it is not a phone number this module will bind a row to.

    ADDS `+`, INFERS NOTHING. Meta delivers `from` and `wa_id` as a FULL international number with
    no `+` (`919876543210`), so supplying the `+` is a notation fix and not a guess. What this
    deliberately does NOT do is prepend a country code: a ten-digit value becomes `+9876543210`,
    which is a different number from `+919876543210` and therefore simply fails the claim
    comparison. That is the fail-closed direction, and it is the defect
    `identity.customer.normalize_phone_preserving_country` was written for - `normalize_phone`
    prepended `91` to complete foreign numbers and sent OTPs to unrelated Indian subscribers. A
    basket that cannot be claimed is recoverable; a basket bound to the wrong person is not.

    Anything shorter than eight digits, or starting with a zero after the `+`, is `''`: those are
    not E.164 at all, and `customer_cart._key` refuses them on the session side too.
    """
    compact = "".join(str(phone or "").split())
    if not compact:
        return ""
    candidate = compact if compact.startswith("+") else "+" + compact
    return candidate if _E164_RE.fullmatch(candidate) else ""


def new_token() -> str:
    """An unguessable basket token. `secrets`, never `random` - see `.kiro/steering`'s note on
    SnapStart freezing the `random` PRNG state into every restored sandbox."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def handoff_key(token: str) -> str:
    """The CommerceKeys partition key for a hand-off row."""
    return TOKEN_PREFIX + str(token or "")


def message_key(message_id: str) -> str:
    """The CommerceKeys partition key for the wamid index. See `MESSAGE_INDEX_PREFIX`."""
    return MESSAGE_INDEX_PREFIX + str(message_id or "")


def token_from_key(key: Any) -> str:
    """The token inside a `WABASKET#...` key, or `''`. Used by the claim action, which receives a
    token from a URL and must not be able to address any other row in a shared-partition table."""
    text = str(key or "")
    return text[len(TOKEN_PREFIX):] if text.startswith(TOKEN_PREFIX) else ""


def build_handoff(basket: Basket, phone: str, *, token: str, now: int,
                  lifetime: int = HANDOFF_LIFETIME_SECONDS) -> Dict[str, Any]:
    """The hand-off row, ready to put with `attribute_not_exists(orderId)`.

    Raises `ValueError` for a phone that is not E.164, for one of our own numbers, and for an
    empty basket - all three are programming errors at this point rather than customer states,
    because the handler has already checked each one and must not reach here otherwise. Raising
    keeps this module's contract total: a row that exists is a row that was claimable when written.

    `channel` comes from `order_channel.CHANNEL_WHATSAPP` rather than the literal, because
    `checkout/handler.py::_claimed_handoff` reads this field and `finalization.accept_paid` writes
    it onto the order row - three subsystems agreeing on one word, which is exactly the case
    `order_channel` exists for.

    NO MONEY FIELD, AND NO PLACE TO PUT ONE. Not `amountPaise`, not `subtotal`, not a currency.
    The row is lines, quantities, a phone, a channel and two timestamps.
    """
    normalized = e164(phone)
    if not normalized:
        raise ValueError("a hand-off is bound to an E.164 phone")
    if is_business_sender(normalized):
        raise ValueError("a hand-off is never built for one of our own numbers")
    if not basket.lines:
        raise ValueError("a hand-off needs at least one resolvable line")
    if not str(token or ""):
        raise ValueError("a hand-off needs a token")
    return {
        "orderId": handoff_key(token),
        "token": str(token),
        "phone": normalized,
        "lines": [dict(line) for line in basket.lines],
        "lineCount": len(basket.lines),
        "channel": order_channel.CHANNEL_WHATSAPP,
        # The wamid. Loggable in full and stored in full: it is a correlation id, not a secret and
        # not a phone number, and it is what makes a redelivery resolvable.
        "sourceMessageId": basket.message_id,
        "catalogId": basket.catalog_id,
        "createdAt": int(now),
        "expiresAt": int(now) + int(lifetime),
    }


def build_message_index(basket: Basket, token: str, now: int) -> Optional[Dict[str, Any]]:
    """The wamid -> token index row, or `None` when Meta sent no message id.

    `None` is not a failure: without a wamid there is nothing to be idempotent ON, and the caller
    writes the hand-off anyway rather than refusing a real order over a missing field. A webhook
    with no message id is also one Meta will not redeliver under that id, so the replay this index
    defends against cannot occur for it.
    """
    if not basket.message_id:
        return None
    return {"orderId": message_key(basket.message_id),
            "token": str(token),
            "handoffId": handoff_key(token),
            "createdAt": int(now)}


def claimable(row: Optional[Mapping[str, Any]], phone: Any, now: int) -> bool:
    """Whether this row may be merged into the cart of the customer holding `phone`, right now.

    Three conditions, and the caller must treat a `False` from any of them IDENTICALLY - the same
    opaque refusal a missing row gets. A refusal that distinguished "wrong number" from "no such
    basket" would make the endpoint an existence oracle for tokens.

    1. EXACT E.164 MATCH. Not a suffix match, not a digits-only comparison: the row stores the
       sender's E.164 and the claim supplies `normalize_phone_preserving_country(session phone)`,
       and both go through the same `_E164_RE`. A suffix comparison would make `+919876543210` and
       `+15559876543210` the same customer.
    2. UNCLAIMED. `claimedAt` absent. The durable guarantee is the conditional update the caller
       performs, not this check - two concurrent claims both pass here and only one wins the
       write. This exists so the ordinary second claim is refused without a wasted Wix call.
    3. UNEXPIRED. `expiresAt > now`, the same strict comparison `customer_cart.resolve` makes, so
       an expired basket reads as absent to both.
    """
    if not isinstance(row, Mapping):
        return False
    if not str(row.get("orderId") or "").startswith(TOKEN_PREFIX):
        return False
    stored = e164(row.get("phone"))
    presented = e164(phone)
    if not stored or not presented or stored != presented:
        return False
    if row.get("claimedAt"):
        return False
    lines = row.get("lines")
    if not isinstance(lines, (list, tuple)) or not lines:
        return False
    try:
        expires_at = int(row.get("expiresAt") or 0)
    except (TypeError, ValueError):
        return False
    return expires_at > int(now)


def claim_pointer_key(customer_id: Any) -> str:
    """The CommerceKeys partition key for a customer's claimed-channel pointer."""
    return CLAIM_POINTER_PREFIX + str(customer_id or "")


def build_claim_pointer(row: Mapping[str, Any], customer_id: Any, *, now: int, cart_id: Any,
                        lifetime: int = CLAIM_POINTER_LIFETIME_SECONDS) -> Dict[str, Any]:
    """The pointer `_claimed_handoff` reads. Carries the CHANNEL and no money, like the row itself.

    `customerId` is on it so `customer_auth.authorize_resource` can refuse a row belonging to
    somebody else, the same way every other customer-scoped row in this table is checked.

    `cart_id` IS REQUIRED, AND IT IS WHAT BOUNDS THE POINTER'S MEANING. `CLAIM_POINTER_LIFETIME_SECONDS`
    matching `customer_cart.CART_LIFETIME` is NOT sufficient on its own, which is the defect this
    argument closes: the cart is CONSUMED at payment and the pointer is not, so a customer who
    claimed a WhatsApp basket, paid it, and then placed an ordinary website order days later was
    still inside the pointer's thirty days and had `whatsapp` stamped on the second order - on the
    attempt, the `PAYREF#` row, the order row, the `/orders` tag and the GST invoice's
    `Source:` line. A mislabelled order cannot be told apart from a real one afterwards.
    Recording the Wix cart the lines were merged INTO makes the pointer describe one basket rather
    than one customer, so it stops answering the moment that cart is gone.

    The value is the cart id `CustomerCart.ensure` returned, which has already been through
    `cart_v2.identifier` - so both sides of the comparison in `active_claim` are the same
    lowercased UUID rather than two spellings of one cart.
    """
    return {
        "orderId": claim_pointer_key(customer_id),
        "customerId": str(customer_id or ""),
        "channel": order_channel.canonical(row.get("channel")),
        "handoffId": str(row.get("orderId") or ""),
        "token": str(row.get("token") or ""),
        "wixCartId": _cart_key(cart_id),
        "claimedAt": int(now),
        "expiresAt": int(now) + int(lifetime),
    }


def _cart_key(cart_id: Any) -> str:
    """A cart id reduced to the one comparable form. `''` for anything that is not one.

    Lowercased and stripped rather than validated through `cart_v2.identifier`, because that
    raises and `active_claim` must not - and because a value that is not a cart id at all simply
    fails to match, which is the answer either way.
    """
    return str(cart_id or "").strip().lower()


def active_claim(pointer: Optional[Mapping[str, Any]], now: int, *,
                 cart_id: Any) -> Optional[Dict[str, Any]]:
    """The pointer if it still describes the customer's current basket, else `None`.

    TOTAL AND NON-RAISING, because its one caller is `_website_prepare`'s attribution read, which
    runs on the money path. A malformed pointer degrades to "no claim", and `order_channel.canonical`
    then answers `website` - the asymmetric default that under-claims the WhatsApp channel rather
    than mislabelling a website order.

    `cart_id` is the customer's CURRENT Wix cart, and a mismatch takes exactly that same degraded
    path rather than a distinct one: the pointer was written for the cart the hand-off was merged
    into, so a different cart is a different basket and is NOT the WhatsApp one however recently
    the claim happened. An absent or unresolvable cart is also a mismatch - `''` never equals a
    stored id, and a pointer written before this field existed carries `''` and therefore stops
    answering, which is the fail-closed direction.
    """
    if not isinstance(pointer, Mapping):
        return None
    try:
        expires_at = int(pointer.get("expiresAt") or 0)
    except (TypeError, ValueError):
        return None
    if expires_at <= int(now):
        return None
    current = _cart_key(cart_id)
    if not current or current != _cart_key(pointer.get("wixCartId")):
        return None
    return {"channel": order_channel.canonical(pointer.get("channel")),
            "handoffId": str(pointer.get("handoffId") or ""),
            "token": str(pointer.get("token") or ""),
            "wixCartId": current}


def catalog_items(row: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """`[{productId, variantId, quantity}]` from a stored row, re-validated on the way out.

    DynamoDB hands integers back as `Decimal`, which `cart_v2.catalog_item` refuses outright
    (`type(quantity) is not int`). So the quantity is re-made with `int()` here - `int(Decimal)`
    is exact for a whole number and raises for nothing a quantity can legitimately be - and the
    bounds are re-applied, because the row was written by a different Lambda and a reader that
    trusts a stored bound is a reader that cannot be changed independently.
    """
    items: List[Dict[str, Any]] = []
    for line in row.get("lines") or []:
        if not isinstance(line, Mapping):
            continue
        product_id = str(line.get("productId") or "")
        variant_id = str(line.get("variantId") or "")
        if not product_id or not variant_id:
            continue
        quantity, _ = _quantity(line.get("quantity"))
        items.append({"productId": product_id, "variantId": variant_id, "quantity": quantity})
    return items
