#!/usr/bin/env python3
"""Verify the WhatsApp / Plivo call paths against a REAL call you place yourself.

An agent cannot place a WhatsApp call. So this does the two halves that can be
automated: it reports whether the preconditions are right BEFORE you dial, then
watches CloudWatch for the exact event chain AFTER you dial and tells you which
legs fired.

    python scripts/test_call_paths.py preflight
    python scripts/test_call_paths.py watch            # then place the call
    python scripts/test_call_paths.py watch --minutes 15
    python scripts/test_call_paths.py watch --json

Nothing here sends a message, places a call, or changes configuration. It is
read-only: GetFunctionConfiguration, GetAlias, DescribeSecret (never
GetSecretValue) and FilterLogEvents.

THE TWO LEGS, which are independent
-----------------------------------
A real inbound WhatsApp call to +91 93309 94400 drives two separate paths:

  1. WEBHOOK leg  -> Meta posts call events to POST /whatsapp
                     (wecare-whatsapp-calling). On DISCONNECT this is what
                     sends the follow-up SMS (AWS End User Messaging) and the
                     Sinch RCS notification.
  2. MEDIA leg    -> Meta opens a SIP leg to calling.sip.servers[0], which
                     today is sip.wecare.digital (the Lightsail Asterisk box),
                     NOT Plivo. If and when it is repointed at Plivo, Plivo
                     fetches XML from POST /plivo/answer
                     (wecare-plivo-answer), and on the hangup pass that
                     function sends its own post-call SMS.

Leg 1 works today. Leg 2 reaching Plivo is what is unproven: every
`plivo_answer` event so far has an empty `sipHeaders`, which is the signature of
a synthetic test rather than a real SIP call.

DUPLICATE SMS WARNING
---------------------
Both legs can send a post-call SMS on the same call, from different functions:

  wecare-whatsapp-calling  _send_disconnect_sms   -> AWS End User Messaging, ivr-default DLT
  wecare-plivo-answer      _send_post_call_sms    -> wecare-sms-aws, ivr-default

POST_CALL_SMS_ENABLED is currently true on plivo-answer. If you repoint Meta at
Plivo while the webhook leg also sends, one call produces TWO SMS to the same
customer under the same DLT template. Decide which leg owns that message before
the repoint. `preflight` flags this.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import time
from typing import Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
TEST_NUMBER = "+91 93309 94400"
PHONE_ID = "1016149501586345"

OK = "PASS"
NO = "FAIL"
WARN = "WARN"
INFO = "INFO"


def _lam():
    return boto3.client("lambda", region_name=REGION)


def _logs():
    return boto3.client("logs", region_name=REGION)


def _line(status: str, label: str, detail: str = "") -> None:
    print(f"  [{status:4s}] {label}" + (f"\n         {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #

def preflight() -> int:
    lam = _lam()
    problems = 0

    print(f"\nPREFLIGHT  account 775261844268 / {REGION}   test number {TEST_NUMBER}\n")

    # --- where is Meta sending the media leg? -------------------------------
    print("Media leg target (Meta calling settings)")
    try:
        payload = {
            "requestContext": {"http": {"method": "GET", "path": "/wa-business/calling-settings"}},
            "httpMethod": "GET", "path": "/wa-business/calling-settings",
            "headers": {"origin": "https://wecare.digital"},
            "queryStringParameters": {"phoneId": PHONE_ID},
        }
        raw = lam.invoke(FunctionName="wecare-whatsapp-business-api:live",
                         Payload=json.dumps(payload).encode())["Payload"].read().decode()
        body = json.loads(json.loads(raw)["body"])
        calling = (body.get("settings") or {}).get("calling") or {}
        sip = calling.get("sip") or {}
        servers = sip.get("servers") or []
        host = servers[0].get("hostname") if servers else None
        port = servers[0].get("port") if servers else None
        _line(INFO, f"calling={calling.get('status')}  sip={sip.get('status')}  "
                    f"srtp={calling.get('srtp_key_exchange_protocol')}")
        if host and "plivo" in str(host).lower():
            _line(OK, f"SIP target is Plivo: {host}:{port}",
                  "a real call SHOULD now reach wecare-plivo-answer")
        elif host:
            _line(WARN, f"SIP target is {host}:{port}, NOT Plivo",
                  "the media leg goes to the Lightsail Asterisk box. A real call will "
                  "NOT reach Plivo until calling.sip.servers[0] is repointed.")
        else:
            _line(NO, "no SIP server configured")
            problems += 1
        # the redaction fix should be live
        if servers and "sip_user_password" in servers[0]:
            _line(NO, "the API is still returning sip_user_password",
                  "deploy the redaction fix in wecare-whatsapp-business-api")
            problems += 1
        elif servers and servers[0].get("sip_user_password_set") is not None:
            _line(OK, "SIP password is redacted in the API response")
    except Exception as exc:  # noqa: BLE001
        _line(NO, f"could not read calling settings: {exc}")
        problems += 1

    # --- alias + flag state on each function ---------------------------------
    print("\nFunction state")
    expectations = {
        "wecare-whatsapp-calling": {"SINCH_RCS_ENABLED": "true", "AUTO_PICKUP_ENABLED": "true"},
        "wecare-plivo-answer": {"POST_CALL_SMS_ENABLED": "true"},
        "wecare-sms-aws": {},
        "wecare-rcs-send": {},
    }
    for name, want in expectations.items():
        try:
            cfg = lam.get_function_configuration(FunctionName=name)
            env = (cfg.get("Environment") or {}).get("Variables", {})
            try:
                alias = lam.get_alias(FunctionName=name, Name="live")["FunctionVersion"]
                ver = lam.get_function_configuration(FunctionName=f"{name}:{alias}")
                current = ver.get("CodeSha256") == cfg.get("CodeSha256")
                _line(OK if current else WARN,
                      f"{name}  live=v{alias}"
                      + ("" if current else "  ALIAS IS BEHIND $LATEST — republish"))
                if not current:
                    problems += 1
            except ClientError:
                _line(INFO, f"{name}  no live alias (invoked unqualified)")
            for key, expected in want.items():
                actual = env.get(key)
                _line(OK if actual == expected else WARN,
                      f"    {key}={actual}  (expected {expected})")
        except ClientError as exc:
            _line(NO, f"{name}: {exc}")
            problems += 1

    # --- the /plivo/answer token gate ---------------------------------------
    print("\n/plivo/answer authentication")
    sm = boto3.client("secretsmanager", region_name=REGION)
    token_secret = False
    try:
        sm.describe_secret(SecretId="wecare/plivo-answer")   # never GetSecretValue
        token_secret = True
    except ClientError:
        pass
    env = (_lam().get_function_configuration(FunctionName="wecare-plivo-answer")
           .get("Environment") or {}).get("Variables", {})
    if token_secret or "PLIVO_ANSWER_TOKEN" in env:
        _line(OK, "a token is configured — the gate is ARMED",
              "every Plivo URL must carry ?token=<value> or calls get 403")
    else:
        _line(WARN, "no token in wecare/plivo-answer and none in env — gate is OPEN",
              "POST /plivo/answer is AuthorizationType=NONE, and an unauthenticated "
              "CallStatus=completed can trigger an SMS. Run:  "
              "python scripts/store_provider_secret.py plivo-answer --generate")

    # --- duplicate SMS risk --------------------------------------------------
    print("\nDuplicate post-call SMS risk")
    plivo_sms = env.get("POST_CALL_SMS_ENABLED", "true").lower() == "true"
    wa_env = (_lam().get_function_configuration(FunctionName="wecare-whatsapp-calling")
              .get("Environment") or {}).get("Variables", {})
    rcs_on = wa_env.get("SINCH_RCS_ENABLED", "false").lower() == "true"
    if plivo_sms:
        _line(WARN, "plivo-answer POST_CALL_SMS_ENABLED=true",
              "if the media leg is repointed at Plivo while wecare-whatsapp-calling "
              "also sends its disconnect SMS, one call sends TWO messages under the "
              "same ivr-default DLT template. Pick one owner.")
    if rcs_on:
        _line(INFO, "SINCH_RCS_ENABLED=true — RCS fires on call DISCONNECT, not connect",
              "wecare-whatsapp-calling -> lambda_utils.sinch_rcs.send_rcs_ivr_notification")

    print(f"\n{'preflight clean' if problems == 0 else str(problems) + ' blocking problem(s)'}\n")
    print("Now place a real WhatsApp call to " + TEST_NUMBER + ", let it play and hang up,")
    print("then run:  python scripts/test_call_paths.py watch\n")
    return 1 if problems else 0


# --------------------------------------------------------------------------- #
# watch
# --------------------------------------------------------------------------- #

CHECKS = [
    # (leg, label, log group, filter pattern, what it proves)
    ("webhook", "Meta call webhook received",
     "/aws/lambda/wecare-whatsapp-calling", "calls",
     "Meta is delivering call events to POST /whatsapp"),
    ("webhook", "RCS notification attempted (on disconnect)",
     "/aws/lambda/wecare-whatsapp-calling", "wa_call_rcs_notification",
     "the Sinch RCS leg ran; check rcs_sent=true inside the event"),
    ("webhook", "Disconnect SMS attempted",
     "/aws/lambda/wecare-whatsapp-calling", "disconnect_sms",
     "the webhook-leg SMS ran"),
    ("media", "Plivo fetched the IVR XML",
     "/aws/lambda/wecare-plivo-answer", "plivo_answer",
     "Plivo hit the answer URL"),
    ("media", "Plivo post-call SMS queued",
     "/aws/lambda/wecare-plivo-answer", "plivo_post_call_sms_queued",
     "the media-leg SMS was handed to wecare-sms-aws"),
    ("media", "Plivo post-call SMS FAILED",
     "/aws/lambda/wecare-plivo-answer", "plivo_post_call_sms_failed",
     "the media-leg SMS raised; read the error field"),
    ("media", "request refused by the token gate",
     "/aws/lambda/wecare-plivo-answer", "plivo_answer_rejected",
     "a Plivo URL is missing ?token= — add it in the Plivo console"),
    ("sms", "SMS provider invoked",
     "/aws/lambda/wecare-sms-aws", "sms",
     "wecare-sms-aws actually ran"),
    ("rcs", "RCS send path ran",
     "/aws/lambda/wecare-rcs-send", "rcs",
     "wecare-rcs-send was invoked"),
]


def watch(minutes: int, as_json: bool) -> int:
    logs = _logs()
    now = int(time.time() * 1000)
    since = now - minutes * 60 * 1000
    results: List[dict] = []

    for leg, label, group, pattern, meaning in CHECKS:
        entry = {"leg": leg, "check": label, "logGroup": group, "pattern": pattern,
                 "meaning": meaning, "count": 0, "samples": []}
        try:
            response = logs.filter_log_events(
                logGroupName=group, startTime=since, endTime=now,
                filterPattern=pattern, limit=25)
            events = response.get("events", [])
            entry["count"] = len(events)
            entry["samples"] = [e["message"].strip()[:400] for e in events[:3]]
        except logs.exceptions.ResourceNotFoundException:
            entry["error"] = "log group does not exist"
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)[:160]
        results.append(entry)

    # The decisive signal: a REAL SIP call carries SIP headers. Synthetic tests do not.
    real_sip = False
    for entry in results:
        if entry["pattern"] == "plivo_answer":
            for sample in entry["samples"]:
                try:
                    start = sample.index("{")
                    payload = json.loads(sample[start:])
                    if str(payload.get("sipHeaders") or "").strip():
                        real_sip = True
                except (ValueError, json.JSONDecodeError):
                    continue

    if as_json:
        print(json.dumps({"windowMinutes": minutes, "realSipCallSeen": real_sip,
                          "checks": results}, indent=2))
        return 0

    print(f"\nWATCH  last {minutes} min   {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
    current_leg = None
    for entry in results:
        if entry["leg"] != current_leg:
            current_leg = entry["leg"]
            print(f"{current_leg.upper()} leg")
        if entry.get("error"):
            _line(INFO, f"{entry['check']}: {entry['error']}")
            continue
        failure_check = "FAILED" in entry["check"] or "refused" in entry["check"]
        if entry["count"]:
            _line(NO if failure_check else OK,
                  f"{entry['check']}  ({entry['count']} event(s))", entry["meaning"])
            for sample in entry["samples"]:
                print(f"           {sample[:200]}")
        else:
            _line(INFO if failure_check else WARN, f"{entry['check']}  (nothing)",
                  "" if failure_check else entry["meaning"])

    print("\nVERDICT")
    if real_sip:
        _line(OK, "a plivo_answer event carried SIP headers",
              "this is a REAL SIP call reaching Plivo. The media leg works.")
    else:
        _line(WARN, "no plivo_answer event carried SIP headers",
              "either the call did not reach Plivo (Meta still points at "
              "sip.wecare.digital), or only synthetic requests arrived. Do NOT "
              "delete the Lightsail instance on this result.")
    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["preflight", "watch"])
    parser.add_argument("--minutes", type=int, default=10,
                        help="how far back to look in watch mode (default 10)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()
    return preflight() if args.mode == "preflight" else watch(args.minutes, args.json)


if __name__ == "__main__":
    sys.exit(main())
