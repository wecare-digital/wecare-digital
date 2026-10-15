#!/usr/bin/env python3
"""Prove AWS End User Messaging can actually send.

AWS End User Messaging is the only SMS provider, for Indian (DLT) and international
destinations alike, so "the sender id looks registered" is not evidence that a send
works. This exercises the real code path through lambda_utils.comms against the real
account.

DEFAULT IS DRY RUN. `DryRun=True` makes AWS validate the origination identity,
the DLT parameters and the destination, and return a MessageId, WITHOUT
delivering anything and without spending. That is the only safe way to verify an
India A2P path, because a real send to an unregistered template is a DLT
compliance event, not just a failed message.

    python scripts/aws_sms_check.py                          # dry run, both routes
    python scripts/aws_sms_check.py --india-only
    python scripts/aws_sms_check.py --intl-only
    python scripts/aws_sms_check.py --to +919903300044       # override destination
    python scripts/aws_sms_check.py --live --to +91...       # ACTUALLY SEND
    python scripts/aws_sms_check.py --json

--live really delivers and really spends. It requires an explicit --to so nobody
can trigger a real send by accepting a default. Both regions bill against a
$200/month TEXT ceiling that cannot be raised without an AWS quota request.

Never prints a credential. Phone numbers are truncated to the last 4 digits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 required: use .venv/bin/python")

from lambda_utils.comms import dlt as dlt_mod          # noqa: E402
from lambda_utils.comms import numbers                  # noqa: E402
from lambda_utils.comms import region as region_mod     # noqa: E402
from lambda_utils.comms import sms as sms_mod           # noqa: E402

ACCOUNT = "775261844268"

# Defaults exist only for dry runs. --live refuses to use them.
DEFAULT_INDIA = "+919903300044"
DEFAULT_INTL = "+14255551234"

OK, NO, WARN, INFO = "PASS", "FAIL", "WARN", "INFO"


def line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status:4s}] {label}" + (f"\n         {detail}" if detail else ""))


def account_state(region: str) -> dict:
    """Read the region's sending capability. No secrets involved."""
    c = boto3.client("pinpoint-sms-voice-v2", region_name=region)
    out: dict = {"region": region}
    try:
        out["senderIds"] = [
            {"senderId": s["SenderId"], "country": s.get("IsoCountryCode"),
             "registered": s.get("Registered")}
            for s in c.describe_sender_ids().get("SenderIds", [])
        ]
    except Exception as exc:  # noqa: BLE001
        out["senderIds"] = f"error: {type(exc).__name__}"
    try:
        out["phoneNumbers"] = [
            {"number": p["PhoneNumber"], "type": p.get("NumberType"),
             "status": p.get("Status"),
             "intl": p.get("InternationalSendingEnabled")}
            for p in c.describe_phone_numbers().get("PhoneNumbers", [])
        ]
    except Exception as exc:  # noqa: BLE001
        out["phoneNumbers"] = f"error: {type(exc).__name__}"
    try:
        out["spendLimits"] = {
            s["Name"]: {"enforced": s.get("EnforcedLimit"), "max": s.get("MaxLimit")}
            for s in c.describe_spend_limits().get("SpendLimits", [])
        }
    except Exception as exc:  # noqa: BLE001
        out["spendLimits"] = f"error: {type(exc).__name__}"
    return out


def report_state(state: dict) -> int:
    problems = 0
    region = state["region"]
    print(f"\nAccount state — {region}")

    sids = state.get("senderIds")
    if isinstance(sids, list):
        registered = [s for s in sids if s.get("registered")]
        if region == region_mod.INDIA_REGION:
            wd = [s for s in registered if s["senderId"] == dlt_mod.SENDER_ID]
            if wd:
                line(OK, f"sender id {dlt_mod.SENDER_ID} registered "
                         f"({wd[0]['country']})")
            else:
                line(NO, f"sender id {dlt_mod.SENDER_ID} is NOT registered here",
                     "Indian A2P cannot be DLT compliant without it")
                problems += 1
        elif sids:
            line(INFO, f"{len(sids)} sender id(s) present")
    else:
        line(WARN, f"sender ids unreadable: {sids}")

    nums = state.get("phoneNumbers")
    if isinstance(nums, list):
        sims = [n for n in nums if n.get("type") == "SIMULATOR"]
        intl = [n for n in nums if n.get("intl")]
        if region != region_mod.INDIA_REGION:
            if any(n["number"] == sms_mod.ORIGINATION_IDENTITY for n in intl):
                line(OK, f"origination identity {sms_mod.ORIGINATION_IDENTITY} "
                         "present with international sending enabled")
            else:
                line(NO, f"{sms_mod.ORIGINATION_IDENTITY} not found as an "
                         "international-capable number here")
                problems += 1
        if sims:
            line(WARN, f"{len(sims)} SIMULATOR number(s) in this region",
                 "a simulator accepts a send and returns a MessageId without "
                 "delivering. This is why OriginationIdentity must stay pinned "
                 "rather than relying on pool selection.")
        if region == region_mod.INDIA_REGION and not nums:
            line(OK, "no phone numbers, as expected — India sends by sender id")
    else:
        line(WARN, f"phone numbers unreadable: {nums}")

    limits = state.get("spendLimits")
    if isinstance(limits, dict):
        text = limits.get("TEXT_MESSAGE_MONTHLY_SPEND_LIMIT", {})
        line(INFO, f"TEXT monthly spend limit {text.get('enforced')} "
                   f"(max {text.get('max')})",
             "max == enforced means it cannot be raised without an AWS quota request"
             if text.get("enforced") == text.get("max") else "")
        rcs = limits.get("RCS_MESSAGE_MONTHLY_SPEND_LIMIT", {})
        if rcs and float(rcs.get("enforced") or 0) <= 1:
            line(WARN, f"RCS monthly spend limit is {rcs.get('enforced')} "
                       f"(max {rcs.get('max')})",
                 "AWS RCS is not usable at this limit — see Stage 5")
    return problems


def attempt(destination: str, *, template_key: str, live: bool, label: str) -> dict:
    """One send through the real provider. Dry run unless live."""
    e164 = numbers.to_e164(destination)
    route = region_mod.resolve(e164)
    svc = sms_mod.AwsSmsProvider()

    body = ("WECARE.DIGITAL AWS End User Messaging verification. "
            "No action required.")
    if route.is_india:
        # An Indian send must carry approved content. Reuse the approved
        # ivr-default body verbatim rather than inventing copy that would not
        # match the registered template.
        body = (
            "Thanks for contacting WECARE.DIGITAL!\n\n"
            "Submit your request here: https://wecare.digital/submit-request/ "
            "or send us a message / voice note on WhatsApp: "
            "https://wecare.digital/r/wa.\n\n"
            "We'll review it and follow up if needed."
        )

    result = svc.send_sms(e164, body, dlt_template_key=template_key,
                         dry_run=not live)
    out = result.as_dict()
    out["label"] = label
    out["destinationLast4"] = numbers.last4(e164)
    out["live"] = live
    return out


def report_attempt(res: dict) -> int:
    label = res["label"]
    print(f"\n{label}")
    mode = "LIVE SEND" if res["live"] else "dry run"
    route = res.get("route") or {}
    line(INFO, f"{mode} -> region {route.get('region')}  "
               f"requiresDlt={route.get('requiresDlt')}  "
               f"dest ...{res['destinationLast4']}")
    d = res.get("dlt") or {}
    if d.get("templateId"):
        line(INFO, f"DLT entity {d.get('entityId')} template "
                   f"{d.get('templateId')} ({d.get('templateKey')}, "
                   f"source {d.get('source')})")
    if res["success"]:
        line(OK, f"accepted by AWS  providerMessageId={res.get('providerMessageId')}",
             "dry run: validated and NOT delivered" if not res["live"] else
             "delivered for real")
        return 0
    line(NO, f"{res.get('errorCode')}: {res.get('error')}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", help="destination in E.164, e.g. +919903300044")
    ap.add_argument("--india-only", action="store_true")
    ap.add_argument("--intl-only", action="store_true")
    ap.add_argument("--template", default="ivr-default",
                    help="DLT template key for Indian destinations")
    ap.add_argument("--live", action="store_true",
                    help="ACTUALLY SEND. Requires --to. Delivers and spends.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.live and not args.to:
        sys.exit("--live requires an explicit --to. Refusing to deliver to a default.")

    ident = boto3.client("sts").get_caller_identity()
    if ident["Account"] != ACCOUNT:
        sys.exit(f"wrong account {ident['Account']}, expected {ACCOUNT}")

    problems = 0
    results = []
    states = []

    want_india = not args.intl_only
    want_intl = not args.india_only
    if args.to:
        # A single explicit destination decides its own route.
        if numbers.is_india(numbers.to_e164(args.to)):
            want_india, want_intl = True, False
        else:
            want_india, want_intl = False, True

    if not args.json:
        print(f"\nAWS END USER MESSAGING CHECK   account {ident['Account']}")
        print(f"  mode: {'LIVE SEND' if args.live else 'DRY RUN (nothing delivered)'}")

    regions = []
    if want_india:
        regions.append(region_mod.INDIA_REGION)
    if want_intl:
        regions.append(region_mod.DEFAULT_REGION)
    for r in regions:
        st = account_state(r)
        states.append(st)
        if not args.json:
            problems += report_state(st)

    if want_india:
        res = attempt(args.to or DEFAULT_INDIA, template_key=args.template,
                      live=args.live, label="India route (ap-south-1 + DLT)")
        results.append(res)
        if not args.json:
            problems += report_attempt(res)

    if want_intl:
        res = attempt(args.to or DEFAULT_INTL, template_key="",
                      live=args.live, label="International route (us-east-1)")
        results.append(res)
        if not args.json:
            problems += report_attempt(res)

    if args.json:
        print(json.dumps({"account": ident["Account"], "live": args.live,
                          "states": states, "attempts": results}, indent=2,
                         default=str))
        return 0 if all(r["success"] for r in results) else 1

    print()
    if problems:
        print(f"{problems} problem(s). Do NOT rely on SMS delivery until these clear.\n")
        return 1
    print("AWS End User Messaging is ready for both routes.")
    if not args.live:
        print("This was a DRY RUN: AWS validated identity, DLT and destination")
        print("without delivering. Do one --live send to a number you control")
        print("to prove delivery end to end.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
