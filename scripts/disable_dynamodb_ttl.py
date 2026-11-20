#!/usr/bin/env python3
"""One-off: turn DynamoDB TTL OFF on every table that previously had it.

The repo no longer declares or enables TTL (see commit "remove DynamoDB TTL from all
tables"), but live tables may still have it enabled, so DynamoDB would keep reaping
items. This script disables it.

Dry-run by default. Pass --apply to execute. Idempotent: DescribeTimeToLive first,
and UpdateTimeToLive(Enabled=False) is only called for tables whose status is
ENABLED (DISABLING/DISABLED are left alone). Never enables TTL.

Amplify-managed tables have physical names like ``Message-<apiId>-NONE``; they are
resolved from ListTables by model-name prefix. Fixed-name tables are used as-is.
"""
from __future__ import annotations

import argparse
import sys

# Amplify model name -> TTL attribute that was configured (informational; the
# attribute actually sent is the one DescribeTimeToLive reports).
AMPLIFY_MODELS = {
    "Message": "expiresAt",
    "DLQMessage": "expiresAt",
    "AuditLog": "expiresAt",
    "VoiceAws": "expiresAt",
    "VoiceCDR": "expiresAt",
    "WhatsAppVoice": "expiresAt",
    "WhatsAppInbound": "expiresAt",
    "WhatsAppOutbound": "expiresAt",
    "RazorpayWebhookLog": "expiresAt",
    "WebhookDedup": "ttl",
    "SystemEvent": "ttl",
    "CatalogCache": "ttl",
    "AdClickAttribution": "ttl",
    "WhatsAppCalling": "ttl",
    "RateLimitTracker": "lastUpdatedAt",
    "FlowDraft": "ttl",
    "FlowLog": "ttl",
}

PREFIX = "stack-wecare-digital"
FIXED_TABLES = [
    f"{PREFIX}-CustomerSessionsTable",
    f"{PREFIX}-CartTable",
    f"{PREFIX}-AgentApprovalsTable",
    f"{PREFIX}-ThreadOwnershipTable",
    f"{PREFIX}-PstnSoftphoneSessions",
    f"{PREFIX}-DownloadGrantsTable",  # secure-file grants
    f"{PREFIX}-SecureFilesTable",
    f"{PREFIX}-SiteLanguageCache",
    f"{PREFIX}-NotificationEvents",
    f"{PREFIX}-NotificationDeliveries",
    f"{PREFIX}-NotificationAttempts",
    f"{PREFIX}-NotificationOutbox",
    f"{PREFIX}-LinkClicksTable",
    "wecare-workspace-mcp",
]


def resolve_amplify_name(model: str, live: list[str]) -> str | None:
    """Return the physical table for an Amplify model, or None if absent/ambiguous."""
    matches = [t for t in live if t.startswith(model + "-") and t.endswith("-NONE")]
    return matches[0] if len(matches) == 1 else None


def list_all_tables(client) -> list[str]:
    names: list[str] = []
    token = None
    while True:
        kw = {"Limit": 100}
        if token:
            kw["ExclusiveStartTableName"] = token
        r = client.list_tables(**kw)
        names += r.get("TableNames", [])
        token = r.get("LastEvaluatedTableName")
        if not token:
            return names


def target_tables(client) -> tuple[list[str], list[str]]:
    live = list_all_tables(client)
    live_set = set(live)
    targets: list[str] = []
    missing: list[str] = []
    for model in AMPLIFY_MODELS:
        name = resolve_amplify_name(model, live)
        (targets if name else missing).append(name or model)
    for name in FIXED_TABLES:
        (targets if name in live_set else missing).append(name)
    return targets, missing


def disable_ttl(client, table: str, apply: bool) -> str:
    try:
        desc = client.describe_time_to_live(TableName=table)["TimeToLiveDescription"]
    except client.exceptions.ResourceNotFoundException:
        return "missing"
    status = desc.get("TimeToLiveStatus")
    attr = desc.get("AttributeName")
    if status != "ENABLED":
        return f"skip ({status})"
    if not apply:
        return f"would disable (attribute {attr})"
    client.update_time_to_live(
        TableName=table,
        TimeToLiveSpecification={"Enabled": False, "AttributeName": attr},
    )
    return f"disabled (attribute {attr})"


def run(client, apply: bool, out=print) -> dict[str, str]:
    targets, missing = target_tables(client)
    results: dict[str, str] = {}
    for table in targets:
        results[table] = disable_ttl(client, table, apply)
        out(f"{table}: {results[table]}")
    for name in missing:
        results[name] = "not found"
        out(f"{name}: not found")
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually disable TTL (default is a dry run)")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args(argv)
    import boto3

    client = boto3.client("dynamodb", region_name=args.region)
    print("APPLY" if args.apply else "DRY RUN (use --apply to execute)")
    run(client, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
