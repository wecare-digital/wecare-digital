"""disable_dynamodb_ttl: dry-run by default, idempotent, never enables TTL. Fake client only."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("disable_ttl", ROOT / "scripts/disable_dynamodb_ttl.py")
dt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dt)


class _NotFound(Exception):
    pass


class FakeDdb:
    class exceptions:
        ResourceNotFoundException = _NotFound

    def __init__(self, ttl):
        self.ttl = dict(ttl)  # table -> (status, attribute)
        self.updates = []

    def list_tables(self, **kw):
        return {"TableNames": sorted(self.ttl)}

    def describe_time_to_live(self, TableName):
        if TableName not in self.ttl:
            raise _NotFound()
        status, attr = self.ttl[TableName]
        return {"TimeToLiveDescription": {"TimeToLiveStatus": status, "AttributeName": attr}}

    def update_time_to_live(self, TableName, TimeToLiveSpecification):
        self.updates.append((TableName, TimeToLiveSpecification))
        self.ttl[TableName] = ("DISABLING", TimeToLiveSpecification["AttributeName"])


def _client():
    return FakeDdb({
        "Message-abc123-NONE": ("ENABLED", "expiresAt"),
        "AuditLog-abc123-NONE": ("DISABLED", None),
        "stack-wecare-digital-LinkClicksTable": ("ENABLED", "expiresAt"),
        "stack-wecare-digital-DownloadGrantsTable": ("ENABLED", "expiresAt"),
        "stack-wecare-digital-CartTable": ("DISABLING", "expiresTtl"),
        "UnrelatedTable": ("ENABLED", "ttl"),
    })


def test_dry_run_changes_nothing():
    c = _client()
    res = dt.run(c, apply=False, out=lambda *_: None)
    assert c.updates == []
    assert res["Message-abc123-NONE"].startswith("would disable")


def test_apply_disables_only_enabled_and_is_idempotent():
    c = _client()
    dt.run(c, apply=True, out=lambda *_: None)
    assert sorted(t for t, _ in c.updates) == [
        "Message-abc123-NONE",
        "stack-wecare-digital-DownloadGrantsTable",
        "stack-wecare-digital-LinkClicksTable",
    ]
    assert all(spec["Enabled"] is False for _, spec in c.updates)
    assert ("Message-abc123-NONE", {"Enabled": False, "AttributeName": "expiresAt"}) in c.updates
    n = len(c.updates)
    res = dt.run(c, apply=True, out=lambda *_: None)
    assert len(c.updates) == n
    assert res["Message-abc123-NONE"].startswith("skip")
    assert res["AuditLog-abc123-NONE"].startswith("skip")
    assert "UnrelatedTable" not in res
    assert res["WebhookDedup"] == "not found"
