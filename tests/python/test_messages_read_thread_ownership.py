"""Read-only Meta ownership exposure must never treat missing state as sendable."""
import importlib.util
import os
from pathlib import Path
import time

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "amplify/functions/core/messages-read/handler.py"
spec = importlib.util.spec_from_file_location("messages_read_ownership_contract", SOURCE)
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)


class Table:
    def __init__(self, record):
        self.record = record
        self.reads = []

    def get_item(self, *, Key, ConsistentRead=False):
        self.reads.append((Key, ConsistentRead))
        return {"Item": self.record} if self.record else {}


class Db:
    def __init__(self, record):
        self.table = Table(record)

    def Table(self, name):
        assert name == handler.THREAD_OWNERSHIP_TABLE
        return self.table


def msg():
    return {
        "standbySourced": True,
        "awsPhoneNumberId": "phone-number-id-waba-t-direct-1055232054343117",
        "senderBsuid": "IN.known_test_recipient",
    }


def test_standby_owner_requires_explicit_fresh_handover(monkeypatch):
    now = int(time.time())
    database = Db({
        "owned": True, "lastSignal": "handover_gained",
        "lastUserActivityAt": now, "updatedAt": now,
    })
    monkeypatch.setattr(handler, "dynamodb", database)
    state = handler._read_standby_thread_ownership(msg())
    assert state == {
        "tracked": True, "owned": True, "idle": False,
        "lastSignal": "handover_gained",
    }
    assert len(database.table.reads) == 1
    key, consistent = database.table.reads[0]
    assert consistent is True
    assert key["recordType"] == "OWNER"
    assert key["threadKey"].startswith("1055232054343117#")


def test_standby_and_expired_owner_are_not_sendable(monkeypatch):
    now = int(time.time())
    for record in (
        {"owned": False, "lastSignal": "standby_observed",
         "lastUserActivityAt": now, "updatedAt": now},
        {"owned": True, "lastSignal": "handover_gained",
         "lastUserActivityAt": now - 90000, "updatedAt": now - 90000},
    ):
        monkeypatch.setattr(handler, "dynamodb", Db(record))
        state = handler._read_standby_thread_ownership(msg())
        assert state["tracked"] is True
        assert state["owned"] is False


def test_unknown_identity_or_missing_owner_cannot_grant_send(monkeypatch):
    monkeypatch.setattr(handler, "dynamodb", Db({}))
    assert handler._read_standby_thread_ownership(msg())["owned"] is False
    invalid = dict(msg(), senderBsuid="invalid#cross_account")
    assert handler._read_standby_thread_ownership(invalid)["tracked"] is False
    assert handler._read_standby_thread_ownership(
        dict(msg(), awsPhoneNumberId="unrecognized-sender")
    )["tracked"] is False
