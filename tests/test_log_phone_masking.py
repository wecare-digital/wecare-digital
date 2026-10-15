"""A phone number, a customer name, or raw exception text must not reach a log line.

WHY THIS TEST EXISTS. CodeQL's `py/clear-text-logging-sensitive-data` reported 202 open
alerts on this repository with **zero** triaged, and the volume was itself the problem:
roughly 155 were `phoneNumberId` / `metaPhoneId` / `phoneHash`, which are opaque Meta
business identifiers and SHA hashes rather than customer data, and that noise was hiding
about twenty sites that logged a **full E.164 number** and three that logged a
customer's WhatsApp profile name. A gate that fires on the safe majority trains people to
ignore it, so this asserts only the part that is genuinely a disclosure.

WHY IT PARSES INSTEAD OF GREPPING, which is the expensive lesson in here. A dict entry of
the shape ``'to': whatsapp_phone`` occurs in three completely different roles:

    logger.info(json.dumps({'event': 'sent', 'to': whatsapp_phone}))    a log  -> mask
    payload = {'messaging_product': 'whatsapp', 'to': whatsapp_phone}   the Meta request
    _store_call_log({'fromNumber': from_number, ...})                   the stored record

Masking the second breaks sending; masking the third destroys the record the CRM exists
to keep. Two successive regex heuristics got this wrong. The first, "wrap any matching
line", hit 11 payload and item dicts. The second, "walk backwards to the nearest
`logger.`", hit 20 more -- including `_store_call_log({...})` sitting a few lines below an
unrelated `logger.info`, which masked the call log's numbers and dropped the caller's name
from it. `tests/test_calling.py::test_bsuid_extraction_from_contacts` is what caught that.

Bracket structure is the only thing that answers "which call is this dict in", so this
module walks the AST and asks the tree. `json.dumps` is transparent: the classifier looks
through it to whatever consumes the result, because `json.dumps` feeding
`lambda_client.invoke` is a payload and `json.dumps` feeding `logger.info` is a log.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "amplify/functions"

LOG_LEVELS = {"info", "warning", "error", "debug", "critical", "exception", "log"}

#: Keys naming a subscriber phone number. `*Id`-suffixed names are excluded: a Meta
#: phone-number id such as `1055232054343117` is a business identifier this repo's own
#: docs publish, not a number anyone can call.
#:
#: `formatted`, `norm`/`normalised` and `buyer` were added on 2026-09-29 while extending
#: this module to f-strings. They are not hypothetical spellings: `formatted_phone` and
#: `norm_phone` are what `outbound-whatsapp` and `bulk-worker` call the number *after*
#: normalisation, which is the point at which it is most likely to be logged ("sent to
#: X"), and `buyer_phone` is the conventional name for an order purchaser's number. The
#: original alternation covered the inbound-facing names only, so the outbound-facing ones
#: were invisible.
PHONE_KEY = re.compile(
    r"^(?:(?:sender|recipient|caller|contact|customer|display|receiving|to|from|whatsapp"
    r"|dest\w*|clean|formatted|norm|normalised|normalized|buyer)_?)?phone(?:_?number|_?e164)?$"
    r"|^phone_?number$|^msisdn$|^wa_id$"
    r"|^from$|^to$|^to_?number$|^from_?number$",
    re.I,
)

#: Keys that unambiguously carry an END CUSTOMER's own name. Deliberately NOT bare
#: `name`/`username`: in these handlers those are a WhatsApp template name, an order
#: line-item name, or the STAFF Cognito username that `middleware.py` logs so an
#: administrative action can be attributed. Attribution is an audit requirement, and a
#: gate demanding its removal would be asking for the wrong thing.
PERSON_KEY = re.compile(
    r"^(?:sender|caller|contact|customer|buyer|recipient)_?(?:name|username)$", re.I)

NOT_SENSITIVE_KEY = re.compile(
    r"(_?id|_?ids|_?hash|_?key|_?type|_?count|_?status|_?limit|_?score|_?bsuid"
    r"|_?prefix|_?suffix)$", re.I)


def _handlers() -> list[pathlib.Path]:
    return sorted(p for p in FUNCTIONS.rglob("*.py") if "__pycache__" not in str(p))


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    table: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[child] = node
    return table


def _consuming_call(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.Call | None:
    """The nearest enclosing Call, seeing through json.dumps()."""
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.Call):
            func = current.func
            if isinstance(func, ast.Attribute) and func.attr == "dumps":
                current = parents.get(current)
                continue
            return current
        current = parents.get(current)
    return None


def _is_logger(call: ast.Call | None) -> bool:
    if call is None or not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr not in LOG_LEVELS:
        return False
    owner = call.func.value
    name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
    return "logger" in str(name).lower() or "log" == str(name).lower()


def _is_sanitised(value: ast.expr) -> bool:
    """True when the expression cannot carry the identifying value through."""
    if isinstance(value, ast.Constant):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in ("mask_phone", "mask_email", "mask", "redact_pii", "redact_string",
                    "bool", "len", "last4", "_mask", "_mask_tail", "_mask_phone"):
            return True
    # A SLICE truncates and is therefore safe (`phone[-4:]`, `phone[:6]`). An INDEX does
    # not: `contact['id']` is a dict lookup that returns the whole value, and treating
    # the two alike hid two raw contact ids behind `existing['id']` and `contact['id']`.
    if isinstance(value, ast.Subscript):
        return isinstance(value.slice, ast.Slice)
    if isinstance(value, ast.BoolOp):             # x or None / x or ''
        return all(_is_sanitised(v) for v in value.values)
    if isinstance(value, ast.IfExp):
        return _is_sanitised(value.body) and _is_sanitised(value.orelse)
    if isinstance(value, ast.BinOp):              # phone[:6] + '***'
        return True
    return False


def offences() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _handlers():
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:                                   # pragma: no cover
            pytest.fail(f"{path} does not parse: {type(exc).__name__}")
        parents = _parents(tree)
        lines = source.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            if not _is_logger(_consuming_call(node, parents)):
                continue
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                name = key.value
                if NOT_SENSITIVE_KEY.search(name):
                    continue
                if not (PHONE_KEY.match(name) or PERSON_KEY.match(name)):
                    continue
                if _is_sanitised(value):
                    continue
                line = getattr(value, "lineno", node.lineno)
                found.append((str(path.relative_to(ROOT)), line, lines[line - 1].strip()))
    return found


def test_no_unmasked_phone_or_name_in_a_log_line():
    found = offences()
    if found:
        rendered = "\n".join(f"  {p}:{n}  {code}" for p, n, code in found)
        pytest.fail(
            f"{len(found)} logging site(s) put a subscriber number or a person's name "
            f"into CloudWatch in clear text.\n"
            f"Wrap the value in mask_phone() / mask_email() from lambda_utils.privacy, or "
            f"log only its presence with bool(). Do NOT change a dict that is an API "
            f"payload or a stored item -- read this module's docstring first.\n{rendered}"
        )


def test_the_masking_helpers_actually_mask():
    import sys
    sys.path.insert(0, str(FUNCTIONS / "shared"))
    from lambda_utils.privacy import mask_email, mask_phone

    assert mask_phone("+918100640044") == "+91****0044"
    assert mask_phone("") == "***"
    assert mask_phone("12345") == "***"
    # The point: country code and last four survive, the subscriber digits do not.
    assert "810064" not in mask_phone("+918100640044")
    assert mask_email("someone@wecare.digital") == "s***@wecare.digital"


def _classify(source: str) -> list[str]:
    """Labels in SOURCE order. `ast.walk` is breadth-first, so it must be sorted."""
    tree = ast.parse(source)
    parents = _parents(tree)
    labels = [(node.lineno,
               "LOG" if _is_logger(_consuming_call(node, parents)) else "DATA")
              for node in ast.walk(tree) if isinstance(node, ast.Dict)]
    return [label for _, label in sorted(labels)]


def test_the_detector_can_actually_see_an_offence():
    """A gate that cannot fail is not a gate.

    This is the failure mode `pageaudit.js` had: a census that treats every observation
    as a success is indistinguishable from one that is not running.
    """
    source = ("import json\n"
              "def h():\n"
              "    logger.info(json.dumps({'event': 'x', 'senderPhone': sender_phone}))\n")
    assert _classify(source) == ["LOG"]
    tree = ast.parse(source)
    value = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)][0].values[1]
    assert not _is_sanitised(value)


def test_the_masked_form_is_accepted():
    source = ("import json\n"
              "def h():\n"
              "    logger.info(json.dumps({'senderPhone': mask_phone(sender_phone)}))\n")
    tree = ast.parse(source)
    value = [n for n in ast.walk(tree) if isinstance(n, ast.Dict)][0].values[0]
    assert _is_sanitised(value)


def test_the_detector_does_not_judge_payloads_or_stored_items():
    """The three roles that a `'to': phone` entry can play, as real code."""
    payload = ("import json\n"
               "def send():\n"
               "    lambda_client.invoke(Payload=json.dumps({'to': whatsapp_phone}))\n")
    assert _classify(payload) == ["DATA"]

    stored = ("def store():\n"
              "    _store_call_log({'fromNumber': from_number, 'toNumber': to_number})\n")
    assert _classify(stored) == ["DATA"]

    item = ("def put():\n"
            "    table.put_item(Item={'senderPhone': sender_phone})\n")
    assert _classify(item) == ["DATA"]


def test_a_logger_call_near_a_store_call_is_not_confused_for_it():
    """The exact shape that broke `whatsapp-calling`'s stored call log.

    A `logger.info(...)` immediately above `_store_call_log({...})` made a
    nearest-logger-above heuristic classify the stored record as a log.
    """
    source = (
        "import json\n"
        "def h():\n"
        "    logger.info(json.dumps({'event': 'call_event', 'from': from_number}))\n"
        "    _store_call_log({\n"
        "        'fromNumber': from_number,\n"
        "        'callerName': caller_name,\n"
        "    })\n"
    )
    assert _classify(source) == ["LOG", "DATA"]


def test_raw_exception_text_is_not_logged_where_codeql_found_taint():
    """Fourteen sites logged `str(e)`.

    Steering is explicit that an exception's text may be logged only when our own code
    built it from known-safe parts, and CodeQL tracks taint across function boundaries,
    so a message boto3 assembled from a caller-supplied value is not safe. These now log
    `type(e).__name__`.
    """
    known = {
        "amplify/functions/ai/ai-generate-response/handler.py": 10,
        "amplify/functions/messaging/inbound-whatsapp-handler/handler.py": 1,
        "amplify/functions/messaging/outbound-whatsapp/handler.py": 1,
        "amplify/functions/messaging/partner-token-refresh/handler.py": 1,
        "amplify/functions/payments/razorpay-webhook/handler.py": 1,
    }
    for relative, expected in known.items():
        text = (ROOT / relative).read_text()
        actual = text.count("type(e).__name__")
        assert actual >= expected, (
            f"{relative} should log the exception TYPE at >= {expected} site(s); "
            f"found {actual}"
        )


# ── Flow tokens: a phone number hiding behind a key that does not look like one ──

#: A WhatsApp Flow token is `{prefix}-{uuid4}-waba-{n}-ph-{phone}` and
#: `flows/common.get_phone_from_token` recovers the number by splitting on `-ph-`. So a
#: log line carrying a whole Flow token carries a full E.164 number. Four sites did,
#: under the key `flowToken` -- which no phone-shaped-field-name check can see. This is
#: the class of finding that made the 202-alert CodeQL backlog worth reading rather than
#: dismissing: the signal was real and it was not where the noise was.
TOKEN_KEY = re.compile(r"^flow_?token$", re.I)


def _token_offences() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _handlers():
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:                                          # pragma: no cover
            continue
        parents = _parents(tree)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            if not _is_logger(_consuming_call(node, parents)):
                continue
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if not TOKEN_KEY.match(key.value):
                    continue
                masked = (
                    isinstance(value, ast.Call)
                    and getattr(value.func, "id", getattr(value.func, "attr", ""))
                    in ("mask_flow_token",)
                )
                if masked:
                    continue
                line = getattr(value, "lineno", node.lineno)
                found.append((str(path.relative_to(ROOT)), line, lines[line - 1].strip()))
    return found


def test_no_raw_flow_token_in_a_log_line():
    found = _token_offences()
    if found:
        rendered = "\n".join(f"  {p}:{n}  {code}" for p, n, code in found)
        pytest.fail(
            f"{len(found)} logging site(s) log a whole WhatsApp Flow token, whose "
            f"`-ph-` suffix IS the customer's phone number.\n"
            f"Use mask_flow_token() from lambda_utils.privacy.\n{rendered}"
        )


def test_mask_flow_token_removes_the_phone_and_keeps_the_correlation():
    import sys
    sys.path.insert(0, str(FUNCTIONS / "shared"))
    from lambda_utils.privacy import mask_flow_token

    token = "sr-2f1c9e5a-0d3b-4a7e-9c11-8b6d5e4f3a2b-waba-1-ph-+918100640044"
    masked = mask_flow_token(token)

    assert "918100640044" not in masked
    assert masked.endswith("-ph-***")
    # The half that makes a Flow token useful in a log survives: which flow, which
    # send, which business number.
    assert masked.startswith("sr-2f1c9e5a-0d3b-4a7e-9c11-8b6d5e4f3a2b-waba-1")

    # A token with no phone segment is returned unchanged rather than mangled.
    assert mask_flow_token("flow-abc-123") == "flow-abc-123"
    assert mask_flow_token("") == ""
    assert mask_flow_token(None) == ""


def test_the_arithmetic_truncation_is_gone():
    """`flow_token[:25]` was correct only because a uuid4 is 36 characters.

    It stops being correct the moment a prefix grows, and nothing would have failed.
    """
    handler = (ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py").read_text()
    assert "flow_token[:25]" not in handler


# ── contactId: an "opaque surrogate key" that is the phone number ────────────────

#: The field that looked safest of all, and was the largest disclosure in the tree.
#: `inbound-whatsapp-handler._deterministic_contact_id` mints a contact id as
#: `f'wa{digits}'` where digits are the normalised E.164, so a WhatsApp-originated
#: `contactId` IS the customer's number behind a two-character prefix -- and it is the
#: standard correlation field, so it appeared in 83 logger dicts. Contacts created
#: through the API get a uuid instead, which discloses nothing, which is why
#: `mask_contact_id` masks one form and passes the other through.
CONTACT_KEY = re.compile(r"^contact_?id$", re.I)


def _contact_offences() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _handlers():
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:                                          # pragma: no cover
            continue
        parents = _parents(tree)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            if not _is_logger(_consuming_call(node, parents)):
                continue
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if not CONTACT_KEY.match(key.value):
                    continue
                wrapped = (
                    isinstance(value, ast.Call)
                    and getattr(value.func, "id", getattr(value.func, "attr", ""))
                    == "mask_contact_id"
                )
                if wrapped or isinstance(value, ast.Constant):
                    continue
                line = getattr(value, "lineno", node.lineno)
                found.append((str(path.relative_to(ROOT)), line, lines[line - 1].strip()))
    return found


def test_no_unmasked_contact_id_in_a_log_line():
    found = _contact_offences()
    if found:
        rendered = "\n".join(f"  {p}:{n}  {code}" for p, n, code in found[:40])
        pytest.fail(
            f"{len(found)} logging site(s) log a raw contactId. The deterministic form "
            f"is 'wa' + the customer's E.164 digits.\n"
            f"Use mask_contact_id() from lambda_utils.privacy.\n{rendered}"
        )


def test_mask_contact_id_masks_the_phone_form_and_passes_the_uuid_form():
    import sys
    sys.path.insert(0, str(FUNCTIONS / "shared"))
    from lambda_utils.privacy import mask_contact_id

    # The deterministic form: wa + normalised digits.
    assert mask_contact_id("wa918100640044") == "wa***0044"
    assert "918100640" not in mask_contact_id("wa918100640044")

    # The API form is a uuid and carries nothing, so masking it would throw away a
    # usable correlation key for no gain.
    uuid_form = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
    assert mask_contact_id(uuid_form) == uuid_form

    assert mask_contact_id("") == ""
    assert mask_contact_id(None) == ""
    # `wa` followed by non-digits is not the deterministic form.
    assert mask_contact_id("wanderer") == "wanderer"


def test_the_deterministic_scheme_is_still_what_the_helper_assumes():
    """If the minting changes, this masking is wrong and should fail loudly.

    The helper keys on a literal `wa` prefix plus digits. That is only correct while
    `_deterministic_contact_id` produces it, so the assumption is pinned to the source
    rather than left implicit.
    """
    handler = (ROOT / "amplify/functions/messaging/inbound-whatsapp-handler/handler.py").read_text()
    assert "def _deterministic_contact_id" in handler
    assert "f'wa{digits}'" in handler, (
        "the deterministic contact-id format changed; re-check mask_contact_id"
    )


# ── f-strings: the spelling this module could not see ────────────────────────────

#: THE BLIND SPOT, found 2026-09-29.
#:
#: Everything above walks `ast.Dict` nodes, because the disclosures this module was written
#: for were structured logs: `logger.info(json.dumps({'senderPhone': sender_phone}))`. That
#: is the right shape to parse and the AST work above is what makes it safe to judge. But a
#: dict is not the only way to put a number in a log line, and the other way had no coverage
#: at all:
#:
#:     logger.info(f"IVR response sent to {sender_phone} for {button_id}")
#:     logger.info(f"INBOUND CALL from {caller_name or from_number} ...")
#:     logger.info(f'[{request_id}] Sent to {formatted_phone}: {msg_id}')
#:
#: There is no `ast.Dict` anywhere in those, so `offences()` returned clean while eleven
#: sites across five handlers logged full E.164 numbers - and one logged the customer's
#: WhatsApp profile name with a fallback to their number, so which of the two it disclosed
#: depended on a value the log did not record.
#:
#: CodeQL found six of the eleven. It missed five because taint has to reach the site, and
#: this module missed all eleven because it was looking for the wrong node type. Two
#: independent checks, both green, one real defect - which is the argument for asserting the
#: property rather than either tool's reachable subset.
#:
#: The classifier is reused wholesale: `_consuming_call` + `_is_logger` decide that an
#: f-string really is inside a logger call rather than inside a payload built with an
#: f-string, and `_is_sanitised` decides whether the interpolated expression reduces the
#: value. So `{mask_phone(to)}`, `{bool(caller_name)}` and `{phone[-4:]}` all pass, exactly
#: as they do in a dict.


def _formatted_values(tree: ast.AST):
    """Every `{...}` placeholder in the file, with the JoinedStr that holds it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.FormattedValue):
                    yield node, part


def _interpolated_name(expr: ast.expr) -> str:
    """The identifying NAME a placeholder expression refers to, or ''.

    Three shapes carry a phone number in these handlers and all three must be read:

        {to_number}                      Name
        {call.recipient_phone}           Attribute
        {metadata['display_phone_number']}  Subscript with a constant index

    A Subscript with a SLICE is excluded here on purpose - `_is_sanitised` already treats
    `phone[-4:]` as safe, and re-reporting it would make the gate wrong in the direction
    that gets gates switched off.
    """
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant):
        return str(expr.slice.value)
    if isinstance(expr, ast.Call):
        # `metadata.get('display_phone_number', 'N/A')` - the key names the value, and this
        # is the exact form the whatsapp-calling webhook used.
        func = expr.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and expr.args:
            first = expr.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value
    return ""


def _sensitive_names(expr: ast.expr) -> list[str]:
    """Names in EXPR that identify a subscriber, looking through `or` fallbacks.

    `caller_name or from_number` must be judged on both operands. `_is_sanitised` already
    refuses that BoolOp, but the reported name should say which field leaked rather than
    just pointing at the line.
    """
    if isinstance(expr, ast.BoolOp):
        return [n for value in expr.values for n in _sensitive_names(value)]
    name = _interpolated_name(expr)
    if not name or NOT_SENSITIVE_KEY.search(name):
        return []
    return [name] if (PHONE_KEY.match(name) or PERSON_KEY.match(name)) else []


def fstring_offences() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in _handlers():
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:                                   # pragma: no cover
            pytest.fail(f"{path} does not parse: {type(exc).__name__}")
        parents = _parents(tree)
        lines = source.splitlines()

        for joined, part in _formatted_values(tree):
            if not _is_logger(_consuming_call(joined, parents)):
                continue
            if _is_sanitised(part.value):
                continue
            names = _sensitive_names(part.value)
            if not names:
                continue
            line = getattr(part.value, "lineno", joined.lineno)
            found.append((str(path.relative_to(ROOT)), line,
                          f"{{{'/'.join(names)}}}  {lines[line - 1].strip()[:110]}"))
    return found


def test_no_unmasked_phone_or_name_in_a_logged_fstring():
    found = fstring_offences()
    if found:
        rendered = "\n".join(f"  {p}:{n}  {code}" for p, n, code in found)
        pytest.fail(
            f"{len(found)} logger f-string(s) interpolate a subscriber number or a "
            f"person's name in clear text.\n"
            f"Wrap the value in mask_phone() from lambda_utils.privacy, or log only its "
            f"presence with bool() / its shape with len().\n{rendered}"
        )


def _fstring_labels(source: str) -> list[tuple[int, bool, list[str]]]:
    tree = ast.parse(source)
    parents = _parents(tree)
    out = []
    for joined, part in _formatted_values(tree):
        out.append((
            getattr(part.value, "lineno", joined.lineno),
            _is_logger(_consuming_call(joined, parents)),
            [] if _is_sanitised(part.value) else _sensitive_names(part.value),
        ))
    return sorted(out)


def test_the_fstring_detector_can_actually_see_an_offence():
    """Every real shape that was leaking, plus every shape that must stay quiet."""
    # The bare name.
    assert _fstring_labels(
        'def h():\n    logger.info(f"sent to {to_number} ok")\n'
    ) == [(2, True, ["to_number"])]

    # The name-or-number fallback, which discloses one of two things.
    assert _fstring_labels(
        'def h():\n    logger.info(f"from {caller_name or from_number}")\n'
    ) == [(2, True, ["caller_name", "from_number"])]

    # `.get()` on a webhook metadata dict - the whatsapp-calling webhook's form.
    assert _fstring_labels(
        'def h():\n'
        '    logger.info(f"dp={metadata.get(\'display_phone_number\', \'N/A\')}")\n'
    ) == [(2, True, ["display_phone_number"])]

    # Post-normalisation name, which the original PHONE_KEY alternation did not cover.
    #
    # Selected by predicate rather than by index. The first draft asserted `[0][2]` and
    # failed, because both placeholders sit on line 2 and `sorted()` falls through to
    # comparing the name lists, where `[]` (from `{msg_id}`) sorts before
    # `['formatted_phone']`. An index into a sorted list is a positional assumption; the
    # thing being asserted is "the phone placeholder is flagged", so say that.
    flagged = [names for _, _, names in _fstring_labels(
        'def h():\n    logger.info(f"Sent to {formatted_phone}: {msg_id}")\n'
    ) if names]
    assert flagged == [["formatted_phone"]]


def test_the_fstring_detector_stays_quiet_where_it_should():
    masked = 'def h():\n    logger.info(f"sent to {mask_phone(to_number)} ok")\n'
    assert _fstring_labels(masked) == [(2, True, [])]

    presence = 'def h():\n    logger.info(f"named: {bool(caller_name)}")\n'
    assert _fstring_labels(presence) == [(2, True, [])]

    shape = 'def h():\n    logger.info(f"len={len(formatted_phone)}")\n'
    assert _fstring_labels(shape) == [(2, True, [])]

    tail = 'def h():\n    logger.info(f"tail={to_number[-4:]}")\n'
    assert _fstring_labels(tail) == [(2, True, [])]

    # An opaque Meta business identifier is NOT a subscriber number. Masking it would
    # destroy a correlation key this repo's own docs publish, and `NOT_SENSITIVE_KEY`
    # is what keeps the gate off it.
    opaque = 'def h():\n    logger.info(f"pid={phone_number_id} aws={aws_phone_id}")\n'
    assert [names for _, _, names in _fstring_labels(opaque)] == [[], []]

    # An f-string building a REQUEST, not a log. Masking this would break sending, which
    # is the same distinction the dict classifier above exists to make.
    payload = ('def h():\n'
               '    urllib.request.Request(f"https://graph/{to_number}/messages")\n')
    assert [is_log for _, is_log, _ in _fstring_labels(payload)] == [False]
