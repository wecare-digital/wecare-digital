"""The provider allow-list and the gates that read it are positive, and they can fail.

`scripts/provider_allowlist.py` is the only provider vocabulary CI uses. These tests pin
three things:

* the allow-list approves exactly the supported providers, each with a stated purpose;
* the source gate passes on the tree, and fails on an injected reference of every kind -
  a gate never seen red is not known to work;
* the live gate and the webhook tooling apply the same list to what is deployed.

Synthetic violations name an invented provider, `acme`, and the reserved-looking host
`api.example-unknown.com`. Nothing here names a retired provider: the gates do not know
any, which is the point.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_provider_allowlist as gate  # noqa: E402
import provider_allowlist as allow  # noqa: E402

SUPPORTED = {"wecare", "aws", "meta", "razorpay", "plivo", "sinch", "google", "microsoft",
             "truecaller", "openai", "github"}
SUPPORTED_VOICE = {"wecare-plivo-answer", "wecare-pstn-softphone", "wecare-voice-aws",
                   "wecare-voice-cdr-read", "wecare-whatsapp-calling", "wecare-whatsapp-voice"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scan(tmp_path, owner: str, text: str, name: str = "sample.py"):
    """Scan ``text`` as if it lived at ``owner`` (a repo-relative path)."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    scan = gate.Scan()
    scan.scan_file(owner, path)
    return scan.findings


def _rules(findings) -> dict:
    out: dict = {}
    for f in findings:
        out.setdefault(f.rule, []).append(f.value)
    return out


# --------------------------------------------------------------------------------------
# the allow-list itself
# --------------------------------------------------------------------------------------
def test_the_allowlist_approves_exactly_the_supported_providers():
    """Adding a provider takes two edits - the entry and this set - on purpose."""
    keys = [p.key for p in allow.PROVIDERS]
    assert len(keys) == len(set(keys))
    assert set(keys) == SUPPORTED


def test_every_entry_states_its_purpose_and_well_formed_vocabulary():
    host = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9-]+$")
    for entry in (*allow.PROVIDERS, *allow.REFERENCES, *allow.LIBRARIES):
        assert len(entry.purpose) > 10, entry.key
    for provider in allow.PROVIDERS:
        for domain in provider.domains + provider.transport_domains:
            assert host.match(domain), (provider.key, domain)
        for prefix in provider.secret_prefixes:
            assert prefix.startswith("wecare/") and prefix != "wecare/", (provider.key, prefix)
        for route in provider.webhook_routes:
            assert route == allow.normalise_route(route), (provider.key, route)
        if provider.transport_domains or provider.transport_scope:
            assert provider.transport_domains and provider.transport_scope, provider.key
    ids = [i for p in allow.PROVIDERS for i in p.provider_ids]
    assert len(ids) == len(set(ids)), "a provider id is claimed twice"


def test_single_capability_providers_are_scoped():
    sinch = next(p for p in allow.PROVIDERS if p.key == "sinch")
    assert sinch.transport_scope == allow.RCS_TRANSPORT_SCOPE
    assert sinch.provider_ids == ("sinch-rcs",)
    assert allow.host_owner("convapi.aclwhatsapp.com",
                            "amplify/functions/messaging/rcs-send/handler.py")[0] == "sinch"
    assert allow.host_owner("convapi.aclwhatsapp.com",
                            "amplify/functions/messaging/whatsapp-calling/handler.py")[0] is None
    assert allow.host_owner("developers.sinch.com", "anywhere.py")[0] == "sinch"
    assert allow.secret_owner("wecare/sinch/rcs", "lambda:wecare-rcs-send")[0] == "sinch"
    assert allow.secret_owner("wecare/sinch/rcs", "lambda:wecare-outbound-sms")[0] is None


def test_channel_functions_are_the_supported_sets():
    assert allow.CHANNEL_FUNCTIONS["voice"] == SUPPORTED_VOICE
    assert allow.CHANNEL_FUNCTIONS["sms"] == {"wecare-sms-aws", "wecare-outbound-sms"}
    assert allow.CHANNEL_FUNCTIONS["rcs"] == {"wecare-rcs-send", "wecare-rcs-dlr"}
    assert allow.channel_function_ok("wecare-invoice-engine"), "invoice is not voice"
    assert not allow.channel_function_ok("wecare-voice-acme")
    assert not allow.channel_function_ok("stack-wecare-sms-acme")


def test_sms_is_end_user_messaging_only():
    assert "pinpoint-sms-voice-v2" in allow.AWS_SERVICES
    assert "pinpoint" not in allow.AWS_SERVICES
    assert "Message" not in allow.PLIVO_VOICE_RESOURCES
    assert allow.RCS_CHANNELS == {"RCS", "rcs"}


def test_the_configured_upi_vpa_is_razorpay_issued():
    """The collection VPA ends in a PSP bank handle, which is Razorpay's settlement bank -
    matched by shape, so the bank's name is never provider vocabulary."""
    source = (ROOT / "src" / "config" / "constants.ts").read_text(encoding="utf-8")
    vpa = re.search(r"upiVpa:\s*'([^']+)'", source).group(1)
    assert allow.RAZORPAY_VPA.match(vpa), vpa
    manifest = json.loads((ROOT / "config" / "lambda-env-manifest.json").read_text())
    upi = {env["RAZORPAY_UPI_ID"] for env in manifest["functions"].values()
           if "RAZORPAY_UPI_ID" in env}
    assert upi and all(allow.RAZORPAY_VPA.match(v) for v in upi)
    assert not allow.RAZORPAY_VPA.match("merchant@acmebank")


def test_webhook_route_vocabulary():
    assert allow.is_webhook_route("POST /razorpay-webhook")
    assert allow.is_webhook_route("/api/plivo/answer")
    assert allow.is_webhook_route("/sms-in/acme")
    assert allow.is_webhook_route("/webhook/acme-dlr")
    assert not allow.is_webhook_route("/workspace/engage/voice-in")
    assert not allow.is_webhook_route("/v1/projects/{project_id}/webhooks")
    assert allow.webhook_route_ok("/prod/plivo/hangup")
    assert allow.webhook_route_ok("/oauth/callback"), "a tail of an approved route"
    assert allow.webhook_route_ok("/verify-callback")
    assert not allow.webhook_route_ok("/acme-callback"), "a tail must start at a segment"
    assert not allow.webhook_route_ok("/sms-in/acme")


# --------------------------------------------------------------------------------------
# the source gate: green on the tree, red on every kind of injected reference
# --------------------------------------------------------------------------------------
def test_the_gate_passes_on_the_current_tree(capsys):
    assert gate.main([]) == 0, capsys.readouterr().out
    out = capsys.readouterr().out
    assert "PROVIDER ALLOW-LIST OK" in out


def test_the_gate_exercises_every_rule_on_the_tree():
    """Not vacuous: the tree really contains hosts, secrets, packages and routes to check."""
    counts = {"hosts": 0, "secrets": 0}
    original_host, original_secret = allow.host_owner, allow.secret_owner

    def host(h, owner=""):
        counts["hosts"] += 1
        return original_host(h, owner)

    def secret(s, owner=""):
        counts["secrets"] += 1
        return original_secret(s, owner)

    allow.host_owner, allow.secret_owner = host, secret
    try:
        scan = gate.run()
    finally:
        allow.host_owner, allow.secret_owner = original_host, original_secret
    assert scan.findings == []
    assert scan.files > 300
    assert counts["hosts"] > 50 and counts["secrets"] > 50, counts


def test_an_unknown_host_fails(tmp_path):
    found = _rules(_scan(tmp_path, "amplify/functions/x/handler.py",
                         'URL = "https://api.example-unknown.com/v1/send"\n'))
    assert found == {"hosts": ["api.example-unknown.com"]}


def test_a_host_in_a_comment_or_docstring_is_prose(tmp_path):
    text = ('"""Calls https://api.example-unknown.com in an earlier design."""\n'
            '# see https://api.example-unknown.com/docs\n'
            'X = 1\n')
    assert _scan(tmp_path, "amplify/functions/x/handler.py", text) == []
    ts = "// https://api.example-unknown.com\n/* https://api.example-unknown.com */\nexport const a = 1;\n"
    assert _scan(tmp_path, "src/lib/a.ts", ts, "a.ts") == []


@pytest.mark.parametrize("text", [
    'const u = `https://${host}/x`;\n',                 # a host the source cannot judge
    'const u = "https://cognito-idp.${region}.amazonaws.com";\n',
    '<input placeholder="https://your-server.example-unknown.com/hook" />;\n',
    "const appId = 'digital.wecare.app';\n",            # bundle id, first party reversed
])
def test_templates_placeholders_and_bundle_ids_are_not_hosts(tmp_path, text):
    assert _scan(tmp_path, "src/components/A.tsx", text, "A.tsx") == []


def test_a_public_ip_endpoint_fails_and_a_local_one_does_not(tmp_path):
    """A provider reached through a bare public IP (a relay with a whitelisted address, say)
    is not a named, approved host. Loopback and private addresses are not providers."""
    local = 'LOCAL = "http://127.0.0.1:3000"\nLAN = "http://10.0.0.5:8080/x"\n'
    assert _scan(tmp_path, "amplify/functions/x/handler.py", local) == []
    found = _rules(_scan(tmp_path, "amplify/functions/x/handler.py",
                         'PROXY = "http://54.1.2.3:8899/send"\n'))
    assert found == {"hosts": ["54.1.2.3"]}


def test_the_rcs_transport_is_confined_to_the_rcs_modules(tmp_path):
    text = 'BASE = "https://convapi.aclwhatsapp.com/v1/projects"\nSECRET = "wecare/sinch/rcs"\n'
    outside = _rules(_scan(tmp_path, "amplify/functions/messaging/whatsapp-calling/handler.py", text))
    assert outside == {"hosts": ["convapi.aclwhatsapp.com"], "secrets": ["wecare/sinch/rcs"]}
    assert _scan(tmp_path, "amplify/functions/messaging/rcs-send/handler.py", text) == []


def test_the_rcs_transport_addresses_rcs_only(tmp_path):
    text = ('body = {"channel_identity": {"channel": "SMS", "identity": "x"},\n'
            '        "channel_priority_order": ["RCS", "SMS"]}\n')
    found = _rules(_scan(tmp_path, "amplify/functions/messaging/rcs-send/handler.py", text))
    assert found == {"rcs-transport": ["SMS", "SMS"]}


def test_an_unapproved_secret_fails(tmp_path):
    found = _rules(_scan(tmp_path, "amplify/functions/x/handler.py",
                         'SECRET = "wecare/acme/api-key"\nOK = "wecare/razorpay/api"\n'))
    assert found == {"secrets": ["wecare/acme/api-key"]}


def test_unapproved_packages_fail_in_code_and_manifests(tmp_path):
    py = _rules(_scan(tmp_path, "amplify/functions/x/handler.py",
                      "import acme_sdk\nimport boto3\nfrom PIL import Image\n"))
    assert py == {"packages": ["acme_sdk"]}
    ts = _rules(_scan(tmp_path, "src/lib/a.ts",
                      "import { send } from '@acme/sdk';\nimport React from 'react';\n"
                      "import x from './local';\nimport fs from 'node:fs';\n", "a.ts"))
    assert ts == {"packages": ["@acme/sdk"]}
    req = _rules(_scan(tmp_path, "amplify/functions/x/requirements.txt",
                       "boto3==1.0\nacme-sdk==2.0  # vendor client\n", "requirements.txt"))
    assert req == {"packages": ["acme-sdk"]}
    pkg = _rules(_scan(tmp_path, "amplify/package.json",
                       json.dumps({"dependencies": {"aws-cdk-lib": "1", "acme-sdk": "1"}}),
                       "package.json"))
    assert pkg == {"packages": ["acme-sdk"]}


def test_an_unapproved_webhook_route_fails(tmp_path):
    backend = _rules(_scan(tmp_path, "amplify/functions/x/handler.py",
                           'ROUTE = "POST /sms-in/acme"\nOK = "/plivo/answer"\n'))
    assert backend == {"webhook-routes": ["/sms-in/acme"]}
    ui = _rules(_scan(tmp_path, "src/pages/x.tsx",
                      'const hook = "https://wecare.digital/api/webhook/acme-dlr";\n'
                      'const page = "/workspace/engage/voice-in";\n', "x.tsx"))
    assert ui == {"webhook-routes": ["/webhook/acme-dlr"]}


def test_provider_values_and_selectors_are_vocabulary(tmp_path):
    text = ('import os\n'
            'a = {"provider": "acme"}\n'
            'b = dict(provider="plivo")\n'          # Plivo voice uses PROVIDER_PLIVO
            'c = {"provider": "aws-end-user-messaging"}\n'
            'SOURCE = os.environ.get("CATALOG_SOURCE", "acme")\n'
            'MODE = os.environ.get("TRANSLATE_PROVIDER", "auto")\n')
    found = _rules(_scan(tmp_path, "amplify/functions/x/handler.py", text))
    assert found == {"provider-ids": ["provider='acme'", "provider='plivo'",
                                      "CATALOG_SOURCE='acme'"]}


def test_credential_env_keys_carry_an_approved_namespace(tmp_path):
    text = ('import os\n'
            'A = os.environ.get("ACME_API_KEY")\n'
            'B = os.environ["META_APP_ID"]\n'
            'C = os.getenv("TABLE_NAME")\n')
    assert _rules(_scan(tmp_path, "amplify/functions/x/handler.py", text)) == {
        "env-namespaces": ["ACME_API_KEY"]}
    ts = "const k = process.env.NEXT_PUBLIC_ACME_CLIENT_ID;\n"
    assert _rules(_scan(tmp_path, "src/lib/a.ts", ts, "a.ts")) == {
        "env-namespaces": ["NEXT_PUBLIC_ACME_CLIENT_ID"]}


def test_sms_transport_is_end_user_messaging_and_plivo_is_voice(tmp_path):
    text = ('import boto3\n'
            'boto3.client("pinpoint").send_messages(ApplicationId="x")\n'
            'boto3.client("pinpoint-sms-voice-v2")\n'
            'sns = boto3.client("sns")\n'
            'sns.publish(PhoneNumber="+10000000000", Message="hi")\n'
            'sns.publish(TopicArn="arn:aws:sns:us-east-1:1:t", Message="hi")\n'
            'URL = f"https://api.plivo.com/v1/Account/{auth}/Message/"\n'
            'OK = f"https://api.plivo.com/v1/Account/{auth}/Call/"\n')
    found = _rules(_scan(tmp_path, "amplify/functions/x/handler.py", text))
    assert found == {"sms-transport": ["pinpoint", "Message", "publish(PhoneNumber=...)"]}


def test_channel_lambdas_are_the_supported_set(tmp_path):
    text = 'TARGETS = ["wecare-voice-acme", "wecare-sms-acme", "wecare-plivo-answer"]\n'
    found = _rules(_scan(tmp_path, "amplify/functions/x/handler.py", text))
    assert found == {"channel-lambdas": ["wecare-voice-acme", "wecare-sms-acme"]}


def test_function_directories_at_any_depth_are_in_the_supported_set(tmp_path, monkeypatch):
    functions = tmp_path / "amplify" / "functions"
    for rel in ("messaging/plivo-answer", "messaging/voice-in/acme", "messaging/sms-acme",
                "payments/invoice-engine", "shared/lambda_utils/voice"):
        (functions / rel).mkdir(parents=True)
        (functions / rel / "handler.py").write_text("X = 1\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    scan = gate.Scan()
    scan.scan_function_dirs()
    assert sorted(f.value for f in scan.findings) == ["wecare-sms-acme", "wecare-voice-in-acme"]


def test_upi_addresses_are_razorpay_issued(tmp_path):
    text = 'A = "merchant@acmebank"\nB = "shop.rzp@psp"\nC = "upi://pay?pa=pay@acme&am=1"\n'
    found = _rules(_scan(tmp_path, "amplify/functions/x/handler.py", text))
    assert found == {"upi-vpa": ["merchant@acmebank", "pay@acme"]}


def test_the_env_manifest_is_held_to_the_same_list(tmp_path):
    manifest = {"functions": {
        "wecare-rcs-send": {"RCS_SECRET_NAME": "wecare/sinch/rcs"},
        "wecare-outbound-sms": {"RCS_SECRET_NAME": "wecare/sinch/rcs",
                                "ACME_BASE_URL": "https://api.example-unknown.com"},
        "wecare-voice-acme": {"CATALOG_SOURCE": "acme"},
    }}
    found = _rules(_scan(tmp_path, "config/lambda-env-manifest.json", json.dumps(manifest),
                         "lambda-env-manifest.json"))
    assert found == {
        "channel-lambdas": ["wecare-voice-acme"],
        "env-namespaces": ["ACME_BASE_URL"],
        "secrets": ["wecare/sinch/rcs"],
        "hosts": ["api.example-unknown.com"],
        "provider-ids": ["CATALOG_SOURCE='acme'"],
    }


def test_the_cli_fails_on_an_explicit_violating_file(tmp_path, capsys):
    bad = tmp_path / "bad.py"
    bad.write_text('URL = "https://api.example-unknown.com/x"\n', encoding="utf-8")
    assert gate.main([str(bad)]) == 1
    assert "api.example-unknown.com" in json.dumps(
        [f.value for f in gate.run([str(bad)]).findings])
    good = tmp_path / "good.py"
    good.write_text('URL = "https://graph.facebook.com/v26.0"\n', encoding="utf-8")
    assert gate.main([str(good)]) == 0
    assert gate.main([str(tmp_path / "missing.py")]) == 2
    capsys.readouterr()


# --------------------------------------------------------------------------------------
# the live gate applies the same list to the account
# --------------------------------------------------------------------------------------
class _Paginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self):
        return iter(self.pages)


class _Fake:
    def __init__(self, secrets, functions, routes):
        self.secrets, self.functions, self.routes = secrets, functions, routes

    def get_paginator(self, name):
        if name == "list_secrets":
            return _Paginator([{"SecretList": [{"Name": n} for n in self.secrets]}])
        return _Paginator([{"Functions": [
            {"FunctionName": fn, "Environment": {"Variables": env}}
            for fn, env in self.functions.items()]}])

    def get_apis(self, **_):
        return {"Items": [{"ApiId": "api1"}]}

    def get_routes(self, **_):
        return {"Items": [{"RouteKey": r} for r in self.routes]}


@pytest.fixture
def live(monkeypatch):
    module = _load("provider_policy_live_under_test", SCRIPTS / "check_provider_policy_live.py")
    monkeypatch.setattr(module, "deploy_map", lambda: {
        "wecare-rcs-send", "wecare-checkout", "wecare-voice-acme", "wecare-outbound-sms"})
    return module


def test_the_live_gate_passes_an_approved_account(live):
    fake = _Fake(secrets=["wecare/razorpay/api", "wecare/sinch/rcs"],
                 functions={"wecare-rcs-send": {"RCS_SECRET_NAME": "wecare/sinch/rcs"},
                            "wecare-checkout": {"CATALOG_SOURCE": "aws",
                                                "PUBLIC_SITE_URL": "https://wecare.digital"}},
                 routes=["POST /razorpay-webhook", "POST /webhook/sinch-rcs", "GET /contacts"])
    findings, counts = live.collect(lambda _service: fake)
    assert findings == []
    assert counts["secrets"] == 2 and counts["functions"] == 2 and counts["routes"] == 3


def test_the_live_gate_fails_on_anything_unapproved(live):
    fake = _Fake(secrets=["wecare/acme/api"],
                 functions={
                     "wecare-outbound-sms": {"RCS_SECRET_NAME": "wecare/sinch/rcs",
                                             "ACME_API_KEY": "redacted-not-printed",
                                             "ACME_BASE": "https://api.example-unknown.com/v1"},
                     "wecare-checkout": {"CATALOG_SOURCE": "acme"},
                     "wecare-voice-acme": {},
                     "wecare-unmapped": {}},
                 routes=["POST /sms-in/acme", "POST /razorpay-webhook"])
    findings, _ = live.collect(lambda _service: fake)
    refs = {(kind, ref) for kind, _resource, ref, _why in findings}
    assert ("secret", "wecare/acme/api") in refs
    assert ("env", "RCS_SECRET_NAME -> wecare/sinch/rcs") in refs
    assert ("env", "ACME_API_KEY") in refs
    assert ("env", "ACME_BASE -> api.example-unknown.com") in refs
    assert ("env", "CATALOG_SOURCE=acme") in refs
    assert ("route", "POST /sms-in/acme") in refs
    assert ("lambda", "wecare-voice-acme") in refs
    assert ("lambda", "wecare-unmapped") in refs
    assert "redacted-not-printed" not in json.dumps(findings), "a credential value was printed"


# --------------------------------------------------------------------------------------
# the webhook tooling describes and checks approved routes only
# --------------------------------------------------------------------------------------
def test_the_webhook_inventory_is_two_sided_and_positive():
    inventory = _load("webhook_inventory_under_test", SCRIPTS / "webhook_inventory.py")
    live = {f"{method} {path}" for _p, path, method, _a, _f in inventory.ENDPOINTS}
    assert inventory.route_failures(live | {"GET /contacts"}) == []
    for _p, path, _m, _a, _f in inventory.ENDPOINTS:
        assert allow.webhook_route_ok(path), path
    failures = inventory.route_failures(live | {"POST /sms-in/acme"})
    assert failures == ["POST /sms-in/acme is a webhook route that is not on the provider "
                        "allow-list (scripts/provider_allowlist.py)"]
    missing = inventory.route_failures(live - {"POST /razorpay-webhook"})
    assert len(missing) == 1 and "POST /razorpay-webhook should be live" in missing[0]


def test_the_webhook_registry_publishes_only_approved_routes():
    registry = _load("webhook_registry_under_test", SCRIPTS / "sync_webhook_registry.py")
    assert registry.unapproved_rows() == []
    assert registry.WEBHOOKS, "an empty registry would pass vacuously"
