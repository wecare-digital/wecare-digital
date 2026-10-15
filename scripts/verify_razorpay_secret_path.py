#!/usr/bin/env python3
"""Prove the _razorpay_creds() fix resolves, and that the old path could not.

Mirrors the exact logic now shipped in
amplify/functions/messaging/partner-onboarding/handler.py. Reports only whether
each field is populated, its length, and an irreversible sha256 prefix - never a
value and never any part of one.
"""
import hashlib
import json

import boto3

sm = boto3.client("secretsmanager", region_name="us-east-1")

API_ONLY = ("wecare/razorpay/api",)
OLD_ONLY = "wecare/razorpay-webhook"


def fingerprint(value: str) -> str:
    """A stable, non-reversible identity for a value.

    Short values are not hashed: a sha256 of a handful of characters is invertible by
    brute force, so it would disclose what it is meant to hide. A Razorpay key id is
    ~20 characters, so this branch is a guard rather than the expected path.
    """
    if not value:
        return "sha256:-"
    if len(value) <= 8:
        return "<short>"
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def creds(secret_ids):
    for sid in secret_ids:
        try:
            raw = sm.get_secret_value(SecretId=sid).get("SecretString", "") or "{}"
            d = json.loads(raw)
            k = (d.get("key_id") or "").strip()
            s = (d.get("key_secret") or "").strip()
            if k and s:
                return sid, k, s
        except Exception:  # noqa: BLE001
            continue
    return None, "", ""


def main() -> int:
    src, k, s = creds(API_ONLY)
    print("CANONICAL API code path")
    print(f"  resolved from      : {src}")
    # Not `prefix={k[:4]}`, which is what this printed until 2026-09-29 while the
    # docstring above claimed it reported only populated-ness and length. Four
    # characters of a live key id is an issuer prefix, and the repository's
    # credential-fingerprint rule is the one this broke: never print a prefix or a
    # suffix of a credential, because an issuer prefix plus an exact length is a
    # meaningful head start. The sha256 prefix still distinguishes the
    # new path's key id from the old path's, which is the only thing it is for.
    print(f"  key_id populated   : {bool(k)}  len={len(k)}  {fingerprint(k)}")
    print(f"  key_secret populated: {bool(s)}  len={len(s)}")
    print(f"  would return 501   : {not (k and s)}")

    osrc, ok, os_ = creds((OLD_ONLY,))
    raw = sm.get_secret_value(SecretId=OLD_ONLY)["SecretString"]
    fields = sorted(json.loads(raw))
    print("\nOLD code path (read only wecare/razorpay-webhook)")
    print(f"  fields present     : {fields}")
    print(f"  key_id populated   : {bool(ok)}")
    print(f"  would return 501   : {not (ok and os_)}")

    ok_fix = bool(k and s) and not bool(ok and os_)
    print("\nRESULT:", "FIX CONFIRMED - new path resolves, old path could not"
          if ok_fix else "INCONCLUSIVE")
    return 0 if ok_fix else 1


if __name__ == "__main__":
    raise SystemExit(main())
