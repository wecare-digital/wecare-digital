#!/usr/bin/env python3
"""Patch only the deployed standby name projection and its webhook call site.

Start from the exact live Lambda ZIP, fail closed on unexpected source shapes,
and leave every other runtime file unchanged. Dry-run unless --apply is given.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import zipfile

from pathlib import Path

from release_standby_inbox import (
    FUNCTION, PROJECTION, WRITER, ROOT, client, get_version_package, wait_for_update,
)

HANDLER = "handler.py"
PROJECTION_SOURCE = ROOT / "amplify/functions/shared/lambda_utils/standby_inbox.py"

WRITER_EDITS = [
    (
        '                          message: Dict[str, Any], content: str = "",\n'
        '                          now: Optional[int] = None) -> bool:',
        '                          message: Dict[str, Any], content: str = "",\n'
        '                          sender_name: str = "", now: Optional[int] = None) -> bool:',
    ),
    (
        '            "content": str(content or "")[:4000],\n'
        '            "messageTimestamp":',
        '            "content": str(content or "")[:4000],\n'
        '            "senderName": str(sender_name or "").strip()[:160],\n'
        '            "messageTimestamp":',
    ),
    (
        '                message=message, content=content,\n'
        '            )',
        '                message=message, content=content, sender_name=sender_name,\n'
        '            )',
    ),
]

HANDLER_EDITS = [
    (
        "                            _mp, _mb, _mw = _thread_identity(value, _m)\n"
        "                            if thread_ownership.store_standby_message(\n"
        "                                    _mp or _pid, bsuid=_mb or _bsuid, wa_id=_mw or _waid,\n"
        "                                    message=_m, content=_c):",
        "                            _mp, _mb, _mw = _thread_identity(value, _m)\n"
        "                            from lambda_utils import standby_inbox\n"
        "                            _sender_name = standby_inbox.profile_name_from_contacts(_m, _contacts)\n"
        "                            if thread_ownership.store_standby_message(\n"
        "                                    _mp or _pid, bsuid=_mb or _bsuid, wa_id=_mw or _waid,\n"
        "                                    message=_m, content=_c, sender_name=_sender_name):",
    ),
]


def _patch_exact(original: bytes, edits: list[tuple[str, str]], path: str) -> bytes:
    text = original.decode("utf-8")
    for before, after in edits:
        hits = text.count(before)
        if hits != 1:
            raise RuntimeError(f"{path}: expected 1 patch anchor; got {hits}")
        text = text.replace(before, after, 1)
    compile(text, path, "exec")
    return text.encode("utf-8")


def patched_zip(source_zip: bytes, projection_source: bytes) -> tuple[bytes, dict]:
    compile(projection_source, PROJECTION, "exec")
    out = io.BytesIO()
    changed = []
    seen = set()
    with zipfile.ZipFile(io.BytesIO(source_zip)) as source:
        names = set(source.namelist())
        required = {WRITER, HANDLER, PROJECTION, "lambda_utils/message_store.py"}
        if not required.issubset(names):
            raise RuntimeError(f"deployed package missing: {sorted(required - names)}")
        if "def mirror(" not in source.read(PROJECTION).decode("utf-8"):
            raise RuntimeError("deployed standby projection does not match expected baseline")
        for name in (WRITER, HANDLER):
            if name not in names:
                raise RuntimeError("required runtime path missing")
        with zipfile.ZipFile(out, "w") as target:
            for info in source.infolist():
                path = info.filename
                if path in seen:
                    raise RuntimeError("duplicate ZIP entry")
                seen.add(path)
                raw = source.read(info)
                if path == WRITER:
                    raw = _patch_exact(raw, WRITER_EDITS, WRITER)
                elif path == HANDLER:
                    raw = _patch_exact(raw, HANDLER_EDITS, HANDLER)
                elif path == PROJECTION:
                    raw = projection_source
                if path in {WRITER, HANDLER, PROJECTION}:
                    changed.append(path)
                target.writestr(info, raw)
    return out.getvalue(), {"modifiedFiles": sorted(changed), "preservedOtherFiles": len(seen) - len(changed)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-version", default="")
    parser.add_argument("--expected-code-sha", default="")
    args = parser.parse_args()
    if args.apply and (not args.expected_version or not args.expected_code_sha):
        parser.error("--apply requires expected-version and expected-code-sha")

    api = client()
    alias, latest, old_sha, source = get_version_package(
        api, expected_version=args.expected_version,
        expected_sha=args.expected_code_sha,
    )
    prior_version = str(alias["FunctionVersion"])
    updated, summary = patched_zip(source, PROJECTION_SOURCE.read_bytes())
    new_sha = base64.b64encode(hashlib.sha256(updated).digest()).decode("ascii")
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "oldVersion": prior_version, "oldSha": old_sha,
        "newSha": new_sha, "zipBytes": len(updated), **summary,
    }, sort_keys=True), flush=True)
    if not args.apply:
        return 0

    updated_result = api.update_function_code(
        FunctionName=FUNCTION, ZipFile=updated, RevisionId=latest["RevisionId"],
    )
    if updated_result.get("CodeSha256") != new_sha:
        raise RuntimeError("Lambda update checksum mismatch; live alias unchanged")
    wait_for_update(api)
    version = str(api.publish_version(
        FunctionName=FUNCTION,
        CodeSha256=new_sha,
        Description="Show exact-match Meta standby WhatsApp profile names in inbox",
    )["Version"])
    if api.get_function_configuration(
            FunctionName=FUNCTION, Qualifier=version).get("CodeSha256") != new_sha:
        raise RuntimeError("published version SHA mismatch; live alias unchanged")
    current_alias = api.get_alias(FunctionName=FUNCTION, Name="live")
    if (str(current_alias.get("FunctionVersion")) != prior_version
            or str(current_alias.get("RevisionId")) != str(alias.get("RevisionId"))):
        raise RuntimeError("live alias moved concurrently; no switch performed")
    api.update_alias(
        FunctionName=FUNCTION, Name="live", FunctionVersion=version,
        RevisionId=current_alias["RevisionId"],
    )
    final_alias = api.get_alias(FunctionName=FUNCTION, Name="live")
    final_config = api.get_function_configuration(FunctionName=FUNCTION, Qualifier="live")
    if (str(final_alias.get("FunctionVersion")) != version
            or final_config.get("CodeSha256") != new_sha):
        raise RuntimeError("live alias/code verification failed; inspect manually")
    print(json.dumps({"release": "verified", "previousVersion": prior_version,
                      "liveVersion": version, "sha": new_sha}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
