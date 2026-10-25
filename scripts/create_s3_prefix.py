#!/usr/bin/env python3
"""Create a folder (prefix marker) in the EXISTING bucket. Never creates a bucket.

Read this before using it, because S3 folders are not what they look like
----------------------------------------------------------------------------
S3 has no directories. `secure/d/public/receipts/x.png` is one flat key; the "folders" the console
shows are inferred from the `/` characters in keys that exist. So writing an object to a new
prefix needs no folder, and a prefix with no objects does not appear at all.

Measured in `wecare-digital-get` on 2026-09-30: **zero** 0-byte folder markers exist. Every
prefix in the bucket - `o/stack/`, `secure/d/`, `secure/u/` and the rest - exists only because
a real object was written into it.

So a marker is only worth creating when the prefix must be visible or reserved *before* its
first object arrives. Two reasons that can be true here:

1. **It survives a cleanup wipe.** `operations/system-cleanup._wipe_s3_prefix` deletes content
   and explicitly skips keys ending in `/`, so a marked folder still exists after a purge while
   an unmarked one silently vanishes from the console.
2. **It documents intent.** `secure/d/public/Invoice/customer_invoice/` is where `invoice-engine` and
   `inbound-whatsapp-handler` now write, and it held no objects, so nothing in the console
   showed that the invoice location had moved there.

The bucket is fixed and the guard is deliberate
----------------------------------------------
`.kiro/steering/blog-production-s3.md` requires the existing bucket `wecare-digital-get` and
forbids creating another without explicit approval; `.kiro/hooks/block-s3-bucket-creation.json`
refuses the command shapes that would. This script has no create-bucket path at all - it
verifies the bucket exists and refuses if it does not, rather than helpfully making one.

Keys are composed through `lambda_utils.media_paths`, which owns the `o/` (public, served by
CloudFront with no authentication) versus `secure/` (gated) distinction. A prefix passed here
must already be rooted; an unrooted one is refused rather than silently placed under `o/`,
because guessing the root is how something private ends up public.

Usage:
    python scripts/create_s3_prefix.py --list
    python scripts/create_s3_prefix.py secure/d/public/Invoice/customer_invoice/ --dry-run
    python scripts/create_s3_prefix.py secure/d/public/Invoice/customer_invoice/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "amplify" / "functions" / "shared"))
from lambda_utils import media_paths  # noqa: E402

REGION = "us-east-1"
BUCKET = media_paths.BUCKET

#: Prefixes this repository's code writes to and which are worth marking. Each names the writer,
#: so a reader can tell a deliberate reservation from a stray folder.
KNOWN_PREFIXES = {
    media_paths.INVOICE_CUSTOMER_IMAGE_PREFIX: (
        "invoice-engine (PNG) and inbound-whatsapp-handler. Under secure/d/public/ but listed "
        "in media_paths.PRIVATE_DELIVERABLE_PREFIXES, so the edge redirects it: a rendered "
        "invoice (name, address, amount, GST breakdown) is served only by presigned URL."
    ),
}


def s3():
    return boto3.client("s3", region_name=REGION)


def bucket_exists() -> bool:
    """False whenever the bucket cannot be CONFIRMED - including with no credentials at all.

    BotoCoreError, not just ClientError. `NoCredentialsError` is a BotoCoreError and is NOT a
    subclass of ClientError, so `except ClientError` did not catch it: with no credentials the
    call raised straight out of here, printed a traceback, and exited 1.

    That exit code is the whole problem. tests/test_create_s3_prefix.py deliberately accepts
    0 or 2 - its own comment reads "Exit 2 is the no-credentials path, which is fine in CI" -
    and treats anything else as a crash. So a credential-less runner made this script look
    broken rather than unauthenticated. Measured on 2026-09-30: the `Handler auth enforcement
    (source)` job went red on `stack` itself with
    `botocore.exceptions.NoCredentialsError: Unable to locate credentials`, from `--list`,
    which mutates nothing.

    Returning False routes it through main()'s existing `return 2`, which is the documented
    "cannot confirm" answer.
    """
    try:
        s3().head_bucket(Bucket=BUCKET)
        return True
    except (ClientError, BotoCoreError):
        return False


def validate(prefix: str) -> str:
    """Return the normalised prefix, or raise ValueError explaining why it is refused."""
    if not prefix or prefix.strip() == "":
        raise ValueError("a prefix is required")
    prefix = prefix.strip().lstrip("/")
    if not prefix.endswith("/"):
        # A marker must end in `/` or `_wipe_s3_prefix` will delete it as content on the first
        # cleanup run, which is the opposite of the reason for creating it.
        prefix += "/"
    if prefix in ("o/", "secure/"):
        raise ValueError(f"{prefix!r} is a root, not a folder; it already exists")
    if not (prefix.startswith("o/") or prefix.startswith("secure/")):
        raise ValueError(
            f"{prefix!r} is not rooted. Use `o/...` for the PUBLIC tree (CloudFront serves it "
            f"with no authentication) or `secure/...` for the gated tree - except "
            f"`secure/d/public/`, which CloudFront also serves publicly. Composing through "
            f"lambda_utils.media_paths.public()/.secure() is how the code does it. Refusing "
            f"rather than assuming a root, because guessing wrong makes private data public.\n"
            f"       Also note: a key at the bucket ROOT still returned HTTP 200 on the apex "
            f"host, so addressing one level above the data errors nowhere and alarms nothing."
        )
    if "//" in prefix:
        raise ValueError(f"{prefix!r} contains an empty path segment")
    return prefix


def describe(prefix: str) -> dict:
    client = s3()
    listing = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=1000)
    contents = listing.get("Contents", []) or []
    marker_present = any(item["Key"] == prefix for item in contents)
    real_objects = [item for item in contents
                    if not item["Key"].endswith("/")]
    return {
        "prefix": prefix,
        "markerPresent": marker_present,
        "objectCount": len(real_objects),
        "gated": media_paths.is_gated(prefix),
    }


def create(prefix: str, dry_run: bool) -> str:
    state = describe(prefix)
    if state["markerPresent"]:
        return "exists"
    if dry_run:
        return f"would create a 0-byte marker at {prefix}"
    # A 0-byte object whose key ends in `/` is the only thing S3 recognises as a folder, and it
    # is what the console renders and what `_wipe_s3_prefix` preserves.
    s3().put_object(Bucket=BUCKET, Key=prefix, Body=b"")
    return "created"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prefix", nargs="?", help="rooted prefix, e.g. secure/d/public/Invoice/customer_invoice/")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true",
                        help="show the known prefixes and whether each is marked")
    args = parser.parse_args(argv)

    if not bucket_exists():
        # Both causes are named because they need opposite responses, and the old message
        # asserted only one of them. On a runner with no AWS credentials this path is reached
        # with the bucket perfectly healthy, and "not reachable" sent the reader looking for a
        # deleted bucket.
        print(f"ERROR: bucket {BUCKET} could not be confirmed. Either there are no usable AWS "
              f"credentials in this environment (the usual cause in CI, and nothing is wrong), "
              f"or the bucket really is unreachable. This script does NOT create buckets - "
              f"the existing bucket is mandated by .kiro/steering/blog-production-s3.md.",
              file=sys.stderr)
        return 2

    print(f"bucket: {BUCKET}  (existing; never created here)")

    if args.list or not args.prefix:
        print("\nknown prefixes this repository writes to:")
        for prefix, why in KNOWN_PREFIXES.items():
            state = describe(prefix)
            root = "GATED " if state["gated"] else "PUBLIC"
            print(f"\n  {prefix}")
            print(f"    root         : {root}")
            print(f"    marker       : {'present' if state['markerPresent'] else 'ABSENT'}")
            print(f"    objects      : {state['objectCount']}")
            print(f"    written by   : {why}")
        if not args.prefix:
            print("\nPass a prefix to create one. Nothing was changed.")
        return 0

    try:
        prefix = validate(args.prefix)
    except ValueError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 2

    root = "GATED (no unauthenticated access)" if media_paths.is_gated(prefix) \
        else "PUBLIC (CloudFront serves this without authentication)"
    print(f"prefix: {prefix}\nroot  : {root}\ndry run: {args.dry_run}\n")

    print(f"result: {create(prefix, args.dry_run)}")
    if args.dry_run:
        print("\ndry run: nothing changed")
        return 0

    state = describe(prefix)
    print("\nread-back verification:")
    print(f"  marker present : {state['markerPresent']}")
    print(f"  objects under  : {state['objectCount']}")
    print(f"  gated          : {state['gated']}")
    if not state["markerPresent"]:
        print("\nFAIL: the marker is not readable back", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
