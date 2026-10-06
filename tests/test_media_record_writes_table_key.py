"""The MediaFiles record must carry the table's hash key, and the download call
sites must agree with the one surviving signature.

Why these are tested together
-----------------------------
Both are the same class of defect found on 2026-10-06: a write that could never
succeed, and a call that bound the wrong value to the wrong parameter - neither of
which produced a visible error.

`_store_media_record` built its item with `fileId`, but
`stack-wecare-digital-MediaFilesTable`'s hash key is `id` (verified live:
`KeySchema [{'AttributeName': 'id', 'KeyType': 'HASH'}]`). So every `put_item`
raised `ValidationException: Missing the key id` - 17 out of 17 writes in the seven
days to 2026-10-06 - and the `except` around it reports the failure as
"MediaFile table write failed, but s3Key is stored in message record", i.e. as an
expected absence rather than a bug. The message row kept working, so nothing
surfaced. What broke was downstream: `mediaId` stayed null, and the daily Meta
media-DELETE cron (`wecare-media-cleanup`) scanned an empty table and deleted
nothing, every day, while reporting success.

That is why the assertion here is on the KEY specifically and not merely on
"put_item was called": a call that is made and rejected is exactly what happened.
"""

import ast
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py"

sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(ROOT / "amplify/functions/messaging/inbound-whatsapp-handler"))
sys.path.insert(0, str(ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/modules"))

# The physical hash key of MediaFilesTable. Read from the live table rather than
# guessed; if the table is ever re-created with a different key this constant is the
# single place to change.
MEDIA_FILES_HASH_KEY = "id"


@pytest.fixture(scope="module")
def h():
    """Load THIS handler by path, under a name nothing else uses.

    `import handler` is ambiguous in the full suite: every Lambda in this repo has a
    `handler.py`, several test modules put their own function's directory on
    `sys.path`, and the first one to import wins `sys.modules['handler']` for the
    rest of the run. Importing by name passed in isolation and then resolved to a
    different function's handler under `pytest tests`, which is a false negative
    waiting to happen on a test whose whole job is to catch a silent failure.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("inbound_whatsapp_handler_r1", HANDLER)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {"AWS_REGION": "us-east-1"}):
        with patch("boto3.resource"), patch("boto3.client"):
            spec.loader.exec_module(module)
    return module


def _written_item(h):
    table = MagicMock()
    with patch.object(h.dynamodb, "Table", return_value=table):
        file_id = h._store_media_record(
            "msg-1",
            "o/stack/whatsapp-media/incoming/wecare-digital-abc123.jpg",
            {"mime_type": "image/jpeg", "file_size": 95093},
            "wamid-media-1",
        )
    assert table.put_item.called, "the record was never written at all"
    return file_id, table.put_item.call_args.kwargs["Item"]


def test_item_carries_the_table_hash_key(h):
    file_id, item = _written_item(h)
    assert MEDIA_FILES_HASH_KEY in item, (
        f"the item has no {MEDIA_FILES_HASH_KEY!r} attribute, so put_item fails with "
        f"ValidationException: Missing the key {MEDIA_FILES_HASH_KEY} and the Meta "
        f"media-DELETE cron finds nothing to delete. Keys written: {sorted(item)}"
    )
    assert item[MEDIA_FILES_HASH_KEY] == file_id
    # The returned id is what the message row stores as `mediaId`, so a write that
    # succeeds while returning None would still leave the row unlinked.
    assert file_id


def test_file_id_is_kept_for_back_compat(h):
    file_id, item = _written_item(h)
    assert item.get("fileId") == file_id, (
        "fileId was dropped; readers written against the old shape would break"
    )


def test_the_record_still_carries_what_cleanup_needs(h):
    """media-cleanup deletes at Meta by whatsappMediaId and needs the age."""
    _, item = _written_item(h)
    assert item["whatsappMediaId"] == "wamid-media-1"
    assert "uploadedAt" in item
    assert item["s3Key"].startswith("o/stack/whatsapp-media/incoming/")


def test_only_one_download_media_direct_api_definition():
    """Two defs of the same name is not an overload; the last one simply wins.

    There used to be a 5-parameter definition above a 6-parameter one. The earlier
    was unreachable, and the call sites were written against it, so they passed 5
    positional arguments into the 6-parameter signature: `request_id` landed in
    `phone_number_id` and the mime hint landed in `request_id`.
    """
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    defs = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_download_media_direct_api"]
    assert len(defs) == 1, (
        f"{len(defs)} definitions of _download_media_direct_api at lines "
        f"{[d.lineno for d in defs]}; only the last would ever run"
    )


def test_download_call_sites_pass_phone_number_id_by_keyword():
    """Guards against the positional-argument slide returning."""
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_download_media_direct_api"
    ]
    assert calls, "no call site found - the test would pass vacuously"
    for call in calls:
        kwargs = {k.arg for k in call.keywords}
        assert {"phone_number_id", "request_id"} <= kwargs, (
            f"call at line {call.lineno} passes phone_number_id/request_id "
            f"positionally; keywords present: {sorted(kwargs)}"
        )


def test_media_bucket_cors_predicate_rejects_an_absent_config():
    """The R1 regression gate must fail on the state that actually occurred.

    `check_retired_origins.py` imports this predicate to assert the media bucket
    allows the dashboard origin. The bug it guards was an ABSENT configuration, so
    None and [] must both be refused - a predicate that only checked for a wrong
    entry is what let the absence through for eleven days.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from provision_media_bucket_cors import (
        CORS_RULE,
        REQUIRED_ORIGIN,
        rules_allow_required_origin,
    )

    assert rules_allow_required_origin(None) is False
    assert rules_allow_required_origin([]) is False
    # A rule that allows the origin but not PUT does not let a presigned upload
    # through, so it must not count as a pass.
    assert rules_allow_required_origin(
        [{"AllowedOrigins": [REQUIRED_ORIGIN], "AllowedMethods": ["GET"]}]
    ) is False
    assert rules_allow_required_origin(
        [{"AllowedOrigins": ["https://example.com"], "AllowedMethods": ["PUT"]}]
    ) is False
    assert rules_allow_required_origin([CORS_RULE]) is True
    # No wildcard origin: this bucket also holds third-party blog sources.
    assert "*" not in CORS_RULE["AllowedOrigins"]
