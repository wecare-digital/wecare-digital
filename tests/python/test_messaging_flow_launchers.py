"""MSG-2 follow-up: every Flow launcher's token reaches a handler that can serve it.

MSG-2 made the legacy endpoint handlers (Submit Request `sr`, Amend, Track Request, Order
Notes, Appointment, Sehat, Enterprise Assist, generic) and the router's INIT fallback refuse a
token that has no server-issued flow_sessions session (HTTP 427). These tests pin what each
current launcher's token reaches when the Flow opens, so a launcher that starts minting a
session-less token for a session-checking handler fails here, not on a customer's handset:

* every `mint_token` call in the Lambdas records a session in the same function, or mints a
  prefix whose INIT is a static screen that reads no customer data;
* the session-issuing launchers (paid services, F001) reach their own session-checking
  handler, never a legacy MSG-2 handler;
* outbound-whatsapp's default token for each registered Flow-button template, and the paid
  invoice's review token, open a static screen or are refused at the router.
"""
import ast
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
FUNCTIONS = ROOT / "amplify/functions"
BUSINESS_API = FUNCTIONS / "messaging/whatsapp-business-api"
OUTBOUND = FUNCTIONS / "messaging/outbound-whatsapp/handler.py"
PHONE = "919800000003"

#: Token prefix -> the handler its INIT reaches. Each one verifies the session itself.
SESSION_CHECKED = {
    "srpaid": "paid_service_targets.handle_init",
    "amendpaid": "paid_service_targets.handle_init",
    "request_pickup": "paid_service_targets.handle_init",
    "drop_docs": "drop_docs.handle_init",
    "shipments": "shipments.handle_init",
    "subscribe": "subscribe_profile.route",
}
#: Token prefix -> the static screen its INIT answers, with no session and no data read.
STATIC_INIT = {"leave": "FEEDBACK", "referral": "REFER"}

#: Every INIT destination the router can import, recorded instead of run.
DESTINATIONS = (
    ("paid_service_targets", "handle_init"), ("drop_docs", "handle_init"),
    ("shipments", "handle_init"), ("subscribe_profile", "route"),
    # The MSG-2 session-required handlers.
    ("submit_request", "handle_init"), ("amend_request", "handle_f005_init"),
    ("track_request", "handle_init"), ("order_notes", "handle_init"),
    ("appointment", "handle_init"), ("sehat_appointment", "handle_init"),
    ("enterprise_assist", "handle_init"), ("generic", "handle_welcome"),
    ("generic", "handle_form"), ("generic", "handle_any_screen"),
)


@pytest.fixture(scope="module")
def flows():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    sys.path.insert(0, str(BUSINESS_API))
    try:
        from flows import (router, paid_service_targets, drop_docs, shipments,
                           subscribe_profile, submit_request, amend_request, track_request,
                           order_notes, appointment, sehat_appointment, enterprise_assist,
                           generic, service_flow_launcher)
        from lambda_utils import flow_sessions
        from lambda_utils.ecommerce import review_token
        yield SimpleNamespace(
            router=router, paid_service_targets=paid_service_targets, drop_docs=drop_docs,
            shipments=shipments, subscribe_profile=subscribe_profile,
            submit_request=submit_request, amend_request=amend_request,
            track_request=track_request, order_notes=order_notes, appointment=appointment,
            sehat_appointment=sehat_appointment, enterprise_assist=enterprise_assist,
            generic=generic, service_flow_launcher=service_flow_launcher,
            flow_sessions=flow_sessions, review_token=review_token)
    finally:
        sys.path.remove(str(BUSINESS_API))


@pytest.fixture
def reached(flows, monkeypatch):
    """Names of the handlers a routed request reached. Nothing touches a store."""
    hits = []

    def recorder(name):
        def record(*_args, **_kwargs):
            hits.append(name)
            return {"screen": "RECORDED", "data": {}}
        return record

    for module, attr in DESTINATIONS:
        monkeypatch.setattr(getattr(flows, module), attr, recorder(f"{module}.{attr}"))
    monkeypatch.setattr(flows.router, "log_flow_event", lambda *_a, **_k: None)
    return hits


def _init(flows, token):
    return flows.router.route_flow(action="INIT", screen="", data={}, flow_token=token,
                                   request_id="req")


def _unsessioned(flows, prefix):
    """A token minted the way launchers mint it, with no session recorded."""
    return flows.flow_sessions.mint_token(prefix, PHONE, "1")


def _callee(call):
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


class _MintCalls(ast.NodeVisitor):
    """Each positional `mint_token(prefix, phone, ...)` call with its innermost function."""

    def __init__(self):
        self.stack, self.found = [], []

    def visit_FunctionDef(self, node):
        self.stack.append(node)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        # The PSTN browser-token minter takes keywords only; it is not a Flow token.
        if _callee(node) == "mint_token" and node.args and self.stack:
            self.found.append((self.stack[-1], node))
        self.generic_visit(node)


def _mint_sites():
    sites = []
    for path in sorted(FUNCTIONS.rglob("*.py")):
        if "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        visitor = _MintCalls()
        visitor.visit(ast.parse(path.read_text(), str(path)))
        for func, call in visitor.found:
            first = call.args[0]
            prefix = first.value if isinstance(first, ast.Constant) else None
            records = any(isinstance(n, ast.Call) and _callee(n) == "record_session"
                          for n in ast.walk(func))
            sites.append((path.relative_to(FUNCTIONS).as_posix(), func.name, prefix, records))
    return sites


def test_every_mint_site_records_a_session_or_opens_a_static_screen(flows, reached):
    sites = _mint_sites()
    found = {(path, name) for path, name, _prefix, _records in sites}
    assert {
        ("messaging/whatsapp-business-api/flows/service_flow_launcher.py",
         "_launch_verified_attempt"),
        ("messaging/whatsapp-business-api/flows/paid_drop_docs.py", "prepare_and_send"),
        ("messaging/whatsapp-business-api/flows/subscribe_profile.py", "launch_session_token"),
        ("messaging/whatsapp-business-api/handler.py", "_customer_leave_review_template"),
        ("messaging/whatsapp-business-api/handler.py", "_customer_referral_template"),
    } <= found
    for path, name, prefix, records in sites:
        assert records or prefix in STATIC_INIT, (
            f"{path}:{name} mints a {prefix or 'computed'!r} Flow token without recording a "
            "flow_sessions session; its handler would answer HTTP 427")
    for prefix, screen in STATIC_INIT.items():
        assert _init(flows, _unsessioned(flows, prefix)) == {"screen": screen, "data": {}}
    assert reached == []


def test_session_issuing_launchers_reach_their_own_session_checking_handler(flows, reached):
    prefixes = {spec.token_prefix for spec in flows.service_flow_launcher.LAUNCH_SPECS.values()}
    prefixes.add(flows.subscribe_profile.CONTRACT["tokenPrefix"])
    assert prefixes == set(SESSION_CHECKED)
    for prefix in sorted(prefixes):
        reached.clear()
        _init(flows, _unsessioned(flows, prefix))
        assert reached == [SESSION_CHECKED[prefix]], prefix


def _outbound_default_flow_key():
    """outbound-whatsapp's own template -> Flow-key inference, read from its source."""
    source = OUTBOUND.read_text()
    # The default token outbound builds when a caller sends a Flow button without one.
    assert ("or _infer_flow_key_from_template(template_name) or 'flow')" in source
            and "f'{_fb_key[:10]}-{uuid.uuid4()}-waba-{_fb_waba}-ph-{_fb_ph}'" in source), (
        "outbound's default Flow token changed: re-check which handler it reaches (MSG-2)")
    nodes = [node for node in ast.parse(source).body
             if (isinstance(node, ast.Assign)
                 and any(getattr(t, "id", "") == "_TEMPLATE_FLOW_KEYS" for t in node.targets))
             or (isinstance(node, ast.FunctionDef)
                 and node.name == "_infer_flow_key_from_template")]
    env = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(OUTBOUND), "exec"), env)
    return lambda name: env["_infer_flow_key_from_template"](name) or "flow"


def test_outbound_default_token_never_reaches_a_customer_data_handler(flows, reached):
    from lambda_utils import whatsapp_templates

    flow_key = _outbound_default_flow_key()
    templates = [t for t in whatsapp_templates.ALL if "flow" in t.buttons]
    assert templates
    for template in templates:
        key = flow_key(template.name)
        token = f"{key[:10]}-{uuid.uuid4()}-waba-1-ph-{PHONE}"
        if key in STATIC_INIT:
            assert _init(flows, token) == {"screen": STATIC_INIT[key], "data": {}}
        else:
            # A staff or scheduled send with no server token: refused (427), nothing read.
            with pytest.raises(flows.flow_sessions.FlowSessionRejected) as refused:
                _init(flows, token)
            assert refused.value.reason == "unknown_flow_token", template.name
        assert reached == [], template.name


def test_paid_invoice_review_token_opens_static_feedback(flows, reached):
    assert _init(flows, flows.review_token.mint()) == {"screen": "FEEDBACK", "data": {}}
    assert reached == []
