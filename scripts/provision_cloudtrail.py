#!/usr/bin/env python3
"""Provision the account's management-event audit trail (gap `OBS-TRAIL-001`).

Before this ran, the account had **0 CloudTrail trails and 0 event data stores**.
CloudTrail's 90-day console event history still answered questions -- it is what
dated the provider secret deletions in `docs/execution/phase-05-status.md` -- but
nothing was retained past 90 days and nothing was queryable with Athena. That is
the HIGH-severity half of the gap: not "no events", but "no durable record and no
query path".

ENCRYPTION, and why it is SSE-S3 rather than SSE-KMS. The gap register asks for an
SSE-KMS bucket. The account has exactly two customer-managed keys and neither is
usable here: `alias/wecaredigital` is an `ECC_NIST_P256` / `SIGN_VERIFY` key owned
by Route 53 DNSSEC and cannot encrypt at all, and `alias/wecare-secrets-manager`
is the key behind Secrets Manager and the credential-backup buckets -- putting
audit logs on the secrets key destroys a separation that exists on purpose. A third
key would be a `KMS create`, which `.kiro/steering/maintenance-reporting.md` (retired 2026-10-09, af7858fa) puts
behind pointwise confirmation. So the bucket uses SSE-S3 (`AES256`), and
**log-file validation is enabled**, which is the control that actually detects
tampering -- encryption at rest does not. Moving to a dedicated CMK later is a
one-field change on both the bucket and the trail.

The bucket policy carries `aws:SourceArn` and `aws:SourceAccount` conditions, so a
CloudTrail trail in another account cannot write here (the confused-deputy pattern
`.kiro/steering/aws-agent-rules.md` (retired; now .kiro/steering/00-common.md) requires).

    python scripts/provision_cloudtrail.py --plan
    python scripts/provision_cloudtrail.py --apply
    python scripts/provision_cloudtrail.py --verify
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import boto3
from botocore.exceptions import ClientError

ACCOUNT = "775261844268"
REGION = "us-east-1"
BUCKET = f"wecare-cloudtrail-{ACCOUNT}"
TRAIL = "wecare-management-events"
TRAIL_ARN = f"arn:aws:cloudtrail:{REGION}:{ACCOUNT}:trail/{TRAIL}"

#: No `S3KeyPrefix`. CloudTrail always writes under `AWSLogs/<account>/`, so setting
#: a prefix of "AWSLogs" produces `AWSLogs/AWSLogs/<account>/` and the bucket policy
#: resource no longer matches what the service writes -- which is exactly the
#: `InsufficientS3BucketPolicyException` this script hit on its first run.
OBJECT_PATH = f"AWSLogs/{ACCOUNT}/*"

#: Glacier Instant Retrieval after 90 days is the point where the console's own
#: 90-day history stops being an alternative, and 400 days covers a full year of
#: audit plus a month of overlap for annual reviews.
LIFECYCLE = {
    "Rules": [
        {
            "ID": "archive-then-expire",
            "Status": "Enabled",
            "Filter": {"Prefix": ""},
            "Transitions": [{"Days": 90, "StorageClass": "GLACIER_IR"}],
            "Expiration": {"Days": 400},
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
        }
    ]
}


#: Management events, both read and write, from every source (no readOnly or eventSource
#: filter), which is what the original basic selector logged.
MANAGEMENT_SELECTOR = {
    "Name": "Management events",
    "FieldSelectors": [{"Field": "eventCategory", "Equals": ["Management"]}],
}

#: Data events stay OFF: S3/Lambda data events on ~76 tables and ~70 functions would
#: dominate the bill and the signal. To log one function's callers temporarily, add a
#: selector with eventCategory=Data, resources.type=AWS::Lambda::Function and
#: resources.ARN StartsWith the function ARN. StartsWith also matches `:live` and version
#: ARNs, which a basic selector's exact ARN does not. That is how the caller of
#: `wecare-catalog-management` was identified on 2026-10-25: root, from an operator
#: machine, smoke-testing `:live` right after a fleet deploy. It has no production caller.
ADVANCED_SELECTORS = [MANAGEMENT_SELECTOR]


def logs_all_management_events(response: dict) -> bool:
    """True when the trail logs read AND write management events from every source."""
    basic = response.get("EventSelectors") or []
    if basic:
        return any(s.get("IncludeManagementEvents") is True and s.get("ReadWriteType") == "All"
                   and not s.get("ExcludeManagementEventSources") for s in basic)
    return any(
        {f["Field"] for f in s.get("FieldSelectors", [])} == {"eventCategory"}
        and next(f for f in s["FieldSelectors"] if f["Field"] == "eventCategory").get("Equals")
        == ["Management"]
        for s in response.get("AdvancedEventSelectors") or [])


def bucket_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AWSCloudTrailAclCheck",
                "Effect": "Allow",
                "Principal": {"Service": "cloudtrail.amazonaws.com"},
                "Action": "s3:GetBucketAcl",
                "Resource": f"arn:aws:s3:::{BUCKET}",
                "Condition": {"StringEquals": {"aws:SourceArn": TRAIL_ARN}},
            },
            {
                "Sid": "AWSCloudTrailWrite",
                "Effect": "Allow",
                "Principal": {"Service": "cloudtrail.amazonaws.com"},
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{BUCKET}/{OBJECT_PATH}",
                "Condition": {
                    "StringEquals": {
                        "s3:x-amz-acl": "bucket-owner-full-control",
                        "aws:SourceArn": TRAIL_ARN,
                        "aws:SourceAccount": ACCOUNT,
                    }
                },
            },
            {
                "Sid": "DenyInsecureTransport",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [
                    f"arn:aws:s3:::{BUCKET}",
                    f"arn:aws:s3:::{BUCKET}/*",
                ],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            },
        ],
    }


def _s3():
    return boto3.client("s3", region_name=REGION)


def _ct():
    return boto3.client("cloudtrail", region_name=REGION)


def _bucket_exists(s3) -> bool:
    try:
        s3.head_bucket(Bucket=BUCKET)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchBucket", "NotFound"):
            return False
        raise


def _trail_exists(ct) -> bool:
    try:
        ct.get_trail(Name=TRAIL)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TrailNotFoundException":
            return False
        raise


def plan() -> int:
    s3, ct = _s3(), _ct()
    print(f"bucket {BUCKET}: {'EXISTS' if _bucket_exists(s3) else 'ABSENT'}")
    print(f"trail  {TRAIL}: {'EXISTS' if _trail_exists(ct) else 'ABSENT'}")
    existing = ct.describe_trails().get("trailList", [])
    print(f"trails in account: {len(existing)} -> {[t['Name'] for t in existing]}")
    stores = ct.list_event_data_stores().get("EventDataStores", [])
    print(f"event data stores: {len(stores)}")
    return 0


def apply() -> int:
    s3, ct = _s3(), _ct()

    if not _bucket_exists(s3):
        # us-east-1 must NOT be passed as a LocationConstraint.
        s3.create_bucket(Bucket=BUCKET)
        print(f"created bucket {BUCKET}")
    else:
        print(f"bucket {BUCKET} already present")

    s3.put_public_access_block(
        Bucket=BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": False,   # the CloudTrail service policy is not "public"
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=BUCKET,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                    "BucketKeyEnabled": True,
                }
            ]
        },
    )
    s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_lifecycle_configuration(Bucket=BUCKET, LifecycleConfiguration=LIFECYCLE)
    s3.put_bucket_policy(Bucket=BUCKET, Policy=json.dumps(bucket_policy()))
    print("bucket hardened: public access blocked, AES256 + bucket keys, versioned, "
          "lifecycle set, TLS-only policy")

    if not _trail_exists(ct):
        ct.create_trail(
            Name=TRAIL,
            S3BucketName=BUCKET,
            IncludeGlobalServiceEvents=True,
            IsMultiRegionTrail=True,
            EnableLogFileValidation=True,
        )
        print(f"created trail {TRAIL} (multi-region, global events, validation on)")
    else:
        ct.update_trail(
            Name=TRAIL,
            S3BucketName=BUCKET,
            IncludeGlobalServiceEvents=True,
            IsMultiRegionTrail=True,
            EnableLogFileValidation=True,
        )
        print(f"updated trail {TRAIL}")

    ct.put_event_selectors(TrailName=TRAIL, AdvancedEventSelectors=ADVANCED_SELECTORS)
    ct.start_logging(Name=TRAIL)
    print("logging started")
    time.sleep(5)
    return verify()


def verify() -> int:
    ct, s3 = _ct(), _s3()
    failures = []

    try:
        trail = ct.get_trail(Name=TRAIL)["Trail"]
    except ClientError as exc:
        print(f"trail missing: {exc.response['Error']['Code']}", file=sys.stderr)
        return 1

    checks = {
        "IsMultiRegionTrail": trail.get("IsMultiRegionTrail") is True,
        "IncludeGlobalServiceEvents": trail.get("IncludeGlobalServiceEvents") is True,
        "LogFileValidationEnabled": trail.get("LogFileValidationEnabled") is True,
        "S3BucketName": trail.get("S3BucketName") == BUCKET,
    }
    status = ct.get_trail_status(Name=TRAIL)
    checks["IsLogging"] = status.get("IsLogging") is True

    selectors = ct.get_event_selectors(TrailName=TRAIL)
    checks["IncludeManagementEvents"] = logs_all_management_events(selectors)
    for selector in selectors.get("AdvancedEventSelectors") or []:
        if selector.get("Name") != MANAGEMENT_SELECTOR["Name"]:
            print(f"  ..    data-event selector: {selector.get('Name')}")

    enc = s3.get_bucket_encryption(Bucket=BUCKET)
    rule = enc["ServerSideEncryptionConfiguration"]["Rules"][0]
    checks["BucketEncrypted"] = bool(rule["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"])

    pab = s3.get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    checks["BlockPublicAcls"] = pab["BlockPublicAcls"] is True
    checks["RestrictPublicBuckets"] = pab["RestrictPublicBuckets"] is True

    for name, ok in checks.items():
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}")
        if not ok:
            failures.append(name)

    delivery = status.get("LatestDeliveryTime")
    delivery_error = status.get("LatestDeliveryError")
    print(f"  ..    LatestDeliveryTime: {delivery}")
    if delivery_error:
        print(f"  FAIL  LatestDeliveryError: {delivery_error}")
        failures.append("LatestDeliveryError")

    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}", file=sys.stderr)
        return 1
    print("\nall checks passed"
          + ("" if delivery else " (no log file delivered yet -- first delivery "
                                "can take up to 15 minutes)"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.apply:
        return apply()
    if args.verify:
        return verify()
    return plan()


if __name__ == "__main__":
    raise SystemExit(main())
