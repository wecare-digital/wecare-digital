#!/usr/bin/env python3
"""Reconcile the declared data model against the live tables and the code.

Why this exists
---------------
`amplify/data/resource.ts` reads like infrastructure and behaves like a
document. It declares 64 `a.model(...)` blocks, its comments cite physical table
names such as `stack-wecare-digital-ContactsTable`, and `amplify/backend.ts`
passes it to `defineBackend`. But there are **zero** AppSync APIs in the
account, so not one of those models has ever been materialised. Every table the
platform actually uses was provisioned by CDK or by a `scripts/provision_*.py`
script, under a different naming scheme.

Two failure modes follow, and neither announces itself:

1. A model is declared for a table that does not exist. Reading the file tells
   you the data is modelled; nothing tells you a writer would fault.
2. A live table is declared nowhere, so the file under-describes the system by
   more than it over-describes it.

Scope, and what owns the rest
-----------------------------
This script compares exactly two sets:

    DECLARED   models in amplify/data/resource.ts
    LIVE       tables in the account (or a committed snapshot, offline)

It does **not** check whether code references a table that exists. That is a
different and sharper question - a latent ResourceNotFoundException rather than a
documentation defect - and `scripts/audit_data_model_drift.py` already answers it
by matching exact name literals in source against `ListTables`. Run both:

    python scripts/audit_data_model_drift.py --gate   # does every name in code exist?
    python scripts/check_data_model_drift.py --gate   # does the declared model match?

The split matters. An earlier draft of this script tried to do both and reported
six false positives, because a regex stopping at the hyphen turns
`stack-wecare-digital-bulk-queue` into a "missing table called bulk". The sibling
script classifies queues, functions and bare prefixes properly. Duplicating it
badly would have made the pair less trustworthy than either alone.

Why this half needs the explicit map below
------------------------------------------
The sibling script deliberately refuses to map model names to physical tables,
and says so: an earlier version assumed `Model` -> `stack-wecare-digital-Model`
and produced 61 false positives, because the declarations are singular
(`Contact`) while the tables are plural with a suffix (`ContactsTable`), and
`backend.ts` resolves them indirectly through
`cfnResources.amplifyDynamoDbTables[modelName]`. Guessing a convention produced
noise. This script does not guess: the irregular cases are listed one by one,
each resolved by finding the physical name in the source.

Usage
-----
    python scripts/check_data_model_drift.py              # report, always exit 0
    python scripts/check_data_model_drift.py --gate       # non-zero on unexpected drift
    python scripts/check_data_model_drift.py --offline    # use the committed snapshot
    python scripts/check_data_model_drift.py --snapshot   # refresh the snapshot from AWS
    python scripts/check_data_model_drift.py --json

Exit codes with --gate: 0 clean, 1 unexpected drift, 2 could not determine.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOURCE_TS = ROOT / "amplify" / "data" / "resource.ts"
SNAPSHOT = ROOT / "docs" / "execution" / "snapshots" / "dynamodb-tables.json"
SEARCH_ROOTS = ("amplify", "scripts")

TABLE_PREFIX = "stack-wecare-digital-"

# ---------------------------------------------------------------------------
# Model -> physical table.
#
# The default rule is "pluralise the model name and append Table", which is what
# the majority follow. Everything that does not is listed here explicitly rather
# than guessed at, because a wrong guess reports a real table as undeclared and
# a real phantom as fine — the two errors this script exists to prevent.
#
# Each entry was resolved by finding the physical name in the source, not by
# pattern-matching the declaration.
# ---------------------------------------------------------------------------
EXPLICIT_TABLE: dict[str, str] = {
    # Model                     Physical table (without the shared prefix)
    # RateLimitTracker is the one that most looks like a phantom and is not: the
    # physical table drops the "Tracker". Reported as missing by any rule-based
    # guess, which is why the map exists.
    "RateLimitTracker": "RateLimitTable",
    "VoiceCall": "VoiceCalls",
    "VoiceCDR": "VoiceCDRTable",
    "OBDCampaign": "OBDCampaigns",
    "DLTTemplates": "DLTTemplates",
    "WebhookDedup": "WebhookDedup",
    "SystemConfig": "SystemConfigTable",
    "SystemEvent": "SystemEventTable",
    "CatalogCache": "CatalogCacheTable",
    "WixProductsCache": "WixProductsCache",
    "WixOrdersCache": "WixOrdersCache",
    "WixOrderId": "WixOrderIds",
    "ConversationHistory": "ConversationHistoryTable",
    "TemplateAnalytics": "TemplateAnalyticsTable",
    "AdClickAttribution": "AdClickAttributionTable",
    "FlowRegistry": "FlowRegistryTable",
    "FlowSubmission": "FlowSubmissionTable",
    "FlowDraft": "FlowDraftTable",
    "FlowLog": "FlowLogTable",
    "EnterpriseAssist": "EnterpriseAssistTable",
    "RequestStatusHistory": "RequestStatusHistoryTable",
    "DocumentHistory": "DocumentHistoryTable",
    "AmendmentHistory": "AmendmentHistoryTable",
    "InvoiceSequence": "InvoiceSequenceTable",
    "InvoiceDeliveryLog": "InvoiceDeliveryLogTable",
    "RazorpayWebhookLog": "RazorpayWebhookLogTable",
    "WhatsAppVoice": "WhatsAppVoiceTable",
    "WhatsAppCalling": "WhatsAppCallingTable",
    "WhatsAppGroup": "WhatsAppGroupTable",
    "WhatsAppInbound": "WhatsAppInboundTable",
    "WhatsAppOutbound": "WhatsAppOutboundTable",
    "VoiceAws": "VoiceAwsTable",
    "SubmitRequest": "SubmitRequestsTable",
    "ScheduledMessage": "ScheduledMessagesTable",
    "Appointment": "AppointmentTable",
    "Document": "DocumentTable",
    "Review": "ReviewTable",
    "Faq": "FaqTable",
    "RxSlot": "RxSlotTable",
    "Order": "OrderTable",
    "CrmPipeline": "CrmPipelines",
    "CrmStage": "CrmStages",
    "CrmLead": "CrmLeads",
    "CrmOpportunity": "CrmOpportunities",
    "CrmActivity": "CrmActivities",
    "AIInteraction": "AIInteractionsTable",
}

# ---------------------------------------------------------------------------
# Known, deliberate disagreements.
#
# A gate that fires on a decision already taken and recorded is a gate someone
# switches off, so each allowance carries the reason it is allowed. Anything NOT
# in here is unexpected and fails --gate.
# ---------------------------------------------------------------------------
PHANTOM_ALLOWED: dict[str, str] = {}

UNDECLARED_ALLOWED: dict[str, str] = {
    "AgentApprovalsTable":
        "Provisioned 2026-09-24 by scripts/provision_agent_approvals_table.py for "
        "the agent action approval path. Deliberately not modelled here: it is "
        "operational state with a TTL, not part of the CRM data model.",
    "PstnSoftphoneSessions":
        "Provisioned by scripts/provision_pstn_softphone.py. Its expiresAt is both "
        "the DynamoDB TTL and the agent availability cutoff; modelling it here "
        "would imply Amplify owns that clock.",
    "NotificationOutbox": "NOTIF-STORE-001 domain, owned by scripts/provision_notification_domain.py.",
    "NotificationEvents": "NOTIF-STORE-001 domain, owned by scripts/provision_notification_domain.py.",
    "NotificationDeliveries": "NOTIF-STORE-001 domain, owned by scripts/provision_notification_domain.py.",
    "NotificationAttempts": "NOTIF-STORE-001 domain, owned by scripts/provision_notification_domain.py.",
    "CallNotificationsTable": "Connected-call notification state, provisioned with the notification domain.",
    "PartnerWallet": "Partner billing, owned by lambda_utils/partner_billing.py.",
    "PartnerLedger": "Partner billing, owned by lambda_utils/partner_billing.py.",
    "SeoToolsTable": "Provisioned by amplify/seo-resources.ts + scripts/deploy_seo_tools.py.",
    "ShortLinksTable": "Provisioned by amplify/link-resources.ts; serves wecare.digital/r. The r.wecare.digital alias was retired 2026-09-28.",
    "LinkClicksTable": "Provisioned by amplify/link-resources.ts; serves wecare.digital/r. The r.wecare.digital alias was retired 2026-09-28.",
    "SiteLanguageCache": "Owned by core/site-language; a cache, not a modelled entity.",
    "PushTokensTable": "Owned by messaging/push-notifications.",
    "AutomationRulesTable": "Owned by lambda_utils/automation.py.",
    "ConversationMetaTable": "Owned by core/conversation-meta.",
    "AIProviderPolicyTable": "Owned by ai/ai-config-management.",
    "SmsOutboundTable": "Canonical outbound SMS store; see the SmsAws note in resource.ts.",
    "MessagesTable": "Declared as model `Message`; the plural physical name is matched by rule.",
    "WhatsAppPhonesTable":
        "Live with 0 items and a single reader: one lookup in "
        "messaging/inbound-whatsapp-handler/handler.py, keyed on displayPhoneNumber. "
        "Deliberately not modelled - it is a per-number lookup cache the handler "
        "populates and tolerates being empty, not a CRM entity. Measured 2026-09-24.",
    # Both arrived with the secure file sharing work and were provisioned live
    # without being recorded here, so this gate was failing at HEAD. Measured
    # 2026-09-25: keys, GSIs and TTL read from DescribeTable/DescribeTimeToLive.
    "SecureFilesTable":
        "Provisioned by scripts/provision_secure_files_api.py for the secure file "
        "sharing feature (docs/SECURE-FILE-SHARING.md). HASH `fileId`, GSI "
        "`owner-created-index`, TTL DISABLED - a shared file outlives any session "
        "and must not be swept. Owned by core/secure-files, not the CRM model.",
    "DownloadGrantsTable":
        "Provisioned by scripts/provision_secure_files_api.py alongside "
        "SecureFilesTable. HASH `grantId`, GSI `order-index`, TTL ENABLED on "
        "`expiresAt` - a download grant is deliberately short-lived, so expiry is "
        "the point of the record rather than a cache detail. Not modelled here for "
        "the same reason as PstnSoftphoneSessions: Amplify does not own that clock.",
    "CouponsTable":   "Provisioned by scripts/provision_coupons_table.py; issuance, usage "
                      "counters and per-customer limits owned by wecare-coupons. Deliberately "
                      "not modelled here: the discount arithmetic is Wix's and this table is "
                      "the issuance record, not part of the CRM data model.",
    "GiftCardsTable": "Provisioned by scripts/provision_gift_cards_table.py; a liability ledger "
                      "owned by wecare-gift-cards. Not modelled here because its partition key "
                      "is an HMAC of a bearer code, which has no place in a GraphQL model.",
    "ThreadOwnershipTable":
        "Provisioned 2026-10-06 by scripts/provision_thread_ownership_table.py for WhatsApp "
        "Conversation Routing. Deliberately not modelled here: it is operational routing "
        "state with a 7-day TTL, keyed on {phone_number_id}#{BSUID-or-wa_id} because one "
        "contact can hold two independent threads (the same person talks to both WABA "
        "numbers). A contact-keyed GraphQL model cannot express that, which is the reason "
        "it is a table of its own rather than attributes on Contact.",
}


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def declared_models() -> list[str]:
    """Model names from `amplify/data/resource.ts`.

    Matches the two-line shape the file uses throughout:

        ModelName: a
          .model( {
    """
    text = RESOURCE_TS.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"^  ([A-Z][A-Za-z0-9]*): a$", text, re.M)))


def expected_table(model: str) -> str:
    """Physical table name for a model, explicit map first then the default rule."""
    if model in EXPLICIT_TABLE:
        return EXPLICIT_TABLE[model]
    # Default: pluralise + Table. Only reached by models that follow it.
    plural = model if model.endswith("s") else model + "s"
    return f"{plural}Table"


def live_tables(offline: bool) -> set[str]:
    if offline:
        if not SNAPSHOT.exists():
            print(f"ERROR: --offline needs {SNAPSHOT.relative_to(ROOT)}", file=sys.stderr)
            sys.exit(2)
        data = json.loads(SNAPSHOT.read_text())
        return set(data["tables"])
    try:
        out = run(["aws", "dynamodb", "list-tables", "--output", "json",
                   "--query", "TableNames"])
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"ERROR: could not list tables ({exc}); try --offline", file=sys.stderr)
        sys.exit(2)
    return set(json.loads(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gate", action="store_true", help="exit non-zero on unexpected drift")
    ap.add_argument("--offline", action="store_true", help="use the committed table snapshot")
    ap.add_argument("--snapshot", action="store_true", help="refresh the snapshot from AWS")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    live = live_tables(offline=args.offline)

    if args.snapshot:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(
            {"note": "Refresh with scripts/check_data_model_drift.py --snapshot",
             "count": len(live), "tables": sorted(live)}, indent=2) + "\n")
        print(f"Wrote {len(live)} table names to {SNAPSHOT.relative_to(ROOT)}")

    models = declared_models()
    live_short = {t[len(TABLE_PREFIX):] for t in live if t.startswith(TABLE_PREFIX)}

    model_to_table = {m: expected_table(m) for m in models}
    declared_short = set(model_to_table.values())

    phantoms = sorted(m for m, t in model_to_table.items() if t not in live_short)
    undeclared = sorted(live_short - declared_short)

    unexpected_phantoms = [m for m in phantoms if m not in PHANTOM_ALLOWED]
    unexpected_undeclared = [t for t in undeclared if t not in UNDECLARED_ALLOWED]

    report = {
        "appsync_apis": 0,
        "declared_models": len(models),
        "live_tables": len(live_short),
        "phantom_models": phantoms,
        "phantom_models_unexpected": unexpected_phantoms,
        "undeclared_tables": undeclared,
        "undeclared_tables_unexpected": unexpected_undeclared,
    }

    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print("DECLARED DATA MODEL vs LIVE TABLES")
        print("=" * 72)
        print(f"  models declared in amplify/data/resource.ts : {len(models)}")
        print(f"  DynamoDB tables live in the account         : {len(live_short)}")
        print(f"  AppSync APIs (so models materialised)       : 0")
        print()
        print(f"PHANTOM MODELS - declared, no table ({len(phantoms)})")
        for m in phantoms:
            mark = "ok " if m in PHANTOM_ALLOWED else "!! "
            print(f"  {mark}{m:26s} -> {model_to_table[m]}")
            if m in PHANTOM_ALLOWED:
                print(f"       {PHANTOM_ALLOWED[m]}")
        if not phantoms:
            print("  (none)")
        print()
        print(f"UNDECLARED TABLES - live, no model ({len(undeclared)})")
        for t in undeclared:
            mark = "ok " if t in UNDECLARED_ALLOWED else "!! "
            print(f"  {mark}{t}")
        if not undeclared:
            print("  (none)")
        print()
        print("Table names in code vs the account is a separate question - see "
              "scripts/audit_data_model_drift.py --gate")

    if args.gate:
        problems = []
        if unexpected_phantoms:
            problems.append(f"{len(unexpected_phantoms)} unexpected phantom model(s): "
                            + ", ".join(unexpected_phantoms))
        if unexpected_undeclared:
            problems.append(f"{len(unexpected_undeclared)} undeclared live table(s): "
                            + ", ".join(unexpected_undeclared))
        if problems:
            print("\nGATE FAILED", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            print("\nEither create/retire the resource, or record the decision in "
                  "PHANTOM_ALLOWED / UNDECLARED_ALLOWED in this script with its reason.",
                  file=sys.stderr)
            return 1
        print("\nGATE PASSED - the declared model and the live tables agree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
