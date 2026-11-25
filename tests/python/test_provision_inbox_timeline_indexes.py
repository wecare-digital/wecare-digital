"""Never touch AWS: exercise exact provisioning requests with a fake client."""
import importlib.util
from pathlib import Path

import pytest

from lambda_utils.inbox_timeline_indexes import INDEXES, all_active, index_definition

PATH = Path(__file__).resolve().parents[2] / "scripts/provision_inbox_timeline_indexes.py"
SPEC = importlib.util.spec_from_file_location("provision_inbox_timeline_indexes", PATH)
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)


class Client:
    def __init__(self):
        self.updates = []

    def update_table(self, **kwargs):
        self.updates.append(kwargs)


def table(*, indexes=(), billing="PAY_PER_REQUEST"):
    return {
        "TableStatus": "ACTIVE",
        "BillingModeSummary": {"BillingMode": billing},
        "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
        "AttributeDefinitions": [
            {"AttributeName": name, "AttributeType": kind}
            for name, kind in (("id", "S"), ("channel", "S"), ("contactId", "S"), ("timestamp", "N"))
        ],
        "GlobalSecondaryIndexes": list(indexes),
    }


def active(partition):
    return {**index_definition(partition), "IndexStatus": "ACTIVE"}


def test_adds_one_index_at_a_time_then_noops():
    client = Client()
    assert SCRIPT.create_next(client, "manual", table()) == INDEXES["channel"]
    assert client.updates[0]["GlobalSecondaryIndexUpdates"] == [{"Create": index_definition("channel")}]
    assert client.updates[0]["AttributeDefinitions"] == [
        {"AttributeName": "channel", "AttributeType": "S"},
        {"AttributeName": "timestamp", "AttributeType": "N"},
    ]
    assert SCRIPT.create_next(client, "manual", table(indexes=[active("channel")])) == INDEXES["contactId"]
    ready = table(indexes=[active("channel"), active("contactId")])
    assert SCRIPT.create_next(client, "manual", ready) is None
    assert all_active(ready) and len(client.updates) == 2


def test_refuses_incompatible_table_or_backfill_and_requires_explicit_provisioned_capacity():
    client = Client()
    other = table()
    other["KeySchema"] = [{"AttributeName": "messageId", "KeyType": "HASH"}]
    with pytest.raises(ValueError, match="canonical MessagesTable"):
        SCRIPT.create_next(client, "wrong", other)
    with pytest.raises(ValueError, match="ACTIVE"):
        SCRIPT.create_next(client, "manual", table(indexes=[{**active("channel"), "Backfilling": True}]))
    drift = {**active("channel"), "Projection": {"ProjectionType": "KEYS_ONLY"}}
    with pytest.raises(ValueError, match="live schema differs"):
        SCRIPT.create_next(client, "manual", table(indexes=[drift]))
    with pytest.raises(ValueError, match="explicit positive"):
        SCRIPT.create_next(client, "manual", table(billing="PROVISIONED"))
    assert not client.updates
    SCRIPT.create_next(client, "manual", table(billing="PROVISIONED"), 7, 11)
    assert client.updates[0]["GlobalSecondaryIndexUpdates"][0]["Create"]["ProvisionedThroughput"] == {
        "ReadCapacityUnits": 7, "WriteCapacityUnits": 11,
    }
