#!/usr/bin/env python3
"""Narrow guarded release for read-only Meta thread ownership in the inbox.

This modifies only handler.py inside the exact deployed messages-read ZIP.
Dry-run by default; --apply requires live version and checksum preconditions.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request
import zipfile

import boto3

REGION = "us-east-1"
FUNCTION = "wecare-messages-read"
FILE = "handler.py"
SOURCE = Path(__file__).resolve().parents[1] / "amplify/functions/core/messages-read/handler.py"
BEGIN = "def _read_one_message(message_id: str, request_id: str, origin: str = '') -> Dict[str, Any]:"
OLD_END = "\n\ndef _update_payment_message("
NEW_END = "\n\ndef _read_standby_thread_ownership("
HELPER_BEGIN = "def _read_standby_thread_ownership(item: Dict[str, Any]) -> Dict[str, Any]:"

OLD_READ_ONE = """def _read_one_message(message_id: str, request_id: str, origin: str = '') -> Dict[str, Any]:
    result = dynamodb.Table(MESSAGES_TABLE).get_item(Key={'id': message_id})
    item = result.get('Item')
    if not item:
        return cors_response(404, {'error': 'Message not found'}, origin)
    message = _convert_from_dynamodb(item)
    log_event(logger, 'message_read_one', messageId=message_id, requestId=request_id)
    return cors_response(200, {'message': message}, origin)"""


def unique_replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"expected one exact patch anchor; found {source.count(old)}")
    return source.replace(old, new, 1)


def pull_section(text: str, begin: str, end: str) -> str:
    a = text.find(begin)
    if a < 0:
        raise RuntimeError(f"missing desired source anchor: {begin}")
    b = text.find(end, a)
    if b < 0:
        raise RuntimeError(f"missing desired source end: {end}")
    return text[a:b]


def patch_runtime(original: bytes, desired: bytes) -> bytes:
    deployed = original.decode("utf-8")
    latest = desired.decode("utf-8")
    if HELPER_BEGIN in deployed or "threadOwnership" in deployed:
        raise RuntimeError("ownership lookup already present in runtime; refuse overwrite")
    new_read = pull_section(latest, BEGIN, NEW_END)
    new_helper = pull_section(latest, HELPER_BEGIN, OLD_END)
    if "ConsistentRead=True" not in new_helper or "_SAFE_BSUID.fullmatch" not in new_helper:
        raise RuntimeError("desired helper has lost fail-closed identity checks")
    out = unique_replace(deployed, "import logging\nimport boto3",
                         "import logging\nimport re\nimport time\nimport boto3")
    anchor = "MESSAGES_TABLE = os.environ.get('MESSAGES_TABLE', 'stack-wecare-digital-MessagesTable')"
    desired_extra = (
        "THREAD_OWNERSHIP_TABLE = os.environ.get('THREAD_OWNERSHIP_TABLE', 'stack-wecare-digital-ThreadOwnershipTable')\n"
        "_META_SENDER_PHONE_IDS = frozenset({'1016149501586345', '1055232054343117'})\n"
        "_SAFE_BSUID = re.compile(r'^[A-Za-z0-9._:-]{1,160}$')"
    )
    if desired_extra not in latest:
        raise RuntimeError("desired source does not contain reviewed ownership constants")
    out = unique_replace(out, anchor, anchor + "\n" + desired_extra)
    out = unique_replace(out, OLD_READ_ONE, new_read)
    out = unique_replace(out, OLD_END, "\n\n" + new_helper + OLD_END)
    compile(out, FILE, "exec")
    return out.encode("utf-8")


def patched_zip(original_zip: bytes, desired_source: bytes) -> tuple[bytes, dict]:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original_zip), "r") as deployed:
        entries = deployed.infolist()
        if not any(x.filename == FILE for x in entries):
            raise RuntimeError("live package missing handler.py")
        seen = set()
        with zipfile.ZipFile(out, "w") as updated:
            for info in entries:
                if info.filename in seen:
                    raise RuntimeError("duplicate ZIP member")
                seen.add(info.filename)
                data = deployed.read(info)
                if info.filename == FILE:
                    data = patch_runtime(data, desired_source)
                updated.writestr(info, data)
    return out.getvalue(), {"modifiedFiles": [FILE], "preservedFiles": len(seen) - 1}


def check_live(client, expected_version: str = "", expected_sha: str = ""):
    alias = client.get_alias(FunctionName=FUNCTION, Name="live")
    live = client.get_function(FunctionName=FUNCTION, Qualifier="live")
    cfg = client.get_function_configuration(FunctionName=FUNCTION)
    version = str(alias["FunctionVersion"])
    old_sha = str(live["Configuration"]["CodeSha256"])
    if expected_version and version != expected_version:
        raise RuntimeError("live alias version changed")
    if expected_sha and old_sha != expected_sha:
        raise RuntimeError("live code checksum changed")
    if cfg.get("CodeSha256") != old_sha or cfg.get("State") != "Active" or cfg.get("LastUpdateStatus") != "Successful":
        raise RuntimeError("$LATEST differs from live or is updating")
    with urllib.request.urlopen(live["Code"]["Location"], timeout=40) as stream:
        original = stream.read()
    if base64.b64encode(hashlib.sha256(original).digest()).decode("ascii") != old_sha:
        raise RuntimeError("downloaded live ZIP checksum mismatch")
    return alias, cfg, old_sha, original


def wait_update(client, seconds: int = 100):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        cfg = client.get_function_configuration(FunctionName=FUNCTION)
        if cfg.get("LastUpdateStatus") == "Successful" and cfg.get("State") == "Active":
            return
        if cfg.get("LastUpdateStatus") == "Failed":
            raise RuntimeError("Lambda code update failed")
        time.sleep(4)
    raise RuntimeError("Lambda update timed out")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--expected-version", default="")
    p.add_argument("--expected-code-sha", default="")
    args = p.parse_args()
    if args.apply and not (args.expected_version and args.expected_code_sha):
        p.error("apply requires expected version and SHA")
    api = boto3.client("lambda", region_name=REGION)
    alias, cfg, old_sha, original = check_live(
        api, expected_version=args.expected_version, expected_sha=args.expected_code_sha)
    updated, details = patched_zip(original, SOURCE.read_bytes())
    new_sha = base64.b64encode(hashlib.sha256(updated).digest()).decode("ascii")
    print(json.dumps({"mode": "apply" if args.apply else "dry-run",
                      "oldVersion": alias["FunctionVersion"], "oldSha": old_sha,
                      "newSha": new_sha, "zipSize": len(updated), **details}), flush=True)
    if not args.apply:
        return 0
    applied = api.update_function_code(
        FunctionName=FUNCTION, ZipFile=updated, RevisionId=cfg["RevisionId"])
    if applied.get("CodeSha256") != new_sha:
        raise RuntimeError("updated Lambda checksum mismatch; live alias unchanged")
    wait_update(api)
    version = str(api.publish_version(
        FunctionName=FUNCTION, CodeSha256=new_sha,
        Description="Authenticated current Meta thread ownership in Unified Inbox")["Version"])
    verified = api.get_function_configuration(FunctionName=FUNCTION, Qualifier=version)
    if verified.get("CodeSha256") != new_sha:
        raise RuntimeError("published checksum mismatch; live alias unchanged")
    current = api.get_alias(FunctionName=FUNCTION, Name="live")
    if current.get("FunctionVersion") != alias.get("FunctionVersion") or current.get("RevisionId") != alias.get("RevisionId"):
        raise RuntimeError("alias changed concurrently; leave live unchanged")
    api.update_alias(FunctionName=FUNCTION, Name="live",
                     FunctionVersion=version, RevisionId=current["RevisionId"])
    verified_alias = api.get_alias(FunctionName=FUNCTION, Name="live")
    verified_live = api.get_function_configuration(FunctionName=FUNCTION, Qualifier="live")
    if verified_alias.get("FunctionVersion") != version or verified_live.get("CodeSha256") != new_sha:
        raise RuntimeError("live alias verification failed; inspect manually")
    print(json.dumps({"release": "verified", "prior": alias["FunctionVersion"],
                      "liveVersion": version, "checksum": new_sha}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
