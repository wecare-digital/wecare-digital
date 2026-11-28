"""Website F004: a note bound to one paid existing-order service.

Only authenticated checkout can reserve a form. The immutable per-click reservation
and conditional per-order active pointer precede any payable message. A lost send
response never frees that pointer. The paid invoice hook uses one FlowSubmission
claim per attempt, not a fabricated Meta message or a second order.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from lambda_utils import canonical_flows, contact_key, contact_store, flow_completion, shared_tables
from lambda_utils.ecommerce import order_keys, payment_attempt

VERSION = "F004-website-v1"
SERVICE = "SUBMIT_REQUEST"
CAPABILITY = "submit_request"
KEY_RE = re.compile(r"[a-f0-9]{32}")
NOTE_LIMIT = 300


def clean_note(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("NOTE_REQUIRED")
    value = value.strip()
    # Count UTF-16 code units, exactly the browser maxlength contract.
    if not value or len(value.encode("utf-16-le")) // 2 > NOTE_LIMIT:
        raise ValueError("INVALID_NOTE")
    return value


def valid_key(value: Any) -> bool:
    return isinstance(value, str) and KEY_RE.fullmatch(value) is not None


def _read(table, key_name, key):
    return table.get_item(Key={key_name: key}, ConsistentRead=True).get("Item") or {}


def _pointer_id(order_id):
    return "WEBF004#" + order_id


def _click_id(owner, key):
    return "WEBF004KEY#" + owner + "#" + key


def _owned_pointer(keys, owner, order_id, number):
    row = _read(keys, "orderId", _pointer_id(order_id))
    if row and (row.get("kind") != VERSION or row.get("customerId") != owner
                or row.get("selectedOrderId") != order_id or row.get("selectedOrderNumber") != number):
        raise RuntimeError("F004 pointer ownership mismatch")
    return row


def _owned_attempt(attempts, pointer):
    aid = str(pointer.get("paymentAttemptId") or "")
    row = _read(attempts, "paymentAttemptId", aid) if aid else {}
    if row and (row.get("websiteForm") != VERSION
                or row.get("customerId") != pointer.get("customerId")
                or row.get("selectedOrderId") != pointer.get("selectedOrderId")
                or row.get("selectedOrderNumber") != pointer.get("selectedOrderNumber")
                or row.get("websiteRequestKey") != pointer.get("requestKey")
                or row.get("serviceCode") != SERVICE
                or row.get("singleOrderService") is not True):
        raise RuntimeError("F004 attempt ownership mismatch")
    return row


def state(keys, attempts, *, owner, order_id, number):
    """No note, customer id or provider details escape this projection."""
    pointer = _owned_pointer(keys, owner, order_id, number)
    if not pointer:
        return {"state": "idle", "orderNumber": number}
    attempt = _owned_attempt(attempts, pointer)
    status = str(attempt.get("status") or "")
    if status == payment_attempt.PAYMENT_PAID:
        # The completion marker is written ONLY after a strong read of the durable
        # submission. Captured payment on its own is never a successful request.
        phase = "received" if attempt.get("websiteSubmissionId") else "saving"
    elif (pointer.get("sendRefused") is True or
          (payment_attempt.may_retry(attempt)
           and 0 < int(attempt.get("paymentRequestExpiresAt") or 0) <= int(time.time()))):
        phase = "failed"
    else:
        phase = "pending"
    result = {"state": phase, "orderNumber": number, "requestKey": pointer["requestKey"]}
    if phase == "pending":
        options = resume_options(keys, attempts, owner=owner, order_id=order_id, number=number)
        if options:
            result.update(resumeAvailable=True, amountPaise=options["amountPaise"])
    return result


def resume_options(keys, attempts, *, owner, order_id, number):
    """Reopen ONLY the same owner-bound website gateway order, never mint another.

    Legacy WhatsApp attempts and unbound/ambiguous creates are status-only. The
    amount comes from the frozen attempt and is checked against both bindings.
    """
    from lambda_utils.ecommerce import website_checkout
    pointer = _owned_pointer(keys, owner, order_id, number)
    if not pointer or pointer.get("sendRefused"):
        return None
    attempt = _owned_attempt(attempts, pointer)
    if (attempt.get("checkoutMode") != website_checkout.CHECKOUT_MODE_WEBSITE
            or attempt.get("status") != payment_attempt.PAYMENT_PENDING
            or attempt.get("paidAt") or attempt.get("verifiedProviderPaymentId")
            or attempt.get("verifiedCapturedPaise")):
        return None
    aid = str(attempt.get("paymentAttemptId") or "")
    gateway = str(attempt.get("providerOrderId") or "")
    reference = str(attempt.get("referenceId") or "")
    amount = int(attempt.get("amountPaise") or 0)
    if not aid or not gateway or not reference or amount <= 0:
        return None
    binding = order_keys.resolve_gateway_order(keys, gateway) or {}
    payref = order_keys.resolve_payment_reference(keys, reference) or {}
    line = payref.get("serviceLine") or {}
    if (binding.get("customerId") != owner or binding.get("paymentAttemptId") != aid
            or binding.get("gatewayOrderId") != gateway or binding.get("referenceId") != reference
            or binding.get("requestKey") != pointer["requestKey"]
            or binding.get("currency") != "INR" or binding.get("amountPaise") != amount
            or not binding.get("accountKeyId")
            or payref.get("customerId") != owner or payref.get("paymentAttemptId") != aid
            or payref.get("checkoutMode") != website_checkout.CHECKOUT_MODE_WEBSITE
            or payref.get("websiteForm") != VERSION or payref.get("amountPaise") != amount
            or line.get("singleOrder") is not True or line.get("serviceCode") != SERVICE
            or line.get("selectedOrderId") != order_id or line.get("selectedOrderNumber") != number):
        return None
    return website_checkout._browser_options(
        key_id=str(binding["accountKeyId"]), gateway_order_id=gateway,
        amount_paise=amount, currency="INR", prefill={}, payment_attempt_id=aid)


def prepare_native(*, keys, attempts, owner, order_id, number, key, note, snapshot,
                   expected_amount, now, initiation_enabled, create_order,
                   find_order_by_receipt, account_mode_of, payref_fields,
                   attempt_fields, reserve_attempt, prefill):
    """Use the proven Standard Checkout engine with the F004 per-order lock.

    Only the winning allocation may contact the provider. A second key, stale
    click or ambiguous response must not create another payable order. The
    caller has already owner-checked the original order and freshly priced its SKU.
    """
    from lambda_utils.ecommerce import website_checkout
    current = state(keys, attempts, owner=owner, order_id=order_id, number=number)
    if current["state"] in ("pending", "saving"):
        return current
    if not initiation_enabled:
        raise ValueError("PAYMENT_INITIATION_DISABLED")
    if quote(snapshot, number)["totalPayablePaise"] != expected_amount:
        raise ValueError("SERVICE_PRICE_CHANGED")
    # A request key is single-use even after its previous attempt completed.
    if _read(keys, "orderId", _click_id(owner, key)):
        raise ValueError("REQUEST_KEY_CONFLICT")
    allocation = {}

    def allocate(aid, amount):
        if amount != expected_amount or not reserve(
                keys, attempts, owner=owner, order_id=order_id, number=number,
                key=key, note=note, amount=amount, attempt_id=aid):
            raise website_checkout.CheckoutRejected("F004_REQUEST_ALREADY_RESERVED")
        try:
            reference = order_keys.allocate_payment_reference(
                keys, payment_attempt_id=aid, extra=payref_fields)
        except Exception:
            # No provider call has taken place. Release only this exact reservation.
            refused(keys, order_id=order_id, attempt_id=aid)
            raise
        allocation.update(attempt=aid, reference=reference)
        return reference

    def create(**kwargs):
        # The generic checkout engine supports a stale-key recovery create; F004
        # deliberately does NOT. Only a fresh winning per-order allocation may create.
        if not allocation:
            raise website_checkout.CheckoutRejected("F004_CREATE_NOT_OWNED")
        return create_order(**kwargs)

    def find(receipt):
        return find_order_by_receipt(receipt) if allocation else None

    def persist(attempt):
        if (attempt.get("paymentAttemptId") != allocation.get("attempt")
                or attempt.get("referenceId") != allocation.get("reference")):
            raise RuntimeError("F004_ATTEMPT_BINDING_MISMATCH")
        reserve_attempt(dict(attempt, **attempt_fields))

    try:
        prepared = website_checkout.prepare_checkout(
            customer_id=owner, snapshot=snapshot,
            presented_snapshot_hash=snapshot.snapshot_hash, request_key=key, now=now,
            keys_table=keys, attempts_table=attempts, create_order=create,
            find_order_by_receipt=find, account_mode_of=account_mode_of,
            initiation_enabled=initiation_enabled, prefill=prefill,
            reserve_attempt=persist, allocate_reference=allocate,
            purchased_snapshot=snapshot.frozen_data)
    except website_checkout.CheckoutRejected:
        # A lost claim is not a payment failure. Read the active reservation.
        current = state(keys, attempts, owner=owner, order_id=order_id, number=number)
        if current["state"] in ("pending", "saving", "received"):
            return current
        raise
    current = state(keys, attempts, owner=owner, order_id=order_id, number=number)
    if (allocation and prepared.status == website_checkout.CHECKOUT_OPTIONS_READY
            and current.get("requestKey") == key and current["state"] == "pending"):
        options = resume_options(keys, attempts, owner=owner, order_id=order_id, number=number)
        if options and options["paymentAttemptId"] == allocation["attempt"]:
            current["options"] = options
    return current


def reserve(keys, attempts, *, owner, order_id, number, key, note, amount, attempt_id):
    """One create right. A competing click or any uncertain write cannot send.

    Per-click anchors are never removed, even after a newer request succeeds.
    An orphaned reservation after a crash fails closed for reconciliation.
    """
    if not valid_key(key):
        raise ValueError("INVALID_REQUEST_KEY")
    note = clean_note(note)
    fingerprint = hashlib.sha256(json.dumps(
        [order_id, number, note, amount], ensure_ascii=True, separators=(",", ":")
    ).encode()).hexdigest()
    click_id = _click_id(owner, key)
    old_click = _read(keys, "orderId", click_id)
    if old_click:
        if (old_click.get("kind") != VERSION or old_click.get("intentFingerprint") != fingerprint
                or old_click.get("customerId") != owner):
            raise ValueError("REQUEST_KEY_CONFLICT")
        return False
    previous = _owned_pointer(keys, owner, order_id, number)
    if previous:
        current = state(keys, attempts, owner=owner, order_id=order_id, number=number)
        if current["state"] not in ("received", "failed"):
            return False
    row = {
        "kind": VERSION, "customerId": owner, "selectedOrderId": order_id,
        "selectedOrderNumber": number, "requestKey": key,
        "paymentAttemptId": attempt_id, "reservedAt": int(time.time()),
    }
    try:
        keys.put_item(Item={"orderId": click_id, **row, "intentFingerprint": fingerprint},
                      ConditionExpression="attribute_not_exists(orderId)")
    except Exception as exc:
        if order_keys.is_conditional_failure(exc):
            return False
        raise
    try:
        if previous:
            keys.put_item(Item={"orderId": _pointer_id(order_id), **row},
                          ConditionExpression="paymentAttemptId = :previous AND customerId = :owner",
                          ExpressionAttributeValues={":previous": previous["paymentAttemptId"], ":owner": owner})
        else:
            keys.put_item(Item={"orderId": _pointer_id(order_id), **row},
                          ConditionExpression="attribute_not_exists(orderId)")
    except Exception as exc:
        if order_keys.is_conditional_failure(exc):
            return False
        raise
    return True


def refused(keys, *, order_id, attempt_id):
    """Only a proven pre-send failure or explicit sender refusal may release."""
    keys.update_item(Key={"orderId": _pointer_id(order_id)},
                     UpdateExpression="SET sendRefused=:yes",
                     ConditionExpression="paymentAttemptId=:attempt",
                     ExpressionAttributeValues={":yes": True, ":attempt": attempt_id})


def quote(snapshot, number):
    frozen = snapshot.frozen_data
    items = frozen.get("items") or []
    meta = frozen.get("pricingMetadata") or {}
    if len(items) != 1 or items[0].get("quantity") != 1:
        raise ValueError("INVALID_F004_QUOTE")
    q = snapshot.quote
    parts = {
        "itemSubtotalPaise": items[0].get("unitPricePaise"),
        "supplyGstPaise": meta.get("supplyGstPaise"),
        "delightPaise": meta.get("discountPaise"),
        "expressPaise": meta.get("expressPaise"),
        "convenienceFeePaise": q.convenience_fee_paise,
        "convenienceGstPaise": q.convenience_gst_paise,
        "totalPayablePaise": q.total_payable_paise,
    }
    if (q.currency != "INR" or any(type(v) is not int or v < 0 for v in parts.values())
            or parts["totalPayablePaise"] <= 0
            or parts["itemSubtotalPaise"] + parts["supplyGstPaise"] - parts["delightPaise"]
            + parts["expressPaise"] + parts["convenienceFeePaise"] + parts["convenienceGstPaise"]
            != parts["totalPayablePaise"]):
        raise ValueError("INVALID_F004_QUOTE")
    return {"orderNumber": number, "currency": q.currency, **parts}


def complete(db, attempts, attempt, *, contact, phone, reference_id):
    """Called only by the existing verified post-invoice internal dispatcher.

    Verify the paid attempt, its original order and exact service activity, then
    use the shared completion writer. Never launch a WhatsApp form for web F004.
    """
    aid = str(attempt.get("paymentAttemptId") or "")
    owner = str(attempt.get("customerId") or "")
    oid = str(attempt.get("selectedOrderId") or "")
    number = str(attempt.get("selectedOrderNumber") or "")
    cid = contact_key.resolve(contact)
    note = clean_note(attempt.get("websiteRequestNote"))
    if (attempt.get("websiteForm") != VERSION or not valid_key(attempt.get("websiteRequestKey"))
            or attempt.get("serviceCode") != SERVICE or attempt.get("flowCapability") != CAPABILITY
            or attempt.get("singleOrderService") is not True or not all((aid, owner, oid, number, cid, phone))
            or attempt.get("status") != payment_attempt.PAYMENT_PAID
            or attempt.get("finalizationStage") != "ORDER_FINALIZED"
            or attempt.get("orderId") != oid or attempt.get("orderNumber") != number
            or not reference_id or attempt.get("referenceId") != reference_id
            or not attempt.get("verifiedProviderPaymentId")
            or attempt.get("verifiedCapturedPaise") != attempt.get("amountPaise")
            or contact.get("checkoutCustomerId") != owner
            or contact_store.digits(attempt.get("customerPhone")) != contact_store.digits(phone)):
        raise ValueError("UNVERIFIED_F004_PAYMENT")
    orders = db.Table(shared_tables.orders_table_name())
    order = _read(orders, "orderId", oid)
    activities = [(i, a) for i, a in enumerate(order.get("serviceActivities") or [])
                  if isinstance(a, dict) and a.get("paymentAttemptId") == aid
                  and a.get("serviceCode") == SERVICE and a.get("flowCapability") == CAPABILITY
                  and a.get("providerPaymentId") == attempt.get("verifiedProviderPaymentId")
                  and a.get("amountPaise") == attempt.get("amountPaise")]
    if (order.get("customerId") != owner or order.get("orderNumber") != number
            or aid not in (order.get("serviceActivityPaymentIds") or []) or len(activities) != 1):
        raise ValueError("UNVERIFIED_F004_ORDER_ACTIVITY")
    form = {"selected_target": "order:" + number, "note": note, "order_id": oid,
            "subject": "Submit Request", "description": note}
    name = str(contact.get("name") or "").strip()
    token = "website:f004:" + aid
    result = flow_completion.claim_completion(
        flow_token=token, screen="CONFIRMATION", flow_code="01.WD_SR",
        flow_type="form_submit", phone=contact_store.digits(phone), contact_id=cid,
        sender_name=name, form_data=form, reference_prefix="WD-SR", status="open",
        channel=flow_completion.CHANNEL_WEBSITE, ttl_seconds=0,
        extra={
            "flowId": canonical_flows.canonical_flow_id(CAPABILITY),
            "flowName": "WD-F004-Submit-Request", "flowVersion": "7.3", "schemaVersion": "1",
            "source": "website", "customerId": owner, "customerPhone": contact_store.digits(phone),
            "customerName": name, "targetType": "order", "targetReference": number,
            "orderId": oid, "orderNumber": number, "paymentAttemptId": aid,
            "referenceId": reference_id, "singleOrderService": True, "paymentStatus": "paid",
            "subject": "Submit Request", "description": note,
        },
    )
    if result.status not in ("created", "duplicate"):
        raise RuntimeError("F004_SUBMISSION_UNAVAILABLE")
    sid = result.submission_id
    saved = _read(db.Table(shared_tables.flow_submissions_table_name()), "submissionId", sid)
    if (saved.get("paymentAttemptId") != aid or saved.get("customerId") != owner
            or saved.get("orderId") != oid or saved.get("orderNumber") != number
            or saved.get("channel") != flow_completion.CHANNEL_WEBSITE
            or saved.get("description") != note or saved.get("flowToken") != token):
        raise RuntimeError("F004_SUBMISSION_READBACK_MISMATCH")
    index = activities[0][0]
    prefix = f"serviceActivities[{index}]"
    orders.update_item(Key={"orderId": oid},
                       UpdateExpression=f"SET {prefix}.flowStatus=:done, {prefix}.flowSubmissionId=:sid",
                       ConditionExpression=f"customerId=:owner AND {prefix}.paymentAttemptId=:aid",
                       ExpressionAttributeValues={":owner": owner, ":aid": aid, ":done": "COMPLETED", ":sid": sid})
    # The actual saved row is also the staff Flow Responses record. Update the
    # existing contact projection without inventing a WhatsApp conversation message.
    stamp = saved.get("createdAt")
    if stamp:
        try:
            db.Table(shared_tables.contacts_table_name()).update_item(
                Key={"id": cid},
                UpdateExpression="SET openServiceRequestId=:sid, openServiceRequestAt=:at, lastFlowSubmissionId=:sid",
                ConditionExpression="attribute_exists(id) AND checkoutCustomerId=:owner AND (attribute_not_exists(openServiceRequestAt) OR openServiceRequestAt <= :at)",
                ExpressionAttributeValues={":sid": sid, ":at": stamp, ":owner": owner})
        except Exception as exc:
            if not order_keys.is_conditional_failure(exc):
                raise
    attempts.update_item(Key={"paymentAttemptId": aid},
                         UpdateExpression="SET websiteSubmissionId=:sid, websiteRequestCompletedAt=:now",
                         ConditionExpression="#s=:paid AND websiteForm=:version AND customerId=:owner AND (attribute_not_exists(websiteSubmissionId) OR websiteSubmissionId=:sid)",
                         ExpressionAttributeNames={"#s": "status"},
                         ExpressionAttributeValues={":sid": sid, ":now": int(time.time()), ":paid": payment_attempt.PAYMENT_PAID,
                                                    ":version": VERSION, ":owner": owner})
    return {"outcome": "WEBSITE_REQUEST_COMPLETED", "serviceCode": SERVICE}
