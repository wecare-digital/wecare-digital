#!/usr/bin/env python3
"""Narrow production release: add the reviewed AI standby inbox projection.

Unlike deploy_all_lambdas.py this starts with the exact *currently deployed*
wecare-inbound-whatsapp ZIP, not the evolving monorepo HEAD. It changes only
lambda_utils/thread_ownership.py and adds lambda_utils/standby_inbox.py.

Dry-run is the default. --apply requires explicit live version + code SHA
preconditions and never changes Meta routing, contacts, events or messages.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import time
import urllib.request
import zipfile

import boto3

REGION = "us-east-1"
FUNCTION = "wecare-inbound-whatsapp"
WRITER = "lambda_utils/thread_ownership.py"
PROJECTION = "lambda_utils/standby_inbox.py"
ROOT = Path(__file__).resolve().parents[1]
PROJECTION_SRC = ROOT / "amplify/functions/shared/lambda_utils/standby_inbox.py"

ANCHOR = """        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning('{"event":"standby_context_write_failed","error":"%s"}',"""

REPLACEMENT = """        # Mirroring is read-only with respect to the customer and WhatsApp.
        # Context storage above remains the source for retry/reconciliation.
        try:
            from lambda_utils import standby_inbox
            projected = standby_inbox.mirror(
                phone_number_id, bsuid=bsuid, wa_id=wa_id,
                message=message, content=content,
            )
            if not projected:
                logger.warning('{"event":"standby_inbox_projection_retry_needed"}')
        except Exception as exc:
            logger.warning('{"event":"standby_inbox_projection_retry_needed","errorType":"%s"}',
                           type(exc).__name__)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning('{"event":"standby_context_write_failed","error":"%s"}',"""


def patch_writer(original: bytes) -> bytes:
    text = original.decode("utf-8")
    if "standby_inbox_projection_retry_needed" in text:
        raise RuntimeError("deployed writer already contains a standby projection")
    start = text.find("def store_standby_message(")
    if start < 0:
        raise RuntimeError("deployed writer does not contain store_standby_message")
    tail = text[start:]
    if tail.count(ANCHOR) != 1:
        raise RuntimeError(f"expected one exact standby-writer anchor; found {tail.count(ANCHOR)}")
    updated = text[:start] + tail.replace(ANCHOR, REPLACEMENT, 1)
    compile(updated, WRITER, "exec")
    return updated.encode("utf-8")


def patched_zip(original_zip: bytes, projection_source: bytes) -> tuple[bytes, dict]:
    compile(projection_source, PROJECTION, "exec")
    out = io.BytesIO()
    changed = []
    seen = set()
    with zipfile.ZipFile(io.BytesIO(original_zip), "r") as existing:
        files = {z.filename for z in existing.infolist()}
        if WRITER not in files or "lambda_utils/message_store.py" not in files:
            raise RuntimeError("runtime package missing reviewed dependencies")
        if PROJECTION in files:
            raise RuntimeError("standby projection already deployed; refuse overwrite")
        provider = existing.read("lambda_utils/message_store.py").decode("utf-8")
        if "def build_message_item(" not in provider:
            raise RuntimeError("deployed message_store lacks build_message_item")
        with zipfile.ZipFile(out, "w") as updated:
            for info in existing.infolist():
                if info.filename in seen:
                    raise RuntimeError("duplicate filename in deployed ZIP")
                seen.add(info.filename)
                raw = existing.read(info)
                if info.filename == WRITER:
                    raw = patch_writer(raw)
                    changed.append(WRITER)
                updated.writestr(info, raw)
            updated.writestr(PROJECTION, projection_source, compress_type=zipfile.ZIP_DEFLATED)
            changed.append(PROJECTION)
    return out.getvalue(), {"modifiedFiles": changed, "retainedFiles": len(seen) - 1}


def client():
    return boto3.client("lambda", region_name=REGION)


def get_version_package(api, *, expected_version: str = "", expected_sha: str = ""):
    alias = api.get_alias(FunctionName=FUNCTION, Name="live")
    version = str(alias["FunctionVersion"])
    if expected_version and version != expected_version:
        raise RuntimeError(f"live alias moved: expected {expected_version}, actual {version}")
    live = api.get_function(FunctionName=FUNCTION, Qualifier="live")
    latest = api.get_function_configuration(FunctionName=FUNCTION)
    sha = str(live["Configuration"]["CodeSha256"])
    if expected_sha and sha != expected_sha:
        raise RuntimeError("live code checksum changed since review")
    if str(latest.get("CodeSha256")) != sha:
        raise RuntimeError("$LATEST differs from live; refusing to overwrite staged code")
    if latest.get("State") != "Active" or latest.get("LastUpdateStatus") != "Successful":
        raise RuntimeError("function not stable")
    with urllib.request.urlopen(live["Code"]["Location"], timeout=35) as response:
        zdata = response.read()
    calculated = base64.b64encode(hashlib.sha256(zdata).digest()).decode("ascii")
    if calculated != sha:
        raise RuntimeError("downloaded Lambda ZIP checksum mismatch")
    return alias, latest, sha, zdata


def wait_for_update(api, seconds: int = 90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        cfg = api.get_function_configuration(FunctionName=FUNCTION)
        status = cfg.get("LastUpdateStatus")
        if status == "Successful" and cfg.get("State") == "Active":
            return cfg
        if status == "Failed":
            raise RuntimeError("Lambda code update failed")
        time.sleep(4)
    raise RuntimeError("Lambda update did not finish within wait limit")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="publish the patch and switch the live alias")
    p.add_argument("--expected-version", default="", help="required on --apply")
    p.add_argument("--expected-code-sha", default="", help="required on --apply")
    args = p.parse_args()
    if args.apply and (not args.expected_version or not args.expected_code_sha):
        p.error("--apply requires --expected-version and --expected-code-sha")

    api = client()
    alias, latest, old_sha, original = get_version_package(
        api, expected_version=args.expected_version,
        expected_sha=args.expected_code_sha)
    current_version = str(alias["FunctionVersion"])
    patch, details = patched_zip(original, PROJECTION_SRC.read_bytes())
    new_sha = base64.b64encode(hashlib.sha256(patch).digest()).decode("ascii")
    report = {
        "mode": "apply" if args.apply else "dry-run",
        "oldAliasVersion": current_version,
        "oldCodeSha256": old_sha,
        "newCodeSha256": new_sha,
        "newZipBytes": len(patch),
        **details,
    }
    print(json.dumps(report, sort_keys=True), flush=True)
    if not args.apply:
        return 0

    update = api.update_function_code(
        FunctionName=FUNCTION, ZipFile=patch,
        RevisionId=latest["RevisionId"])
    if update.get("CodeSha256") != new_sha:
        raise RuntimeError("UpdateFunctionCode checksum mismatch; alias remains unchanged")
    wait_for_update(api)
    new_version = str(api.publish_version(
        FunctionName=FUNCTION, CodeSha256=new_sha,
        Description="AI standby messages visible in the read-only Unified Inbox",
    )["Version"])
    published = api.get_function_configuration(FunctionName=FUNCTION, Qualifier=new_version)
    if published.get("CodeSha256") != new_sha:
        raise RuntimeError("Published version checksum mismatch; alias remains unchanged")

    # Compare-and-swap: another deploy moving live must make this release fail.
    current_alias = api.get_alias(FunctionName=FUNCTION, Name="live")
    if (str(current_alias.get("FunctionVersion")) != current_version
            or str(current_alias.get("RevisionId")) != str(alias.get("RevisionId"))):
        raise RuntimeError("live alias moved while packaging; refuse switch")
    api.update_alias(
        FunctionName=FUNCTION, Name="live", FunctionVersion=new_version,
        RevisionId=current_alias["RevisionId"])
    verified_alias = api.get_alias(FunctionName=FUNCTION, Name="live")
    if str(verified_alias.get("FunctionVersion")) != new_version:
        # Best-effort rollback only if this script's alias version is still active.
        if str(verified_alias.get("FunctionVersion")) == new_version:
            api.update_alias(
                FunctionName=FUNCTION, Name="live", FunctionVersion=current_version,
                RevisionId=verified_alias["RevisionId"])
        raise RuntimeError("unexpected alias target after release")
    print(json.dumps({
        "release": "verified",
        "previousVersion": current_version,
        "liveVersion": new_version,
        "codeSha256": new_sha,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
