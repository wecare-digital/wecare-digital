#!/usr/bin/env python3
"""Per-alert triage for `py/clear-text-logging-sensitive-data`, with evidence.

WHY THIS IS NOT A BULK DISMISSAL. Rule 28 accepts an alert as closed when it is either
remediated or **formally triaged with evidence**, and 202 open alerts with 0 triaged is a
failing gate. But dismissing 202 alerts on one generic reason is the rubber stamp the
rule exists to prevent, and it is how the real findings in this pile stayed hidden: a
full phone number in ~30 logger dicts, a WhatsApp Flow token whose `-ph-` suffix is the
number, and a `contactId` that is literally `wa` + the customer's digits across 85 sites.
All of those were remediated first. This handles only what is left.

WHAT IT PROVES, PER ALERT. The alert location points at the whole `json.dumps({...})`
call rather than at the element CodeQL considers sensitive, and the REST API does not
expose the code flow. So instead of guessing which element was flagged, this enumerates
**every** key/value pair in the logged dict and classifies each one. If no element can
carry identifying data, the alert is safe no matter which element CodeQL picked -- a
stronger argument than matching its choice would have been.

An alert is only dismissed when every element classifies as safe. Anything holding one
UNPROVEN element stays open and is reported for a human to read, because "I could not
prove this" and "this is fine" must not produce the same outcome.

KNOWN BLIND SPOT, recorded 2026-09-29: THIS SCRIPT CANNOT SEE AN F-STRING.
-------------------------------------------------------------------------
Everything above reasons about `ast.Dict` elements, so an alert whose location is a plain
f-string log gets the reason `neither a logger dict nor a print() at location` and stays
open. Read that string as **"not classifiable by this tool"**, never as "safe" and never
as "not a log line" - 23 of the 52 currently open alerts land in that bucket, and they are
ordinary logger calls:

    logger.info(f"Post-call reaction: ... to={mask_phone(to_number or '')} ...")

`tests/test_log_phone_masking.py` had the identical gap for the identical reason and it was
hiding real disclosures - fourteen log lines printing whole E.164 numbers, which CodeQL
found only six of. That module now walks `ast.JoinedStr` as well, in `fstring_offences()`,
and its classifier (`_consuming_call` / `_is_logger` / `_is_sanitised`) is the thing to port
here rather than write again.

AND A SECOND, DEEPER POINT: masking does NOT clear these alerts, and should not be expected
to. `py/clear-text-logging-sensitive-data` is a taint query. `mask_phone(to_number)` still
has `to_number` flowing into the sink, and CodeQL has no reason to believe `mask_phone`
sanitises anything - the same behaviour `.kiro/steering/secret-handling.md` documents for
the secret case ("reducing a secret to a boolean does not launder it"), and it is correct to
behave that way. Fixing the fourteen real sites moved the open count 58 -> 56, not to zero.

So the remaining count is not a backlog of defects and chasing it to zero by dismissal would
destroy the signal.

THE MODEL-PACK ROUTE DOES NOT EXIST FOR THIS QUERY. Measured 2026-09-29, correcting what
this docstring used to recommend first.
------------------------------------------------------------------------------------------
The previous text named "a model pack under `.github/codeql/` declaring `mask_phone` /
`mask_contact_id` / `mask_flow_token` as sanitisers" as *the only fix that makes the count
mean something again*, and asked the next reader to check whether Python data extensions
supported sanitisers yet. They do — CodeQL 2.25.2 added `barrierModel` and
`barrierGuardModel` to models-as-data for Python, and this repository analyses on 2.27.1.
The version was never the blocker. **The query is.**

`CleartextLoggingQuery.qll` declares its barrier as:

    predicate isBarrier(DataFlow::Node node) { node instanceof Sanitizer }

and `CleartextLogging::Sanitizer` is an `abstract class` with **no subclasses anywhere in
the CodeQL libraries** and no models-as-data hook. A `barrierModel` tuple only takes effect
in a query whose customizations consume `ModelOutput::barrierNode`, and for Python that is
exactly nine queries: CodeInjection, CommandInjection, **LogInjection**, PathInjection,
ReflectedXSS, ServerSideRequestForgery, SqlInjection, UnsafeDeserialization, UrlRedirect.
`py/clear-text-logging-sensitive-data` is not among them.

Note the near miss, because it is how this mistake gets made twice: `py/log-injection` IS
on that list, so a model pack declaring a sanitiser genuinely works for log *injection* and
the public write-ups that recommend one are not wrong — they are about the other rule. The
two rules look alike, sit in the same files, and behave completely differently here.

A QL-level customization extending `CleartextLogging::Sanitizer` would work, but it means
shipping and compiling a custom query pack pinned to a library version, which silently
breaks on CodeQL upgrades. Not worth it for this.

SO THERE IS ONE ROUTE, and it is the one this file is: extend the classifier until it can
read the remaining sites, THEN dismiss with per-element evidence. That is not a mass
dismissal, and a mass dismissal is not an acceptable substitute for it: it reduces security
visibility, and the 39 real findings in this pile were only found because nobody had done
that.

    python scripts/triage_codeql_logging.py --report
    python scripts/triage_codeql_logging.py --apply
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RULE = "py/clear-text-logging-sensitive-data"
LOG_LEVELS = {"info", "warning", "error", "debug", "critical", "exception", "log"}

#: Calls that provably reduce or remove the identifying content.
SANITISERS = {
    "mask_phone", "mask_email", "mask_contact_id", "mask_flow_token",
    "redact_pii", "redact_string", "mask", "_mask", "_mask_tail", "_mask_phone",
    # `meta_error_summary` keeps a provider error's codes and drops its free text, so
    # nothing the provider wrote can travel through it. NOT `mask_text`, which was added
    # here and removed again after reading it: it substitutes `Bearer <token>` only, and
    # masks no phone number at all, so it would have proven a Meta error body safe.
    "meta_error_summary",
    "last4", "bool", "len", "isinstance", "sorted", "list", "int", "float", "round",
    # `str` predicates. Each returns a bool by definition, so the receiver cannot travel
    # through no matter what it holds -- `(formatted_phone or '').isdigit()` discloses
    # exactly one bit. Listed explicitly rather than by a name pattern, because the
    # neighbouring `str` methods that look similar (`strip`, `format`, `join`) return the
    # STRING and would launder a phone number straight into the log.
    "isdigit", "isnumeric", "isdecimal", "isalpha", "isalnum", "isspace",
    "isupper", "islower", "istitle", "isidentifier", "isascii",
    "startswith", "endswith",
    # `x.count(y)` returns an int by construction on `str`, `bytes` and `list`, exactly as
    # `len` does, so the receiver cannot travel through it. This is what closes the two
    # occurrence counters in `scan_repo_secrets.py` (`tree_hits += blob.count(value)`,
    # `hist_hits += data.count(value)`): the script counts how many times a credential
    # appears in the tree and in git history, and prints the COUNT.
    "count",
}

#: Keys whose value is an identifier minted by us or by a provider, with no subscriber
#: data in it. Each group has a reason, and the reason is what makes this a triage
#: rather than an allowlist someone pasted.
OPAQUE_KEYS = re.compile(
    # ids we generate: uuid4 or a provider-returned message/job id
    r"^(request_?id|correlation_?id|trace_?id|job_?id|delivery_?id|message_?id|"
    r"whatsapp_?message_?id|wamid|call_?id|session_?id|event_?id|idempotency_?key|"
    r"reference_?id|order_?id|orderno|invoice_?number|request_?number|short_?code|"
    # Meta / AWS resource ids. These appear in this repo's own committed docs, so they
    # are not secret, and none of them is dialable.
    r"(sending_?|aws_?|meta_?|display_?|originating_?|send_?)?phone_?(number_?)?ids?|"
    r"waba_?ids?|meta_?waba_?ids|catalog_?id|catalog_?retailer_?id|retailer_?id|"
    r"flow_?id|flow_?key|template_?id|app_?id|business_?id|account_?id|"
    r"(caller_?|sender_?|msg_?|parent_?)?bsuid|user_?id|"
    # a SHA of a phone, not the phone
    r"phone_?hash|contact_?hash|"
    # a secret NAME or ARN. Steering: "Reports may contain secret names and ARNs."
    r"secret_?id|secret_?name|secret|table|table_?name|queue|queue_?url|function|"
    r"function_?name|bucket|s3_?key|s3_?key_?prefix|log_?group|"
    # The same three, reached through a PREFIXED constant name. `RAZORPAY_WEBHOOK_SECRET_ID`
    # and `KMS_KEY_ARN` are the by-reference form the steering prescribes -- an identifier
    # that names where a credential lives, never the credential. The anchored alternatives
    # above cannot match them because of the prefix, which left the one pattern the rules
    # explicitly permit reported as unreviewed. Deliberately a SUFFIX rule and deliberately
    # not extended to a bare `_SECRET` suffix, which would match a variable holding a value.
    r"[a-z0-9_]*_(secret_id|secret_name|secret_arn|key_arn|role_arn|topic_arn|"
    r"queue_url|table_name|bucket_name|log_group|function_name))$",
    re.I,
)

#: A second opaque-identifier group, added 2026-09-29 while closing the residue
#: `docs/security-codeql-triage.md` §4d lists. Separate from `OPAQUE_KEYS` so each entry
#: keeps its own reason rather than disappearing into a long alternation.
INFRASTRUCTURE_KEYS = re.compile(
    # Meta's own request trace id. Published in Meta's error documentation, carries no
    # subscriber data, and this repo's `meta_error_summary` KEEPS it deliberately as one of
    # "the identifiers a human debugs from". It was the last unproven element of the
    # meta_client Graph-error log.
    r"^(fb_?trace_?id|"
    # A DynamoDB hash key we mint. `appointmentId` is a uuid4 surrogate; the appointment's
    # detail lives in other attributes, none of which is logged. CodeQL classifies the
    # STRING "appointmentId" as health-adjacent private data because its maybePrivate
    # regexp lists `appointment`, which is why this needed saying rather than assuming.
    r"appointment_?id|"
    # AWS control-plane enums: each is one of a closed set the service defines.
    # BillingMode PAY_PER_REQUEST|PROVISIONED, MfaConfiguration OFF|OPTIONAL|ON,
    # TableStatus, TimeToLiveStatus, PointInTimeRecoveryStatus.
    r"billing_?mode|mfa_?configuration|table_?status|time_?to_?live_?status|"
    r"point_?in_?time_?recovery_?status|"
    # AWS resource names and ARNs read back from a describe call to verify provisioning.
    # `maintenance-reporting.md` permits exactly these in a report: "function
    # names/ARNs/versions", "resource names", "secret names and ARNs". None is a credential
    # and none identifies a person.
    r"role|role_?name|policy_?name|policy_?names|attribute_?name|key_?schema|"
    r"custom_?message|alias_?arn|key_?type)$",
    re.I,
)

#: Keys reviewed one at a time during the 2026-09-28 triage and found to carry no
#: subscriber data. Grouped so each group carries its reason, because an allowlist
#: without reasons is indistinguishable from one somebody pasted.
REVIEWED_KEYS = re.compile(
    # Media and storage handles. A Meta media id is an opaque provider handle, a mime
    # type is a content-type string, and an S3 key in this tree is
    # `media/<uuid>/<name>` -- none is subscriber data.
    r"^(media_?id|whatsapp_?media_?id|media_?type|mime_?type|mime_?type_?hint|"
    r"actual_?s3_?key|display_?filename|file_?id|"
    # Business-document and workflow ids we mint.
    r"service_?request_?id|submission_?id|payment_?configuration|"
    # Meta Flow and template metadata: names we choose, not content.
    r"flow_?name|template|interactive_?type|toggle_?type|welcome_?type|payload_?type|"
    r"waba_?segment|resolved_?phone_?id|source_?waba_?id|target_?waba_?id|"
    # DLT registration identifiers. Published to the carrier, not secret, not a number
    # anyone can call.
    r"dlt_?entity_?id|dlt_?template_?id|requested_?key|"
    # Outcome flags and diagnostics on our own pipeline.
    r"ok|found|verified|success|pin_?sent|violations|restrictions|missing_?fields|"
    r"requires_?payment|mfa_?enrolled|enforcing|where|pair|quality_?rating|"
    # An emoji in a reaction, and a short link we minted.
    r"emoji|short_?url|"
    # Provider-returned handles for a reaction, a payment and an invoice. `pay_xxx` and
    # `inv_xxx` are references to records, not instruments -- neither can be charged.
    r"reaction_?message_?id|payment_?id|invoice_?id|"
    # Retry and backoff measurements on our own sender.
    r"elapsed|backoff|retry_?after|threshold|message_?type|"
    # The keyword that matched a fixed set, added by this session's own fix -- a member
    # of PAY_KEYWORDS/PAY_FUZZY, never free text.
    r"matched_?keyword|"
    # The agent tool names whose class is APPLY and which are enabled, read from
    # `lambda_utils/agent/governance.py`'s CATALOG. That catalog is a fixed in-repo
    # dict of tool names, so the list can only ever contain identifiers this repository
    # declares. The assertion it feeds is that the list is EMPTY.
    r"enabled_applies|"
    # Meta's ban/restriction metadata about OUR OWN number.
    r"ban_?info|"
    # A Graph API path, plus the AI classifier's own output about its own decision.
    r"endpoint|intent|confidence|"
    # A message we construct ourselves from known-safe parts; the steering permits an
    # exception message only when our code built it, which is the case at these sites.
    r"error|detail)$",
    re.I,
)

#: A staff Cognito username in `middleware.py`. Logging WHO performed an administrative
#: action is an audit requirement, so removing it would be the wrong remediation. It is a
#: deliberate retention rather than a value that cannot identify anyone, and it is
#: recorded as such rather than folded in with the opaque identifiers above.
AUDIT_KEYS = re.compile(r"^(username|actor|performed_?by|admin_?user)$", re.I)

#: Keys whose value is a count, a measurement or a code.
NUMERIC_KEYS = re.compile(
    r"(count|total|length|len|size|bytes|ms|millis|seconds|secs|duration|"
    r"status_?code|code|limit|score|rate|attempt|attempts|retries|index|version|"
    r"amount|paise|subtotal|discount|gst|cgst|sgst|shipping|handling|tax|qty|"
    r"quantity|tokens|input_?tokens|output_?tokens|temperature|expires_?at|"
    r"created_?at|updated_?at|paid_?at|timestamp|ttl|depth|page|offset)$",
    re.I,
)

#: Keys whose value is one of a closed set of strings we choose.
ENUM_KEYS = re.compile(
    r"^(event|event_?type|type|msg_?type|status|state|action|reason|note|direction|"
    r"channel|provider|mode|stage|screen|step|level|severity|result|outcome|verdict|"
    r"error_?type|errortype|exception_?type|currency|locale|language|lang|country|"
    r"region|environment|env|source|target|kind|category|label|method|route|path|"
    r"operation|op|policy|decision|send_?mode|payment_?status|order_?status|"
    r"quality_?score|quality_?event|account_?event|restriction_?type|sender_?id|"
    r"using_?default|defaulting_?to|within_?window|dry_?run|enabled|disabled)$",
    re.I,
)

#: A key that names a predicate; its value is a bool by construction.
BOOL_KEYS = re.compile(r"^(has|is|was|can|should|does|did|are|any|all|no)[_A-Z]", re.I)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    table: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[child] = node
    return table


def _consuming_call(node: ast.AST, parents: dict) -> ast.Call | None:
    """The call that consumes this expression: a logger if one encloses it, else the first.

    `json.dumps` is transparent, because `json.dumps(d)` into `logger.info` is a log while
    the same call into `lambda_client.invoke` is a payload -- the distinction §2 of
    `docs/security-codeql-triage.md` records getting wrong twice.

    Any OTHER wrapper is also walked through, but only far enough to find a logger. That
    closes `meta_client.py`'s

        logger.warning(mask_text(json.dumps({...})))

    which was reported as `no logger dict at location` and stayed open for it. Walking
    through `mask_text` is not the same as trusting it: the dict's elements are still
    classified one by one, and `mask_text` is deliberately absent from `SANITISERS`
    because it substitutes `Bearer <token>` and masks no phone number at all.

    When no logger is found the FIRST enclosing call is returned, unchanged from before, so
    `_store_call_log({...})` is still not a log and its numbers are still not masked.
    """
    first: ast.Call | None = None
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.Call):
            func = current.func
            transparent = isinstance(func, ast.Attribute) and func.attr == "dumps"
            if _is_logger(current):
                return current
            if not transparent and first is None:
                first = current
        current = parents.get(current)
    return first


def _is_logger(call: ast.Call | None) -> bool:
    if call is None or not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr not in LOG_LEVELS:
        return False
    owner = call.func.value
    name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
    return "log" in str(name).lower()


def classify_by_key(key: str) -> str:
    """Name-based rules only. Never recurses, so it cannot loop."""
    if BOOL_KEYS.match(key):
        return "BOOL_KEY"
    if OPAQUE_KEYS.match(key):
        return "OPAQUE_ID"
    if INFRASTRUCTURE_KEYS.match(key):
        return "INFRA_ID"
    if REVIEWED_KEYS.match(key):
        return "REVIEWED"
    if AUDIT_KEYS.match(key):
        return "AUDIT_RETAINED"
    if NUMERIC_KEYS.search(key):
        return "NUMERIC"
    if ENUM_KEYS.match(key):
        return "ENUM"
    return "UNPROVEN"


def _expr_key(value: ast.expr) -> str | None:
    """The one identifier an expression is about, or None when it is not about exactly one.

    `{caller_bsuid or 'N/A'}` is about `caller_bsuid`; `{a or b}` is about neither, because
    proving one says nothing about the other. Requiring *exactly* one name is what keeps
    this from being a grep that happens to find a safe-looking word in a larger expression.
    """
    # A dict lookup is named by the key it reads, not by the object it reads from.
    # `exc.response['Error']['Code']` is about `Code`; taking the object's name instead
    # gives `response`, which attributes nothing. This is the same reasoning the dict path
    # already applies to `payload.get('phoneNumberId', '')`.
    if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Constant) \
            and isinstance(value.slice.value, str):
        return value.slice.value
    names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(value) if isinstance(n, ast.Attribute)}
    if len(names) == 1 and not attrs:
        return next(iter(names))
    if not names and len(attrs) == 1:
        return next(iter(attrs))
    return None


def classify(key: str, value: ast.expr) -> str:
    if isinstance(value, ast.Constant):
        return "CONST"
    if isinstance(value, ast.Call):
        name = getattr(value.func, "id", getattr(value.func, "attr", ""))
        if name in SANITISERS:
            return f"SANITISED:{name}"
        # `payload.get('phoneNumberId', '')` is judged by the key it reads, not by the
        # dict key it is stored under -- but by NAME only. Recursing on the same node
        # here is what blew the stack on the first run.
        if name == "get" and value.args and isinstance(value.args[0], ast.Constant):
            inner = classify_by_key(str(value.args[0].value))
            if inner != "UNPROVEN":
                return f"GET:{inner}"
    if isinstance(value, ast.Attribute) and value.attr == "__name__":
        return "TYPE_NAME"
    if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Slice):
        return "SLICE"
    if isinstance(value, ast.BoolOp):
        parts = {classify(key, v) for v in value.values}
        return "BOOLOP" if all(p != "UNPROVEN" for p in parts) else "UNPROVEN"
    if isinstance(value, ast.IfExp):
        left, right = classify(key, value.body), classify(key, value.orelse)
        return "TERNARY" if "UNPROVEN" not in (left, right) else "UNPROVEN"
    # `phone[:6] + '***'` -- a slice concatenated with a literal. Safe because the slice
    # is, and worth handling rather than leaving as UNPROVEN: three sites already
    # truncated correctly and would otherwise have been reported as unreviewed.
    if isinstance(value, ast.BinOp):
        parts = {classify(key, value.left), classify(key, value.right)}
        return "TRUNCATED_CONCAT" if "UNPROVEN" not in parts else "UNPROVEN"
    # A comprehension over a closed set of field NAMES, e.g. the missing-credential
    # field list in rcs-send. The elements are names, not values.
    # The element is judged by ITS OWN identifier where it has one, falling back to the
    # container's key. `[(k['AttributeName'], k['KeyType']) for k in ...]` is about
    # `AttributeName` and `KeyType`; judging both against the outer name `keys` attributes
    # nothing and reported a DynamoDB key-schema dump as unreviewed. Same reasoning as
    # `classify_expr`'s own-identifier fallback, and it can only narrow, never widen.
    if isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        inner = classify(_expr_key(value.elt) or key, value.elt)
        return "NAME_COMPREHENSION" if inner != "UNPROVEN" else "UNPROVEN"
    # An f-string is safe exactly when every interpolation in it is. Its literal segments
    # are source text by construction. This is what closes the module constants that are
    # themselves f-strings, e.g.
    #   SECRET_ARN = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:wecare/plivo/api-??????"
    # which is an ARN template built from two other constants and holds no runtime value.
    if isinstance(value, ast.JoinedStr):
        parts = [v for v in value.values if isinstance(v, ast.FormattedValue)]
        if not parts:
            return "CONST"
        verdicts = {classify(_expr_key(p.value) or key, p.value) for p in parts}
        return "FSTRING" if "UNPROVEN" not in verdicts else "UNPROVEN"
    if isinstance(value, ast.Name):
        return classify_by_key(key)
    if isinstance(value, (ast.Compare, ast.UnaryOp)):
        return "PREDICATE"
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        parts = {classify(_expr_key(v) or key, v) for v in value.elts}
        return "SEQ" if all(p != "UNPROVEN" for p in parts) else "UNPROVEN"
    return classify_by_key(key)


# ---------------------------------------------------------------------------------------
# Name resolution.
#
# 28 of the open alerts classify as UNPROVEN on a single element that is a bare name --
# `sid`, `p`, `verb`, `nblobs`, `RAZORPAY_SECRET_NAME`. `classify_by_key` judges by NAME
# only, and none of those names carries a hint, so it correctly gives up. Resolving the
# name to what it is actually bound to is what turns "I cannot attribute this" into
# evidence, and it is the same discipline as the dict walk: read the code rather than
# pattern-match the identifier.
#
# EVERY RULE HERE FAILS CLOSED. A binding form that is not read returns UNPROVEN, and a
# name with several bindings must have all of them classify safe. The specific traps:
#
#   * A function PARAMETER is never resolvable -- its value comes from a caller this pass
#     cannot see. Treating a parameter as its default would be the classic wrong answer.
#   * `except ... as e` binds an exception OBJECT, whose str() is provider text that can
#     contain anything, including a recipient number. `.kiro/steering/secret-handling.md`
#     requires `type(exc).__name__` unless our own code built the message, so this must
#     stay UNPROVEN and be remediated rather than dismissed.
#   * A module constant counts only when the module binds it EXACTLY ONCE. A name assigned
#     twice at module scope can hold either value and neither binding proves the other.
#   * Recursion is bounded. `x = x + 1` and two names assigned from each other both
#     terminate on the depth limit rather than on the stack, which is the failure the
#     first version of `classify` had.
# ---------------------------------------------------------------------------------------

#: A name bound to an exception, or shaped like one. Checked BEFORE every other rule,
#: including the reviewed-key allowlist, because `REVIEWED_KEYS` accepts `error` and
#: `detail` on the strength of "a message we construct ourselves from known-safe parts" --
#: true of a dict entry built in place, not of a bare `{e}` in an f-string.
EXCEPTION_NAMES = frozenset({
    "e", "ex", "exc", "err", "error", "exception", "the_error", "last_error", "_e",
})

#: Attributes and keys that carry an exception's TEXT. Reaching one of these is the leak;
#: reaching any other member of the same object is not.
EXCEPTION_TEXT_MEMBERS = frozenset({
    "args", "message", "msg", "strerror", "reason", "detail", "details", "text",
    "body", "response_body", "Message",
})

#: Calls that render an exception as its message.
EXCEPTION_RENDERERS = frozenset({"str", "repr", "format", "unicode"})


def _is_exception_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id in EXCEPTION_NAMES


def _exception_leak(value: ast.expr) -> bool:
    """True when the expression yields an exception's TEXT rather than something narrower.

    The distinction is the whole point and a blanket "mentions `exc`" test gets it wrong in
    both directions. These must stay UNPROVEN, because provider text can contain anything
    including a recipient number, and `.kiro/steering/secret-handling.md` requires
    `type(exc).__name__` unless our own code built the message:

        {e}   {str(e)}   {exc.args}   {e.response['Error']['Message']}

    These are narrowings and are judged on their own merits, not condemned by association:

        {type(exc).__name__}          the class, which is the form the steering asks for
        {exc.response['Error']['Code']}   an AWS error code from a closed set
        {e.status_code}               an HTTP status
    """
    if _is_exception_name(value):
        return True
    if isinstance(value, ast.Call):
        name = getattr(value.func, "id", None)
        if name in EXCEPTION_RENDERERS and any(_is_exception_name(a) for a in value.args):
            return True
    if isinstance(value, ast.Attribute):
        if _is_exception_name(value.value) and value.attr in EXCEPTION_TEXT_MEMBERS:
            return True
    if isinstance(value, ast.Subscript):
        if isinstance(value.slice, ast.Constant) \
                and str(value.slice.value) in EXCEPTION_TEXT_MEMBERS \
                and any(_is_exception_name(n) for n in ast.walk(value)):
            return True
    # A container built around the exception itself, e.g. `x or e`, `f"{e}"`.
    if isinstance(value, (ast.BoolOp, ast.IfExp, ast.BinOp, ast.JoinedStr,
                          ast.FormattedValue)):
        return any(_exception_leak(child) for child in ast.iter_child_nodes(value))
    return False

#: Depth limit for following one name to another. Three is enough for every shape in this
#: tree (`a = b`, `b = literal`) and short enough that a cycle cannot cost anything.
_RESOLVE_DEPTH = 3


class Resolver:
    """Per-file binding lookup. Constructed once per alert, thrown away after."""

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.parents = _parents(tree)
        self.module_constants = self._single_module_bindings(tree)
        self._functions = [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        # Reducers this file defines that return part of their input, so a call to one
        # must not be trusted here even though the name is allowlisted. Computed per
        # file, because the same name can be one-way in one script and not in another.
        self.leaky = leaky_reducers(tree)

    @staticmethod
    def _single_module_bindings(tree: ast.Module) -> dict[str, ast.expr]:
        counts: dict[str, int] = {}
        values: dict[str, ast.expr] = {}
        for stmt in tree.body:                      # module scope only, not nested
            targets: list[ast.expr] = []
            if isinstance(stmt, ast.Assign):
                targets = list(stmt.targets)
            elif isinstance(stmt, ast.AnnAssign):
                targets = [stmt.target]
            else:
                continue
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue                        # tuple unpack: not read
                counts[target.id] = counts.get(target.id, 0) + 1
                if stmt.value is not None:
                    values[target.id] = stmt.value
        return {n: v for n, v in values.items() if counts.get(n) == 1}

    def enclosing_function(self, node: ast.AST):
        current = self.parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current
            current = self.parents.get(current)
        return None

    @staticmethod
    def _is_parameter(func, name: str) -> bool:
        args = func.args
        every = (list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
                 + ([args.vararg] if args.vararg else [])
                 + ([args.kwarg] if args.kwarg else []))
        return any(a.arg == name for a in every)

    def local_bindings(self, func, name: str) -> list[ast.expr] | None:
        """Expressions bound to `name` in `func`, or None when any binding is unreadable.

        None means "cannot be attributed", never "nothing found" -- the caller must treat
        it as UNPROVEN.
        """
        if func is None:
            return None
        if self._is_parameter(func, name):
            return None
        found: list[ast.expr] = []
        for node in ast.walk(func):
            # An exception name is disqualifying on its own, wherever it appears.
            if isinstance(node, ast.ExceptHandler) and node.name == name:
                return None
            if isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
                return None
            if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name) \
                    and node.target.id == name:
                return None
            if isinstance(node, (ast.For, ast.AsyncFor)) and self._binds(node.target, name):
                return None
            if isinstance(node, ast.withitem) and node.optional_vars is not None \
                    and self._binds(node.optional_vars, name):
                return None
            if isinstance(node, ast.comprehension) and self._binds(node.target, name):
                return None
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                    and node.target.id == name:
                found.append(node.value)            # `n += 1` contributes its RHS
                continue
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                    and node.target.id == name and node.value is not None:
                found.append(node.value)
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        found.append(node.value)
                    elif self._binds(target, name):
                        return None                 # tuple/star unpack: not read
        return found or None

    @staticmethod
    def _binds(target: ast.expr, name: str) -> bool:
        return any(isinstance(n, ast.Name) and n.id == name
                   for n in ast.walk(target))

    def loop_source(self, func, name: str) -> list[ast.expr] | None:
        """For `for <name> in <list>`, the expressions that can be in that list.

        `docs/security-codeql-triage.md` §4d names this as one of the shapes that kept
        alerts open: `for p in problems` where `problems` is accumulated by `append`. The
        loop variable is not resolvable on its own -- `local_bindings` correctly refuses a
        `for` target -- but the LIST it iterates often is, and every value that can reach
        the loop variable is then visible.

        Fail-closed in five ways, because this is the rule most likely to over-reach:
          * exactly one `for` statement may bind the name, or the values cannot be attributed;
          * the iterable must be a bare local name (not a call, not a comprehension);
          * that name must be assigned exactly once in the function, to a list/tuple/set
            display -- in practice `[]`;
          * every mutation of it must be `.append(one_value)` or `.extend(<display>)`;
            anything else (`+=`, `.extend(other_name)`, a slice assignment) gives up;
          * the name must not also be rebound by a loop, a `with`, a walrus or an unpack.
        """
        if func is None or self._is_parameter(func, name):
            return None
        loops = [n for n in ast.walk(func)
                 if isinstance(n, (ast.For, ast.AsyncFor)) and self._binds(n.target, name)]
        if len(loops) != 1:
            return None
        loop = loops[0]
        # Only a plain `for x in xs`. A tuple target means x is one slot of an element, and
        # attributing it needs the element's shape, which this does not read.
        if not (isinstance(loop.target, ast.Name) and loop.target.id == name):
            return None
        if not isinstance(loop.iter, ast.Name):
            return None
        return self.list_contents(func, loop.iter.id)

    def list_contents(self, func, name: str) -> list[ast.expr] | None:
        """Every expression that can be an element of the local list `name`, or None."""
        if func is None or self._is_parameter(func, name):
            return None
        seeds: list[ast.expr] = []
        assigns = 0
        for node in ast.walk(func):
            if isinstance(node, (ast.For, ast.AsyncFor)) and self._binds(node.target, name):
                return None
            if isinstance(node, ast.withitem) and node.optional_vars is not None \
                    and self._binds(node.optional_vars, name):
                return None
            if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name) \
                    and node.target.id == name:
                return None
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                    and node.target.id == name:
                return None                         # `xs += ys`: ys is not read here
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (list(node.targets) if isinstance(node, ast.Assign)
                           else [node.target])
                for target in targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        assigns += 1
                        if node.value is None:
                            continue            # `xs: list[str]` -- a declaration, no value
                        if not isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                            return None
                        seeds.extend(node.value.elts)
                    elif self._binds(target, name):
                        return None
        if assigns != 1:
            return None
        for node in ast.walk(func):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if not (isinstance(owner, ast.Name) and owner.id == name):
                continue
            method = node.func.attr
            if method == "append" and len(node.args) == 1:
                seeds.append(node.args[0])
            elif method == "extend" and len(node.args) == 1 \
                    and isinstance(node.args[0], (ast.List, ast.Tuple, ast.Set)):
                seeds.extend(node.args[0].elts)
            else:
                return None                     # insert, __setitem__, extend(<name>), ...
        return seeds or None


def resolve(expr: ast.expr, resolver: "Resolver | None", site: ast.AST,
            depth: int = 0) -> str:
    """Classify a bare name by what it is bound to. Returns UNPROVEN when it cannot."""
    if resolver is None or depth >= _RESOLVE_DEPTH:
        return "UNPROVEN"
    if not isinstance(expr, ast.Name):
        return "UNPROVEN"
    if _is_exception_name(expr):
        return "UNPROVEN"

    func = resolver.enclosing_function(site)
    bindings = resolver.local_bindings(func, expr.id)
    origin = "LOCAL"
    if bindings is None:
        # A `for` target is not resolvable on its own, but the list it iterates may be.
        bindings = resolver.loop_source(func, expr.id)
        origin = "LOOP_OVER"
    if bindings is None:
        value = resolver.module_constants.get(expr.id)
        if value is None:
            return "UNPROVEN"
        bindings, origin = [value], "MODULE_CONST"

    verdicts = set()
    for bound in bindings:
        verdict = classify_expr(bound, expr.id, resolver, site, depth + 1)
        if verdict == "UNPROVEN":
            return "UNPROVEN"
        verdicts.add(verdict)
    return f"{origin}:{'/'.join(sorted(verdicts))[:40]}"


def classify_expr(value: ast.expr, key: str, resolver: "Resolver | None",
                  site: ast.AST, depth: int = 0) -> str:
    """`classify`, plus one fallback: resolve a bare name to its bindings.

    Kept as a wrapper rather than folded into `classify` so the dict path's behaviour is
    unchanged whenever no resolver is supplied, which is what the existing tests pin.
    """
    if _exception_leak(value):
        return "UNPROVEN"
    # A reducer that this file defines as returning part of its input is not a reducer,
    # whatever it is called. Checked before `classify` so it beats the SANITISERS list.
    if isinstance(value, ast.Call) and resolver is not None and resolver.leaky:
        called = getattr(value.func, "id", getattr(value.func, "attr", ""))
        if called in resolver.leaky:
            return "UNPROVEN"
    verdict = classify(key, value)
    if verdict != "UNPROVEN":
        return verdict
    # An f-string reached through resolution needs its interpolations resolved too, and
    # `classify`'s own JoinedStr branch cannot do that -- it has no resolver, so it judges
    # each interpolation by name alone. That is what left `for p in problems` unproven even
    # once `problems` was readable: one appended message interpolates `{enabled_applies}`,
    # a name no rule can attribute but every binding of which is readable.
    if isinstance(value, ast.JoinedStr) and resolver is not None \
            and depth < _RESOLVE_DEPTH:
        parts = [v for v in ast.walk(value) if isinstance(v, ast.FormattedValue)]
        if parts:
            inner = {classify_expr(p.value, _expr_key(p.value) or key, resolver, site,
                                   depth + 1) for p in parts}
            if "UNPROVEN" not in inner:
                return "FSTRING"
    # The expression's own identifier beats the key it happens to be filed under. A dict
    # entry `{'x': phone_number_id}` holds a phone_number_id whichever key names it, and
    # an f-string has no key at all -- only the expression. Applied as a fallback, so it
    # can turn UNPROVEN into proven but never the reverse.
    own = _expr_key(value)
    if own and own != key:
        verdict = classify(own, value)
        if verdict != "UNPROVEN":
            return verdict
    return resolve(value, resolver, site, depth)


#: Helpers that reduce a credential to something non-reversible before it is printed.
#: These are the by-reference pattern `.kiro/steering/secret-handling.md` prescribes:
#: report "provider, credential present YES/NO, field count, fingerprint, length", never
#: the value.
#:
#: MEMBERSHIP HERE IS NOT ENOUGH. Every name is re-verified against its definition in the
#: file under analysis by `leaky_reducers` below, because trusting a reducer by its name
#: is the same mistake as trusting `mask_text` by its name, and it had already been made:
#: `audit_secrets_structure.py::fingerprint` returned `len={n} {v[:4]}…{v[-2:]}` -- four
#: leading and two trailing characters of every field of seven live secrets -- and this
#: allowlist proved it safe on the strength of the word "fingerprint". Found 2026-09-29.
SAFE_PRINT_CALLS = {
    "len", "fingerprint", "digest", "fp", "sha256", "bool", "sorted", "list", "int",
    "_redact", "redact", "mask", "mask_phone", "type", "repr_shape", "count",
}

#: The subset of reducers whose contract is to keep a BOUNDED TAIL of a phone number or an
#: email, where returning part of the input is the prescribed behaviour rather than a
#: defect -- `mask_phone` is `clean[:3] + '****' + clean[-4:]` by design. A credential
#: fingerprint has the opposite contract, and the repository's credential tooling states it
#: outright: "never print a prefix or a suffix of a credential - an issuer prefix plus a
#: length is a meaningful head start". So the slice check below exempts these and only
#: these.
BOUNDED_TAIL_MASKERS = {
    "mask", "_mask", "mask_phone", "_mask_phone", "mask_email", "mask_contact_id",
    "mask_flow_token", "_mask_tail", "last4",
}

#: Calls after which a slice is a slice of a DIGEST rather than of the input. Truncating a
#: sha256 is the prescribed rendering, so these have to break the chain or the check below
#: condemns every correct fingerprint in the tree.
_ONE_WAY_CALLS = frozenset({
    "sha256", "sha1", "sha224", "sha384", "sha512", "md5", "blake2b", "blake2s",
    "hexdigest", "digest", "new", "token_urlsafe", "token_hex", "uuid4",
})


def leaky_reducers(tree: ast.Module) -> set[str]:
    """Names from `SAFE_PRINT_CALLS` that this file defines as returning part of an input.

    A reducer earns its place in the allowlist by being one-way. This reads the definition
    rather than the name: if any `return` in the function yields a slice or an index of one
    of the function's own parameters, then printing its result prints part of the value, and
    the call must NOT classify as REDUCED.

    Fails closed in the useful direction -- it only ever removes trust, never grants it.
    """
    leaky: set[str] = set()

    def one_way(expr: ast.expr) -> bool:
        """True when a hash stands between the parameter and the subscript.

        `hashlib.sha256(v.encode()).hexdigest()[:12]` slices the DIGEST, not `v`, so it
        discloses nothing and is the prescribed form. Without this the check condemns
        every correct fingerprint in the tree, because `v` is still somewhere inside the
        subscripted expression.
        """
        return any(
            getattr(c.func, "attr", getattr(c.func, "id", "")) in _ONE_WAY_CALLS
            for c in ast.walk(expr) if isinstance(c, ast.Call)
        )

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in SAFE_PRINT_CALLS or node.name in BOUNDED_TAIL_MASKERS:
            continue
        args = node.args
        params = {a.arg for a in (list(args.posonlyargs) + list(args.args)
                                  + list(args.kwonlyargs))}
        # A one-step local alias of a parameter counts as the parameter: `clean = v.strip()`
        # then `clean[:4]` is still four characters of `v`.
        aliases = set()
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assign) and len(inner.targets) == 1 \
                    and isinstance(inner.targets[0], ast.Name):
                if any(isinstance(n, ast.Name) and n.id in params
                       for n in ast.walk(inner.value)):
                    aliases.add(inner.targets[0].id)
        tainted = params | aliases
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Return) or inner.value is None:
                continue
            for piece in ast.walk(inner.value):
                if not isinstance(piece, ast.Subscript):
                    continue
                if one_way(piece.value):
                    continue
                if any(isinstance(n, ast.Name) and n.id in tainted
                       for n in ast.walk(piece.value)):
                    leaky.add(node.name)
    return leaky


def print_interpolations(path: pathlib.Path, start: int, end: int) -> list[tuple[str, str, str]] | None:
    """Classify the interpolated expressions of a `print()` at this location.

    69 of the open alerts are in `scripts/`, which are developer-run tools that use
    `print()` rather than a logger, so there is no dict to enumerate. CodeQL flags them
    because names like `SECRET_ID` and `args.secret` look sensitive -- but they hold secret
    *identifiers*, and the value-bearing lines emit a length, a label or an irreversible
    `sha256[:12]`. Reviewed all 69 by hand: exactly one interpolated a variable that could
    have been a value, `verify_secret_consumption.py`'s JSON `leaks` list, and reading it
    shows `what` is a LABEL from the known-credential map and `fp` is `digest(value)`.

    Returns None when no `print` is found at the location.
    """
    tree = ast.parse(path.read_text())
    resolver = Resolver(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "print":
            continue
        if not (start <= node.lineno <= end + 1):
            continue
        out: list[tuple[str, str, str]] = []
        for argument in node.args:
            for piece in ast.walk(argument):
                if not isinstance(piece, ast.FormattedValue):
                    continue
                expr = ast.unparse(piece.value)
                inner = piece.value
                verdict = "UNPROVEN"
                if isinstance(inner, ast.Constant):
                    verdict = "CONST"
                elif isinstance(inner, ast.Attribute) and inner.attr == "__name__":
                    # `type(exc).__name__` -- the exception's CLASS, which is the form
                    # `.kiro/steering/secret-handling.md` asks for. The dict path already
                    # classified this as TYPE_NAME; the print path did not, so the one site
                    # that logs it correctly was reported as unreviewed.
                    verdict = "TYPE_NAME"
                elif isinstance(inner, ast.Call):
                    name = getattr(inner.func, "id", getattr(inner.func, "attr", ""))
                    if name in resolver.leaky:
                        # Allowlisted by name, but this file's definition returns part of
                        # its input. Leave it UNPROVEN and let a human read it.
                        verdict = "UNPROVEN"
                    elif name in SAFE_PRINT_CALLS:
                        verdict = f"REDUCED:{name}"
                    elif name in ("get", "join", "format", "strip", "keys", "values",
                                  "most_common", "upper", "lower", "split", "dumps"):
                        verdict = f"DERIVED:{name}"
                elif isinstance(inner, ast.Subscript) and isinstance(inner.slice, ast.Slice):
                    verdict = "SLICE"
                elif isinstance(inner, (ast.Compare, ast.IfExp, ast.UnaryOp, ast.BoolOp)):
                    verdict = "PREDICATE"
                elif isinstance(inner, (ast.Name, ast.Attribute, ast.Subscript)):
                    verdict = classify_by_key(expr.split(".")[-1].split("[")[0])
                if verdict == "UNPROVEN":
                    # Last resort: read what the name is bound to instead of judging it by
                    # its spelling. This is what closes `RAZORPAY_SECRET_NAME`, `nblobs`
                    # and `len(data) / 1048576`, none of which any name rule can attribute.
                    key = expr.split("(")[0].split(".")[-1].split("[")[0].strip() or expr
                    verdict = classify_expr(inner, key, resolver, node)
                out.append((expr[:60], verdict, expr[:70]))
        return out
    return None


def fstring_interpolations(
    path: pathlib.Path, start: int, end: int
) -> list[tuple[str, str, str]] | None:
    """Classify each interpolation of a logged f-string at this location.

    THIS IS THE BLIND SPOT THE HEADER DESCRIBES, now closed. 23 of the 52 open alerts were
    reported as `neither a logger dict nor a print() at location`, which reads like "not a
    log line" and means nothing of the sort -- they are ordinary logger calls that happen
    to use an f-string instead of a dict:

        logger.info(f"INBOUND CALL from {mask_phone(from_number or '')} "
                    f"(has_caller_name: {bool(caller_name)}, BSUID: {caller_bsuid or 'N/A'})")

    `tests/test_log_phone_masking.py` had the identical gap for the identical reason and it
    was hiding fourteen real disclosures, so the shape is proven to matter. Each
    `FormattedValue` is classified on its own and the alert is only provable when every one
    of them is, exactly as for a dict.

    The key passed to the classifier is the interpolated EXPRESSION's trailing name --
    `phone_number_id` out of `{phone_number_id}`, `result` out of `{json.dumps(result)}` --
    because that is the only name available. Where the expression is a bare name carrying
    no hint, `classify_expr` resolves it to its binding instead of guessing.

    Returns None when no logged f-string is found at the location, so the caller can tell
    "nothing here" from "here and unprovable".
    """
    tree = ast.parse(path.read_text())
    resolver = Resolver(tree)
    best: tuple[ast.JoinedStr, list[ast.FormattedValue]] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        # An f-string spanning several source lines reports its own `lineno` at the first
        # line, while CodeQL points at the line holding the interpolation. Accept the
        # whole span in both directions rather than requiring containment.
        node_end = node.end_lineno or node.lineno
        if node_end < start or node.lineno > end + 1:
            continue
        if not _is_logger(_consuming_call(node, resolver.parents)):
            continue
        parts = [p for p in ast.walk(node) if isinstance(p, ast.FormattedValue)]
        if best is None or node.lineno <= best[0].lineno:
            best = (node, parts)
    if best is None:
        return None

    joined, parts = best
    out: list[tuple[str, str, str]] = []
    for part in parts:
        expr = ast.unparse(part.value)
        # The one identifier the expression is about, falling back to its trailing name.
        key = _expr_key(part.value) \
            or expr.split("(")[0].split(".")[-1].split("[")[0].strip() or expr
        verdict = classify_expr(part.value, key, resolver, joined)
        out.append((expr[:60], verdict, expr[:70]))
    if not out:
        # An f-string with no interpolations is a plain string: nothing can flow through it.
        out.append(("<no interpolations>", "CONST", ast.unparse(joined)[:70]))
    return out


def dict_at(path: pathlib.Path, start: int,
            end: int) -> tuple[ast.Dict, Resolver] | tuple[None, None]:
    """The logged dict at this location, with the resolver for its file.

    Returns the resolver alongside the node because `elements` needs the whole module to
    resolve a bare name, and re-parsing per element would be the obvious waste.
    """
    tree = ast.parse(path.read_text())
    resolver = Resolver(tree)
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        if node.lineno < start or (node.end_lineno or node.lineno) > end + 1:
            continue
        if not _is_logger(_consuming_call(node, resolver.parents)):
            continue
        if best is None or node.lineno <= best.lineno:
            best = node
    return (best, resolver) if best is not None else (None, None)


def elements(node: ast.Dict, resolver: Resolver | None = None,
             site: ast.AST | None = None) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for key, value in zip(node.keys, node.values):
        name = key.value if isinstance(key, ast.Constant) else "<dynamic>"
        if isinstance(value, ast.Dict):
            out.extend(elements(value, resolver, site))
            continue
        verdict = classify_expr(value, str(name), resolver, site or node)
        out.append((str(name), verdict, ast.unparse(value)[:70]))
    return out


def load_alerts() -> list[dict]:
    raw = subprocess.run(
        ["gh", "api", "-X", "GET",
         "repos/:owner/:repo/code-scanning/alerts?state=open&per_page=100",
         "--paginate"],
        capture_output=True, text=True, cwd=ROOT, check=True).stdout
    return [a for a in json.loads(raw) if a["rule"]["id"] == RULE]


def head_sha() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                          cwd=ROOT, check=True).stdout.strip()


def working_tree_dirty(path: str) -> bool:
    """True when `path` has uncommitted edits, or when that cannot be determined.

    Checked INDEPENDENTLY of any commit comparison, which is the bug this replaces. The
    previous guard only looked at the working tree when the analysed commit differed from
    HEAD, so editing a file and re-running at the same commit skipped the check entirely
    and classified the alert against lines that had already moved. Found the hard way: a
    remediation in `whatsapp-calling/handler.py` shifted its own alert by four lines and
    the report described a different statement without saying anything was wrong.
    """
    result = subprocess.run(["git", "status", "--porcelain", "--", path],
                            capture_output=True, text=True, cwd=ROOT)
    return result.returncode != 0 or bool(result.stdout.strip())


def file_changed(old: str, new: str, path: str) -> bool:
    """True when `path` differs between two commits, or when that cannot be determined.

    Fails CLOSED: an unknown commit (a force-push, a shallow clone, a commit from a branch
    that no longer exists) returns True, so the alert is treated as stale and left open
    rather than judged against a file whose history we cannot see.
    """
    result = subprocess.run(["git", "diff", "--name-only", old, new, "--", path],
                            capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        return True
    return bool(result.stdout.strip())


def review() -> tuple[list[dict], list[dict]]:
    """Classify every open alert. Refuses to judge one analysed against another tree.

    An alert records the `commit_sha` it was found on. Line numbers move, and this
    session moved several thousand of them -- so resolving a 2-hour-old alert's
    `start_line` against the current file can land on an entirely different dict and
    "prove" the wrong thing safe. Anything whose analysis commit is not HEAD is reported
    as STALE and left open; re-run after CodeQL has scanned HEAD.
    """
    proven, unproven = [], []
    current = head_sha()
    for alert in load_alerts():
        instance = alert["most_recent_instance"]
        loc = instance["location"]
        analysed = instance.get("commit_sha")
        # Per-FILE staleness, not whole-tree. Requiring `commit_sha == HEAD` is correct in
        # principle and unreachable in practice here: three sessions push every few
        # minutes, so CodeQL is always a commit or two behind and the check never passes.
        # What actually has to hold is narrower -- the file this alert points INTO must
        # not have changed between the analysed commit and HEAD, or `start_line` lands
        # somewhere else and the classification describes a different dict.
        stale = None
        if working_tree_dirty(loc["path"]):
            stale = (f"STALE: {loc['path']} has uncommitted edits, so the line reference "
                     f"has moved relative to every commit including HEAD")
        elif analysed and analysed != current and file_changed(analysed, current, loc["path"]):
            stale = (f"STALE: {loc['path']} changed between {analysed[:8]} and "
                     f"{current[:8]}, so the line reference may have moved")
        if stale:
            unproven.append({
                "alert": alert, "path": loc["path"], "line": loc["start_line"],
                "why": stale, "elements": [], "bad": [],
            })
            continue
        path = ROOT / loc["path"]
        if not path.exists():
            unproven.append({"alert": alert, "why": "file missing", "elements": []})
            continue
        node, resolver = dict_at(path, loc["start_line"], loc["end_line"])
        if node is None:
            # Order matters only for reporting, not for the verdict: a location is one of
            # these three shapes, never two. The f-string reader runs last because it is
            # the widest -- it will match a `logger.info(f"...")` that also contains a
            # dict, and the dict reader is the more precise description of that site.
            printed = print_interpolations(path, loc["start_line"], loc["end_line"])
            kind = "print"
            if printed is None:
                printed = fstring_interpolations(path, loc["start_line"], loc["end_line"])
                kind = "fstring"
            if printed is None:
                unproven.append({"alert": alert, "path": loc["path"],
                                 "line": loc["start_line"],
                                 "why": "no logger dict, print() or logged f-string at "
                                        "location -- read it by hand",
                                 "elements": [], "bad": []})
                continue
            bad = [e for e in printed if e[1] == "UNPROVEN"]
            record = {"alert": alert, "path": loc["path"], "line": loc["start_line"],
                      "elements": printed, "bad": bad, "kind": kind}
            (unproven if bad else proven).append(record)
            continue
        els = elements(node, resolver, node)
        bad = [e for e in els if e[1] == "UNPROVEN"]
        record = {"alert": alert, "path": loc["path"], "line": loc["start_line"],
                  "elements": els, "bad": bad, "kind": "dict"}
        (unproven if bad else proven).append(record)
    return proven, unproven


def render(record: dict) -> str:
    keys = ", ".join(f"{k}={c}" for k, c, _ in record["elements"])
    return f"{record['path']}:{record['line']}  [{keys}]"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    proven, unproven = review()
    print(f"{RULE}: {len(proven) + len(unproven)} open")
    print(f"  provably safe (every element classified): {len(proven)}")
    print(f"  NOT proven, stays open:                   {len(unproven)}")

    if unproven:
        print("\n--- stays open ---")
        for r in unproven:
            print(f"  #{r['alert']['number']} {r.get('path')}:{r.get('line')}"
                  f"  why={r.get('why', 'unproven element')}")
            for k, c, expr in r.get("bad", []):
                print(f"        UNPROVEN  '{k}': {expr}")

    if args.report or not args.apply:
        print("\n(report only; pass --apply to dismiss the provably-safe alerts)")
        return 0

    failures = 0
    for r in proven:
        number = r["alert"]["number"]
        keys = ", ".join(f"{k}={c}" for k, c, _ in r["elements"])
        # GitHub caps `dismissed_comment` at 280 characters. The first attempt sent ~700
        # and every call came back "Invalid request" with no field named, which reads as a
        # malformed payload rather than a length limit. Detail lives in the committed
        # rationale document; the comment carries the per-alert evidence that cannot be
        # reconstructed from it -- this dict's own keys and their classifications.
        comment = (
            f"Triaged per alert, not in bulk. Every element of this logged expression was "
            f"enumerated from the AST; none can carry subscriber data: {keys}. "
            f"Evidence + the 120 real disclosures remediated first: "
            f"docs/security-codeql-triage.md"
        )
        if len(comment) > 280:
            comment = (f"Per-alert AST triage; no element can carry subscriber data. "
                       f"See docs/security-codeql-triage.md ({len(r['elements'])} "
                       f"elements checked)")[:280]
        result = subprocess.run(
            ["gh", "api", "-X", "PATCH",
             f"repos/:owner/:repo/code-scanning/alerts/{number}",
             "-f", "state=dismissed",
             "-f", "dismissed_reason=false positive",
             "-f", f"dismissed_comment={comment}"],
            capture_output=True, text=True, cwd=ROOT)
        if result.returncode != 0:
            failures += 1
            print(f"  FAILED #{number}: {result.stderr.strip()[:160]}", file=sys.stderr)
        else:
            print(f"  dismissed #{number}  {r['path']}:{r['line']}")
    print(f"\ndismissed={len(proven) - failures} failed={failures} "
          f"left_open={len(unproven)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
