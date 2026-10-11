"""V1 + feat-003 — the 24h configurable access-window invariant (pure math).

These pin the owner rule: ₹49 = one window of VAULT_ACCESS_WINDOW_HOURS (default 24); inside it
downloads are free; opening is idempotent (no double-charge / double-count on a replay); the
window opens at delivery and renewing increments accessWindowCount on the SAME entitlement.
"""
import importlib
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pytest

from lambda_utils.ecommerce import vault_window


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("VAULT_ACCESS_WINDOW_HOURS", raising=False)
    monkeypatch.delenv("VAULT_ACCESS_WINDOW_GRACE_SECONDS", raising=False)
    importlib.reload(vault_window)
    yield
    importlib.reload(vault_window)


def test_defaults_are_24h_and_300s():
    assert vault_window.window_hours() == 24
    assert vault_window.window_grace_seconds() == 300


def test_config_overrides_window_and_grace(monkeypatch):
    monkeypatch.setenv("VAULT_ACCESS_WINDOW_HOURS", "48")
    monkeypatch.setenv("VAULT_ACCESS_WINDOW_GRACE_SECONDS", "0")
    assert vault_window.window_hours() == 48
    assert vault_window.window_grace_seconds() == 0


def test_bad_config_falls_back_to_defaults(monkeypatch):
    monkeypatch.setenv("VAULT_ACCESS_WINDOW_HOURS", "not-a-number")
    assert vault_window.window_hours() == 24


def test_no_window_means_closed_and_awaiting_purchase():
    ent = {"entitlementState": "ACTIVE"}
    now = 1_000_000
    assert vault_window.window_open(ent, now) is False
    assert vault_window.window_count(ent) == 0
    assert vault_window.status_label(ent, now) == "Awaiting purchase"


def test_open_window_starts_now_and_counts_one():
    ent = {"entitlementState": "ACTIVE"}
    now = 1_000_000
    fields, opened = vault_window.open_window(ent, now)
    assert opened is True
    assert fields["accessWindowStartedAt"] == now
    assert fields["accessWindowEndsAt"] == now + 24 * 3600
    assert fields["accessWindowCount"] == 1


def test_inside_window_is_open_and_free():
    now = 1_000_000
    ent = {"accessWindowEndsAt": now + 10 * 3600, "accessWindowCount": 1}
    assert vault_window.window_open(ent, now) is True
    assert vault_window.window_open(ent, now + 10 * 3600) is True  # exactly at the edge
    assert "Active" in vault_window.status_label(ent, now)


def test_grace_keeps_a_boundary_download_alive_but_status_is_honest():
    now = 1_000_000
    ent = {"accessWindowEndsAt": now, "accessWindowCount": 1}
    # 200s past the end, inside the 300s grace -> still openable for a mid-flight download.
    assert vault_window.window_open(ent, now + 200) is True
    # ...but the status label ignores grace and reads Expired once the clock passes the end.
    assert vault_window.status_label(ent, now + 1) == "Expired"


def test_past_grace_is_closed():
    now = 1_000_000
    ent = {"accessWindowEndsAt": now, "accessWindowCount": 1}
    assert vault_window.window_open(ent, now + 301) is False
    assert vault_window.status_label(ent, now + 301) == "Expired"


def test_opening_is_idempotent_while_open_no_double_count():
    now = 1_000_000
    ent = {"accessWindowEndsAt": now + 10 * 3600, "accessWindowCount": 1}
    fields, opened = vault_window.open_window(ent, now)
    assert opened is False and fields == {}  # a duplicate tap changes nothing


def test_renewing_a_closed_window_increments_count_same_entitlement():
    now = 1_000_000
    ent = {"accessWindowEndsAt": now - 3600, "accessWindowCount": 1}  # expired
    fields, opened = vault_window.open_window(ent, now)
    assert opened is True
    assert fields["accessWindowCount"] == 2  # renewal, not a new entitlement
    assert fields["accessWindowStartedAt"] == now


def test_seconds_remaining_excludes_grace():
    now = 1_000_000
    ent = {"accessWindowEndsAt": now + 3600, "accessWindowCount": 1}
    assert vault_window.seconds_remaining(ent, now) == 3600
    assert vault_window.seconds_remaining({"accessWindowEndsAt": now - 1}, now) == 0


# ── handler-level: the _redeem window gate ──────────────────────────────────
import importlib.util  # noqa: E402

FUNC_DIR = pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/core/secure-files"


@pytest.fixture()
def handler(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location(
        "wecare_secure_files_handler_window", FUNC_DIR / "handler.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wecare_secure_files_handler_window"] = module
    spec.loader.exec_module(module)
    return module


class _FakeGrants:
    """Minimal grants table: get_item / update_item (SET window fields), with a condition hook."""
    def __init__(self, rows):
        self.rows = {r["grantId"]: dict(r) for r in rows}

    def get_item(self, Key, ConsistentRead=False):
        row = self.rows.get(Key["grantId"])
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item, **_):
        self.rows[Item["grantId"]] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, **_):
        row = self.rows[Key["grantId"]]
        row["accessWindowStartedAt"] = ExpressionAttributeValues[":s"]
        row["accessWindowEndsAt"] = ExpressionAttributeValues[":e"]
        row["accessWindowCount"] = ExpressionAttributeValues[":c"]


class _FakeFiles:
    """Tolerates the ADD downloadCount update on FILES_TABLE; records nothing else."""
    def update_item(self, **_):
        return {}


IDENTITY = {"phone": "919999999999", "subject": "cust-sub-1"}
FILE = {"fileId": "f1", "ownerPhone": "919999999999", "ownerCustomerId": "cust-sub-1",
        "status": "active", "deliverable": "pdf", "deliveryKey": "secure/d/f1.pdf"}


def _entitlement(**extra):
    base = {"grantId": "vault-entitlement#cust-sub-1#f1", "recordType": "VAULT_ENTITLEMENT",
            "entitlementState": "ACTIVE", "customerId": "cust-sub-1", "ownerPhone": "919999999999",
            "fileId": "f1"}
    base.update(extra)
    return base


def _redeem(handler, monkeypatch, entitlement):
    grants = _FakeGrants([entitlement])
    files = _FakeFiles()
    monkeypatch.setattr(handler, "_table", lambda name: files if name == handler.FILES_TABLE else grants)
    monkeypatch.setattr(handler, "_owned_active_file", lambda _f, _i: dict(FILE))
    monkeypatch.setattr(handler, "_download_url", lambda _item, ttl=None: "https://signed/f1?x=1")
    monkeypatch.setattr(handler, "_queue_vault_review", lambda _e: None)
    event = {"queryStringParameters": {"grant": entitlement["grantId"]}}
    resp = handler._redeem("f1", event, IDENTITY, "https://wecare.digital")
    return resp, grants


def test_first_redeem_opens_the_window_and_delivers(handler, monkeypatch):
    resp, grants = _redeem(handler, monkeypatch, _entitlement())  # no window yet
    assert resp["statusCode"] == 200
    row = grants.rows["vault-entitlement#cust-sub-1#f1"]
    assert row["accessWindowCount"] == 1
    assert row["accessWindowEndsAt"] > 0


def test_second_redeem_inside_the_window_is_free(handler, monkeypatch):
    now = int(__import__("time").time())
    ent = _entitlement(accessWindowEndsAt=now + 10 * 3600, accessWindowCount=1)
    resp, grants = _redeem(handler, monkeypatch, ent)
    assert resp["statusCode"] == 200
    # Still one window — a free re-download did not open or count a new one.
    assert grants.rows["vault-entitlement#cust-sub-1#f1"]["accessWindowCount"] == 1


def test_redeem_after_window_closed_is_refused_not_delivered(handler, monkeypatch):
    now = int(__import__("time").time())
    ent = _entitlement(accessWindowEndsAt=now - 3600, accessWindowCount=1)  # expired
    resp, _ = _redeem(handler, monkeypatch, ent)
    assert resp["statusCode"] == 403
    assert "ACCESS_WINDOW_CLOSED" in resp["body"]


# ── feat-004: delivery opens the window (WhatsApp entry path) ────────────────

PAID_GRANT = {
    "grantId": "grant-1", "fileId": "f1", "ownerPhone": "919999999999",
    "customerId": "cust-sub-1", "paid": True, "consumed": False, "channel": "whatsapp",
    "amountPaise": 4900,
}
ACTIVE_FILE = {
    "fileId": "f1", "status": "active", "ownerPhone": "919999999999",
    "ownerCustomerId": "cust-sub-1", "deliverable": "pdf", "deliveryKey": "secure/d/f1.pdf",
    "originalFilename": "report.pdf",
}


class _DeliveryTables:
    """One fake standing in for GRANTS + FILES, enough for deliver_over_whatsapp."""
    def __init__(self, grant, file):
        self.rows = {grant["grantId"]: dict(grant), file["fileId"]: dict(file)}
        self.entitlement_id = "vault-entitlement#cust-sub-1#f1"

    def get_item(self, Key, ConsistentRead=False):
        k = Key.get("grantId") or Key.get("fileId")
        row = self.rows.get(k)
        return {"Item": dict(row)} if row else {}

    def put_item(self, Item, **_):
        self.rows[Item["grantId"]] = dict(Item)

    def update_item(self, Key, UpdateExpression="", ExpressionAttributeValues=None, **_):
        k = Key.get("grantId") or Key.get("fileId")
        row = self.rows.setdefault(k, {"grantId": k})
        vals = ExpressionAttributeValues or {}
        if ":s" in vals:  # window open
            row["accessWindowStartedAt"] = vals[":s"]
            row["accessWindowEndsAt"] = vals[":e"]
            row["accessWindowCount"] = vals[":c"]


def _deliver(handler, monkeypatch, send_ok):
    tables = _DeliveryTables(PAID_GRANT, ACTIVE_FILE)
    monkeypatch.setattr(handler, "_table", lambda _n: tables)
    fake_delivery = type(sys)("whatsapp_delivery")
    fake_delivery.send_document = lambda **_: (send_ok, "sent" if send_ok else "failed")
    fake_delivery.send_download_link = lambda **_: (send_ok, "sent" if send_ok else "failed")
    monkeypatch.setitem(sys.modules, "whatsapp_delivery", fake_delivery)
    monkeypatch.setattr(handler, "_download_url", lambda _item, ttl=None: "https://signed/f1")
    ok, _ = handler.deliver_over_whatsapp("grant-1")
    return ok, tables


def test_successful_whatsapp_delivery_opens_the_window(handler, monkeypatch):
    ok, tables = _deliver(handler, monkeypatch, send_ok=True)
    assert ok is True
    ent = tables.rows[tables.entitlement_id]
    assert ent["accessWindowCount"] == 1
    assert ent["accessWindowEndsAt"] > 0


def test_failed_whatsapp_delivery_leaves_the_window_closed(handler, monkeypatch):
    ok, tables = _deliver(handler, monkeypatch, send_ok=False)
    assert ok is False
    ent = tables.rows.get(tables.entitlement_id) or {}
    # Nothing was delivered, so the clock must NOT have started.
    assert "accessWindowEndsAt" not in ent


# ── feat-005: _public_file surfaces tag + access-window status ───────────────

def test_public_file_reports_awaiting_purchase_without_an_entitlement(handler):
    row = {"fileId": "f1", "displayName": "Report", "tag": "Passport", "status": "active"}
    out = handler._public_file(row, admin=True)
    assert out["tag"] == "Passport"
    assert out["accessWindowStatus"] == "Awaiting purchase"
    assert out["accessWindowOpen"] is False
    assert out["accessWindowCount"] == 0


def test_public_file_reports_active_window_from_entitlement(handler):
    now = int(__import__("time").time())
    row = {"fileId": "f1", "displayName": "Report", "status": "active"}
    ent = {"accessWindowEndsAt": now + 5 * 3600, "accessWindowCount": 1}
    out = handler._public_file(row, admin=True, entitlement=ent, now=now)
    assert out["accessWindowOpen"] is True
    assert "Active" in out["accessWindowStatus"]
    assert out["accessWindowCount"] == 1


def test_public_file_reports_expired_window(handler):
    now = int(__import__("time").time())
    row = {"fileId": "f1", "displayName": "Report", "status": "active"}
    # Well past the end AND past the 300s grace, so it is unambiguously closed.
    ent = {"accessWindowEndsAt": now - 3600, "accessWindowCount": 2}
    out = handler._public_file(row, admin=True, entitlement=ent, now=now)
    assert out["accessWindowOpen"] is False
    assert out["accessWindowStatus"] == "Expired"
    assert out["accessWindowCount"] == 2


def test_tag_is_bounded_and_control_chars_stripped(handler):
    # The sanitiser used by _upload_init: printable only, max 60 chars.
    raw = "Pass\x00port\n" + "x" * 100
    cleaned = "".join(c for c in raw.strip() if c.isprintable())[:60]
    assert "\x00" not in cleaned and "\n" not in cleaned
    assert len(cleaned) <= 60
