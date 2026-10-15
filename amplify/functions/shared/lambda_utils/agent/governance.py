"""What the AI action group is allowed to do, and what it is refused.

Why this module exists
---------------------
`ai/agent-action-group` exposed twelve tools to a Bedrock agent, and eight of them
were things a language model should not be able to choose on its own:

  * SEND - `sendWhatsApp`, `sendSms`, `sendEmail` invoked `wecare-outbound-*`
    with a phone number and a body. No plan, no approval, no receipt. The model's
    tool choice was the authorisation, and the result was a real message to a real
    customer under our registered sender.
  * SCAN - `searchContacts` paginated the whole ContactsTable to exhaustion and
    then filtered in Python. `getStats` did three exhaustive scans. `getMessages`
    scanned both message tables. Every one of those was a `while True` on
    `LastEvaluatedKey`, billed per read, triggered by a model's whim.
  * DELETE - `deleteMessage` hard-deleted from the message store; `deleteContact`
    wrote a `deletedAt` marker.
  * FABRICATE - `createInvoice` returned `{'success': True, 'invoiceId':
    'INV-xxxxxxxx'}` and wrote nothing whatsoever.

The last one is the worst of the four and explains the shape of everything here. A
confident success that did not happen is more damaging than an error, because the
agent repeats it to a person, who then waits for an invoice that does not exist.

So: READ and status tools are enabled. Every APPLY tool is refused
**structurally**. There is deliberately no flag, because the approval, plan-hash
and receipt machinery that would make an APPLY safe does not exist yet - a flag
added now would be a switch nobody could safely throw, and the first person to
find it would throw it.

Three bugs were hiding inside the removed powers
------------------------------------------------
Worth recording, because each is invisible until you look at the power itself:

  * `_delete_message` wrapped the inbound delete in `try/except: pass` then
    deleted from outbound. DynamoDB's `delete_item` SUCCEEDS on a key that does
    not exist, so the inbound attempt never raised, the outbound branch was
    unreachable, and the function reported "deleted successfully" for any id -
    including one that never existed.
  * `_delete_contact` used `update_item ... SET deletedAt` with no existence
    check. DynamoDB upserts, so an unknown id CREATED a row holding nothing but
    `{id, deletedAt}`. A delete that manufactured records.
  * `_find_contact_by_phone` scanned with `contains(phone, last10)` and `Limit=1`.
    `Limit` applies BEFORE the FilterExpression, so it examined one arbitrary item
    and filtered it away, normally finding nobody; and `contains` is a substring
    match, so a hit could be the wrong person. ContactsTable has a `phone-index`
    GSI with an ALL projection, so the scan was never needed - `query_index`
    replaces it with an exact lookup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# Tool classes.
CLASS_READ = "READ"
CLASS_PLAN = "PLAN"
CLASS_APPLY = "APPLY"

# Catalog version. Bumped by hand when a tool's NAME, CLASS or ENABLEMENT changes -
# deliberately not on every deploy, and deliberately not a timestamp. A version that
# moved on each deploy would invalidate every outstanding plan, and a mechanism that
# invalidates everything weekly gets abandoned within a month.
#
# `plans.catalog_fingerprint()` computes the shape independently, so a reclassified
# tool is caught even if somebody forgets to bump this.
CATALOG_VERSION = "2"

# Kill switches. They SUBTRACT ONLY.
#
# `AGENT_DISABLED_TOOLS` is a comma-separated list of tools to switch off, and
# `AGENT_TOOLS_KILL_SWITCH` turns everything off. There is deliberately no variable
# that turns anything ON: a switch able to enable a send is a live-send flag by
# another name, and the first person to find it under pressure would throw it.
# `tests/test_agent_plans.py` asserts that across a list of plausible names.
ENV_DISABLED_TOOLS = "AGENT_DISABLED_TOOLS"
ENV_KILL_SWITCH = "AGENT_TOOLS_KILL_SWITCH"

# Read bounds live in lambda_utils.dynamo_reads and are re-exported at the foot of
# this module, so `gov.DEFAULT_READ_LIMIT` keeps working.


class ToolUnknown(KeyError):
    """The requested tool is not in the catalog. Never guessed at."""


# Which agent surface offers a tool. Two exist and they name the same capabilities
# differently: the Bedrock action group uses camelCase (`sendWhatsApp`) and the
# dashboard chat loop in `/ai/generate` uses snake_case (`send_whatsapp`).
#
# Both spellings are first-class catalog entries rather than one being canonical,
# because both are live and renaming either would change a live response shape. What
# matters is that the two spellings of one capability can never disagree about their
# class or their enablement, and `tests/test_agent_surfaces.py` asserts exactly that.
SURFACE_AGENT = "agent"        # Bedrock action group, camelCase
SURFACE_INTERNAL = "internal"  # dashboard chat tool loop, snake_case


@dataclass(frozen=True)
class Tool:
    name: str
    tool_class: str
    enabled: bool
    summary: str
    # Model-facing. Short, actionable, and free of topology: it travels back
    # through Bedrock into a prompt and then into a transcript.
    refusal: str = ""
    # Operator-facing forensics: WHY the power was removed, in implementation
    # terms. Deliberately excluded from `catalog_summary()`, because table names,
    # function names and API semantics are not a model's business - but they are
    # exactly what the next engineer needs so the power is not reintroduced.
    detail: str = ""
    # Which surface offers this spelling.
    surface: str = SURFACE_AGENT
    # The same capability's name on the other surface, when there is one. Used only
    # to assert the two cannot diverge; not exposed to a model.
    counterpart: str = ""


class ToolRefused(PermissionError):
    """The tool exists and is deliberately not executable."""

    def __init__(self, tool: str, tool_class: str, reason: str) -> None:
        super().__init__(reason)
        self.tool = tool
        self.tool_class = tool_class
        self.reason = reason

    def as_result(self) -> Dict[str, Any]:
        """The refusal, in the shape the handler returns.

        Carries `success: False` AND an explicit `refused: True`, and deliberately
        no key a caller could read as a completed side effect - no `invoiceId`, no
        `messageId`, no `sentAt`. That is the direct lesson of the placeholder
        `createInvoice`.
        """
        return {
            "success": False,
            "refused": True,
            "tool": self.tool,
            "toolClass": self.tool_class,
            "error": self.reason,
        }


_APPROVAL = (
    "Sending is refused. It needs an approved plan and a recorded receipt, and "
    "neither exists yet. Draft what you would send and hand it to a person for "
    "approval - do not state that anything was sent."
)

_APPROVAL_DETAIL = (
    "A model's tool choice is not an approval. This invoked the outbound sender "
    "directly with a phone number and a body, so the model's decision was the only "
    "authorisation between it and a real customer, under our registered sender. "
    "Build the plan-hash / approval / receipt path first, then route the send "
    "through it."
)

CATALOG: Dict[str, Tool] = {
    # ---------------- enabled: READ and status ----------------
    "getContact": Tool(
        name="getContact", tool_class=CLASS_READ, enabled=True,
        summary="Look up one contact by id, phone or email."),
    "searchContacts": Tool(
        name="searchContacts", tool_class=CLASS_READ, enabled=True,
        summary="Find contacts matching a query. Bounded and may be truncated."),
    "getMessages": Tool(
        name="getMessages", tool_class=CLASS_READ, enabled=True,
        summary="Recent messages for one contact. Bounded and may be truncated."),
    "getStats": Tool(
        name="getStats", tool_class=CLASS_READ, enabled=True,
        summary="Approximate counts of contacts and messages."),
    "listTools": Tool(
        name="listTools", tool_class=CLASS_READ, enabled=True,
        summary=("List the tools available now, and the ones that are refused with "
                 "the reason. Call this rather than guessing at a tool name.")),

    # ---------------- refused: APPLY ----------------
    "sendWhatsApp": Tool(
        name="sendWhatsApp", tool_class=CLASS_APPLY, enabled=False,
        summary="Send a WhatsApp message to a contact.",
        refusal=_APPROVAL, detail=_APPROVAL_DETAIL),
    "sendSms": Tool(
        name="sendSms", tool_class=CLASS_APPLY, enabled=False,
        summary="Send an SMS to a contact.",
        refusal=_APPROVAL, detail=_APPROVAL_DETAIL),
    "sendEmail": Tool(
        name="sendEmail", tool_class=CLASS_APPLY, enabled=False,
        summary="Send an email to a contact.",
        refusal=_APPROVAL, detail=_APPROVAL_DETAIL),
    "createContact": Tool(
        name="createContact", tool_class=CLASS_APPLY, enabled=False,
        summary="Create a contact.",
        refusal=("Creating a contact record is refused here. Ask a person to "
                 "create it, then look it up."),
        detail=("The contact service owns creation, including the invariant that "
                "`id` is the physical key and `contactId` is its alias. A second "
                "writer duplicating that logic is how the two drift apart.")),
    "updateContact": Tool(
        name="updateContact", tool_class=CLASS_APPLY, enabled=False,
        summary="Update a contact.",
        refusal=("Changing a contact record is refused here. Report what should "
                 "change and let a person apply it."),
        detail=("An unreviewed field-level update chosen by a model can overwrite "
                "provenance-bearing fields, which the identity work records per "
                "field precisely so an import cannot be admitted wholesale.")),
    "deleteContact": Tool(
        name="deleteContact", tool_class=CLASS_APPLY, enabled=False,
        summary="Mark a contact deleted.",
        refusal="Deleting a contact is refused. Only a person can do that.",
        detail=("The previous implementation used an unconditional `update_item`, "
                "which DynamoDB treats as an upsert, so deleting an unknown id "
                "CREATED a row containing only `{id, deletedAt}`. A delete that "
                "manufactures records. Deletion needs an existence check and a "
                "reviewed path.")),
    "deleteMessage": Tool(
        name="deleteMessage", tool_class=CLASS_APPLY, enabled=False,
        summary="Delete a message.",
        refusal=("Deleting a message is refused. Messages are the record of what "
                 "was said to a customer, so only a person can remove one. Do not "
                 "state that a message was deleted."),
        detail=("The previous implementation reported success for any id at all: "
                "`delete_item` succeeds on a key that does not exist, the inbound "
                "attempt was wrapped in `try/except: pass`, so the outbound branch "
                "was unreachable and every call returned 'deleted successfully'.")),
    "createInvoice": Tool(
        name="createInvoice", tool_class=CLASS_APPLY, enabled=False,
        summary="Create an invoice for a contact.",
        refusal=("Creating an invoice is refused here. Do not state that an "
                 "invoice exists; request one through the invoice service and "
                 "report only a number it returns."),
        detail=("The previous implementation fabricated `INV-<random>` and wrote "
                "nothing, so the agent told people an invoice existed when it did "
                "not. The invoice-engine function owns the GST number sequence, "
                "and minting an identifier outside it breaks that series.")),
}

# --------------------------------------------------------------------------
# The dashboard chat surface: /ai/generate, context='internal-admin'
# --------------------------------------------------------------------------
# Added 2026-09-23, and this is the half that mattered.
#
# Phase 6.1 removed eight ungoverned powers from the Bedrock action group - a
# surface that cannot currently be reached at all, because agent 4UUQYFWX64 is
# NOT_PREPARED. Meanwhile the surface every operator actually uses, `/ai/generate`
# with `context: 'internal-admin'`, ran a 30-tool Bedrock Converse loop whose
# `_execute_internal_tool` dispatched straight to live sends and hard deletes:
# `send_whatsapp_pay`, `make_voice_call`, `delete_messages`, `delete_media_files`
# and `clear_all_contact_data` among them. Three UIs are wired to it
# (FloatingAgent, InternalChatTab, the dashboard AI tab).
#
# Its system prompt did not merely permit that, it pushed for it:
#     "ALWAYS use your tools to execute tasks. Never explain how to do something
#      manually." / "Be proactive: 'send message to Jignesh' -> search first, then
#      send." / "For payment requests, use send_whatsapp_pay tool directly."
#
# The only guard anywhere was a substring match in FloatingAgent against the text
# the USER typed - `['delete all', 'clear all', ...]` - evaluated before the model
# had chosen anything, so "tidy up Asha's records" reached `clear_all_contact_data`
# without a prompt. InternalChatTab had no guard at all, and its 30 tool checkboxes
# were display-only: the toggles were never included in the request body.
#
# So the same policy now covers both surfaces. 12 READ, 18 APPLY.
_SEND = (
    "Sending is refused. Draft what you would send and hand it to a person for "
    "approval - do not state that anything was sent."
)
_SEND_DETAIL = (
    "This dispatched to a live outbound sender chosen by the model, so the model's "
    "tool selection was the only authorisation between a chat box and a real "
    "customer under our registered sender. Route it through the plan / approval / "
    "receipt path before re-enabling."
)
_DESTRUCTIVE = (
    "Deleting data is refused. Report what you believe should be removed and let a "
    "person do it. Do not state that anything was deleted."
)


def _read(name: str, summary: str, counterpart: str = "") -> Tool:
    return Tool(name=name, tool_class=CLASS_READ, enabled=True, summary=summary,
                surface=SURFACE_INTERNAL, counterpart=counterpart)


def _apply(name: str, summary: str, refusal: str, detail: str,
           counterpart: str = "") -> Tool:
    return Tool(name=name, tool_class=CLASS_APPLY, enabled=False, summary=summary,
                refusal=refusal, detail=detail, surface=SURFACE_INTERNAL,
                counterpart=counterpart)


CATALOG.update({
    # ---------------- READ: enabled ----------------
    "search_contacts": _read("search_contacts", "Find contacts by name, phone or email.",
                             counterpart="searchContacts"),
    "get_messages": _read("get_messages", "Recent messages for a contact.",
                          counterpart="getMessages"),
    "get_stats": _read("get_stats", "Dashboard counts.", counterpart="getStats"),
    "get_voice_cdr": _read("get_voice_cdr", "Recent voice call records."),
    "get_billing_summary": _read("get_billing_summary", "AWS spend summary."),
    "get_invoice_list": _read("get_invoice_list", "Existing invoices."),
    "get_products": _read("get_products", "Storefront products from the native catalog."),
    "get_orders": _read("get_orders", "Customer orders from the native order store."),
    "list_media_files": _read("list_media_files", "Stored media files."),
    "list_scheduled_messages": _read("list_scheduled_messages",
                                     "Messages already scheduled."),
    "list_submit_requests": _read("list_submit_requests", "Flow submissions."),
    "list_templates": _read("list_templates", "Approved message templates."),

    # ---------------- APPLY: refused ----------------
    # Sends. Every one of these reached a real recipient on the model's decision.
    "send_whatsapp": _apply("send_whatsapp", "Send a WhatsApp message.",
                            _SEND, _SEND_DETAIL, counterpart="sendWhatsApp"),
    "send_whatsapp_buttons": _apply("send_whatsapp_buttons",
                                    "Send an interactive button message.",
                                    _SEND, _SEND_DETAIL),
    "send_whatsapp_flow": _apply("send_whatsapp_flow", "Send a WhatsApp Flow.",
                                 _SEND, _SEND_DETAIL),
    "send_template": _apply("send_template", "Send an approved template.",
                            _SEND, _SEND_DETAIL),
    "send_sms": _apply("send_sms", "Send an SMS.", _SEND, _SEND_DETAIL,
                       counterpart="sendSms"),
    "send_email": _apply("send_email", "Send an email.", _SEND, _SEND_DETAIL,
                         counterpart="sendEmail"),
    "make_voice_call": _apply(
        "make_voice_call", "Place a voice call to a contact.", _SEND,
        "A model placing a PSTN call is a send with a per-minute cost and a person "
        "on the other end. " + _SEND_DETAIL),
    "send_whatsapp_pay": _apply(
        "send_whatsapp_pay", "Send a payment request.",
        "Requesting money is refused. Prepare the details for a person to review; "
        "do not state that a payment request was sent.",
        "This asked a customer for money on the model's decision. Payment capture, "
        "refund and payment-configuration changes are prohibited outright, and a "
        "payment REQUEST is the same conversation with the customer."),
    "schedule_message": _apply(
        "schedule_message", "Schedule a message for later.",
        "Scheduling a message is refused - it is a send with a delay. Hand the "
        "details to a person; do not state that anything was scheduled.",
        "A deferred send is still a send, and it is worse to review after the fact "
        "because the model that chose it is long gone by the time it goes out."),
    "create_invoice": _apply(
        "create_invoice", "Create an invoice.",
        "Creating an invoice is refused here. Do not state that an invoice exists.",
        "The invoice-engine function owns the GST number sequence; minting a number "
        "outside it breaks that series.", counterpart="createInvoice"),

    # Contact writes.
    "create_contact": _apply(
        "create_contact", "Create a contact.",
        "Creating a contact record is refused here. Ask a person to create it.",
        "The contact service owns creation, including the invariant that `id` is "
        "physical and `contactId` is its alias.", counterpart="createContact"),
    "update_contact": _apply(
        "update_contact", "Update a contact.",
        "Changing a contact record is refused here. Report what should change and "
        "let a person apply it.",
        "An unreviewed field-level update chosen by a model can overwrite "
        "provenance-bearing fields.", counterpart="updateContact"),
    "add_contact_email": _apply(
        "add_contact_email", "Add an email to a contact.",
        "Changing a contact record is refused here. Report it and let a person "
        "apply it.",
        "Same writer-ownership reasoning as update_contact; an email address is the "
        "field an account-recovery path would trust."),

    # Deletes. The sharpest of the set.
    "delete_contact": _apply("delete_contact", "Delete a contact.",
                             _DESTRUCTIVE,
                             "An unconditional marker write, which DynamoDB treats "
                             "as an upsert - so deleting an unknown id created a "
                             "row rather than removing one.",
                             counterpart="deleteContact"),
    "delete_messages": _apply(
        "delete_messages", "Delete a contact's messages.", _DESTRUCTIVE,
        "Messages are the record of what was said to a customer. A model choosing "
        "to remove them destroys the evidence of its own earlier actions."),
    "delete_media_files": _apply(
        "delete_media_files", "Delete stored media.", _DESTRUCTIVE,
        "Media referenced by a sent message; deleting it breaks the record "
        "retrospectively."),
    "clear_all_contact_data": _apply(
        "clear_all_contact_data", "Erase everything held about a contact.",
        _DESTRUCTIVE,
        "The widest blast radius in the whole tool set, and it was reachable from a "
        "chat box. The only guard was FloatingAgent matching the substring 'clear "
        "all' in what the user typed, so any phrasing the model interpreted as "
        "tidying up - and every request routed through InternalChatTab, which had "
        "no guard at all - went straight through."),
})


def resolve(name: str) -> Tool:
    """The catalog entry, or `ToolUnknown`. Never a default."""
    key = str(name or "")
    if key not in CATALOG:
        raise ToolUnknown(f"unknown tool: {key!r}")
    return CATALOG[key]


def killed_tools() -> frozenset:
    """Tools switched off by the environment, lowercased for comparison.

    Read on every call rather than cached at import: this is an incident-response
    control, and a value that only takes effect after every warm sandbox recycles is
    not one. An unrecognised name is ignored, because a typo in an incident variable
    must not take the working tools down with it.
    """
    raw = os.environ.get(ENV_DISABLED_TOOLS, "") or ""
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def kill_switch_engaged() -> bool:
    return str(os.environ.get(ENV_KILL_SWITCH, "")).strip().lower() in (
        "1", "true", "yes", "on")


def is_enabled(name: str) -> bool:
    """Whether the tool may run right now.

    Catalog enablement AND the kill switches. The two combine with `and`, never
    `or` - that is what makes the environment unable to promote a refused tool.
    """
    try:
        tool = resolve(name)
    except ToolUnknown:
        return False
    if not tool.enabled:
        return False
    if kill_switch_engaged():
        return False
    return tool.name.lower() not in killed_tools()


def assert_executable(name: str) -> Tool:
    """The catalog entry, if it may run. Raises `ToolRefused` otherwise."""
    tool = resolve(name)
    if not tool.enabled:
        raise ToolRefused(tool.name, tool.tool_class, tool.refusal)
    if kill_switch_engaged():
        raise ToolRefused(
            tool.name, tool.tool_class,
            "All agent tools are switched off by the global kill switch. This is "
            "deliberate and temporary; report it rather than working around it.")
    if tool.name.lower() in killed_tools():
        raise ToolRefused(
            tool.name, tool.tool_class,
            f"{tool.name} is switched off by the kill switch. This is deliberate "
            f"and temporary - it is not the same as a tool that is never allowed.")
    return tool


def tools_for(surface: str) -> Dict[str, Tool]:
    """Catalog entries offered by one surface.

    The two surfaces name the same capabilities differently, so a model must be told
    only the spelling its own surface accepts. Handing it both would invite it to
    call `sendWhatsApp` on a loop that dispatches `send_whatsapp`, and the resulting
    "unknown tool" would look like a bug rather than a naming mismatch.
    """
    return {t.name: t for t in CATALOG.values() if t.surface == surface}


def catalog_summary(surface: str = SURFACE_AGENT) -> Dict[str, Any]:
    """What a model may be told about its own tools.

    Names, classes and summaries only. No table name, function name or ARN - a
    model does not need the topology to call a tool, and anything put here ends up
    in a prompt, then in a transcript.

    `enabled` reflects live enablement including the kill switches, not just the
    catalog default, so a switched-off tool is not advertised as available.
    """
    scoped = tools_for(surface)
    return {
        "enabled": {t.name: {"class": t.tool_class, "summary": t.summary}
                    for t in scoped.values() if is_enabled(t.name)},
        "refused": {t.name: {"class": t.tool_class, "reason": t.refusal}
                    for t in scoped.values() if not is_enabled(t.name)},
    }


# --------------------------------------------------------------------------
# bounded reads
# --------------------------------------------------------------------------
# Moved to lambda_utils/dynamo_reads.py on 2026-09-23 and re-exported here.
#
# They were written for this module, to stop a language model paginating a whole
# table on a whim - but the problem is not agent-specific. `messaging/ad-attribution`
# had the same shape reached from an ordinary HTTP route, and worse in one respect: it
# passed no `Limit` to DynamoDB at all. Two copies of one rule is how the
# stage-prefix bug came back twice before `http_path` was given a shared home.
#
# Re-exported rather than relocated outright so every existing caller and test keeps
# working through `gov.read_page` / `gov.bounded_limit`.
from lambda_utils.dynamo_reads import (  # noqa: E402,F401
    DEFAULT_READ_LIMIT,
    MAX_READ_LIMIT,
    bounded_limit,
    query_index,
    read_page,
)
