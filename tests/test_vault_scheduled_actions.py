"""Offline contracts for Vault schedules: no untargeted or duplicate WhatsApp sends."""
import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "amplify/functions/core/secure-files/handler.py"
WORKER = ROOT / "amplify/functions/messaging/scheduled-messages/handler.py"
UI = ROOT / "src/components/workspace/service/SecureFiles.tsx"
API = ROOT / "src/api/client.ts"
PROVISION = ROOT / "scripts/provision_secure_files_api.py"

def function(name, globals_):
    tree = ast.parse(SECURE.read_text(encoding="utf-8"))
    selected = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == name]
    assert len(selected) == 1, name
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SECURE), "exec"), globals_)
    return globals_[name]

def test_schedule_time_utc_future_and_timezone_required():
    globals_ = {"datetime": datetime, "timezone": timezone, "timedelta": timedelta,
                "Any": Any}
    parse = function("_schedule_time", globals_)
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert parse(future).endswith("+00:00")
    for bad in ("2030-01-01T12:00:00", "bad-date", "2020-01-01T12:00:00Z"):
        try:
            parse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe scheduled date accepted: " + bad)
    for bad in (timedelta(minutes=1), timedelta(days=31)):
        try:
            parse((datetime.now(timezone.utc) + bad).isoformat())
        except ValueError:
            pass
        else:
            raise AssertionError("Too soon or too late was accepted")

def test_dispatch_revalidates_owner_consumes_one_use_token():
    calls = {"sent": 0, "updates": 0}
    sid = "vault-" + ("a" * 32)
    token = "t" * 32
    record = {
        "id": sid, "kind": "VAULT_ACTION_V1", "status": "DISPATCHING",
        "dispatchToken": token, "vaultAction": "access", "fileId": "file-1",
        "ownerCustomerId": "customer-1",
        "scheduledAt": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        "createdBy": "staff",
    }
    class Table:
        def get_item(self, **kwargs):
            return {"Item": dict(record)}
        def update_item(self, **kwargs):
            assert "attribute_not_exists(vaultExecutedAt)" in kwargs["ConditionExpression"]
            assert kwargs["ExpressionAttributeValues"][":token"] == token
            assert "vaultExecutedAt" not in record, "Replay must fail"
            record["vaultExecutedAt"] = kwargs["ExpressionAttributeValues"][":now"]
            calls["updates"] += 1

    def send(file_id, event, origin):
        assert file_id == "file-1"
        assert event["_auth"]["username"] == "scheduled:staff"
        calls["sent"] += 1
        return {"statusCode": 200, "body": json.dumps({"outcome": "VAULT_LINK_SENT"})}

    class ClientError(Exception):
        pass

    g = {
        "Dict": Dict, "Any": Any, "datetime": datetime, "timezone": timezone,
        "timedelta": timedelta, "time": __import__("time"), "json": json,
        "VAULT_SCHEDULE_KIND": "VAULT_ACTION_V1",
        "VAULT_SCHEDULE_ACTIONS": {"offer", "payment", "access"},
        "VAULT_SCHEDULE_TABLE": "scheduled", "_table": lambda name: Table(),
        "_owned_file_for_admin": lambda file_id: (
            {"fileId": file_id, "ownerCustomerId": "customer-1"}, None),
        "_file_access_state": lambda row, now: "READY",
        "_admin_send_access": send,
        "ClientError": ClientError,
    }
    run = function("_dispatch_vault_scheduled_action", g)
    assert run({"scheduleId": sid, "dispatchToken": token})["result"] == "SENT"
    assert calls["sent"] == 1
    # A second delivery of the same internal invocation cannot send again.
    try:
        second = run({"scheduleId": sid, "dispatchToken": token})
    except AssertionError:
        second = {"result": "FAILED"}
    assert second["result"] != "SENT"
    assert calls["sent"] == 1
    assert calls["updates"] == 1

def test_no_send_for_mismatched_file_owner_or_schedule_token():
    sid = "vault-" + "b" * 32
    row = {"kind": "VAULT_ACTION_V1", "status": "DISPATCHING",
           "dispatchToken": "z" * 32, "vaultAction": "offer", "fileId": "f",
           "ownerCustomerId": "original",
           "scheduledAt": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
    class Table:
        def get_item(self, **kwargs):
            return {"Item": row}
    g = {"Dict": Dict, "Any": Any, "datetime": datetime,
         "timezone": timezone, "timedelta": timedelta, "time": __import__("time"),
         "VAULT_SCHEDULE_TABLE": "scheduled", "VAULT_SCHEDULE_KIND": "VAULT_ACTION_V1",
         "VAULT_SCHEDULE_ACTIONS": {"offer", "payment", "access"},
         "_table": lambda name: Table(),
         "_owned_file_for_admin": lambda file_id: (
             {"fileId": "f", "ownerCustomerId": "other"}, None)}
    run = function("_dispatch_vault_scheduled_action", g)
    assert run({"scheduleId": sid, "dispatchToken": "wrong"*7})["result"] == "FAILED"
    assert run({"scheduleId": sid, "dispatchToken": "z"*32}) == {
        "result": "FAILED", "reason": "OWNER_OR_FILE_CHANGED"
    }

def test_schedule_is_transactionally_linked_to_file_and_price_checked():
    secure = SECURE.read_text(encoding="utf-8")
    worker = WORKER.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")
    provision = PROVISION.read_text(encoding="utf-8")
    assert "transact_write_items(" in secure
    assert '"TableName": VAULT_SCHEDULE_TABLE' in secure
    assert '"TableName": FILES_TABLE' in secure
    assert "ownerCustomerId = :owner" in secure
    assert "attribute_not_exists(vaultExecutedAt)" in secure
    assert "if not _vault_offer_catalog_price_valid()" in secure
    assert "SERVICE_VARIANT_BY_KIND[service_requests.VAULT]" in secure
    assert "sku" in secure
    assert "if item.get('kind') == VAULT_SCHEDULE_KIND:" in worker
    assert "outcome, reason = _dispatch_vault_schedule(item, token)" in worker
    assert "VAULT_SCHEDULE_LAMBDA = 'wecare-secure-files:live'" in worker
    assert "Never submit Vault payment templates to the generic sender" in worker
    assert "scheduleVaultAction" in api
    assert "cancelVaultScheduledAction" in api
    assert "Save & publish to Vault" in ui
    assert "Reuse existing Vault file" in ui
    assert "Send Unlock Vault now" in ui
    assert "Resend Unlock Vault" in ui
    assert "Schedule Unlock Vault" in ui
    assert "Send Review & Pay now" in ui
    assert "Resend Review & Pay" in ui
    assert "Schedule Review &amp; Pay" in ui
    assert "Resend Access Vault now" in ui
    assert "Schedule access resend" in ui
    assert "Order-status updates and invoice messages are sent only after verified payment" in ui
    assert "disabled={ schedulingBusy || !scheduledAtLocal }" in ui
    assert '"DELETE", "/secure-files/{fileId}/schedules/{scheduleId}"' in provision
    assert '"Sid": "VaultScheduledMessages"' in provision
