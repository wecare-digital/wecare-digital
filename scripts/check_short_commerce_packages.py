#!/usr/bin/env python3
"""Offline proof of the exact ZIP members produced for the three payment receivers.

Uses deploy_all_lambdas.build_zip, which is the production packager, without
creating any boto3 client or calling AWS. Validates the packaged source files,
the shared one-unit policy, the single invoice engine and ZIP reproducibility.

An emitted code hash is a *candidate* Lambda CodeSha256, not proof of a
published version, release-owner approval, or provider payment verification.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import deploy_all_lambdas as deploy

RECEIVERS = ("wecare-checkout", "wecare-commerce", "wecare-inbound-whatsapp")
SHARED_SOURCE_FILES = (
    "ecommerce/short_purchase.py",
    "ecommerce/cart_contract.py",
    "ecommerce/service_requests.py",
    "ecommerce/pickup_activation.py",
)
INVOICE_FILES = {
    "invoice_engine.py": "payments/invoice-engine/handler.py",
    "receipt_layout.py": "payments/invoice-engine/receipt_layout.py",
}


def verify_contents(spec: deploy.Spec, members: dict[str, bytes]) -> None:
    """Reject a missing or stale member in an otherwise apparently valid ZIP."""
    expected = {"handler.py": spec.handler_file}
    for name in SHARED_SOURCE_FILES:
        expected["lambda_utils/" + name] = deploy.LAMBDA_UTILS / name
    if spec.name in {"wecare-checkout", "wecare-commerce"}:
        for member, relative in INVOICE_FILES.items():
            expected[member] = deploy.FUNCTIONS / relative
        if not any(member.startswith("fonts/") for member in members):
            raise ValueError(f"{spec.name}: invoice font assets not packaged")

    for member, source in expected.items():
        if not source.is_file():
            raise ValueError(f"{spec.name}: source missing: {source.relative_to(deploy.ROOT)}")
        if member not in members:
            raise ValueError(f"{spec.name}: required ZIP member missing: {member}")
        if members[member] != source.read_bytes():
            raise ValueError(f"{spec.name}: ZIP member differs from source: {member}")

    if b"short_purchase" not in members["handler.py"]:
        raise ValueError(f"{spec.name}: handler does not reference one-unit policy")

    for name, source in members.items():
        if name.endswith(".py"):
            try:
                ast.parse(source.decode("utf-8"), filename=name)
            except (SyntaxError, UnicodeError) as exc:
                raise ValueError(f"{spec.name}: invalid packaged Python {name}: {exc}") from exc


def verify_zip(blob: bytes, members: dict[str, bytes], *, name: str) -> None:
    """Check byte-to-member integrity, including the uncompressed dependencies."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(members):
            raise ValueError(f"{name}: ZIP entries differ from assembled package")
        if archive.testzip() is not None:
            raise ValueError(f"{name}: corrupt ZIP member")
        for path, source in members.items():
            if archive.read(path) != source:
                raise ValueError(f"{name}: ZIP entry differs from assembled source: {path}")


def inspect_receivers() -> list[dict]:
    """Package exactly the three receiving functions; no cloud credentials needed."""
    specs = {spec.name: spec for spec in deploy.SPECS}
    result = []
    for name in RECEIVERS:
        spec = specs.get(name)
        if spec is None or spec.standalone:
            raise ValueError(f"{name}: missing or standalone production package spec")
        blob, members = deploy.build_zip(spec)
        verify_contents(spec, members)
        verify_zip(blob, members, name=name)
        second_blob, second_members = deploy.build_zip(spec)
        if second_blob != blob or second_members != members:
            raise ValueError(f"{name}: ZIP content is nondeterministic")
        result.append({
            "name": name,
            "code_sha256": base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii"),
            "files": len(members),
            "zip_bytes": len(blob),
        })
    checkout, commerce = result[:2]
    if checkout["code_sha256"] != commerce["code_sha256"]:
        raise ValueError("checkout and commerce no longer bundle identical payment code")
    return result


def local_git_revision() -> str | None:
    """Identify the exact checked-out tree when Git metadata exists."""
    result = subprocess.run(
        ["git", "-C", str(deploy.ROOT), "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional candidate checksum JSON (not release authorization)")
    args = parser.parse_args()
    try:
        receivers = inspect_receivers()
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

    report = {
        "schema_version": "short-commerce-package-preflight-v1",
        "ok": True,
        "kind": "offline-package-only",
        "production_aliases_modified": False,
        "source_commit": local_git_revision(),
        "receivers": receivers,
    }
    output = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
