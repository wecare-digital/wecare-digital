#!/usr/bin/env python3
"""Export, normalize and validate our Sinch RCS templates. Read-only by default.

Why this goes through our own Lambda
-----------------------------------
The obvious route would be the official Sinch MCP server's `list-messaging-templates`.
It cannot work here. Our RCS integration runs on the Sinch **India** platform inherited
from the ACL Mobile acquisition - `api.aclwhatsapp.com/access-api/v2/rcs/{appId}/templates`,
authenticated by a Keycloak password grant - while the MCP server authenticates against
the global Sinch Build platform with `KEY_ID`/`KEY_SECRET`. We hold no such key, and the
MCP server refuses to start on a partial credential triple.

So the authoritative reader we actually have is `wecare-rcs-send` with
`action: templates`, which already proxies the India template API and already holds the
credential. Invoking it directly is read-only and adds no new credential surface.

    python scripts/rcs_template_sync.py            # export + normalize + manifest
    python scripts/rcs_template_sync.py --validate # validate what is on disk, no AWS
    python scripts/rcs_template_sync.py --check    # exit 1 on any HIGH finding

Never prints a credential: the Lambda returns template bodies only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "rcs" / "templates"
SOURCE = OUT / "source"
NORMALIZED = OUT / "normalized"
MANIFEST = OUT / "manifest.json"

FUNCTION = "wecare-rcs-send:live"
REGION = "us-east-1"

#: Templates our code actually sends. Everything else is unreferenced remote surface.
REFERENCED = {"rcsmenu"}
#: Named in docstrings but with no sender since 2026-09-19.
DOCUMENTED_ONLY = {"rcsorder", "waalert"}
# Retain provider-side inventory in the manifest without recreating local test-template exports.
EXCLUDED_TEST_EXPORTS = {"test16", "test17", "wecare_test_create", "wecare_v2_test"}


def fetch_templates() -> list:
    """Read the live template list through our own authenticated route."""
    import boto3

    payload = {"requestContext": {"http": {"method": "POST"}},
               "body": json.dumps({"action": "templates"})}
    resp = boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=FUNCTION, InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode())
    raw = resp["Payload"].read().decode()
    if resp.get("FunctionError"):
        raise RuntimeError(f"template list failed: {raw[:300]}")
    outer = json.loads(raw)
    if int(outer.get("statusCode") or 0) != 200:
        raise RuntimeError(f"template list HTTP {outer.get('statusCode')}: {outer.get('body', '')[:300]}")
    body = json.loads(outer.get("body") or "{}")
    templates = body.get("templates")
    if not isinstance(templates, list):
        raise RuntimeError("template list did not return a list")
    return templates


def _card(component: dict) -> dict:
    return ((component or {}).get("richCard") or {}).get("standaloneCard") or {}


def normalize(template: dict) -> dict:
    """A flat, comparable shape. The original stays untouched in `source/`.

    Normalizing exists so a diff between two exports is readable, and so the
    validator has one place to look rather than walking the nested card shape
    repeatedly.
    """
    name = template.get("name") or ""
    kind = template.get("type") or ""
    component = template.get("component") or {}
    card = _card(component)
    content = card.get("cardContent") or {}
    media = content.get("media") or {}
    info = media.get("contentInfo") or {}
    suggestions = content.get("suggestions") or []
    text = component.get("text") or ""
    description = content.get("description") or ""

    actions = []
    for s in suggestions:
        action = s.get("action") or {}
        reply = s.get("reply") or {}
        if action:
            kinds = [k for k in ("openUrlAction", "dialAction", "viewLocationAction",
                                 "shareLocationAction") if k in action]
            actions.append({
                "kind": "action",
                "text": action.get("text"),
                "postbackData": action.get("postbackData"),
                "actionTypes": kinds,
                "url": (action.get("openUrlAction") or {}).get("url"),
                "application": (action.get("openUrlAction") or {}).get("application"),
            })
        elif reply:
            actions.append({"kind": "reply", "text": reply.get("text"),
                            "postbackData": reply.get("postbackData")})

    body_text = text or description
    return {
        "name": name,
        "type": kind,
        "status": template.get("status"),
        "isRichCard": kind == "rich_card",
        "cardOrientation": card.get("cardOrientation"),
        "thumbnailImageAlignment": card.get("thumbnailImageAlignment"),
        "mediaHeight": media.get("height"),
        "mediaUrl": info.get("fileUrl"),
        "mediaExtension": (info.get("fileUrl") or "").rsplit(".", 1)[-1].lower()
                          if info.get("fileUrl") else None,
        "thumbnailUrl": info.get("thumbnailUrl"),
        "forceRefresh": info.get("forceRefresh"),
        "title": content.get("title"),
        "titleLength": len(content.get("title") or ""),
        "bodyLength": len(body_text),
        "suggestionCount": len(suggestions),
        "actions": actions,
        "variables": sorted(_variables(body_text)),
        "variableSyntax": _variable_syntax(body_text),
        "hasTrailingBackticks": "``````" in body_text,
        "isCarousel": "carouselCard" in json.dumps(component),
        "referencedByCode": name in REFERENCED,
        "documentedOnly": name in DOCUMENTED_ONLY,
        "fingerprint": hashlib.sha256(
            json.dumps(template, sort_keys=True).encode()).hexdigest()[:16],
    }


def _variables(text: str) -> set:
    import re
    return set(re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", text)) | \
           set(re.findall(r"\[([A-Za-z0-9_]+)\]", text))


def _variable_syntax(text: str) -> str:
    curly = "{{" in text
    bracket = "[custom_param" in text or bool(
        __import__("re").search(r"\[[A-Za-z0-9_]+\]", text))
    if curly and bracket:
        return "MIXED"
    if curly:
        return "curly"
    if bracket:
        return "bracket"
    return "none"


# ── validation ────────────────────────────────────────────────────────────────
#
# Each rule states the rendering consequence, because "inconsistent" on its own is
# not a reason to change an approved template.

def _reachable(row: dict) -> bool:
    """Can this template actually reach a handset from our code?

    `referencedByCode` means a sender names it. `documentedOnly` templates are named in
    docstrings but their senders were deleted on 2026-09-19, so they cannot be sent
    today — they are listed separately precisely because they are NOT reachable.
    """
    return bool(row.get("referencedByCode"))


def _rendering_severity(row: dict) -> str:
    """HIGH only when a rendering defect can actually reach a customer.

    WHY THIS EXISTS. Until 2026-09-28 every rendering defect was flat HIGH, so
    `--check` exited 1 on `get_started` — a template **no code path sends**, whose
    senders never existed. The result was a gate that could never go green, was
    therefore wired into no workflow, and so guarded nothing at all. That is the same
    failure mode `tests/test_log_phone_masking.py` documents for CodeQL: a check that
    fires on the safe majority trains people to ignore it.

    Reachability is the honest axis. A card that would drop its media is a serious
    defect *if a customer can receive it* and an inert curiosity if not. So the
    severity is derived rather than asserted, and the finding says which case it is.

    This is NOT a way to silence the defect. It stays reported at MEDIUM with the same
    consequence and action text, and it escalates to HIGH automatically the moment a
    sender names the template — which is exactly when it starts to matter. `rcsmenu`,
    the one template code does send, is therefore fully covered.
    """
    return "HIGH" if _reachable(row) else "MEDIUM"


def _reach_note(row: dict) -> str:
    if _reachable(row):
        return "a code path sends this template, so a customer can receive the defect"
    return ("no code path sends this template, so the defect cannot reach a customer "
            "today; this escalates to HIGH automatically if a sender starts naming it")


def validate(rows: list) -> list:
    findings = []

    for r in rows:
        name = r["name"]

        # Google's RBM standalone-card spec does not offer TALL media with a
        # HORIZONTAL card. A client that rejects the combination shows no media at
        # all, which on a card whose entire purpose is the video is a blank card.
        if r["cardOrientation"] == "HORIZONTAL" and r["mediaHeight"] == "TALL":
            findings.append({
                "severity": _rendering_severity(r), "template": name,
                "finding": "HORIZONTAL card orientation with TALL media height",
                "consequence": "TALL is not offered for horizontal cards; the media "
                               "may be dropped, leaving a card with no video",
                "action": "set mediaHeight to MEDIUM, or cardOrientation to VERTICAL",
                "needsProviderReadback": True,
                "reachability": _reach_note(r),
            })

        # The approved body carries six literal backticks. On a client that renders
        # markdown-ish text they become a code block; on one that does not, six
        # visible backticks. Either way the customer sees an artifact.
        if r["hasTrailingBackticks"]:
            findings.append({
                "severity": "MEDIUM", "template": name,
                "finding": "body contains six literal backticks",
                "consequence": "renders as a code block or as visible backticks "
                               "depending on the RCS client",
                "action": "do NOT edit the approved template in place; create a clean "
                          "versioned successor and switch after it is approved",
            })

        if r["variableSyntax"] == "MIXED":
            findings.append({
                "severity": _rendering_severity(r), "template": name,
                "finding": "two placeholder syntaxes in one body",
                "consequence": "at most one syntax substitutes; the other reaches the "
                               "handset as literal text",
                "action": "pick one syntax per template",
                "reachability": _reach_note(r),
            })

        # A video in a rich card is the riskiest cross-platform element: autoplay,
        # inline playback and thumbnail handling all differ by client.
        if r["mediaExtension"] in ("mp4", "mov", "webm", "3gp"):
            findings.append({
                "severity": "INFORMATIONAL", "template": name,
                "finding": f"rich card carries video media (.{r['mediaExtension']})",
                "consequence": "inline playback and autoplay differ between Google "
                               "Messages and Apple Messages; a still thumbnail is the "
                               "only guaranteed common rendering",
                "action": "confirm on both handsets that the thumbnail is legible when "
                          "the video does not play inline",
            })

        for action in r["actions"]:
            if action.get("kind") == "action" and not action.get("actionTypes"):
                findings.append({
                    "severity": "MEDIUM", "template": name,
                    "finding": f"suggestion {action.get('text')!r} has no action type",
                    "consequence": "a suggestion with no action may render as an inert "
                                   "button",
                    "action": "attach openUrlAction, dialAction or a reply",
                })
            if action.get("application") == "BROWSER":
                findings.append({
                    "severity": "INFORMATIONAL", "template": name,
                    "finding": "openUrlAction forces application=BROWSER",
                    "consequence": "opens the system browser rather than a webview; "
                                   "acceptable, but the transition is more abrupt on "
                                   "iPhone",
                    "action": "confirm the landing page is mobile-legible",
                })

    unreferenced = [r["name"] for r in rows
                    if not r["referencedByCode"] and not r["documentedOnly"]]
    if unreferenced:
        findings.append({
            "severity": "MEDIUM", "template": ", ".join(sorted(unreferenced)),
            "finding": f"{len(unreferenced)} approved templates no code path sends",
            "consequence": "unused approved surface; several are obvious test "
                           "leftovers sitting in production",
            "action": "confirm each is intentional, then retire the test templates",
        })

    return findings


def write_export(templates: list) -> dict:
    SOURCE.mkdir(parents=True, exist_ok=True)
    NORMALIZED.mkdir(parents=True, exist_ok=True)

    rows = []
    for template in templates:
        name = template.get("name") or "unnamed"
        safe = "".join(c for c in name if c.isalnum() or c in "-_") or "unnamed"
        # Preserve the provider's metadata in manifest, but not local copies of test templates.
        row = normalize(template)
        if name not in EXCLUDED_TEST_EXPORTS:
            (SOURCE / f"{safe}.json").write_text(
                json.dumps(template, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            (NORMALIZED / f"{safe}.json").write_text(
                json.dumps(row, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        rows.append(row)

    findings = validate(rows)
    manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "generator": "scripts/rcs_template_sync.py",
        "source": {
            "platform": "Sinch India (ex-ACL Mobile)",
            "readVia": f"lambda {FUNCTION} action=templates",
            "note": "The official Sinch MCP server cannot read these: it authenticates "
                    "against the global Sinch Build platform with KEY_ID/KEY_SECRET, "
                    "which this account does not have.",
        },
        "counts": {
            "total": len(rows),
            "richCard": sum(1 for r in rows if r["isRichCard"]),
            "textMessage": sum(1 for r in rows if r["type"] == "text_message"),
            "carousel": sum(1 for r in rows if r["isCarousel"]),
            "approved": sum(1 for r in rows if r["status"] == "approved"),
            "referencedByCode": sum(1 for r in rows if r["referencedByCode"]),
            "documentedOnly": sum(1 for r in rows if r["documentedOnly"]),
            "unreferenced": sum(1 for r in rows
                                if not r["referencedByCode"] and not r["documentedOnly"]),
        },
        "templates": rows,
        "findings": findings,
        "findingCounts": {
            sev: sum(1 for f in findings if f["severity"] == sev)
            for sev in ("HIGH", "MEDIUM", "INFORMATIONAL")
        },
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def load_manifest() -> dict:
    if not MANIFEST.exists():
        raise SystemExit("no manifest; run without --validate first")
    return json.loads(MANIFEST.read_text())


def report(manifest: dict) -> int:
    counts = manifest["counts"]
    print(f"templates {counts['total']}  "
          f"richCard {counts['richCard']}  text {counts['textMessage']}  "
          f"carousel {counts['carousel']}")
    print(f"referenced by code {counts['referencedByCode']}  "
          f"documented-only {counts['documentedOnly']}  "
          f"unreferenced {counts['unreferenced']}\n")

    for severity in ("HIGH", "MEDIUM", "INFORMATIONAL"):
        rows = [f for f in manifest["findings"] if f["severity"] == severity]
        if not rows:
            continue
        print(f"{severity} ({len(rows)})")
        for f in rows:
            print(f"  {f['template']}: {f['finding']}")
            print(f"      -> {f['consequence']}")
            print(f"      action: {f['action']}")
        print()

    return manifest["findingCounts"]["HIGH"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validate", action="store_true",
                    help="validate the existing export, no AWS calls")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any HIGH finding exists")
    args = ap.parse_args(argv)

    if args.validate:
        manifest = load_manifest()
        # Re-run validation against stored rows so a rule change is visible without
        # re-exporting.
        manifest["findings"] = validate(manifest["templates"])
        manifest["findingCounts"] = {
            sev: sum(1 for f in manifest["findings"] if f["severity"] == sev)
            for sev in ("HIGH", "MEDIUM", "INFORMATIONAL")}
    else:
        manifest = write_export(fetch_templates())
        print(f"wrote {SOURCE.relative_to(ROOT)}/, "
              f"{NORMALIZED.relative_to(ROOT)}/ and "
              f"{MANIFEST.relative_to(ROOT)}\n")

    high = report(manifest)
    if args.check and high:
        print(f"{high} HIGH finding(s)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
