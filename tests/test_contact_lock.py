"""ContactLock: auto-lock a paying customer, idempotent and fail-OPEN, no boto3 at import."""
import ast
import os
import sys

SHARED = os.path.join(os.path.dirname(__file__), "..", "amplify", "functions", "shared")
sys.path.insert(0, os.path.abspath(SHARED))

from lambda_utils.ecommerce import contact_lock  # noqa: E402


class _Table:
    """A minimal fake implementing exactly the two update_item shapes contact_lock uses:
    a tag-append gated by a `NOT contains(tags, :tag)` condition, and an unconditional
    lock-fields-only update. Records every call so idempotency can be asserted.
    """

    def __init__(self, row=None, fail_times=0):
        self.row = dict(row) if row else {}
        self.calls = []
        self.fail_times = fail_times  # raise on the first N update_item calls

    def update_item(self, Key=None, UpdateExpression="", ConditionExpression=None,
                    ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_):
        self.calls.append(UpdateExpression)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("simulated dynamo failure")
        vals = ExpressionAttributeValues or {}
        tags = list(self.row.get("tags", []))
        # Gated tag-append path.
        if ":maybe_tag" in vals:
            if contact_lock.CUSTOMER_TAG in tags:
                # ConditionExpression `NOT contains(tags, :tag)` fails.
                raise _Cond("ConditionalCheckFailedException")
            tags = tags + [contact_lock.CUSTOMER_TAG]
            self.row["tags"] = tags
        self.row["locked"] = True
        self.row["lockedReason"] = contact_lock.REASON_PAID
        self.row["lockedAt"] = vals.get(":ts")
        return {}


class _Cond(Exception):
    pass


def test_no_boto3_imported_at_module_level():
    src = open(contact_lock.__file__).read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != "boto3" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "boto3"


def test_a_fresh_contact_is_locked_and_customer_tagged():
    t = _Table(row={"id": "c1", "tags": []})
    ok = contact_lock.lock_as_customer(t, "c1", now=1000)
    assert ok is True
    assert t.row["locked"] is True
    assert t.row["lockedReason"] == "paid"
    assert t.row["lockedAt"] == 1000
    assert t.row["tags"] == ["customer"]


def test_replay_does_not_duplicate_the_tag_and_still_succeeds():
    t = _Table(row={"id": "c1", "tags": ["customer"], "locked": True})
    ok = contact_lock.lock_as_customer(t, "c1", now=2000)
    assert ok is True
    # The gated append raised ConditionalCheckFailed; the fallback set lock fields only.
    assert t.row["tags"] == ["customer"]  # not duplicated
    assert t.row["locked"] is True


def test_fail_open_returns_false_never_raises_when_both_writes_fail():
    t = _Table(row={"id": "c1", "tags": []}, fail_times=2)
    ok = contact_lock.lock_as_customer(t, "c1", now=3000)
    assert ok is False  # both update attempts failed, but no exception escaped


def test_empty_contact_id_is_a_no_op_false():
    t = _Table(row={})
    assert contact_lock.lock_as_customer(t, "", now=1) is False
    assert t.calls == []


def test_is_locked_is_total():
    assert contact_lock.is_locked({"locked": True}) is True
    assert contact_lock.is_locked({"locked": False}) is False
    assert contact_lock.is_locked({}) is False
    assert contact_lock.is_locked(None) is False
    assert contact_lock.is_locked("not a dict") is False
