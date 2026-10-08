"""Where an order came from, as two literals and one total coercion.

WHY THIS IS A MODULE AND NOT A STRING COMPARISON
------------------------------------------------
`channel` is ATTRIBUTION: it answers "which surface did this customer place the order from",
website or WhatsApp. It is NOT `checkoutMode`, which is MECHANICS - how the money settles - and
which stays `WEBSITE_RAZORPAY_STANDARD` for both channels. Nothing is added to
`finalization.ACCEPTED_CHECKOUT_MODES` for a WhatsApp order, because a second accepted mode is a
second FINALISATION path, and a label is not a payment flow. Conflating the two is how a new
settlement branch gets opened by something that only wanted to print a word on a page.

That distinction is only worth having if there is exactly one place the value is decided. So this
module owns the two literals and the one coercion, and every caller - `checkout/handler.py`,
`finalization.accept_paid`, `customer-orders._project` - goes through `canonical()` rather than
comparing a string by hand. The same discipline `lambda_utils.payment_status` applies to payment
words, applied to this one: the vocabulary lives in one file or it lives in five.

WHY `canonical()` CANNOT RAISE
------------------------------
Every caller is on a total-by-construction path:

  * `customer-orders._project`'s docstring states the property outright - one unreadable order
    must not blank a customer's whole history, so every coercion in it degrades rather than
    raising.
  * `finalization.accept_paid` is the single writer of the order row and runs AFTER the money has
    been taken. A `ValueError` there would mean a captured payment with no order record.

So `canonical()` is defined over EVERY Python object: `"whatsapp"` for a case-insensitive exact
match on that one word after stripping surrounding whitespace, and `"website"` for literally
anything else - `None`, `""`, a number, a dict, junk. There is no third answer and no error path.

WHY THE DEFAULT IS `website`, AND WHY THAT IS NOT A GUESS
---------------------------------------------------------
Absent means website, and that is TRUE of every row in the order table rather than convenient: no
WhatsApp order can exist yet. The inbound catalogue-order path does not create an order at all
today, and the hand-off that will (plan item 7) is gated OFF by `WA_CATALOG_ORDERS_ENABLED`. So
the backfill for existing rows is "do nothing", and it is correct by measurement, not by
assumption.

The coercion is deliberately ASYMMETRIC: `whatsapp` requires an exact word and everything else
falls to `website`. A typo therefore under-claims the WhatsApp channel rather than mislabelling a
website order, and a mislabelled row is a reporting defect that cannot be distinguished from a
real one after the fact.
"""

#: The website, and the value every pre-existing order row means by carrying no channel at all.
CHANNEL_WEBSITE = 'website'

#: A WhatsApp catalogue order, handed off to the website leg to be priced and paid.
CHANNEL_WHATSAPP = 'whatsapp'

#: Every channel that exists. A frozenset so a caller cannot extend it in place, and so a test
#: can assert the vocabulary is exactly two words - the same reason
#: `finalization.ACCEPTED_CHECKOUT_MODES` is one.
CHANNELS = frozenset({CHANNEL_WEBSITE, CHANNEL_WHATSAPP})


def canonical(value) -> str:
    """One of the two literals, for any input whatsoever. Never raises.

    `str(value)` rather than an `isinstance` check, so a `Decimal` or a dict handed back by
    DynamoDB is `website` instead of a `TypeError` on a path that must not have one. `.strip()`
    because a stored value that picked up a trailing space is still the customer's channel, and
    `.lower()` because `'WhatsApp'` is the spelling Meta's own documentation uses.
    """
    try:
        word = str(value).strip().lower()
    except Exception:
        # A `__str__` that raises is not a channel. Reached only by a hostile object, and the
        # answer is the same as for every other non-match rather than an exception escaping into
        # `accept_paid`.
        return CHANNEL_WEBSITE
    return CHANNEL_WHATSAPP if word == CHANNEL_WHATSAPP else CHANNEL_WEBSITE
