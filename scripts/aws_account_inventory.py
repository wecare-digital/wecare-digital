#!/usr/bin/env python3
"""Account-wide AWS resource inventory across every service family this project uses.

Why this exists
---------------
Historical reports carry dated counts (58 Lambdas, 332 routes, 2 HTTP APIs, 0
authorizers) that are snapshots, not standing truth. The canonical
`.kiro/steering/00-common.md` requires live verification. `generate_
runtime_inventory.py` already joins Lambda -> route -> table -> traffic -> source,
but it does not look at SQS, EventBridge, Secrets Manager, Cognito, SES, S3,
CloudFront, WAF, Route 53, CloudWatch or the IaC stacks. This closes that gap so
"is there already a queue/table/bucket for this?" is answerable before anything
new is provisioned.

Design notes
------------
* **Errors are counted and reported, never swallowed.** A prior alias count read
  34/28 instead of 53/9 because failed calls were treated as "absent". Every
  collector here records its exceptions and the summary prints the total; a
  non-zero error count makes the run PARTIAL rather than silently wrong.
* **No secret values.** Secrets Manager is enumerated with ListSecrets /
  DescribeSecret only. `get_secret_value` and `batch_get_secret_value` are never
  called, per the project secret-safety rule. Environment variable NAMES are
  recorded, values never are.
* Region is `us-east-1` for regional services; SES is additionally checked in
  `ap-south-1` (AWS End User Messaging SMS lives there), and S3/CloudFront/
  Route 53/WAF-CLOUDFRONT are global or us-east-1 scoped.

    python scripts/aws_account_inventory.py
    python scripts/aws_account_inventory.py --json-only
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import sys
import traceback
from datetime import datetime, timezone

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    print("boto3 required", file=sys.stderr)
    raise SystemExit(2)

REGION = "us-east-1"
ALT_REGIONS = ["ap-south-1"]
REPO = pathlib.Path(__file__).resolve().parents[1]
OUT_JSON = REPO / "docs/execution/aws-inventory.json"
OUT_MD = REPO / "docs/execution/aws-inventory.md"

BOTO_CFG = Config(retries={"max_attempts": 10, "mode": "adaptive"})
ERRORS: list[dict] = []


def client(service: str, region: str = REGION):
    return boto3.client(service, region_name=region, config=BOTO_CFG)


def guard(label: str, fn, default=None):
    """Run a collector, recording any failure instead of hiding it."""
    try:
        return fn()
    except (ClientError, BotoCoreError) as exc:
        ERRORS.append({"label": label, "error": f"{type(exc).__name__}: {exc}"})
        return default
    except Exception as exc:  # noqa: BLE001 - collector must not kill the run
        ERRORS.append(
            {
                "label": label,
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=3),
            }
        )
        return default


def paged(clientobj, op: str, key: str, **kw) -> list:
    """Collect every page of a paginated operation."""
    out: list = []
    if clientobj.can_paginate(op):
        for page in clientobj.get_paginator(op).paginate(**kw):
            out.extend(page.get(key, []) or [])
        return out
    resp = getattr(clientobj, op)(**kw)
    out.extend(resp.get(key, []) or [])
    return out


# --------------------------------------------------------------------------- #
# collectors
# --------------------------------------------------------------------------- #

def collect_lambda() -> dict:
    lam = client("lambda")
    fns = paged(lam, "list_functions", "Functions")
    rows = []
    alias_errors = 0
    for fn in fns:
        name = fn["FunctionName"]
        try:
            aliases = paged(lam, "list_aliases", "Aliases", FunctionName=name)
            alias_names = sorted(a["Name"] for a in aliases)
            live = next((a for a in aliases if a["Name"] == "live"), None)
        except (ClientError, BotoCoreError) as exc:
            alias_errors += 1
            ERRORS.append({"label": f"lambda.aliases.{name}", "error": str(exc)})
            alias_names, live = None, None
        rows.append(
            {
                "name": name,
                "runtime": fn.get("Runtime"),
                "package_type": fn.get("PackageType"),
                "architectures": fn.get("Architectures"),
                "memory": fn.get("MemorySize"),
                "timeout": fn.get("Timeout"),
                "last_modified": fn.get("LastModified"),
                "code_sha256": fn.get("CodeSha256"),
                "code_size": fn.get("CodeSize"),
                "layers": [l["Arn"].split(":layer:")[-1] for l in fn.get("Layers", [])],
                "env_var_names": sorted(
                    (fn.get("Environment", {}) or {}).get("Variables", {}).keys()
                ),
                "snapstart": (fn.get("SnapStart", {}) or {}).get("ApplyOn"),
                "aliases": alias_names,
                "live_alias_version": live.get("FunctionVersion") if live else None,
            }
        )
    rows.sort(key=lambda r: r["name"])
    with_live = [r for r in rows if r["live_alias_version"]]
    return {
        "count": len(rows),
        "with_live_alias": len(with_live),
        "without_live_alias": sorted(
            r["name"] for r in rows if not r["live_alias_version"]
        ),
        "alias_read_errors": alias_errors,
        "runtimes": _tally(r["runtime"] for r in rows),
        "package_types": _tally(r["package_type"] for r in rows),
        "snapstart": _tally(r["snapstart"] or "None" for r in rows),
        "functions": rows,
    }


def collect_apigw() -> dict:
    v2 = client("apigatewayv2")
    apis = paged(v2, "get_apis", "Items")
    out_apis = []
    total_routes = 0
    auth_none = 0
    authorizers_total = 0
    for api in apis:
        aid = api["ApiId"]
        routes = paged(v2, "get_routes", "Items", ApiId=aid)
        integrations = {
            i["IntegrationId"]: i
            for i in paged(v2, "get_integrations", "Items", ApiId=aid)
        }
        authorizers = paged(v2, "get_authorizers", "Items", ApiId=aid)
        stages = paged(v2, "get_stages", "Items", ApiId=aid)
        authorizers_total += len(authorizers)
        route_rows = []
        for r in routes:
            target = (r.get("Target") or "").split("/")[-1]
            integ = integrations.get(target, {})
            uri = integ.get("IntegrationUri", "") or ""
            fn = ""
            qualifier = None
            if ":function:" in uri:
                tail = uri.split(":function:")[-1]
                parts = tail.split(":")
                fn = parts[0]
                qualifier = parts[1] if len(parts) > 1 else None
            atype = r.get("AuthorizationType", "NONE")
            if atype == "NONE":
                auth_none += 1
            route_rows.append(
                {
                    "route_key": r.get("RouteKey"),
                    "authorization_type": atype,
                    "authorizer_id": r.get("AuthorizerId"),
                    "target_function": fn,
                    "qualifier": qualifier,
                    "payload_version": integ.get("PayloadFormatVersion"),
                }
            )
        route_rows.sort(key=lambda r: r["route_key"] or "")
        total_routes += len(route_rows)
        out_apis.append(
            {
                "api_id": aid,
                "name": api.get("Name"),
                "protocol": api.get("ProtocolType"),
                "endpoint": api.get("ApiEndpoint"),
                "created": _iso(api.get("CreatedDate")),
                "route_count": len(route_rows),
                "authorizer_count": len(authorizers),
                "authorizers": [
                    {
                        "id": a["AuthorizerId"],
                        "name": a.get("Name"),
                        "type": a.get("AuthorizerType"),
                        "identity_source": a.get("IdentitySource"),
                    }
                    for a in authorizers
                ],
                "stages": [
                    {
                        "name": s.get("StageName"),
                        "auto_deploy": s.get("AutoDeploy"),
                        "access_log": bool(
                            (s.get("AccessLogSettings") or {}).get("DestinationArn")
                        ),
                    }
                    for s in stages
                ],
                "routes": route_rows,
            }
        )

    rest = client("apigateway")
    rest_apis = guard(
        "apigateway.rest",
        lambda: [
            {"id": a["id"], "name": a.get("name"), "created": _iso(a.get("createdDate"))}
            for a in paged(rest, "get_rest_apis", "items")
        ],
        default=[],
    )
    return {
        "http_api_count": len(out_apis),
        "rest_api_count": len(rest_apis),
        "total_routes": total_routes,
        "total_authorizers": authorizers_total,
        "routes_authorization_none": auth_none,
        "http_apis": out_apis,
        "rest_apis": rest_apis,
    }


def collect_dynamodb() -> dict:
    ddb = client("dynamodb")
    names = paged(ddb, "list_tables", "TableNames")
    rows = []
    for name in names:
        desc = guard(f"ddb.describe.{name}", lambda n=name: ddb.describe_table(TableName=n)["Table"])
        if not desc:
            continue
        ttl = guard(
            f"ddb.ttl.{name}",
            lambda n=name: ddb.describe_time_to_live(TableName=n)
            .get("TimeToLiveDescription", {})
            .get("TimeToLiveStatus"),
        )
        cont = guard(
            f"ddb.pitr.{name}",
            lambda n=name: ddb.describe_continuous_backups(TableName=n)
            .get("ContinuousBackupsDescription", {})
            .get("PointInTimeRecoveryDescription", {})
            .get("PointInTimeRecoveryStatus"),
        )
        rows.append(
            {
                "name": name,
                "status": desc.get("TableStatus"),
                "item_count": desc.get("ItemCount"),
                "size_bytes": desc.get("TableSizeBytes"),
                "billing_mode": (desc.get("BillingModeSummary") or {}).get("BillingMode")
                or "PROVISIONED",
                "keys": [
                    f"{k['AttributeName']}({k['KeyType']})" for k in desc.get("KeySchema", [])
                ],
                "gsi_count": len(desc.get("GlobalSecondaryIndexes") or []),
                "stream": (desc.get("StreamSpecification") or {}).get("StreamViewType"),
                "ttl": ttl,
                "pitr": cont,
                "deletion_protection": desc.get("DeletionProtectionEnabled"),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return {
        "count": len(rows),
        "empty_tables": sorted(r["name"] for r in rows if not r["item_count"]),
        "no_pitr": sorted(r["name"] for r in rows if r["pitr"] != "ENABLED"),
        "with_streams": sorted(r["name"] for r in rows if r["stream"]),
        "tables": rows,
    }


def collect_sqs() -> dict:
    sqs = client("sqs")
    urls = paged(sqs, "list_queues", "QueueUrls") or []
    rows = []
    for url in urls:
        attrs = guard(
            f"sqs.attrs.{url.rsplit('/', 1)[-1]}",
            lambda u=url: sqs.get_queue_attributes(QueueUrl=u, AttributeNames=["All"])[
                "Attributes"
            ],
            default={},
        )
        redrive = attrs.get("RedrivePolicy")
        dlq_target = None
        if redrive:
            try:
                dlq_target = json.loads(redrive).get("deadLetterTargetArn", "").rsplit(":", 1)[-1]
            except (ValueError, AttributeError):
                dlq_target = "unparseable"
        rows.append(
            {
                "name": url.rsplit("/", 1)[-1],
                "url": url,
                "visible_messages": int(attrs.get("ApproximateNumberOfMessages", 0) or 0),
                "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0) or 0),
                "fifo": attrs.get("FifoQueue") == "true",
                "kms": bool(attrs.get("KmsMasterKeyId") or attrs.get("SqsManagedSseEnabled") == "true"),
                "dlq_target": dlq_target,
                "is_dlq_name": url.rsplit("/", 1)[-1].lower().endswith(("dlq", "dead-letter")),
                "max_receive_count": (
                    json.loads(redrive).get("maxReceiveCount") if redrive else None
                ),
            }
        )
    rows.sort(key=lambda r: r["name"])
    return {
        "count": len(rows),
        "dlq_like": sorted(r["name"] for r in rows if r["is_dlq_name"]),
        "without_redrive": sorted(
            r["name"] for r in rows if not r["dlq_target"] and not r["is_dlq_name"]
        ),
        "non_empty": {r["name"]: r["visible_messages"] for r in rows if r["visible_messages"]},
        "queues": rows,
    }


def collect_eventbridge() -> dict:
    eb = client("events")
    buses = paged(eb, "list_event_buses", "EventBuses")
    bus_rows = []
    total_rules = 0
    disabled = []
    for bus in buses:
        bname = bus["Name"]
        rules = guard(
            f"events.rules.{bname}",
            lambda b=bname: paged(eb, "list_rules", "Rules", EventBusName=b),
            default=[],
        )
        rule_rows = []
        for r in rules:
            targets = guard(
                f"events.targets.{r['Name']}",
                lambda rn=r["Name"], b=bname: paged(
                    eb, "list_targets_by_rule", "Targets", Rule=rn, EventBusName=b
                ),
                default=[],
            )
            if r.get("State") != "ENABLED":
                disabled.append(f"{bname}/{r['Name']}")
            rule_rows.append(
                {
                    "name": r["Name"],
                    "state": r.get("State"),
                    "schedule": r.get("ScheduleExpression"),
                    "has_pattern": bool(r.get("EventPattern")),
                    "targets": [
                        {
                            "id": t.get("Id"),
                            "arn_tail": t.get("Arn", "").rsplit(":", 2)[-1],
                            "has_dlq": bool(t.get("DeadLetterConfig")),
                            "retry": t.get("RetryPolicy"),
                        }
                        for t in targets
                    ],
                }
            )
        total_rules += len(rule_rows)
        bus_rows.append({"name": bname, "rule_count": len(rule_rows), "rules": rule_rows})

    sched = guard(
        "scheduler.schedules",
        lambda: paged(client("scheduler"), "list_schedules", "Schedules"),
        default=[],
    )
    pipes = guard("pipes.list", lambda: paged(client("pipes"), "list_pipes", "Pipes"), default=[])
    return {
        "bus_count": len(bus_rows),
        "rule_count": total_rules,
        "disabled_rules": sorted(disabled),
        "scheduler_count": len(sched or []),
        "schedules": [
            {"name": s.get("Name"), "state": s.get("State"), "group": s.get("GroupName")}
            for s in (sched or [])
        ],
        "pipe_count": len(pipes or []),
        "buses": bus_rows,
    }


def collect_secrets() -> dict:
    """Metadata only. get_secret_value / batch_get_secret_value are never called."""
    sm = client("secretsmanager")
    secrets = paged(sm, "list_secrets", "SecretList")
    # ListSecrets omits secrets already scheduled for deletion unless asked, and
    # those are exactly the ones the retirement work needs to see.
    pending = guard(
        "secrets.pending_deletion",
        lambda: paged(sm, "list_secrets", "SecretList", IncludePlannedDeletion=True),
        default=[],
    )
    by_arn = {s["ARN"]: s for s in secrets}
    for s in pending or []:
        by_arn.setdefault(s["ARN"], s)
    rows = []
    for s in by_arn.values():
        rows.append(
            {
                "name": s.get("Name"),
                "arn": s.get("ARN"),
                "last_changed": _iso(s.get("LastChangedDate")),
                "last_accessed": _iso(s.get("LastAccessedDate")),
                "rotation_enabled": s.get("RotationEnabled", False),
                "deleted_date": _iso(s.get("DeletedDate")),
                "kms_key": bool(s.get("KmsKeyId")),
                "tags": {t["Key"]: t["Value"] for t in s.get("Tags", [])},
            }
        )
    rows.sort(key=lambda r: r["name"] or "")
    return {
        "count": len(rows),
        "scheduled_for_deletion": sorted(r["name"] for r in rows if r["deleted_date"]),
        "rotation_enabled": sorted(r["name"] for r in rows if r["rotation_enabled"]),
        "never_accessed": sorted(r["name"] for r in rows if not r["last_accessed"]),
        "secrets": rows,
    }


def collect_cognito() -> dict:
    idp = client("cognito-idp")
    pools = paged(idp, "list_user_pools", "UserPools", MaxResults=60)
    rows = []
    for p in pools:
        pid = p["Id"]
        desc = guard(
            f"cognito.describe.{pid}",
            lambda i=pid: idp.describe_user_pool(UserPoolId=i)["UserPool"],
            default={},
        )
        mfa = guard(
            f"cognito.mfa.{pid}",
            lambda i=pid: idp.get_user_pool_mfa_config(UserPoolId=i),
            default={},
        )
        clients = guard(
            f"cognito.clients.{pid}",
            lambda i=pid: paged(idp, "list_user_pool_clients", "UserPoolClients", UserPoolId=i, MaxResults=60),
            default=[],
        )
        groups = guard(
            f"cognito.groups.{pid}",
            lambda i=pid: paged(idp, "list_groups", "Groups", UserPoolId=i),
            default=[],
        )
        rows.append(
            {
                "id": pid,
                "name": p.get("Name"),
                "status": desc.get("Status"),
                "estimated_users": desc.get("EstimatedNumberOfUsers"),
                "mfa_configuration": mfa.get("MfaConfiguration") or desc.get("MfaConfiguration"),
                "software_token_mfa": (mfa.get("SoftwareTokenMfaConfiguration") or {}).get("Enabled"),
                "sms_mfa": bool(mfa.get("SmsMfaConfiguration")),
                "advanced_security": (desc.get("UserPoolAddOns") or {}).get("AdvancedSecurityMode"),
                "deletion_protection": desc.get("DeletionProtection"),
                "password_policy": (desc.get("Policies", {}) or {}).get("PasswordPolicy"),
                "domain": desc.get("Domain") or desc.get("CustomDomain"),
                "lambda_triggers": sorted((desc.get("LambdaConfig") or {}).keys()),
                "group_names": sorted(g["GroupName"] for g in groups or []),
                "clients": [
                    {"id": c["ClientId"], "name": c.get("ClientName")} for c in clients or []
                ],
            }
        )
    idpools = guard(
        "cognito.identity_pools",
        lambda: paged(
            client("cognito-identity"), "list_identity_pools", "IdentityPools", MaxResults=60
        ),
        default=[],
    )
    return {
        "user_pool_count": len(rows),
        "identity_pool_count": len(idpools or []),
        "identity_pools": [
            {"id": p["IdentityPoolId"], "name": p.get("IdentityPoolName")}
            for p in (idpools or [])
        ],
        "user_pools": rows,
    }


def collect_ses() -> dict:
    out = {}
    for region in [REGION] + ALT_REGIONS:
        sesv2 = client("sesv2", region)
        # sesv2.list_email_identities has no paginator in this botocore, so
        # get_paginator raises OperationNotPageableError and the whole SES section
        # comes back empty -- which reads as "no verified senders" when in fact
        # one@wecare.digital is verified. Walk NextToken by hand.
        def _ses_identities(c=sesv2):
            out: list[dict] = []
            token = None
            while True:
                kw = {"PageSize": 100}
                if token:
                    kw["NextToken"] = token
                r = c.list_email_identities(**kw)
                out.extend(r.get("EmailIdentities", []))
                token = r.get("NextToken")
                if not token:
                    return out

        ids = guard(f"ses.identities.{region}", _ses_identities, default=[])
        rows = []
        for i in ids or []:
            name = i["IdentityName"]
            detail = guard(
                f"ses.detail.{region}.{name}",
                lambda c=sesv2, n=name: c.get_email_identity(EmailIdentity=n),
                default={},
            )
            rows.append(
                {
                    "identity": name,
                    "type": i.get("IdentityType"),
                    "sending_enabled": i.get("SendingEnabled"),
                    "verified": detail.get("VerifiedForSendingStatus"),
                    "dkim_status": (detail.get("DkimAttributes") or {}).get("Status"),
                    "dkim_signing": (detail.get("DkimAttributes") or {}).get("SigningEnabled"),
                    "mail_from": (detail.get("MailFromAttributes") or {}).get("MailFromDomain"),
                    "mail_from_status": (detail.get("MailFromAttributes") or {}).get(
                        "MailFromDomainStatus"
                    ),
                }
            )
        account = guard(
            f"ses.account.{region}",
            lambda c=sesv2: c.get_account(),
            default={},
        )
        cfgsets = guard(
            f"ses.configsets.{region}",
            lambda c=sesv2: paged(c, "list_configuration_sets", "ConfigurationSets"),
            default=[],
        )
        out[region] = {
            "identity_count": len(rows),
            "identities": sorted(rows, key=lambda r: r["identity"]),
            "production_access": (account or {}).get("ProductionAccessEnabled"),
            "sending_enabled": (account or {}).get("SendingEnabled"),
            "sending_quota": (account or {}).get("SendQuota"),
            "enforcement_status": (account or {}).get("EnforcementStatus"),
            "configuration_sets": sorted(cfgsets or []),
        }
    return out


def collect_s3() -> dict:
    s3 = client("s3")
    buckets = guard("s3.list", lambda: s3.list_buckets().get("Buckets", []), default=[])
    rows = []
    for b in buckets or []:
        name = b["Name"]
        loc = guard(
            f"s3.loc.{name}",
            lambda n=name: s3.get_bucket_location(Bucket=n).get("LocationConstraint") or "us-east-1",
        )
        # Absent encryption config is a finding reported as `None` in the row, not
        # a collector failure.
        def _encryption(n=name):
            try:
                return s3.get_bucket_encryption(Bucket=n)[
                    "ServerSideEncryptionConfiguration"
                ]["Rules"][0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"]
            except ClientError as exc:
                if exc.response["Error"]["Code"] in (
                    "ServerSideEncryptionConfigurationNotFoundError",
                    "NoSuchEncryptionConfiguration",
                ):
                    return None
                raise

        enc = guard(f"s3.enc.{name}", _encryption)
        pab = guard(
            f"s3.pab.{name}",
            lambda n=name: s3.get_public_access_block(Bucket=n)["PublicAccessBlockConfiguration"],
            default={},
        )
        ver = guard(
            f"s3.ver.{name}",
            lambda n=name: s3.get_bucket_versioning(Bucket=n).get("Status"),
        )
        # A bucket with no policy cannot be public by policy. That is an answer,
        # not a failure, so it must not inflate error_count.
        def _policy_public(n=name):
            try:
                return s3.get_bucket_policy_status(Bucket=n)["PolicyStatus"]["IsPublic"]
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "NoSuchBucketPolicy":
                    return False
                raise

        policy_public = guard(f"s3.pubstatus.{name}", _policy_public)
        rows.append(
            {
                "name": name,
                "created": _iso(b.get("CreationDate")),
                "region": loc,
                "encryption": enc,
                "public_access_block_all": bool(pab)
                and all(
                    pab.get(k)
                    for k in (
                        "BlockPublicAcls",
                        "IgnorePublicAcls",
                        "BlockPublicPolicy",
                        "RestrictPublicBuckets",
                    )
                ),
                "versioning": ver,
                "policy_is_public": policy_public,
            }
        )
    rows.sort(key=lambda r: r["name"])
    return {
        "count": len(rows),
        "unencrypted": sorted(r["name"] for r in rows if not r["encryption"]),
        "public_policy": sorted(r["name"] for r in rows if r["policy_is_public"]),
        "no_full_public_access_block": sorted(
            r["name"] for r in rows if not r["public_access_block_all"]
        ),
        "buckets": rows,
    }


def collect_cloudfront() -> dict:
    cf = client("cloudfront")

    def _all_distributions() -> list:
        # ListDistributions nests Items under DistributionList, so the generic
        # `paged` helper cannot flatten it. Page explicitly.
        out: list = []
        for page in cf.get_paginator("list_distributions").paginate():
            out.extend((page.get("DistributionList") or {}).get("Items", []) or [])
        return out

    raw = guard("cloudfront.list", _all_distributions, default=[])
    rows = []
    for d in raw or []:
        rows.append(
            {
                "id": d.get("Id"),
                "domain": d.get("DomainName"),
                "aliases": (d.get("Aliases") or {}).get("Items", []),
                "status": d.get("Status"),
                "enabled": d.get("Enabled"),
                "origins": [
                    o.get("DomainName") for o in (d.get("Origins") or {}).get("Items", [])
                ],
                "web_acl": d.get("WebACLId") or None,
                "viewer_protocol": (d.get("DefaultCacheBehavior") or {}).get(
                    "ViewerProtocolPolicy"
                ),
                "lambda_edge": [
                    f.get("LambdaFunctionARN", "").rsplit(":", 2)[-2:]
                    for f in (
                        (d.get("DefaultCacheBehavior") or {}).get(
                            "LambdaFunctionAssociations", {}
                        )
                        or {}
                    ).get("Items", [])
                ],
                "price_class": d.get("PriceClass"),
            }
        )
    rows.sort(key=lambda r: r["id"] or "")
    return {
        "count": len(rows),
        "without_web_acl": sorted(r["id"] for r in rows if not r["web_acl"]),
        "distributions": rows,
    }


def collect_waf() -> dict:
    out = {}
    for scope, region in (("REGIONAL", REGION), ("CLOUDFRONT", "us-east-1")):
        wafv2 = client("wafv2", region)
        acls = guard(
            f"waf.{scope}",
            lambda c=wafv2, s=scope: c.list_web_acls(Scope=s, Limit=100).get("WebACLs", []),
            default=[],
        )
        rows = []
        for a in acls or []:
            # ListResourcesForWebACL defaults ResourceType to
            # APPLICATION_LOAD_BALANCER, so asking once reports "associated with
            # nothing" for a web ACL that is in fact protecting a Cognito user pool
            # or an API -- a false CRITICAL finding. Ask for every regional type.
            assoc: list[str] = []
            if scope == "REGIONAL":
                for rtype in (
                    "APPLICATION_LOAD_BALANCER",
                    "API_GATEWAY",
                    "APPSYNC",
                    "COGNITO_USER_POOL",
                    "APP_RUNNER_SERVICE",
                    "VERIFIED_ACCESS_INSTANCE",
                    "AMPLIFY",
                ):
                    assoc.extend(
                        guard(
                            f"waf.assoc.{a['Name']}.{rtype}",
                            lambda c=wafv2, arn=a["ARN"], t=rtype: c.list_resources_for_web_acl(
                                WebACLArn=arn, ResourceType=t
                            ).get("ResourceArns", []),
                            default=[],
                        )
                        or []
                    )
            # A CLOUDFRONT-scope ACL has no ListResourcesForWebACL at all. Its
            # consumers are found from distribution WebACLId and, for an Amplify
            # app (whose distribution is AWS-owned and never appears in
            # ListDistributions), from the app's own wafConfiguration.
            rows.append(
                {
                    "name": a.get("Name"),
                    "id": a.get("Id"),
                    "arn": a.get("ARN"),
                    "associated_resources": assoc,
                }
            )
        out[scope] = {"count": len(rows), "web_acls": rows}
    return out


def collect_route53() -> dict:
    r53 = client("route53")
    zones = guard("route53.zones", lambda: paged(r53, "list_hosted_zones", "HostedZones"), default=[])
    rows = []
    for z in zones or []:
        zid = z["Id"].split("/")[-1]
        records = guard(
            f"route53.records.{zid}",
            lambda i=zid: paged(r53, "list_resource_record_sets", "ResourceRecordSets", HostedZoneId=i),
            default=[],
        )
        types = _tally(r["Type"] for r in records or [])
        rows.append(
            {
                "id": zid,
                "name": z.get("Name"),
                "private": (z.get("Config") or {}).get("PrivateZone"),
                "record_count": len(records or []),
                "record_types": types,
                "has_mx": any(r["Type"] == "MX" for r in records or []),
                "txt_names": sorted(
                    r["Name"] for r in (records or []) if r["Type"] == "TXT"
                ),
            }
        )
    rows.sort(key=lambda r: r["name"] or "")
    return {"zone_count": len(rows), "zones": rows}


def collect_cloudwatch() -> dict:
    cw = client("cloudwatch")
    alarms = guard("cw.alarms", lambda: paged(cw, "describe_alarms", "MetricAlarms"), default=[])
    composite = guard(
        "cw.composite", lambda: paged(cw, "describe_alarms", "CompositeAlarms"), default=[]
    )
    dashboards = guard(
        "cw.dashboards",
        lambda: paged(cw, "list_dashboards", "DashboardEntries"),
        default=[],
    )
    logs = client("logs")
    groups = guard("logs.groups", lambda: paged(logs, "describe_log_groups", "logGroups"), default=[])
    alarm_rows = [
        {
            "name": a.get("AlarmName"),
            "state": a.get("StateValue"),
            "metric": a.get("MetricName"),
            "namespace": a.get("Namespace"),
            "actions": len(a.get("AlarmActions") or []),
            "actions_enabled": a.get("ActionsEnabled"),
        }
        for a in alarms or []
    ]
    alarm_rows.sort(key=lambda r: r["name"] or "")
    no_retention = sorted(
        g["logGroupName"] for g in (groups or []) if not g.get("retentionInDays")
    )
    return {
        "alarm_count": len(alarm_rows),
        "composite_alarm_count": len(composite or []),
        "alarms_in_alarm": sorted(r["name"] for r in alarm_rows if r["state"] == "ALARM"),
        "alarms_insufficient_data": sorted(
            r["name"] for r in alarm_rows if r["state"] == "INSUFFICIENT_DATA"
        ),
        "alarms_without_actions": sorted(r["name"] for r in alarm_rows if not r["actions"]),
        "dashboard_count": len(dashboards or []),
        "dashboards": sorted(d.get("DashboardName") for d in (dashboards or [])),
        "log_group_count": len(groups or []),
        "log_groups_without_retention": no_retention,
        "log_bytes_total": sum(g.get("storedBytes", 0) for g in (groups or [])),
        "alarms": alarm_rows,
    }


def collect_iac() -> dict:
    cfn = client("cloudformation")
    stacks = guard(
        "cfn.stacks",
        lambda: paged(
            cfn,
            "list_stacks",
            "StackSummaries",
            StackStatusFilter=[
                "CREATE_COMPLETE",
                "UPDATE_COMPLETE",
                "UPDATE_ROLLBACK_COMPLETE",
                "ROLLBACK_COMPLETE",
                "CREATE_IN_PROGRESS",
                "UPDATE_IN_PROGRESS",
                "IMPORT_COMPLETE",
            ],
        ),
        default=[],
    )
    stack_rows = sorted(
        (
            {
                "name": s.get("StackName"),
                "status": s.get("StackStatus"),
                "updated": _iso(s.get("LastUpdatedTime") or s.get("CreationTime")),
                "drift": (s.get("DriftInformation") or {}).get("StackDriftStatus"),
                "parent": s.get("ParentId"),
            }
            for s in stacks or []
        ),
        key=lambda r: r["name"] or "",
    )
    amp = client("amplify")
    apps = guard("amplify.apps", lambda: paged(amp, "list_apps", "apps"), default=[])
    app_rows = []
    for a in apps or []:
        branches = guard(
            f"amplify.branches.{a['appId']}",
            lambda i=a["appId"]: paged(amp, "list_branches", "branches", appId=i),
            default=[],
        )
        brows = []
        for b in branches or []:
            jobs = guard(
                f"amplify.jobs.{a['appId']}.{b['branchName']}",
                lambda i=a["appId"], bn=b["branchName"]: amp.list_jobs(
                    appId=i, branchName=bn, maxResults=3
                ).get("jobSummaries", []),
                default=[],
            )
            brows.append(
                {
                    "branch": b.get("branchName"),
                    "stage": b.get("stage"),
                    "enable_auto_build": b.get("enableAutoBuild"),
                    "recent_jobs": [
                        {
                            "id": j.get("jobId"),
                            "status": j.get("status"),
                            "commit": (j.get("commitId") or "")[:12],
                            "end": _iso(j.get("endTime")),
                        }
                        for j in jobs or []
                    ],
                }
            )
        app_rows.append(
            {
                "app_id": a.get("appId"),
                "name": a.get("name"),
                "default_domain": a.get("defaultDomain"),
                "platform": a.get("platform"),
                "repository": a.get("repository"),
                "custom_rule_count": len(a.get("customRules") or []),
                # Sorted so a regenerated inventory diffs to real change only.
                "branches": sorted(brows, key=lambda b: b["branch"] or ""),
            }
        )
    app_rows.sort(key=lambda r: r["app_id"] or "")
    return {
        "cfn_stack_count": len(stack_rows),
        "cfn_stacks": stack_rows,
        "amplify_app_count": len(app_rows),
        "amplify_apps": app_rows,
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _tally(values) -> dict:
    out: dict = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], str(kv[0]))))


def _iso(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.astimezone(timezone.utc).isoformat()
    return str(val)


def collect_crosschecks() -> dict:
    """Checks that only become visible when two services are compared.

    A per-service dump hides these. Every one of them was a live defect when
    this collector was written:
      * two DLQ depth alarms named a `base-` queue prefix that no longer exists,
        so they could never fire
      * the notification DLQ - the one the unified notification service depends
        on - had no alarm at all
      * two PayU alarms still naming a Lambda deleted with the provider

    A fourth entry used to be listed here - "a regional WAF web ACL attached to
    nothing" - and it was this collector's own bug, not an account defect.
    `ListResourcesForWebACL` defaults `ResourceType` to
    `APPLICATION_LOAD_BALANCER` and this account has none, so every regional ACL
    read as unassociated while `wecare-cognito-waf` was in fact attached to both
    user pools. It is kept in the docstring as a warning: a cross-check that
    reports a defect which does not exist costs more than no check at all.
    """
    sqs = client("sqs")
    cw = client("cloudwatch")
    waf_regional = client("wafv2", REGION)
    amp = client("amplify")

    queues = {
        u.rsplit("/", 1)[-1] for u in (paged(sqs, "list_queues", "QueueUrls") or [])
    }
    alarms = paged(cw, "describe_alarms", "MetricAlarms")

    watched: dict[str, list[str]] = {}
    for a in alarms:
        dims = {d["Name"]: d["Value"] for d in a.get("Dimensions", [])}
        q = dims.get("QueueName")
        if q:
            watched.setdefault(q, []).append(a["AlarmName"])

    dlqs = {q for q in queues if "dlq" in q.lower() or "dead-letter" in q.lower()}
    orphan_alarms = {
        q: names for q, names in watched.items() if q not in queues
    }

    # Generalised from QueueName to every dimension whose value names a resource
    # we can enumerate. Restricting it to queues found two broken alarms and
    # missed two more: both PayU alarms still name a Lambda that was deleted with
    # the provider, including a `UrlRequestCount > 0` tripwire meant to catch
    # anyone calling the retired webhook. A tripwire on an absent resource never
    # reports, so it reads OK forever - the same false comfort, one service over.
    ddb_c = client("dynamodb")
    lam_c = client("lambda")
    apig_c = client("apigatewayv2")
    ev_c = client("events")
    pools = {
        "QueueName": queues,
        "TableName": set(
            guard("crosscheck.tables", lambda: paged(ddb_c, "list_tables", "TableNames"), default=None)
            or []
        )
        or None,
        "FunctionName": {
            f["FunctionName"]
            for f in (
                guard(
                    "crosscheck.functions",
                    lambda: paged(lam_c, "list_functions", "Functions"),
                    default=None,
                )
                or []
            )
        }
        or None,
        "ApiName": {
            a["Name"]
            for a in (
                guard("crosscheck.apis", lambda: paged(apig_c, "get_apis", "Items"), default=None)
                or []
            )
        }
        or None,
        "RuleName": {
            r["Name"]
            for r in (
                guard("crosscheck.rules", lambda: paged(ev_c, "list_rules", "Rules"), default=None)
                or []
            )
        }
        or None,
    }
    # A pool that failed to load is None, not empty, so a failed enumeration can
    # never be mistaken for "every resource is missing".
    dangling: dict[str, list[str]] = {}
    for a in alarms:
        for d in a.get("Dimensions", []):
            pool = pools.get(d["Name"])
            if pool and d["Value"] not in pool:
                dangling.setdefault(
                    f"{d['Name']}={d['Value']}", []
                ).append(a["AlarmName"])

    # Regional ACL associations are readable; CLOUDFRONT-scope ones are not, so
    # the Amplify app is asked directly rather than assumed unprotected.
    unassociated = []
    for a in guard(
        "crosscheck.waf",
        lambda: waf_regional.list_web_acls(Scope="REGIONAL", Limit=100).get("WebACLs", []),
        default=[],
    ) or []:
        # Same ResourceType trap as collect_waf: the default is
        # APPLICATION_LOAD_BALANCER, and there are no load balancers in this
        # account, so a single call reports every regional ACL as unassociated.
        # wecare-cognito-waf is in fact attached to both user pools.
        res: list[str] = []
        failed = False
        for rtype in (
            "APPLICATION_LOAD_BALANCER",
            "API_GATEWAY",
            "APPSYNC",
            "COGNITO_USER_POOL",
            "APP_RUNNER_SERVICE",
            "VERIFIED_ACCESS_INSTANCE",
            "AMPLIFY",
        ):
            got = guard(
                f"crosscheck.waf.assoc.{a['Name']}.{rtype}",
                lambda arn=a["ARN"], t=rtype: waf_regional.list_resources_for_web_acl(
                    WebACLArn=arn, ResourceType=t
                ).get("ResourceArns", []),
                default=None,
            )
            if got is None:
                failed = True
            else:
                res.extend(got)
        if not failed and not res:
            unassociated.append(a["Name"])

    amplify_waf = {}
    for app in guard("crosscheck.amplify", lambda: paged(amp, "list_apps", "apps"), default=[]) or []:
        detail = guard(
            f"crosscheck.amplify.{app['appId']}",
            lambda i=app["appId"]: amp.get_app(appId=i)["app"],
            default={},
        )
        cfg = (detail or {}).get("wafConfiguration") or {}
        amplify_waf[app["appId"]] = {
            "web_acl_arn_tail": (cfg.get("webAclArn") or "").rsplit("/", 2)[-2:],
            "status": cfg.get("wafStatus") or "NOT_ASSOCIATED",
        }

    return {
        "dlqs_without_alarm": sorted(dlqs - set(watched)),
        "alarms_watching_nonexistent_queue": orphan_alarms,
        "alarms_with_dangling_dimension": {k: sorted(v) for k, v in sorted(dangling.items())},
        "regional_web_acls_with_zero_associations": sorted(unassociated),
        "amplify_waf": amplify_waf,
    }


COLLECTORS = {
    "lambda": collect_lambda,
    "api_gateway": collect_apigw,
    "dynamodb": collect_dynamodb,
    "sqs": collect_sqs,
    "eventbridge": collect_eventbridge,
    "secrets_manager": collect_secrets,
    "cognito": collect_cognito,
    "ses": collect_ses,
    "s3": collect_s3,
    "cloudfront": collect_cloudfront,
    "waf": collect_waf,
    "route53": collect_route53,
    "cloudwatch": collect_cloudwatch,
    "iac": collect_iac,
    "crosschecks": collect_crosschecks,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--only", help="comma separated collector names")
    args = ap.parse_args()

    selected = (
        {k: v for k, v in COLLECTORS.items() if k in args.only.split(",")}
        if args.only
        else COLLECTORS
    )

    ident = boto3.client("sts", region_name=REGION).get_caller_identity()
    started = datetime.now(timezone.utc)
    data: dict = {
        "generated": started.isoformat(),
        "account": ident["Account"],
        "identity_arn": ident["Arn"],
        "region": REGION,
        "alt_regions": ALT_REGIONS,
    }

    # Collect concurrently, but assign into `data` in a fixed order. Writing keys
    # in thread-completion order reordered the whole document on every run, so a
    # regenerated inventory diffed by ~550 lines and genuine change was invisible
    # in the noise.
    results: dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(guard, name, fn, {}): name for name, fn in selected.items()}
        for fut in concurrent.futures.as_completed(futures):
            name = futures[fut]
            results[name] = fut.result() or {}
            if not args.json_only:
                print(f"  collected {name}", file=sys.stderr)
    for name in COLLECTORS:
        if name in results:
            data[name] = results[name]

    ERRORS.sort(key=lambda e: (e["label"], e["error"]))

    data["errors"] = ERRORS
    data["error_count"] = len(ERRORS)
    data["duration_seconds"] = round(
        (datetime.now(timezone.utc) - started).total_seconds(), 1
    )

    # A partial run must never clobber the full inventory. `--only` is for
    # iterating on one collector, and letting it overwrite the committed
    # artifacts would leave every other family reading `null` - which looks
    # exactly like "resource absent", the failure mode this script exists to
    # avoid.
    partial = bool(args.only)
    out_json = (
        OUT_JSON.with_name(f"{OUT_JSON.stem}.partial.json") if partial else OUT_JSON
    )
    out_md = OUT_MD.with_name(f"{OUT_MD.stem}.partial.md") if partial else OUT_MD
    data["partial_run"] = partial
    data["collectors_run"] = sorted(selected)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, indent=2, default=str))
    if not args.json_only:
        out_md.write_text(render_md(data))
    if partial:
        print(
            f"partial run ({', '.join(sorted(selected))}) -> {out_json.name}; "
            f"the full inventory was left untouched",
            file=sys.stderr,
        )
    print(json.dumps(summary(data), indent=2))
    return 0 if not ERRORS else 1


def summary(d: dict) -> dict:
    return {
        "account": d.get("account"),
        "generated": d.get("generated"),
        "lambda_functions": d.get("lambda", {}).get("count"),
        "lambda_with_live_alias": d.get("lambda", {}).get("with_live_alias"),
        "http_apis": d.get("api_gateway", {}).get("http_api_count"),
        "rest_apis": d.get("api_gateway", {}).get("rest_api_count"),
        "routes": d.get("api_gateway", {}).get("total_routes"),
        "authorizers": d.get("api_gateway", {}).get("total_authorizers"),
        "routes_auth_none": d.get("api_gateway", {}).get("routes_authorization_none"),
        "dynamodb_tables": d.get("dynamodb", {}).get("count"),
        "sqs_queues": d.get("sqs", {}).get("count"),
        "eventbridge_rules": d.get("eventbridge", {}).get("rule_count"),
        "eventbridge_schedules": d.get("eventbridge", {}).get("scheduler_count"),
        "secrets": d.get("secrets_manager", {}).get("count"),
        "secrets_scheduled_deletion": len(
            d.get("secrets_manager", {}).get("scheduled_for_deletion", [])
        ),
        "cognito_user_pools": d.get("cognito", {}).get("user_pool_count"),
        "s3_buckets": d.get("s3", {}).get("count"),
        "cloudfront_distributions": d.get("cloudfront", {}).get("count"),
        "waf_regional": d.get("waf", {}).get("REGIONAL", {}).get("count"),
        "waf_cloudfront": d.get("waf", {}).get("CLOUDFRONT", {}).get("count"),
        "route53_zones": d.get("route53", {}).get("zone_count"),
        "cw_alarms": d.get("cloudwatch", {}).get("alarm_count"),
        "log_groups": d.get("cloudwatch", {}).get("log_group_count"),
        "cfn_stacks": d.get("iac", {}).get("cfn_stack_count"),
        "amplify_apps": d.get("iac", {}).get("amplify_app_count"),
        "dlqs_without_alarm": len(
            d.get("crosschecks", {}).get("dlqs_without_alarm", [])
        ),
        "alarms_watching_nonexistent_queue": len(
            d.get("crosschecks", {}).get("alarms_watching_nonexistent_queue", {})
        ),
        "error_count": d.get("error_count"),
        "duration_seconds": d.get("duration_seconds"),
    }


def render_md(d: dict) -> str:
    s = summary(d)
    lam = d.get("lambda", {})
    api = d.get("api_gateway", {})
    ddb = d.get("dynamodb", {})
    sqs = d.get("sqs", {})
    eb = d.get("eventbridge", {})
    sec = d.get("secrets_manager", {})
    cog = d.get("cognito", {})
    ses = d.get("ses", {})
    s3 = d.get("s3", {})
    cf = d.get("cloudfront", {})
    waf = d.get("waf", {})
    r53 = d.get("route53", {})
    cw = d.get("cloudwatch", {})
    iac = d.get("iac", {})

    L = []
    L.append("# AWS account inventory")
    L.append("")
    L.append(
        f"Generated {d.get('generated')} · account `{d.get('account')}` · "
        f"`{d.get('region')}` (+ {', '.join(d.get('alt_regions', []))}) · "
        f"regenerate with `python scripts/aws_account_inventory.py`"
    )
    L.append("")
    L.append(
        "This file supersedes every dated resource count in the steering files. "
        "Machine-readable companion: `aws-inventory.json`. Secret **names** and "
        "metadata are recorded; no secret value is ever read. Lambda environment "
        "variable **names** are recorded, values never are."
    )
    L.append("")
    L.append(f"Collector errors: **{d.get('error_count')}** "
             f"(a non-zero count makes this inventory PARTIAL, not authoritative).")
    L.append("")
    L.append("## Headline counts")
    L.append("")
    L.append("| Resource | Count |")
    L.append("|---|---:|")
    for label, key in [
        ("Lambda functions", "lambda_functions"),
        ("— with a `live` alias", "lambda_with_live_alias"),
        ("HTTP APIs", "http_apis"),
        ("REST APIs", "rest_apis"),
        ("HTTP API routes", "routes"),
        ("API authorizers", "authorizers"),
        ("Routes with AuthorizationType=NONE", "routes_auth_none"),
        ("DynamoDB tables", "dynamodb_tables"),
        ("SQS queues", "sqs_queues"),
        ("EventBridge rules", "eventbridge_rules"),
        ("EventBridge Scheduler schedules", "eventbridge_schedules"),
        ("Secrets Manager secrets", "secrets"),
        ("— scheduled for deletion", "secrets_scheduled_deletion"),
        ("Cognito user pools", "cognito_user_pools"),
        ("S3 buckets", "s3_buckets"),
        ("CloudFront distributions", "cloudfront_distributions"),
        ("WAF web ACLs (regional)", "waf_regional"),
        ("WAF web ACLs (CloudFront)", "waf_cloudfront"),
        ("Route 53 hosted zones", "route53_zones"),
        ("CloudWatch alarms", "cw_alarms"),
        ("CloudWatch log groups", "log_groups"),
        ("CloudFormation stacks", "cfn_stacks"),
        ("Amplify apps", "amplify_apps"),
    ]:
        L.append(f"| {label} | {s.get(key)} |")
    L.append("")

    L.append("## Lambda")
    L.append("")
    L.append(f"Runtimes: {lam.get('runtimes')}  ·  package types: {lam.get('package_types')}")
    L.append("")
    L.append(f"SnapStart: {lam.get('snapstart')}")
    L.append("")
    L.append(f"Alias read errors: {lam.get('alias_read_errors')}")
    L.append("")
    L.append(
        f"**Without a `live` alias ({len(lam.get('without_live_alias', []))})** — "
        "`$LATEST` reaches production directly for these:"
    )
    L.append("")
    for n in lam.get("without_live_alias", []):
        L.append(f"- `{n}`")
    L.append("")

    L.append("## API Gateway")
    L.append("")
    for a in api.get("http_apis", []):
        L.append(
            f"- **{a['api_id']}** `{a.get('name')}` — {a['route_count']} routes, "
            f"{a['authorizer_count']} authorizers, stages: "
            f"{[st['name'] for st in a.get('stages', [])]}"
        )
        for az in a.get("authorizers", []):
            L.append(f"  - authorizer `{az['name']}` ({az['type']}) {az['identity_source']}")
    if api.get("rest_apis"):
        L.append("")
        L.append("REST APIs:")
        for a in api["rest_apis"]:
            L.append(f"- `{a['id']}` {a.get('name')}")
    L.append("")
    non_none = [
        r
        for a in api.get("http_apis", [])
        for r in a.get("routes", [])
        if r["authorization_type"] != "NONE"
    ]
    L.append(f"Routes with an authorizer attached: **{len(non_none)}**")
    if non_none:
        L.append("")
        for r in non_none[:50]:
            L.append(f"- `{r['route_key']}` — {r['authorization_type']}")
    L.append("")

    L.append("## DynamoDB")
    L.append("")
    L.append(f"Empty tables ({len(ddb.get('empty_tables', []))}): "
             f"{', '.join('`%s`' % t for t in ddb.get('empty_tables', [])) or '(none)'}")
    L.append("")
    L.append(f"Without point-in-time recovery ({len(ddb.get('no_pitr', []))}): "
             f"{', '.join('`%s`' % t for t in ddb.get('no_pitr', [])) or '(none)'}")
    L.append("")
    L.append(f"With streams ({len(ddb.get('with_streams', []))}): "
             f"{', '.join('`%s`' % t for t in ddb.get('with_streams', [])) or '(none)'}")
    L.append("")

    L.append("## SQS")
    L.append("")
    if sqs.get("queues"):
        L.append("| Queue | visible | in flight | DLQ target | maxReceive |")
        L.append("|---|---:|---:|---|---:|")
        for q in sqs["queues"]:
            L.append(
                f"| `{q['name']}` | {q['visible_messages']} | {q['in_flight']} | "
                f"{('`%s`' % q['dlq_target']) if q['dlq_target'] else '—'} | "
                f"{q['max_receive_count'] or '—'} |"
            )
    else:
        L.append("(no queues)")
    L.append("")
    L.append(f"Queues with no redrive policy and not DLQ-named: "
             f"{', '.join('`%s`' % q for q in sqs.get('without_redrive', [])) or '(none)'}")
    L.append("")

    L.append("## EventBridge")
    L.append("")
    for b in eb.get("buses", []):
        L.append(f"- bus `{b['name']}` — {b['rule_count']} rules")
        for r in b.get("rules", []):
            tgt = ", ".join(t["arn_tail"] for t in r.get("targets", [])) or "no target"
            dlq = "dlq" if any(t["has_dlq"] for t in r.get("targets", [])) else "no-dlq"
            L.append(
                f"  - `{r['name']}` {r['state']} "
                f"{r.get('schedule') or ('pattern' if r['has_pattern'] else '')} "
                f"-> {tgt} [{dlq}]"
            )
    L.append("")
    L.append(f"EventBridge Scheduler schedules: {eb.get('scheduler_count')} "
             f"{[x['name'] for x in eb.get('schedules', [])]}")
    L.append("")
    L.append(f"Disabled rules: {eb.get('disabled_rules') or '(none)'}")
    L.append("")

    L.append("## Secrets Manager")
    L.append("")
    L.append("Metadata only. No value was read.")
    L.append("")
    L.append("| Secret | last changed | rotation | scheduled deletion |")
    L.append("|---|---|---|---|")
    for x in sec.get("secrets", []):
        L.append(
            f"| `{x['name']}` | {(x['last_changed'] or '')[:10]} | "
            f"{'yes' if x['rotation_enabled'] else 'no'} | "
            f"{(x['deleted_date'] or '—')[:10]} |"
        )
    L.append("")

    L.append("## Cognito")
    L.append("")
    for p in cog.get("user_pools", []):
        L.append(
            f"- `{p['id']}` **{p['name']}** — users≈{p['estimated_users']}, "
            f"MFA={p['mfa_configuration']}, advanced_security={p['advanced_security']}, "
            f"deletion_protection={p['deletion_protection']}"
        )
        L.append(f"  - clients: {[c['name'] for c in p.get('clients', [])]}")
        L.append(f"  - groups: {p.get('group_names')}")
        L.append(f"  - lambda triggers: {p.get('lambda_triggers')}")
    L.append("")
    L.append(f"Identity pools: {cog.get('identity_pool_count')}")
    L.append("")

    L.append("## SES")
    L.append("")
    for region, blob in ses.items():
        L.append(
            f"### {region} — production_access={blob.get('production_access')}, "
            f"sending={blob.get('sending_enabled')}, quota={blob.get('sending_quota')}"
        )
        L.append("")
        for i in blob.get("identities", []):
            L.append(
                f"- `{i['identity']}` ({i['type']}) verified={i['verified']} "
                f"dkim={i['dkim_status']}/{i['dkim_signing']} "
                f"mail_from={i['mail_from']}/{i['mail_from_status']}"
            )
        L.append("")
        L.append(f"Configuration sets: {blob.get('configuration_sets')}")
        L.append("")

    L.append("## S3")
    L.append("")
    L.append("| Bucket | region | encryption | PAB all | versioning | public policy |")
    L.append("|---|---|---|---|---|---|")
    for b in s3.get("buckets", []):
        L.append(
            f"| `{b['name']}` | {b['region']} | {b['encryption'] or '**none**'} | "
            f"{'yes' if b['public_access_block_all'] else '**no**'} | "
            f"{b['versioning'] or '—'} | "
            f"{'**yes**' if b['policy_is_public'] else 'no'} |"
        )
    L.append("")

    L.append("## CloudFront")
    L.append("")
    for x in cf.get("distributions", []):
        L.append(
            f"- `{x['id']}` {x['domain']} aliases={x['aliases']} "
            f"status={x['status']} enabled={x['enabled']} "
            f"web_acl={x['web_acl'] or '**none**'}"
        )
        L.append(f"  - origins: {x['origins']}")
    L.append("")

    L.append("## WAF")
    L.append("")
    for scope, blob in waf.items():
        L.append(f"- **{scope}**: {blob.get('count')} web ACLs")
        for a in blob.get("web_acls", []):
            L.append(f"  - `{a['name']}` associated: {a.get('associated_resources')}")
    L.append("")

    L.append("## Route 53")
    L.append("")
    for z in r53.get("zones", []):
        L.append(
            f"- `{z['name']}` ({z['id']}) — {z['record_count']} records, "
            f"MX={z['has_mx']}, types={z['record_types']}"
        )
    L.append("")

    L.append("## CloudWatch")
    L.append("")
    L.append(f"- alarms: {cw.get('alarm_count')} (composite {cw.get('composite_alarm_count')})")
    L.append(f"- in ALARM: {cw.get('alarms_in_alarm') or '(none)'}")
    L.append(f"- INSUFFICIENT_DATA: {len(cw.get('alarms_insufficient_data', []))}")
    L.append(f"- alarms with no action: {len(cw.get('alarms_without_actions', []))}")
    L.append(f"- dashboards: {cw.get('dashboards')}")
    L.append(f"- log groups: {cw.get('log_group_count')}, "
             f"stored {round(cw.get('log_bytes_total', 0) / 1e9, 2)} GB")
    L.append(f"- log groups with no retention: "
             f"{len(cw.get('log_groups_without_retention', []))}")
    for g in cw.get("log_groups_without_retention", [])[:40]:
        L.append(f"  - `{g}`")
    L.append("")

    L.append("## IaC")
    L.append("")
    L.append("CloudFormation stacks:")
    L.append("")
    for st in iac.get("cfn_stacks", []):
        L.append(f"- `{st['name']}` {st['status']} updated={(st['updated'] or '')[:10]} "
                 f"drift={st['drift']}")
    L.append("")
    L.append("Amplify:")
    L.append("")
    for a in iac.get("amplify_apps", []):
        L.append(
            f"- `{a['app_id']}` **{a['name']}** platform={a['platform']} "
            f"custom_rules={a['custom_rule_count']} repo={a['repository']}"
        )
        for b in a.get("branches", []):
            L.append(f"  - branch `{b['branch']}` stage={b['stage']} auto_build={b['enable_auto_build']}")
            for j in b.get("recent_jobs", []):
                L.append(
                    f"    - job {j['id']} {j['status']} commit `{j['commit']}` "
                    f"{(j['end'] or '')[:19]}"
                )
    L.append("")

    xc = d.get("crosschecks", {})
    L.append("## Cross-service checks")
    L.append("")
    L.append("Defects that are invisible in any single service listing.")
    L.append("")
    L.append(
        f"**DLQs with no CloudWatch alarm ({len(xc.get('dlqs_without_alarm', []))})** — "
        "messages can pile up unobserved:"
    )
    L.append("")
    for q in xc.get("dlqs_without_alarm", []) or ["(none)"]:
        L.append(f"- `{q}`")
    L.append("")
    orphan = xc.get("alarms_watching_nonexistent_queue", {})
    L.append(
        f"**Alarms watching a queue that does not exist ({len(orphan)})** — "
        "these can never fire:"
    )
    L.append("")
    for q, names in (orphan or {"(none)": []}).items():
        L.append(f"- queue `{q}` watched by {names}")
    L.append("")
    dang = xc.get("alarms_with_dangling_dimension", {})
    L.append(
        f"**Alarms whose dimension names a resource that does not exist "
        f"({len(dang)})** — same class, across every enumerable dimension:"
    )
    L.append("")
    for k, names in (dang or {"(none)": []}).items():
        L.append(f"- `{k}` watched by {names}")
    L.append("")
    L.append(
        f"**Regional WAF web ACLs associated with nothing "
        f"({len(xc.get('regional_web_acls_with_zero_associations', []))})**:"
    )
    L.append("")
    for n in xc.get("regional_web_acls_with_zero_associations", []) or ["(none)"]:
        L.append(f"- `{n}`")
    L.append("")
    L.append("Amplify WAF association (CloudFront-scope ACLs cannot be queried "
             "from the WAF side, so the app is asked directly):")
    L.append("")
    for app_id, blob in (xc.get("amplify_waf") or {}).items():
        L.append(f"- `{app_id}` → {blob.get('status')} {blob.get('web_acl_arn_tail')}")
    L.append("")

    if d.get("errors"):
        L.append("## Collector errors")
        L.append("")
        for e in d["errors"]:
            L.append(f"- `{e['label']}`: {e['error'][:300]}")
        L.append("")

    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
