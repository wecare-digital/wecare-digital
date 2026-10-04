"""The website route RECONCILES a saved Wix cart to the requested basket, inside the clock.

Why reconciliation exists at all
--------------------------------
`CustomerCart.ensure` keeps ONE Wix cart per identity for thirty days and does not reconcile it
with the requested basket; `_require_same_basket` then refuses when they differ. Before Phase 2
that was a corner. After it, it is the normal case -- a contribution amount edit (Rs.200 -> Rs.400)
is a different basket on the same cart -- and the refusal was a DEAD END on this route:
`_website_prepare` had none of `_create`'s Cart V2 arms, so `CartContractError` fell to the generic
arm and answered 503 TEMPORARILY_UNAVAILABLE, a code the browser treats as transient, for a
condition no retry can clear, for up to thirty days. And the customer has no affordance that
touches the server-side cart: `/wix-store/*` appears nowhere in `src/pages/cart.tsx`.

What this file pins, each one a property a future edit could remove without failing anything else
--------------------------------------------------------------------------------------------------
* **The command ORDER is `quantity` -> `add` -> `remove`**, and no `remove` is issued for a key
  that also appears in the requested basket. A remove-then-add of the same key would mint a new
  `lineItemId` and move both `basket_hash` and `narrow_basket_hash`, dropping the one-live-payment
  guard from TIER 1 `CART_ALREADY_PAID` to the TIER 2 in-flight window.
* **The cart is never transiently empty**, replayed against a line-count model rather than
  asserted. `CartV2.remove` raises unless Wix returns a cart object, and whether it does when the
  LAST line is removed is unverified -- so the ordering must keep at least one line alive.
* **Over-cap and over-ceiling refuse HAVING ISSUED NOTHING**, with their own code, because the
  excess lines are on the server cart and "review your cart" would name an action the customer
  cannot take.
* **The clock refuses BEFORE a command, never after.** A command interrupted by a Lambda timeout is
  not an exception, so `execute` never reaches its unlock and the row stays `busy` -- and
  `resolve()` reads `busy` before `expiresAt`, so that is a thirty-day lockout for one customer
  with nothing in this repo able to clear it.
* **Reconciliation is idempotent in effect**, because it diffs live state rather than replaying a
  log. A mid-way `CartBusy` leaves a partially reconciled cart and the next prepare converges
  without double-applying the `add`.
* **Exactly ONE `CustomerCart` per `_v2_snapshot` call**, so one `self.now` governs `ensure`,
  `abandon` and every command.
* **`_website_snapshot(identity, line_items, now)` called POSITIONALLY still works**, which
  `tests/test_graft_money_correctness.py` relies on -- and with `_DEADLINE` at its module default
  it reconciles rather than refusing, because the unset deadline means "not entered through
  `handler`" and not "no time left".
* **T9b: the request-key rotation is safe.** Two baskets get two keys and two reservations; a
  changed basket on the SAME key still raises `INTENT_CHANGED` (that guard is correct and is not
  weakened); a rotated key answers 200 while the cart-keyed `CARTPAYMENT#` pointer still names
  exactly one gateway order; and a fresh key against a live unpaid attempt answers
  `CHECKOUT_AMBIGUOUS / CART_PAYMENT_IN_FLIGHT` reserving nothing and creating no second order.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from contribution_env import (  # noqa: E402
    ATTEMPTS_TABLE, CUSTOMER, KEYS_TABLE, OWNED, STORED_PHONE, WIX_ADDRESS,
    _Identity, body_of, create_event, make_env, prepare_event, seed_cart_pointer)
from contribution_wix import (  # noqa: E402
    CART_ID, CONTRIBUTION_ID, CONTRIBUTION_VARIANT, CONTRIBUTION_VARIANTS, ContributionWix,
    KIOSK_ID, KIOSK_VARIANT, OTHER_ID, OTHER_VARIANT, STORES_APP_ID, contribution_line,
    contribution_paise, kiosk_line, other_line, register_product, saved)

from lambda_utils.ecommerce import payment_attempt  # noqa: E402

THIRD_ID = "3c4d5e6f-0000-4000-8000-000000000003"
THIRD_VARIANT = "3c4d5e6f-0000-4000-8000-000000000093"


def three_line_fake(**over):
    """A saved cart that needs all three command kinds to become the requested basket.

    saved:     kiosk x1, other x1
    requested: kiosk x2, third x1
    diff:      quantity(kiosk -> 2), add(third x1), remove(other)
    """
    kwargs = dict(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1),
                         saved(OTHER_ID, OTHER_VARIANT, 1)])
    kwargs.update(over)
    fake = ContributionWix(**kwargs)
    register_product(fake, THIRD_ID, THIRD_VARIANT, unit_rupees=99)
    return fake


def three_line_request():
    return [kiosk_line(2), third_line(1)]


def third_line(quantity=1):
    return {"catalogReference": {"appId": STORES_APP_ID, "catalogItemId": THIRD_ID,
                                 "options": {"variantId": THIRD_VARIANT}},
            "quantity": quantity}


# ══ T9 — the three-line diff, in both shapes ════════════════════════════════════

@pytest.mark.parametrize("address", [None, dict(WIX_ADDRESS)])
def test_t9_the_three_line_diff_is_issued_as_quantity_then_add_then_remove(monkeypatch, address):
    """Driven in BOTH shapes, and the second one is the load-bearing case.

    Addressless is what keeps the stale-delivery REPLACE gated off, so the request routes to the
    reconcile. Address-carrying with `requires_delivery` true must ALSO reconcile rather than
    replace -- the abandon is gated on `not requires_delivery`, so a physical basket never reaches
    it however stale its address is. That is the assertion that pins the control case from the
    reconcile side, and widening the abandon's condition would break it here as well as there.
    """
    fake_wix = three_line_fake(delivery_address=address)
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    response = h.handler(prepare_event(three_line_request()), None)
    assert response["statusCode"] == 200, body_of(response)

    kinds = [kind for kind, _key, _quantity in wix.commands]
    assert kinds == ["quantity", "add", "remove"], wix.commands
    assert wix.created_carts == [], "a reconcile edits the cart; it does not replace it"
    # No `remove` for a key that is also in the requested basket.
    requested_keys = {(KIOSK_ID.lower(), KIOSK_VARIANT.lower()),
                      (THIRD_ID.lower(), THIRD_VARIANT.lower())}
    assert not [key for kind, key, _q in wix.commands
                if kind == "remove" and key in requested_keys]


def test_t9_the_cart_is_never_transiently_empty(monkeypatch):
    """Replayed against a line-count model rather than asserted.

    `CartV2.remove` routes its response through `_cart()`, which raises unless Wix returns a cart
    object, and whether Wix returns one when the LAST line is removed is unverified. With
    `quantity` -> `add` -> `remove` at least one requested line is always present before any
    removal, so the unverified behaviour is never in the hot path.
    """
    fake_wix = three_line_fake()
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)
    h.handler(prepare_event(three_line_request()), None)

    count = 2                       # the saved cart: kiosk + other
    seen = [count]
    for kind, _key, _quantity in wix.commands:
        if kind == "add":
            count += 1
        elif kind == "remove":
            count -= 1
        seen.append(count)
        assert count >= 1, f"the cart went empty mid-reconcile: {seen}"
    assert min(seen) >= 1


def test_t9_a_one_line_to_one_line_diff_adds_before_it_removes(monkeypatch):
    """The shape the ordering exists for: nothing in common, so the add must land first."""
    fake_wix = ContributionWix(lines=[saved(OTHER_ID, OTHER_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)
    response = h.handler(prepare_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 200, body_of(response)
    assert [kind for kind, _k, _q in wix.commands] == ["add", "remove"]


def test_t9_a_contribution_amount_edit_is_an_add_and_a_remove_in_that_order(monkeypatch):
    """The reconcile's DOMINANT case: Rs.100 -> Rs.250 on a contribution-only cart.

    IT IS NO LONGER A QUANTITY COMMAND, and the reason is the model change rather than a change
    of mind about the reconcile. Changing the amount used to edit the quantity of one Rs.1 line,
    which was a single `update-line-items` call. Three fixed prices are three different VARIANTS,
    so a different amount is a different catalogue reference -- the saved line has to go and the
    new one has to arrive.

    ADD BEFORE REMOVE, which the reconcile guarantees generally and which matters here
    specifically: removing the only line first would empty the cart, and Wix's behaviour when the
    last line is removed is unverified.

    A contribution prepare never writes a delivery address, so the stale-delivery replace cannot
    fire here and the reconcile is what runs.
    """
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    dearer = CONTRIBUTION_VARIANTS[1]
    response = h.handler(prepare_event([contribution_line(dearer)]), None)
    assert response["statusCode"] == 200, body_of(response)
    assert [kind for kind, _k, _q in wix.commands] == ["add", "remove"]
    assert [line["variantId"] for line in wix.lines] == [dearer]
    assert wix.lines[0]["quantity"] == 1
    assert fake.all_rows(ATTEMPTS_TABLE)[0]["amountPaise"] == contribution_paise(dearer)


def test_t9_an_equivalent_basket_issues_no_command_at_all(monkeypatch):
    """One cart, not two, and no write. Reusing the saved cart is the whole point."""
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)
    response = h.handler(prepare_event([contribution_line()]), None)
    assert response["statusCode"] == 200, body_of(response)
    assert wix.commands == []
    assert wix.created_carts == []


# ══ T9 — the two refusals that issue nothing ════════════════════════════════════

def over_cap_fake():
    """Six saved lines against a one-line request: 1 add + 6 removes = 7 > MAX_RECONCILE_COMMANDS."""
    lines = [saved(f"aaaaaaaa-0000-4000-8000-{index:012d}",
                   f"bbbbbbbb-0000-4000-8000-{index:012d}", 1) for index in range(6)]
    fake = ContributionWix(lines=lines)
    for index in range(6):
        register_product(fake, f"aaaaaaaa-0000-4000-8000-{index:012d}",
                         f"bbbbbbbb-0000-4000-8000-{index:012d}")
    return fake


def test_t9_an_over_cap_diff_refuses_with_its_own_code_and_issues_nothing(monkeypatch):
    """`CART_RESET_REQUIRED`, not `CART_NOT_PAYABLE`, and the difference is the recovery.

    The excess lines are on the SERVER cart, which no browser affordance touches, so "remove some
    lines" names lines the customer cannot see. Starting a fresh cart is the one action that works.
    """
    h, fake, wix = make_env(monkeypatch, wix=over_cap_fake())
    seed_cart_pointer(h, fake)
    response = h.handler(prepare_event([kiosk_line(1)]), None)

    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_RESET_REQUIRED"
    assert wix.commands == [], "the pre-check refuses BEFORE issuing anything"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_t9_an_over_ceiling_union_refuses_the_same_way(monkeypatch, env=None):
    """The cost of the add-before-remove ordering, stated rather than hidden: the transient union
    must respect the Wix cart line ceiling too."""
    h, fake, wix = make_env(monkeypatch, wix=over_cap_fake())
    seed_cart_pointer(h, fake)
    monkeypatch.setattr(h, "CART_LINE_CEILING", 2)
    monkeypatch.setattr(h, "MAX_RECONCILE_COMMANDS", 100)
    response = h.handler(prepare_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_RESET_REQUIRED"
    assert wix.commands == []


def test_t9_the_same_condition_through_create_is_cart_not_payable(monkeypatch):
    """`CartResetRequired` shares the `CartContractError` base class, so `_create` sees the parent
    arm. Constructed directly, because `reconcile=False` means `_create` cannot produce it -- and
    asserting what WOULD happen is the point of choosing that base class."""
    h, fake, wix = make_env(monkeypatch, wix=over_cap_fake())
    seed_cart_pointer(h, fake)
    assert issubclass(h.CartResetRequired, h.cart_v2.CartContractError)

    def boom(*args, **kwargs):
        raise h.CartResetRequired("too far")

    monkeypatch.setattr(h, "_reconcile_saved_cart", boom)
    monkeypatch.setattr(h, "_require_same_basket", boom)
    response = h.handler(create_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"


# ══ T9 — the clock ══════════════════════════════════════════════════════════════

def test_t9_too_little_time_left_refuses_before_the_first_command(monkeypatch):
    """Checked BEFORE the execute, never after. A command already in flight when the invocation is
    killed is the failure this margin exists to avoid."""
    fake_wix = three_line_fake()
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)
    monkeypatch.setattr(h, "_seconds_left", lambda: 1.0)

    response = h.handler(prepare_event(three_line_request()), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"
    assert wix.commands == [], "no Wix write may be issued inside the margin"


def test_t9_a_deadline_crossed_mid_run_records_only_what_already_landed(monkeypatch):
    """The partial state is SAFE by construction, not by rollback: the next prepare re-diffs from
    the cart's current state, so an `add` that landed is seen as present and not repeated."""
    fake_wix = three_line_fake()
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    answers = iter([20.0, 20.0, 1.0, 1.0, 1.0, 1.0])
    monkeypatch.setattr(h, "_seconds_left", lambda: next(answers, 1.0))

    response = h.handler(prepare_event(three_line_request()), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"
    kinds = [kind for kind, _k, _q in wix.commands]
    assert kinds == ["quantity", "add"], kinds
    assert fake.all_rows(ATTEMPTS_TABLE) == [], "a refused reconcile reserves nothing"


def test_t9_the_unset_deadline_means_not_entered_through_handler_not_no_time_left(monkeypatch):
    """`_DEADLINE is None` must answer the configured budget.

    A sentinel 0.0 would make `0.0 - time.monotonic()` a large NEGATIVE number, so every caller
    that does not pass through `handler` would refuse before the first command, permanently. Such
    callers exist and are promised to keep working: `tests/test_graft_money_correctness.py` drives
    `_website_snapshot(identity, line_items, now)` positionally.
    """
    # Quantity 2 on the SAVED cart, which is a state the server will never accept in a REQUEST
    # (`_contribution_request` demands exactly 1) but can legitimately find on a 30-day Wix cart
    # left by an older build. It is the cheapest way to give the reconcile one command to issue,
    # which is what this case needs in order to observe that it ran at all.
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 2)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)
    assert h._DEADLINE is None
    assert h._seconds_left() == h.DEFAULT_INVOCATION_BUDGET_SECONDS

    # POSITIONAL, exactly as the money-correctness suite calls it.
    snapshot, _calculated = h._website_snapshot(_Identity(), [contribution_line()], 1_700_000_000)
    assert snapshot is not None
    assert [kind for kind, _k, _q in wix.commands] == ["quantity"]
    assert wix.lines[0]["quantity"] == 1


def test_t9_a_context_with_no_time_left_is_recorded_rather_than_erroring(monkeypatch):
    """`context` is None in every unit test, so the fallback is the configured timeout."""
    h, _fake, _wix = make_env(monkeypatch)

    class _Context:
        def get_remaining_time_in_millis(self):
            return 3_000

    h._set_deadline(_Context())
    assert 0 < h._seconds_left() <= 3.0

    class _Broken:
        def get_remaining_time_in_millis(self):
            return "soon"

    h._set_deadline(_Broken())
    assert h._seconds_left() > 10.0
    h._set_deadline(None)
    assert h._seconds_left() > 10.0


# ══ T9 — a busy cart, and convergence ═══════════════════════════════════════════

def test_t9_a_mid_reconcile_cart_busy_is_reported_and_the_next_prepare_converges(monkeypatch):
    """`CartBusy` propagates untouched, and the partial cart is not rolled back.

    A rollback would be a second mutation on a cart whose state is already uncertain. Convergence
    instead: the second prepare re-reads the cart and re-diffs, so the `add` that already landed
    is seen as present and is NOT applied twice.
    """
    fake_wix = three_line_fake()
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    real_execute = h.customer_cart.CustomerCart.execute
    state = {"count": 0}

    def flaky(self, identity, command):
        state["count"] += 1
        if state["count"] == 3:          # after quantity and add, before remove
            raise h.customer_cart.CartBusy("cart operation requires reconciliation")
        return real_execute(self, identity, command)

    monkeypatch.setattr(h.customer_cart.CustomerCart, "execute", flaky)
    first = h.handler(prepare_event(three_line_request()), None)
    assert first["statusCode"] == 409
    assert body_of(first)["error"] == "CART_RECONCILIATION_REQUIRED"
    assert [kind for kind, _k, _q in wix.commands] == ["quantity", "add"]

    # The second prepare, with `execute` healthy again, converges from where this left off.
    monkeypatch.setattr(h.customer_cart.CustomerCart, "execute", real_execute)
    wix.commands.clear()
    second = h.handler(prepare_event(three_line_request(), requestKey="rk-2"), None)
    assert second["statusCode"] == 200, body_of(second)
    kinds = [kind for kind, _k, _q in wix.commands]
    assert kinds == ["remove"], f"the add must not be re-applied: {kinds}"
    assert sorted(wix.line_count() for _ in [0]) == [2]


def test_t9_a_non_converging_reconcile_refuses_and_reserves_nothing(monkeypatch):
    """The fail-closed backstop stays; it stops being the first ANSWER, not the last word."""
    fake_wix = three_line_fake()
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    # A cart that silently refuses to change: every command is accepted and nothing moves.
    monkeypatch.setattr(h.customer_cart.CustomerCart, "execute",
                        lambda self, identity, command: {})
    response = h.handler(prepare_event(three_line_request()), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "CART_NOT_PAYABLE"
    assert fake.all_rows(ATTEMPTS_TABLE) == []


def test_t9_two_saved_lines_sharing_one_key_refuse_rather_than_guess(monkeypatch):
    """`_require_same_basket` SUMS two lines sharing a key, which is fine for comparison -- but
    there is no single line to EDIT, so the reconcile refuses instead of picking one."""
    fake_wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    duplicated = fake_wix._cart_body()
    duplicated["lineItems"].append(dict(duplicated["lineItems"][0], id="dup"))
    monkeypatch.setattr(h.cart_v2.CartV2, "get", lambda self, cart_id: duplicated)

    with pytest.raises(h.cart_v2.CartContractError):
        h._reconcile_saved_cart(
            h.customer_cart.CustomerCart(h._keys_table(), h.cart_v2.CartV2(wix)),
            _Identity(), CART_ID,
            [{"productId": KIOSK_ID, "variantId": KIOSK_VARIANT, "quantity": 2}])
    assert wix.commands == []


def test_t9_reset_cart_abandons_then_prices_on_a_fresh_cart(monkeypatch):
    """The follow-up the `CART_RESET_REQUIRED` notice's control performs."""
    h, fake, wix = make_env(monkeypatch, wix=over_cap_fake())
    seed_cart_pointer(h, fake)

    refused = h.handler(prepare_event([kiosk_line(1)]), None)
    assert body_of(refused)["error"] == "CART_RESET_REQUIRED"

    calls = []
    real = h.customer_cart.CustomerCart.abandon
    monkeypatch.setattr(h.customer_cart.CustomerCart, "abandon",
                        lambda self, identity: (calls.append(1), real(self, identity))[1])
    response = h.handler(prepare_event([kiosk_line(1)], resetCart=True,
                                       requestKey="rk-reset"), None)
    assert response["statusCode"] == 200, body_of(response)
    assert calls, "resetCart must reach `abandon`"
    assert wix.created_carts, "a fresh cart was minted"
    assert [line["productId"] for line in wix.lines] == [KIOSK_ID]
    assert wix.commands == [], "a replaced cart is created holding the basket, not reconciled"


def test_t9_reset_is_not_readable_on_the_create_route(monkeypatch):
    """`_create` never reads `resetCart`, so the `action:"create"` dispatch default is not a way
    into abandoning a customer's saved Wix cart even with a crafted body."""
    fake_wix = ContributionWix(lines=[saved(KIOSK_ID, KIOSK_VARIANT, 1)],
                              delivery_address=dict(WIX_ADDRESS))
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    calls = []
    real = h.customer_cart.CustomerCart.abandon
    monkeypatch.setattr(h.customer_cart.CustomerCart, "abandon",
                        lambda self, identity: (calls.append(1), real(self, identity))[1])
    h.handler(create_event([kiosk_line(1)], resetCart=True), None)
    assert calls == []


def test_t9_exactly_one_customer_cart_is_built_per_snapshot(monkeypatch):
    """ONE instance, so ONE `self.now` governs `expiresAt = now + CART_LIFETIME`, the quote expiry
    check and every command. A second instance would carry a second clock through one lock
    protocol."""
    fake_wix = three_line_fake()
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    built = []
    real_init = h.customer_cart.CustomerCart.__init__

    def counting(self, table, adapter, now=None):
        built.append(1)
        real_init(self, table, adapter, now=now)

    monkeypatch.setattr(h.customer_cart.CustomerCart, "__init__", counting)
    response = h.handler(prepare_event(three_line_request()), None)
    assert response["statusCode"] == 200, body_of(response)
    assert len(built) == 1, f"{len(built)} CustomerCart instances were built"


# ══ T9b — the request key, the rotation, and the one live payment ═══════════════

def _reservations(fake):
    return [row for row in fake.all_rows(KEYS_TABLE)
            if str(row.get("kind") or "") == "CHECKOUT_REQUEST_KEY"]


def _cart_pointers(fake):
    return [row for row in fake.all_rows(KEYS_TABLE)
            if str(row["orderId"]).startswith("CARTPAYMENT#")]


def test_t9b_a_different_key_for_a_different_basket_is_never_intent_changed(monkeypatch):
    """Basket A then basket B on DIFFERENT keys. The key guard cannot fire, by construction.

    A key is minted per basket fingerprint, so a basket CHANGE never resumes a key reserved for a
    different intent -- which is what removes `INTENT_CHANGED` from the browser's common path.
    What the second post DOES meet is the cart-keyed one-live-payment guard, and that refusal is
    correct and deliberate: a second payable modal for one cart is exactly what it exists to
    refuse. Asserted as "not INTENT_CHANGED" rather than as "200", because claiming two
    simultaneous payable modals for one cart would be asserting the opposite of the guard.
    """
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    first = h.handler(prepare_event([contribution_line()], requestKey="rk-a"), None)
    assert first["statusCode"] == 200, body_of(first)
    second = h.handler(prepare_event([contribution_line(CONTRIBUTION_VARIANTS[1])], requestKey="rk-b"), None)
    assert body_of(second).get("reason") != "INTENT_CHANGED", body_of(second)
    assert body_of(second)["reason"] == "CART_PAYMENT_IN_FLIGHT"
    # The first key is reserved; the refused second reserves nothing, because the cart guard runs
    # BEFORE the reservation.
    assert sorted(row["requestKey"] for row in _reservations(fake)) == ["rk-a"]


def test_t9b_with_the_earlier_attempt_terminal_both_baskets_mint_their_own_reservation(
        monkeypatch):
    """The same two posts with nothing live on the cart: two keys, two reservations, two 200s."""
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    first = h.handler(prepare_event([contribution_line()], requestKey="rk-a"), None)
    assert first["statusCode"] == 200, body_of(first)
    table = fake.Table(ATTEMPTS_TABLE)
    row = table.get_item(Key={"paymentAttemptId": body_of(first)["paymentAttemptId"]})["Item"]
    row["status"] = "FAILED"
    table.put_item(Item=row)

    second = h.handler(prepare_event([contribution_line(CONTRIBUTION_VARIANTS[1])], requestKey="rk-b"), None)
    assert second["statusCode"] == 200, body_of(second)
    assert sorted(row["requestKey"] for row in _reservations(fake)) == ["rk-a", "rk-b"]


def test_t9b_the_same_key_with_a_changed_basket_still_raises_intent_changed(monkeypatch):
    """The guard is CORRECT and is not weakened. A resumed key whose intent moved must refuse."""
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    first = h.handler(prepare_event([contribution_line()], requestKey="rk-same"), None)
    assert first["statusCode"] == 200, body_of(first)
    second = h.handler(prepare_event([contribution_line(CONTRIBUTION_VARIANTS[1])], requestKey="rk-same"), None)
    assert second["statusCode"] == 409
    payload = body_of(second)
    assert payload["status"] == "CHECKOUT_REJECTED"
    assert payload["reason"] == "INTENT_CHANGED"


def test_t9b_a_rotated_key_answers_200_and_the_cart_still_has_one_gateway_order(monkeypatch):
    """The rotation's SAFETY, asserted rather than assumed.

    Seed the reservation the browser's key names with a STALE fingerprint, so the first post
    refuses with `INTENT_CHANGED`; the rotated post then answers 200. The property that matters is
    on the CART-keyed `CARTPAYMENT#` pointer: exactly one, naming one attempt, so the rotation
    cannot have minted a second payable order for the same cart.
    """
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    fake.Table(KEYS_TABLE).put_item(Item={
        "orderId": "REQUESTKEY#" + CUSTOMER + "#rk-stale",
        "kind": "CHECKOUT_REQUEST_KEY", "customerId": CUSTOMER, "requestKey": "rk-stale",
        "intentFingerprint": "a-fingerprint-from-another-basket",
        "paymentAttemptId": "pa_stale", "reservedAt": 1})

    refused = h.handler(prepare_event([contribution_line()], requestKey="rk-stale"), None)
    assert refused["statusCode"] == 409
    assert body_of(refused)["reason"] == "INTENT_CHANGED"
    assert _cart_pointers(fake) == [], "a refused prepare writes no cart pointer"

    rotated = h.handler(prepare_event([contribution_line()], requestKey="rk-rotated"), None)
    assert rotated["statusCode"] == 200, body_of(rotated)
    pointers = _cart_pointers(fake)
    assert len(pointers) == 1, pointers
    assert len(h.gateway_orders) == 1, h.gateway_orders


def test_t9b_leg2_a_fresh_key_against_a_live_unpaid_attempt_is_ambiguous_not_payable(monkeypatch):
    """V5b leg 2, offline. A second payable modal for ONE cart is exactly what this refuses.

    Dismissing the Razorpay modal makes no server call, so the earlier attempt stays in
    `IN_FLIGHT_STATES` while the cart pointer still names it. A FRESH key is the dangerous shape:
    the resume exemption needs the pointer's OWN key, and a fresh key is not it.
    """
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    first = h.handler(prepare_event([contribution_line()], requestKey="rk-first"), None)
    assert first["statusCode"] == 200, body_of(first)
    attempt_id = body_of(first)["paymentAttemptId"]
    before_orders = len(h.gateway_orders)
    before_reservations = len(_reservations(fake))

    second = h.handler(prepare_event([contribution_line()], requestKey="rk-fresh"), None)
    payload = body_of(second)
    assert second["statusCode"] == 409, payload
    assert payload["status"] == "CHECKOUT_AMBIGUOUS"
    assert payload["reason"] == "CART_PAYMENT_IN_FLIGHT"
    assert payload["paymentAttemptId"] == attempt_id
    assert len(h.gateway_orders) == before_orders, "no second gateway order"
    assert len(_reservations(fake)) == before_reservations, "no key was reserved"


def test_t9b_leg2_the_reconcile_may_have_already_landed_when_the_guard_refuses(monkeypatch):
    """A reconcile can RUN and then be refused, and the commands are deliberately not rolled back.

    The snapshot is built before `prepare_checkout` is entered, so the one-live-payment guard can
    answer `CART_PAYMENT_IN_FLIGHT` on a request whose commands already reached Wix. That cannot
    reach money -- the refusal writes no reservation, no attempt and no gateway order, and
    `finalization.accept_paid` builds the order from the frozen snapshot and the attested payload
    rather than from the live cart -- so the right answer is convergence, not a second mutation on
    a cart whose state is already uncertain.
    """
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    first = h.handler(prepare_event([contribution_line()], requestKey="rk-first"), None)
    assert first["statusCode"] == 200, body_of(first)
    wix.commands.clear()
    before_orders = len(h.gateway_orders)

    # THE SECOND REQUEST MUST CARRY A DIFF, or there is no reconcile to observe landing. The
    # customer changed the amount after the first attempt went live, which is a different VARIANT
    # and therefore an add plus a remove rather than a quantity edit.
    second = h.handler(
        prepare_event([contribution_line(CONTRIBUTION_VARIANTS[1])], requestKey="rk-fresh"), None)
    assert body_of(second)["reason"] == "CART_PAYMENT_IN_FLIGHT"
    # The reconcile ran before the guard refused. Leg 3's expectation is the opposite, and an
    # empty list there would mean leg 2 never reached the reconcile at all.
    assert [kind for kind, _k, _q in wix.commands] == ["add", "remove"]
    assert len(h.gateway_orders) == before_orders


def test_t9b_leg3_a_terminal_earlier_attempt_lets_the_next_prepare_through(monkeypatch):
    """With the earlier attempt terminal, the guard passes and no reconcile is needed, so the
    command count is zero -- the other half of leg 2's assertion."""
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    first = h.handler(prepare_event([contribution_line()], requestKey="rk-first"), None)
    assert first["statusCode"] == 200, body_of(first)
    attempt_id = body_of(first)["paymentAttemptId"]

    # Move the earlier attempt out of IN_FLIGHT_STATES.
    table = fake.Table(ATTEMPTS_TABLE)
    row = table.get_item(Key={"paymentAttemptId": attempt_id})["Item"]
    row["status"] = "FAILED"
    table.put_item(Item=row)
    assert not payment_attempt.is_in_flight(row)

    wix.commands.clear()
    second = h.handler(prepare_event([contribution_line()], requestKey="rk-fresh"), None)
    assert second["statusCode"] == 200, body_of(second)
    assert wix.commands == [] or len(wix.commands) == 0


def test_t9b_an_advanced_clock_past_the_in_flight_window_lets_the_prepare_through(monkeypatch):
    """`CART_PAYMENT_IN_FLIGHT_SECONDS` bounds the refusal; it is not permanent."""
    fake_wix = ContributionWix(lines=[saved(CONTRIBUTION_ID, CONTRIBUTION_VARIANT, 1)])
    h, fake, wix = make_env(monkeypatch, wix=fake_wix)
    seed_cart_pointer(h, fake)

    first = h.handler(prepare_event([contribution_line()], requestKey="rk-first"), None)
    assert first["statusCode"] == 200, body_of(first)

    window = h.website_checkout.CART_PAYMENT_IN_FLIGHT_SECONDS
    real_time = h.time.time
    monkeypatch.setattr(h.time, "time", lambda: real_time() + window + 60)

    second = h.handler(prepare_event([contribution_line()], requestKey="rk-fresh"), None)
    assert second["statusCode"] == 200, body_of(second)


# ══ T10's website half, kept beside the reconcile it is about ═══════════════════

def test_the_website_route_reconciles_where_the_create_route_refuses(monkeypatch):
    """The same saved-cart mismatch, two routes, two answers -- and that asymmetry is deliberate.

    The website request comes from the cart page the customer is looking at, so making the Wix
    cart match it is "asking them to review it" carried out. The WhatsApp `_create` path has no
    such surface.
    """
    for route, expected in (("prepare", 200), ("create", 409)):
        fake_wix = ContributionWix(lines=[saved(OTHER_ID, OTHER_VARIANT, 1)],
                                   delivery_address=dict(WIX_ADDRESS))
        h, fake, wix = make_env(monkeypatch, wix=fake_wix)
        seed_cart_pointer(h, fake)
        event = (prepare_event([kiosk_line(1)]) if route == "prepare"
                 else create_event([kiosk_line(1)]))
        response = h.handler(event, None)
        assert response["statusCode"] == expected, (route, body_of(response))
        if route == "create":
            assert body_of(response)["error"] == "CART_NOT_PAYABLE"
            assert wix.commands == []
        else:
            assert [kind for kind, _k, _q in wix.commands] == ["add", "remove"]


def test_a_physical_create_basket_with_no_stored_address_still_refuses(monkeypatch):
    """Sec 3.7's property, asserted rather than the absence of a diff.

    `_create` gained a conditional address requirement because it shares `_v2_snapshot`. That is
    behaviourally inert today -- every catalogue product is PHYSICAL -- but it is still a change to
    a live payment path, so the property is pinned: a physical basket with no stored address
    answers `409 DELIVERY_DETAILS_REQUIRED`, before any Wix write.
    """
    h, fake, wix = make_env(monkeypatch, address=None)
    response = h.handler(create_event([kiosk_line(1)]), None)
    assert response["statusCode"] == 409
    assert body_of(response)["error"] == "DELIVERY_DETAILS_REQUIRED"
    assert wix.wrote() == []
    assert fake.all_rows(ATTEMPTS_TABLE) == []
