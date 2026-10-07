"""The Phase O-1 request store, against a fake that evaluates every condition it is handed.

What is pinned here, and why each is a property rather than a shape:

* **A request exists only after a paid order exists.** No `PAYMENTATTEMPT#` claim with an order
  id -> no `REQ#`, no public id, no write.
* **One order, one request.** A replayed activation writes nothing; a concurrent activation that
  loses the `ORDER#` pointer adopts the winner's request.
* **HIGH-4: an `OPEN#` claim can never lock a customer out.** A claim whose target is missing,
  ABANDONED or already CONSUMED is stale: it is conditionally consumed (tied to that stale target),
  `STALE_OPEN_CLAIM` is logged, and a new intent is minted. Only `statusRank == 0` resumes.
* **Amendment ownership is checked before money moves**, with one identical refusal for missing,
  not-yours and not-a-submit-request.

Offline: `tests/service_requests_fake_dynamo.py`. No AWS, no network, no credential.
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from service_requests_fake_dynamo import FakeClientError, KeysTable, RequestTable  # noqa: E402

from lambda_utils import customer_auth  # noqa: E402
from lambda_utils.ecommerce import service_request_store as store  # noqa: E402
from lambda_utils.ecommerce import service_requests as sr  # noqa: E402

SUBMIT = "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b"
AMEND = "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b"
ALICE = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOB = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def who(customer_id=ALICE):
    return customer_auth.CustomerIdentity(customer_id=customer_id, phone="+910000000000",
                                          subject=customer_id)


@pytest.fixture
def table():
    return RequestTable()


@pytest.fixture
def keys():
    return KeysTable()


_counter = {"n": 0}


def pay(keys, intent, *, customer=ALICE, ref=None, attempt=None, order_id=None,
        order_number="WD-ORD-ABCDEFGH", paid=True, variant=None, paise=9900, kind=None):
    """Seed what checkout + reconciliation leave behind: PAYREF# and (if paid) the claim."""
    _counter["n"] += 1
    n = _counter["n"]
    ref = ref or f"WD-PAY-REF{n:011d}"
    attempt = attempt or f"attempt-{n}"
    order_id = order_id or f"order-{n}"
    keys.seed({"orderId": "PAYREF#" + ref, "kind": "PAYMENT_REFERENCE", "referenceId": ref,
               "paymentAttemptId": attempt, "customerId": customer, "amountPaise": 10193,
               "currency": "INR",
               "serviceLine": {"kind": kind or intent["kind"],
                               "variantId": variant or intent["variantId"],
                               "paise": paise, "intentId": intent["intentId"]}})
    if paid:
        keys.seed({"orderId": "PAYMENTATTEMPT#" + attempt, "kind": "PAYMENT_ATTEMPT_ORDER",
                   "orderIdRef": order_id, "orderNumber": order_number,
                   "paymentAttemptId": attempt, "referenceId": ref})
    return ref, attempt, order_id


def rows(table, prefix):
    return [row for key, row in table.rows.items() if str(key).startswith(prefix)]


def transactions(table):
    return [c for c in table.calls if c[0] == "transact_write_items"]


def submitted(table, keys, customer=ALICE):
    """A paid, activated Submit Request for `customer`. Returns (outcome, intent)."""
    intent = store.request_intent(table, who(customer), "SUBMIT_REQUEST")
    ref, _attempt, _order = pay(keys, intent, customer=customer)
    outcome = store.activate(table, keys, reference_id=ref)
    assert outcome.outcome == store.ACTIVATED
    return outcome, intent


# ══ the intent ═══════════════════════════════════════════════════════════════

def test_an_intent_is_not_a_request(table):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    assert sr.INTENT_ID_RE.match(intent["intentId"])
    assert intent == {"intentId": intent["intentId"], "kind": "SUBMIT_REQUEST",
                      "variantId": SUBMIT, "amountPaise": 9900, "currency": "INR",
                      "targetRequestId": None}
    assert rows(table, "REQ#") == [] and rows(table, "REQNO#") == []


def test_the_same_intent_resumes_rather_than_multiplying(table):
    first = store.request_intent(table, who(), "SUBMIT_REQUEST")
    second = store.request_intent(table, who(), "SUBMIT_REQUEST")
    assert first["intentId"] == second["intentId"]
    assert len(rows(table, "INTENT#")) == 1


def test_mint_and_supersede_are_single_transactions(table, keys):
    target, _ = submitted(table, keys)
    other, _ = submitted(table, keys)
    table.calls.clear()
    store.request_intent(table, who(), "REQUEST_AMENDMENT", target.request_public_id)
    assert [c[0] for c in table.calls if c[0] != "get_item"] == ["transact_write_items"]
    items = transactions(table)[0][1]["TransactItems"]
    assert {k for item in items for k in item} == {"Put"}
    assert sorted(i["Put"]["Item"]["requestId"]["S"].split("#")[0] for i in items) == \
        ["INTENT", "OPEN"]
    table.calls.clear()
    store.request_intent(table, who(), "REQUEST_AMENDMENT", other.request_public_id)
    # Supersede: one transaction (abandon old + new intent + claim move), no separate OPEN# put.
    assert [c[0] for c in table.calls if c[0] != "get_item"] == ["transact_write_items"]
    items = transactions(table)[0][1]["TransactItems"]
    assert [next(iter(i)) for i in items] == ["Update", "Put", "Put"]


def test_a_different_amendment_target_supersedes_the_open_intent(table, keys):
    target, _ = submitted(table, keys)
    other, _ = submitted(table, keys)
    first = store.request_intent(table, who(), "REQUEST_AMENDMENT", target.request_public_id)
    second = store.request_intent(table, who(), "REQUEST_AMENDMENT", other.request_public_id)
    assert first["intentId"] != second["intentId"]
    assert second["targetRequestId"] == other.request_public_id
    old = table.rows["INTENT#" + first["intentId"]]
    assert (old["status"], old["statusRank"]) == ("ABANDONED", 5)
    claim = table.rows[f"OPEN#{ALICE}#{AMEND}"]
    assert claim["targetIntentId"] == second["intentId"] and claim["isConsumed"] is False


@pytest.mark.parametrize("kind", ["DROP_DOCS", "VAULT", "drop_docs"])
def test_drop_docs_and_vault_cannot_be_intended(table, kind):
    with pytest.raises(sr.ServiceRejected) as caught:
        store.request_intent(table, who(), kind)
    assert caught.value.code == "SERVICE_NOT_OFFERED"
    assert table.rows == {}


def test_an_unknown_kind_is_refused(table):
    with pytest.raises(sr.ServiceRejected) as caught:
        store.request_intent(table, who(), "CONTRIBUTE")
    assert caught.value.code == "SERVICE_UNKNOWN_CHOICE"


# ══ HIGH-4: stale OPEN# claims self-heal ═════════════════════════════════════

def _seed_claim(table, target_intent_id, *, variant=SUBMIT, owner=ALICE):
    table.seed({"requestId": f"OPEN#{owner}#{variant}", "ownerCustomerId": owner,
                "targetIntentId": target_intent_id, "isConsumed": False, "claimedAt": 1})


def _stale_log(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records
            if "STALE_OPEN_CLAIM" in r.getMessage()]


def test_a_paid_target_behind_an_unconsumed_claim_mints_a_new_request(table, keys, caplog):
    """The claim still points at an intent that was PAID (CONSUMED, rank 10): stale, not resumed."""
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, intent)
    table.arm_failure("put_item", FakeClientError("ProvisionedThroughputExceededException"))
    assert store.activate(table, keys, reference_id=ref).outcome == store.ACTIVATED
    assert table.rows[f"OPEN#{ALICE}#{SUBMIT}"]["isConsumed"] is False      # the missed consume
    assert table.rows["INTENT#" + intent["intentId"]]["statusRank"] == 10
    with caplog.at_level(logging.WARNING):
        fresh = store.request_intent(table, who(), "SUBMIT_REQUEST")
    assert fresh["intentId"] != intent["intentId"]
    assert table.rows["INTENT#" + fresh["intentId"]]["statusRank"] == 0
    assert table.rows[f"OPEN#{ALICE}#{SUBMIT}"]["targetIntentId"] == fresh["intentId"]
    [alert] = _stale_log(caplog)
    assert alert["alert"] == "STALE_OPEN_CLAIM" and alert["targetRank"] == 10
    assert caplog.records[[r.getMessage() for r in caplog.records].index(
        next(r.getMessage() for r in caplog.records if "STALE_OPEN_CLAIM" in r.getMessage())
    )].levelno == logging.WARNING


def test_an_abandoned_target_behind_an_unconsumed_claim_mints_a_new_request(table, caplog):
    table.seed({"requestId": "INTENT#01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f",
                "ownerCustomerId": ALICE, "kind": "SUBMIT_REQUEST", "variantId": SUBMIT,
                "amountPaise": 9900, "currency": "INR", "status": "ABANDONED", "statusRank": 5,
                "intentFingerprint": "x"})
    _seed_claim(table, "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f")
    with caplog.at_level(logging.WARNING):
        fresh = store.request_intent(table, who(), "SUBMIT_REQUEST")
    assert fresh["intentId"] != "01928f3e-7b2a-7c3d-8e4f-0a1b2c3d4e5f"
    assert _stale_log(caplog)[0]["targetRank"] == 5


def test_a_missing_target_behind_an_unconsumed_claim_mints_a_new_request(table, caplog):
    _seed_claim(table, "01928f3e-7b2a-7c3d-8e4f-000000000000")
    with caplog.at_level(logging.WARNING):
        fresh = store.request_intent(table, who(), "SUBMIT_REQUEST")
    assert table.rows[f"OPEN#{ALICE}#{SUBMIT}"]["targetIntentId"] == fresh["intentId"]
    assert _stale_log(caplog)[0]["targetPresent"] is False


def test_the_paid_target_and_the_abandoned_twin_each_mint_a_new_request(table, keys):
    """The two stale shapes side by side, on the two services, for one customer."""
    paid = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, paid)
    table.arm_failure("put_item", FakeClientError("InternalServerError"))
    store.activate(table, keys, reference_id=ref)
    target = store.resolve_public(table, who(), rows(table, "REQ#")[0]["publicRequestId"])
    abandoned = store.request_intent(table, who(), "REQUEST_AMENDMENT", target["publicRequestId"])
    table.rows["INTENT#" + abandoned["intentId"]].update(status="ABANDONED", statusRank=5)
    again_submit = store.request_intent(table, who(), "SUBMIT_REQUEST")
    again_amend = store.request_intent(table, who(), "REQUEST_AMENDMENT",
                                       target["publicRequestId"])
    assert again_submit["intentId"] != paid["intentId"]
    assert again_amend["intentId"] != abandoned["intentId"]
    for intent in (again_submit, again_amend):
        assert table.rows["INTENT#" + intent["intentId"]]["statusRank"] == 0


def test_a_stale_consume_leaves_a_claim_that_has_since_moved_alone(table):
    """Another request moves the claim between our read and our repair: our repair must lose."""
    _seed_claim(table, "01928f3e-7b2a-7c3d-8e4f-000000000000")
    moved_to = "01928f3e-7b2a-7c3d-8e4f-111111111111"
    table.seed({"requestId": "INTENT#" + moved_to, "ownerCustomerId": ALICE,
                "kind": "SUBMIT_REQUEST", "variantId": SUBMIT, "amountPaise": 9900,
                "currency": "INR", "status": "OPEN", "statusRank": 0,
                "intentFingerprint": store._fingerprint("SUBMIT_REQUEST", SUBMIT, 9900, "")})
    original_put = table.put_item
    state = {"moved": False}

    def racing_put(**kwargs):
        if not state["moved"] and kwargs["Item"].get("staleRepairedAt"):
            state["moved"] = True
            table.rows[f"OPEN#{ALICE}#{SUBMIT}"]["targetIntentId"] = moved_to
        return original_put(**kwargs)

    table.put_item = racing_put
    resolved = store.request_intent(table, who(), "SUBMIT_REQUEST")
    # The repair lost its condition, re-read, and resolved to the claim's NEW (rank 0) target.
    assert resolved["intentId"] == moved_to
    claim = table.rows[f"OPEN#{ALICE}#{SUBMIT}"]
    assert claim["targetIntentId"] == moved_to and claim["isConsumed"] is False
    assert "staleRepairedAt" not in claim


def test_only_status_rank_zero_resolves_to_the_existing_intent(table):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    for rank in (1, 5, 10, "0x", None):
        table.rows["INTENT#" + intent["intentId"]]["statusRank"] = rank
        table.rows[f"OPEN#{ALICE}#{SUBMIT}"].update(isConsumed=False,
                                                    targetIntentId=intent["intentId"])
        assert store.request_intent(table, who(), "SUBMIT_REQUEST")["intentId"] != \
            intent["intentId"]
    table.rows["INTENT#" + intent["intentId"]]["statusRank"] = 0
    table.rows[f"OPEN#{ALICE}#{SUBMIT}"].update(isConsumed=False,
                                                targetIntentId=intent["intentId"])
    assert store.request_intent(table, who(), "SUBMIT_REQUEST")["intentId"] == intent["intentId"]


def test_a_failed_open_consume_after_activation_self_heals_on_the_next_intent(table, keys):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, intent)
    table.arm_failure("put_item", FakeClientError("ProvisionedThroughputExceededException"))
    outcome = store.activate(table, keys, reference_id=ref)
    assert outcome.outcome == store.ACTIVATED          # the swallowed failure did not cost it
    nxt = store.request_intent(table, who(), "SUBMIT_REQUEST")
    assert nxt["intentId"] != intent["intentId"]
    # And the second purchase activates into a SECOND request, never adopting the first.
    ref2, _a2, _o2 = pay(keys, nxt)
    second = store.activate(table, keys, reference_id=ref2)
    assert second.outcome == store.ACTIVATED
    assert second.request_public_id != outcome.request_public_id


def test_a_successful_activation_consumes_the_claim(table, keys):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, intent)
    store.activate(table, keys, reference_id=ref)
    claim = table.rows[f"OPEN#{ALICE}#{SUBMIT}"]
    assert claim["isConsumed"] is True and claim["targetIntentId"] == intent["intentId"]


# ══ activation ═══════════════════════════════════════════════════════════════

def test_no_paid_claim_means_no_request(table, keys, caplog):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, intent, paid=False)
    before = dict(table.rows)
    table.calls.clear()
    assert store.activate(table, keys, reference_id=ref).outcome == store.NOT_PAID
    assert table.rows == before and transactions(table) == []
    assert keys.writes() == []


def test_an_order_without_a_service_line_is_not_a_service_order(table, keys):
    keys.seed({"orderId": "PAYREF#WD-PAY-PLAIN", "paymentAttemptId": "a", "customerId": ALICE})
    assert store.activate(table, keys, reference_id="WD-PAY-PLAIN").outcome == \
        store.NOT_A_SERVICE_ORDER
    assert store.activate(table, keys, reference_id="WD-PAY-ABSENT").outcome == \
        store.NOT_A_SERVICE_ORDER
    assert table.rows == {}


def test_activation_creates_exactly_one_request_order_pointer_and_public_id_in_one_transaction(
        table, keys):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, attempt, order_id = pay(keys, intent)
    table.calls.clear()
    outcome = store.activate(table, keys, reference_id=ref)
    assert outcome.outcome == store.ACTIVATED and sr.PUBLIC_REQUEST_ID_RE.match(
        outcome.request_public_id)
    assert len(transactions(table)) == 1
    [request] = rows(table, "REQ#")
    assert request["publicRequestId"] == outcome.request_public_id
    assert (request["kind"], request["status"], request["customerId"], request["orderId"],
            request["referenceId"], request["paymentAttemptId"], request["intentId"]) == \
        ("SUBMIT_REQUEST", "SUBMITTED", ALICE, order_id, ref, attempt, intent["intentId"])
    assert request["amountPaise"] == 9900 and type(request["amountPaise"]) is int
    [pointer] = rows(table, "ORDER#")
    assert pointer["targetRequestId"] == request["requestId"]
    [reserved] = rows(table, "REQNO#")
    assert reserved["requestId"] == "REQNO#" + outcome.request_public_id
    consumed = table.rows["INTENT#" + intent["intentId"]]
    assert (consumed["status"], consumed["statusRank"], consumed["consumedOrderIds"]) == \
        ("CONSUMED", 10, [order_id])
    assert keys.writes() == []


def test_a_replayed_activation_returns_the_same_request_and_writes_nothing(table, keys):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, attempt, _order = pay(keys, intent)
    first = store.activate(table, keys, reference_id=ref)
    snapshot = {k: dict(v) for k, v in table.rows.items()}
    applied = len(table.applied)
    for again in (store.activate(table, keys, reference_id=ref),
                  store.activate(table, keys, payment_attempt_id=attempt),
                  store.activate(table, keys, reference_id=ref, caller_customer_id=ALICE)):
        assert again.outcome == store.ALREADY_ACTIVE
        assert again.request_public_id == first.request_public_id
    assert table.rows == snapshot and len(table.applied) == applied
    assert len(rows(table, "REQ#")) == 1


def test_a_concurrent_activation_losing_the_order_pointer_returns_the_winner(table, keys):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _attempt, order_id = pay(keys, intent)

    def winner_lands_first(_items):
        table.seed({"requestId": "REQ#winner", "customerId": ALICE, "publicRequestId":
                    "WD-REQ-WINNER22", "kind": "SUBMIT_REQUEST", "createdAt": 1})
        table.seed({"requestId": "ORDER#" + order_id, "targetRequestId": "REQ#winner",
                    "publicRequestId": "WD-REQ-WINNER22", "orderNumber": "WD-ORD-ABCDEFGH",
                    "kind": "SUBMIT_REQUEST", "ownerCustomerId": ALICE})

    table.arm_transaction_override(winner_lands_first)
    outcome = store.activate(table, keys, reference_id=ref)
    assert (outcome.outcome, outcome.request_public_id) == (store.ALREADY_ACTIVE,
                                                            "WD-REQ-WINNER22")
    assert [r["requestId"] for r in rows(table, "REQ#")] == ["REQ#winner"]


def test_a_public_id_collision_regenerates(table, keys):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, intent)
    table.seed({"requestId": "REQNO#WD-REQ-TAKEN222", "targetRequestId": "REQ#someone"})
    minted = iter(["WD-REQ-TAKEN222", "WD-REQ-FRESH222"])
    table.calls.clear()
    outcome = store.activate(table, keys, reference_id=ref, mint_public_id=lambda: next(minted))
    assert outcome.request_public_id == "WD-REQ-FRESH222"
    assert table.rows["REQNO#WD-REQ-TAKEN222"]["targetRequestId"] == "REQ#someone"
    assert len(transactions(table)) == 2


def test_an_abandoned_intent_paid_later_still_activates(table, keys):
    """Money wins: a superseded intent that was nonetheless paid still gets its request."""
    target, _ = submitted(table, keys)
    other, _ = submitted(table, keys)
    first = store.request_intent(table, who(), "REQUEST_AMENDMENT", target.request_public_id)
    store.request_intent(table, who(), "REQUEST_AMENDMENT", other.request_public_id)
    assert table.rows["INTENT#" + first["intentId"]]["status"] == "ABANDONED"
    ref, _a, _o = pay(keys, first)
    outcome = store.activate(table, keys, reference_id=ref)
    assert outcome.outcome == store.ACTIVATED
    request = store.resolve_public(table, who(), outcome.request_public_id)
    assert request["targetPublicRequestId"] == target.request_public_id


@pytest.mark.parametrize("override,reason", [
    ({"customer": BOB}, "CUSTOMER_MISMATCH"),
    ({"variant": AMEND, "kind": "REQUEST_AMENDMENT"}, "VARIANT_MISMATCH"),
    ({"paise": 9901}, "AMOUNT_MISMATCH"),
])
def test_customer_mismatch_variant_mismatch_and_amount_mismatch_create_no_request_and_alert(
        table, keys, caplog, override, reason):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, intent, **override)
    with caplog.at_level(logging.ERROR):
        assert store.activate(table, keys, reference_id=ref).outcome == store.UNMATCHED
    assert rows(table, "REQ#") == [] and rows(table, "ORDER#") == []
    [alert] = [json.loads(r.getMessage()) for r in caplog.records
               if "PAID_SERVICE_UNMATCHED" in r.getMessage()]
    assert alert["reason"] == reason and alert["referenceId"] == ref


def test_a_caller_cannot_activate_somebody_elses_order(table, keys):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref, _a, _o = pay(keys, intent)
    assert store.activate(table, keys, reference_id=ref, caller_customer_id=BOB).outcome == \
        store.NOT_A_SERVICE_ORDER
    assert rows(table, "REQ#") == []


def test_a_second_paid_attempt_on_one_intent_is_loud_and_gets_its_own_request(
        table, keys, caplog):
    intent = store.request_intent(table, who(), "SUBMIT_REQUEST")
    ref1, _a1, _o1 = pay(keys, intent)
    ref2, _a2, _o2 = pay(keys, intent)
    first = store.activate(table, keys, reference_id=ref1)
    with caplog.at_level(logging.ERROR):
        second = store.activate(table, keys, reference_id=ref2)
    assert second.outcome == store.ACTIVATED
    assert second.request_public_id != first.request_public_id
    assert any("DUPLICATE_PAID_INTENT" in r.getMessage() for r in caplog.records)


# ══ amendments ═══════════════════════════════════════════════════════════════

def test_an_amendment_activates_against_the_callers_own_submit_request(table, keys):
    target, _ = submitted(table, keys)
    intent = store.request_intent(table, who(), "REQUEST_AMENDMENT", target.request_public_id)
    assert intent["targetRequestId"] == target.request_public_id
    ref, _a, _o = pay(keys, intent)
    outcome = store.activate(table, keys, reference_id=ref)
    assert outcome.outcome == store.ACTIVATED and outcome.kind == "REQUEST_AMENDMENT"
    items = transactions(table)[-1][1]["TransactItems"]
    assert "ConditionCheck" in items[-1]


def test_an_amendment_against_a_request_the_caller_does_not_own_is_refused_identically_to_a_missing_one(  # noqa: E501
        table, keys):
    bobs, _ = submitted(table, keys, customer=BOB)
    refusals = []
    for target in (bobs.request_public_id, "WD-REQ-ABSENT22", "not-an-id", ""):
        with pytest.raises((customer_auth.CustomerNotAuthorized, sr.ServiceRejected)) as caught:
            store.request_intent(table, who(ALICE), "REQUEST_AMENDMENT", target)
        refusals.append((type(caught.value), str(caught.value)))
    owned_refusals = refusals[:3]
    assert len(set(owned_refusals)) == 1
    assert owned_refusals[0][0] is customer_auth.CustomerNotAuthorized
    assert not rows(table, f"INTENT#") or all(
        r["ownerCustomerId"] == BOB for r in rows(table, "INTENT#"))


def test_an_amendment_target_must_be_a_submit_request(table, keys):
    target, _ = submitted(table, keys)
    intent = store.request_intent(table, who(), "REQUEST_AMENDMENT", target.request_public_id)
    ref, _a, _o = pay(keys, intent)
    amendment = store.activate(table, keys, reference_id=ref)
    with pytest.raises(customer_auth.CustomerNotAuthorized) as caught:
        store.request_intent(table, who(), "REQUEST_AMENDMENT", amendment.request_public_id)
    assert str(caught.value) == "resource does not exist or is not yours"


def test_an_amendment_whose_target_changed_hands_after_payment_is_unmatched(table, keys, caplog):
    target, _ = submitted(table, keys)
    intent = store.request_intent(table, who(), "REQUEST_AMENDMENT", target.request_public_id)
    ref, _a, _o = pay(keys, intent)
    internal = table.rows["REQNO#" + target.request_public_id]["targetRequestId"]
    table.rows[internal]["customerId"] = BOB
    with caplog.at_level(logging.ERROR):
        assert store.activate(table, keys, reference_id=ref).outcome == store.UNMATCHED
    assert any("PAID_SERVICE_UNMATCHED" in r.getMessage() for r in caplog.records)


# ══ data discipline ══════════════════════════════════════════════════════════

def test_a_pointer_row_never_uses_the_key_attribute_for_its_target(table, keys):
    outcome, _ = submitted(table, keys)
    for prefix in ("ORDER#", "REQNO#", "OPEN#"):
        for row in rows(table, prefix):
            assert row["requestId"].startswith(prefix)
            target = row.get("targetRequestId") or row.get("targetIntentId")
            assert target and target != row["requestId"]


def test_every_amount_written_is_an_int_and_a_float_is_refused(table, keys):
    submitted(table, keys)
    for call in transactions(table):
        for item in call[1]["TransactItems"]:
            body = next(iter(item.values()))
            for mapping in (body.get("Item") or {}, body.get("ExpressionAttributeValues") or {}):
                for value in mapping.values():
                    if "N" in value:
                        assert value["N"].lstrip("-").isdigit()
    with pytest.raises(TypeError):
        store._marshal(99.0)
    assert store._marshal(True) == {"BOOL": True}
    assert store._int("9900") == 9900 and store._int("99.5") is None
    assert store._int(True) is None


def test_list_is_one_query_on_the_callers_own_partition(table, keys):
    mine, _ = submitted(table, keys)
    submitted(table, keys, customer=BOB)
    table.calls.clear()
    listed, cursor = store.list_for_customer(table, who())
    assert [c[0] for c in table.calls] == ["query"]
    query = table.calls[0][1]
    assert query["IndexName"] == "customerId-createdAt-index"
    assert query["ExpressionAttributeValues"] == {":c": ALICE}
    assert [row["requestId"] for row in listed] == [mine.request_public_id]
    assert listed[0]["kind"] == "SUBMIT_REQUEST" and cursor == ""


def test_the_list_pages_with_a_cursor_inside_the_callers_partition(table, keys):
    for _ in range(3):
        submitted(table, keys)
    page, cursor = store.list_for_customer(table, who(), limit=2)
    assert len(page) == 2 and cursor
    rest, final = store.list_for_customer(table, who(), limit=2,
                                          cursor=store.decode_cursor(cursor))
    assert len(rest) == 1 and final == ""
    assert table.calls[-1][1]["ExclusiveStartKey"]["customerId"] == ALICE
    with pytest.raises(ValueError):
        store.decode_cursor("not-a-cursor")


def test_the_store_imports_no_boto3_and_no_money_mover():
    import ast
    tree = ast.parse((ROOT / "amplify/functions/shared/lambda_utils/ecommerce/"
                      "service_request_store.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    banned = {"boto3", "botocore", "razorpay_orders", "razorpay_verify", "wix_ecom",
              "wix_writeback", "finalization", "order_creation", "urllib", "requests"}
    assert not {name.split(".")[0] for name in imported} & banned
    assert not {name.split(".")[-1] for name in imported} & banned
