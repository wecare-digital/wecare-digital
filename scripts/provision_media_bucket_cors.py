#!/usr/bin/env python3
"""Put the browser-upload CORS configuration on the media bucket `wecare-digital-get`.

Why this script exists
----------------------
The dashboard does not proxy media through the API. `getMediaUploadUrl` asks
`/whatsapp/send` for a presigned URL and then the **browser** writes straight to S3
(`uploadFileToS3`, `uploadFileViaPresignedPost` in `src/api/client.ts`). That request
is cross-origin, so the browser sends a CORS preflight first, and S3 answers a
preflight from its *bucket* CORS configuration - a presigned URL grants the write but
says nothing about the preflight.

Bucket `wecare-digital-get` was created 2026-09-25 and never got one. Measured
2026-10-06: `get_bucket_cors` returns `NoSuchCORSConfiguration` and the preflight
returns

    403 AccessForbidden  CORSResponse: CORS is not enabled for this bucket.

So every outbound WhatsApp attachment and every new template-header upload failed
before Meta was ever called - 26 presigned URLs issued that day, 0 objects written,
0 `media_upload_complete`. Inbound was unaffected because the Lambda writes
server-side, where no preflight exists. This is why "is S3 connected?" read as
PARTIAL: Lambda to S3 worked, browser to S3 did not.

The retired bucket `app.wecare.digital` *did* have CORS (`PutBucketCors`
2026-09-26, snapshot at
`docs/execution/snapshots/s3-app-bucket-cors-before-stack-origin-removal.json`).
CloudTrail shows `PutBucketCors` was never called on `wecare-digital-get`, so the
setting was simply not carried across the cutover.

It survived unnoticed for the reason `check_retired_origins.py` already names: a
setting with no generator has no diff, so no review can surface it. This file is
that missing generator. `--check` makes the absence an assertable failure, and
`check_retired_origins.py` calls the same assertion so the regression is caught by
the existing gate rather than by a user reporting "Upload failed".

Origins
-------
Only origins this app is actually served from. No wildcard - `AllowedOrigins: ['*']`
on a bucket that also holds third-party source documents would let any page on the
internet read them with the visitor's credentials.

Deliberately NOT included, each for a measured reason:

* the two retired hosts that were in the old bucket's rule - the legacy frontend host
  and the `app.` media host (named without their scheme here on purpose: a docstring
  is a string literal, not a comment, so `check_retired_origins.py` cannot strip it
  and a scheme-qualified mention would make this file fail that gate). Both are
  NXDOMAIN, `RETIRED_HOSTS` refuses them, and an allow-list entry for a name nobody
  owns is a standing offer to whoever claims it next.
* `https://www.wecare.digital` - measured 2026-10-06: **302 to the apex**. A browser
  compares `Access-Control-Allow-Origin` against the literal request origin and never
  follows a redirect, so a redirecting host cannot be a usable allowed origin. The
  same reasoning that put the apex first in `lambda_utils/response.py`.
* `https://d22dm4b0jn71jw.amplifyapp.com` - measured 2026-10-06: **404** at the root,
  so the app is not served there and no browser presents that origin.

Usage
-----
    python scripts/provision_media_bucket_cors.py              # dry run (default)
    python scripts/provision_media_bucket_cors.py --apply      # writes the config
    python scripts/provision_media_bucket_cors.py --check      # assert, exit 1 if wrong

No secret is read, accepted or printed: bucket CORS carries no credential, and
authentication comes from the `wecare-prod` profile on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "docs" / "execution" / "snapshots"

PROFILE = "wecare-prod"
REGION = "us-east-1"

# Must equal `media_paths.BUCKET`. Asserted by `_assert_bucket_matches_media_paths`
# below rather than trusted, because the project specification carries a known typo
# ("wecare-difital-get") for this name and that bucket does not exist. If a future
# instruction spells it that way, it is the typo - do not create the bucket.
BUCKET = "wecare-digital-get"

# The origin that matters. Everything else in CORS_RULE is a WebView or dev origin.
REQUIRED_ORIGIN = "https://wecare.digital"

CORS_RULE = {
    "AllowedOrigins": [
        REQUIRED_ORIGIN,         # the dashboard, measured 200 at the root
        "capacitor://localhost",  # iOS WKWebView (Capacitor default iosScheme)
        "https://localhost",      # Android WebView (Capacitor default androidScheme)
        "http://localhost",       # carried over from the retired bucket's rule
        "http://localhost:3000",  # next dev server
    ],
    # PUT for the private presigned-PUT path, POST for the presigned-POST reuse path
    # (the one that can carry a content-length-range condition), GET/HEAD so a
    # just-uploaded object can be read back without going through CloudFront.
    "AllowedMethods": ["PUT", "POST", "GET", "HEAD"],
    # The presigned PUT is signed over a specific Content-Type and the POST form
    # sends several x-amz-* fields, so the header set is not fixed at author time.
    # This mirrors the retired bucket's rule.
    "AllowedHeaders": ["*"],
    # The upload code checks `res.ok`, but exposing ETag keeps a future integrity
    # check possible from the browser; it is already what the old rule exposed.
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000,
}


def _client():
    import boto3

    return boto3.Session(profile_name=PROFILE, region_name=REGION).client("s3")


def _assert_bucket_matches_media_paths() -> None:
    """Refuse to run if this constant has drifted from the key contract."""
    sys.path.insert(0, str(ROOT / "amplify" / "functions" / "shared"))
    from lambda_utils import media_paths  # noqa: PLC0415

    if media_paths.BUCKET != BUCKET:
        raise SystemExit(
            f"BUCKET mismatch: this script targets {BUCKET!r} but "
            f"media_paths.BUCKET is {media_paths.BUCKET!r}. Fix the drift; do not "
            f"create a second bucket."
        )


def read_cors(s3) -> list[dict] | None:
    """Current rules, or None when the bucket has no CORS configuration at all."""
    from botocore.exceptions import ClientError

    try:
        return s3.get_bucket_cors(Bucket=BUCKET).get("CORSRules", [])
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchCORSConfiguration":
            return None
        raise


def rules_allow_required_origin(rules: list[dict] | None) -> bool:
    if not rules:
        return False
    for rule in rules:
        origins = rule.get("AllowedOrigins") or []
        methods = {m.upper() for m in (rule.get("AllowedMethods") or [])}
        if REQUIRED_ORIGIN in origins and "PUT" in methods:
            return True
    return False


def _write_snapshot(stage: str, rules: list[dict] | None) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    path = SNAPSHOT_DIR / f"s3-{BUCKET}-cors-{stage}-{stamp}.json"
    payload = {
        "bucket": BUCKET,
        "region": REGION,
        "stage": stage,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        # None is not the same as [] here: no configuration at all is the defect,
        # an empty rule list would be a different (and never-observed) state.
        "corsPresent": rules is not None,
        "CORSRules": rules,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--apply", action="store_true",
        help="write the CORS configuration (default is a dry run that writes nothing)",
    )
    ap.add_argument(
        "--check", action="store_true",
        help=f"assert the bucket allows {REQUIRED_ORIGIN} for PUT; exit 1 if it does not",
    )
    args = ap.parse_args()

    _assert_bucket_matches_media_paths()
    s3 = _client()
    current = read_cors(s3)

    print(f"bucket         : s3://{BUCKET}  ({REGION}, profile {PROFILE})")
    print(f"current CORS   : "
          + ("NoSuchCORSConfiguration (none)" if current is None
             else json.dumps(current, indent=2)))

    if args.check:
        ok = rules_allow_required_origin(current)
        print(f"required origin: {REQUIRED_ORIGIN} for PUT -> "
              f"{'ALLOWED' if ok else 'NOT ALLOWED'}")
        if ok:
            print("\nMEDIA BUCKET CORS CHECK PASSED")
            return 0
        print("\nMEDIA BUCKET CORS CHECK FAILED - the browser preflight for a "
              "presigned upload will be refused with 403 'CORS is not enabled for "
              "this bucket', so every dashboard attachment and template-media upload "
              "fails before Meta is called. Fix with: "
              "python scripts/provision_media_bucket_cors.py --apply")
        return 1

    print(f"proposed CORS  : {json.dumps([CORS_RULE], indent=2)}")

    if not args.apply:
        print("\nDRY RUN - nothing was written. Re-run with --apply to put this "
              "configuration on the bucket.")
        return 0

    before = _write_snapshot("before", current)
    print(f"\nsnapshot before: {before.relative_to(ROOT)}")

    s3.put_bucket_cors(Bucket=BUCKET, CORSConfiguration={"CORSRules": [CORS_RULE]})

    # Read back rather than trusting the 200: the point of the snapshot pair is
    # evidence of the live state, not of the call.
    after = read_cors(s3)
    after_path = _write_snapshot("after", after)
    print(f"snapshot after : {after_path.relative_to(ROOT)}")

    if not rules_allow_required_origin(after):
        print("\nAPPLIED BUT NOT VERIFIED - the read-back does not allow "
              f"{REQUIRED_ORIGIN} for PUT. Investigate before relying on this.")
        return 2

    print(f"\nAPPLIED - s3://{BUCKET} now allows {REQUIRED_ORIGIN} for PUT.")
    print("Verify the preflight with:")
    print("  curl -s -o /dev/null -D - -X OPTIONS \\")
    print("    -H 'Origin: https://wecare.digital' \\")
    print("    -H 'Access-Control-Request-Method: PUT' \\")
    print("    -H 'Access-Control-Request-Headers: content-type' \\")
    print(f"    https://{BUCKET}.s3.{REGION}.amazonaws.com/o/stack/whatsapp-media/"
          "outgoing/preflight-probe.bin")
    print("Rollback: aws s3api delete-bucket-cors --bucket "
          f"{BUCKET}  (prior state was no configuration at all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
