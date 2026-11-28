"""MSG-4: send, call and Meta-config writes need an explicit staff role.

`require_auth` is replaced by a fake that records the role each route asks for, so the
tests check the role semantics without Cognito. The whatsapp-business-api handler needs
`cryptography` at import time, so its gates are compiled from the real source (AST) and
exercised in isolation.
"""
import ast
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
MESSAGING = ROOT / "amplify/functions/messaging"
BUSINESS_API = MESSAGING / "whatsapp-business-api/handler.py"


def load(name):
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    path = MESSAGING / name / "handler.py"
    spec = importlib.util.spec_from_file_location(f"role_gate_{name.replace('-', '_')}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RoleRecorder:
    """Stands in for require_auth: grants up to `role`, refuses above it with 403."""
    RANK = {"Viewer": 1, "Operator": 2, "Admin": 3}

    def __init__(self, role="Admin"):
        self.role = role
        self.asked = []

    def __call__(self, event, required_role=None):
        self.asked.append(required_role)
        if required_role is None or self.RANK[required_role] > self.RANK[self.role]:
            return {"statusCode": 403, "body": json.dumps({"error": "Insufficient permissions"})}
        return None


def api_event(method, path="/x", body=None):
    return {"requestContext": {"apiId": "api", "http": {"method": method, "path": path,
                                                         "sourceIp": "1.2.3.4"}},
            "rawPath": path, "pathParameters": {}, "headers": {},
            "body": json.dumps(body or {})}


@pytest.mark.parametrize("name,send_fn,list_fn", [
    ("voice-aws", "_make_call", "_list_calls"),
    ("sms-aws", "_send_sms", "_list_messages"),
])
def test_voice_and_sms_sends_need_operator(name, send_fn, list_fn):
    module = load(name)
    viewer = RoleRecorder("Viewer")
    with mock.patch("lambda_utils.middleware.require_auth", viewer), \
            mock.patch.object(module, send_fn) as send, \
            mock.patch.object(module, list_fn, return_value={"statusCode": 200}) as read:
        refused = module.handler(api_event("POST"), None)
        listed = module.handler(api_event("GET"), None)
    assert refused["statusCode"] == 403 and not send.called
    assert listed["statusCode"] == 200 and read.called
    assert viewer.asked == ["Operator", "Viewer"]


def test_outbound_sms_needs_operator():
    module = load("outbound-sms")
    viewer = RoleRecorder("Viewer")
    with mock.patch("lambda_utils.middleware.require_auth", viewer):
        result = module.handler(api_event("POST", body={"phoneNumber": "+919999999999"}), None)
    assert result["statusCode"] == 403 and viewer.asked == ["Operator"]


def test_rcs_send_needs_operator_but_reads_stay_viewer():
    module = load("rcs-send")
    viewer = RoleRecorder("Viewer")
    with mock.patch("lambda_utils.middleware.require_auth", viewer), \
            mock.patch.object(module, "_send_rcs") as send, \
            mock.patch.object(module, "_list_messages", return_value={"statusCode": 200}) as read:
        refused = module.handler(api_event("POST", body={"action": "send"}), None)
        listed = module.handler(api_event("POST", body={"action": "list"}), None)
    assert refused["statusCode"] == 403 and not send.called
    assert listed["statusCode"] == 200 and read.called
    assert viewer.asked == ["Viewer", "Operator", "Viewer"]


def test_internal_rcs_invoke_still_works_without_a_token():
    module = load("rcs-send")
    with mock.patch.object(module, "_send_rcs", return_value={"statusCode": 200}) as send:
        module.handler({"body": json.dumps({"action": "send"})}, None)
    assert send.called


def test_marketing_ads_needs_admin_and_only_reads_outbound_media():
    module = load("marketing-ads")
    operator = RoleRecorder("Operator")
    with mock.patch.object(module, "require_auth", operator), \
            mock.patch.object(module, "_ads_list") as ads:
        refused = module.handler(api_event("POST", body={"action": "ads"}), None)
    assert refused["statusCode"] == 403 and not ads.called and operator.asked == ["Admin"]

    reads = []
    fake_s3 = SimpleNamespace(get_object=lambda Bucket, Key: reads.append((Bucket, Key)) or {
        "Body": SimpleNamespace(read=lambda: b"img")})
    with mock.patch.object(module.boto3, "client", return_value=fake_s3), \
            mock.patch.object(module, "_graph", return_value=(200, {"images": {}})):
        for bad in ({"s3Key": "secure/u/dropdocs/passport.pdf"},
                    {"s3Key": "secure/d/public/whatsapp/incoming/x.jpg"},
                    {"s3Key": "secure/d/public/whatsapp/outgoing/x.jpg", "bucket": "other"}):
            assert module._upload_image(bad)["statusCode"] == 400
        assert reads == []
        ok = module._upload_image({"s3Key": "secure/d/public/whatsapp/outgoing/ad.jpg"})
    assert ok["statusCode"] == 200
    assert reads == [(module.media_paths.BUCKET, "secure/d/public/whatsapp/outgoing/ad.jpg")]


# ── whatsapp-business-api (compiled from source) ─────────────────────────────

def business_api(names, **env):
    tree = ast.parse(BUSINESS_API.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        targets = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                   if isinstance(node, ast.Assign) else [getattr(node, "name", None)])
        if any(t in names for t in targets):
            nodes.append(node)
    namespace = {"__builtins__": __builtins__, **env}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BUSINESS_API), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("path,method,admin", [
    ("/wa-business/calling-settings", "POST", True),
    ("/wa-business/calling-settings", "HEAD", True),
    ("/wa-business/calling-settings", "GET", False),
    ("/wa-business/profile", "POST", True),
    ("/wa-business/username", "DELETE", True),
    ("/wa-business/commerce-settings", "HEAD", True),
    ("/wa-business/messages/send/text", "POST", False),
])
def test_meta_config_writes_need_admin(path, method, admin):
    recorder = RoleRecorder("Operator")
    ns = business_api({"ADMIN_WRITE_PATH_FRAGMENTS", "_require_admin_write"},
                      Dict=dict, Any=object, require_auth=recorder)
    denied = ns["_require_admin_write"]({}, path, method)
    assert (denied is not None) is admin
    assert recorder.asked == (["Admin"] if admin else [])


def test_catch_all_floor_is_operator_for_every_non_get():
    source = BUSINESS_API.read_text(encoding="utf-8")
    handler = source[source.index("def handler("):]
    assert "floor_role = 'Viewer' if str(method or '').upper() == 'GET' else 'Operator'" in handler
    assert "required_role='Admin' if is_return_transition else floor_role" in handler
    for arm in ("/groups/participants", "/groups/send", "/groups/image"):
        start = handler.index(f"elif '{arm}' in path:")
        assert "if method != 'POST':" in handler[start:start + 160], arm


def test_media_upload_reads_only_outbound_keys():
    from lambda_utils import media_paths

    reads = []
    s3 = SimpleNamespace(get_object=lambda Bucket, Key: reads.append(Key) or {
        "Body": SimpleNamespace(read=lambda: b"bytes"), "ContentType": "image/jpeg"})
    resp = lambda code, body: {"statusCode": code, "body": body}  # noqa: E731
    ns = business_api({"MEDIA_SOURCE_BUCKETS", "OUTBOUND_MEDIA_PREFIXES", "_upload_media"},
                      Dict=dict, os=os, media_paths=media_paths, MEDIA_BUCKET=media_paths.BUCKET,
                      PHONE1_META_ID="1", s3_client=s3, _resp=resp, base64=None,
                      _validate_media=lambda ctype, size: None,
                      _graph_media_multipart=lambda *a: {"id": "media-1"})
    upload = ns["_upload_media"]
    for key in ("secure/u/dropdocs/passport.pdf", "secure/d/public/valut/file.pdf",
                "secure/d/public/whatsapp/incoming/photo.jpg",
                "secure/d/public/Invoice/customer_invoice/inv.png"):
        assert upload({"s3Key": key})["statusCode"] == 400
    assert reads == []
    for key in ("secure/d/public/whatsapp/outgoing/a.jpg",
                "secure/d/public/whatsapp/wa-tpl/img/b.png"):
        assert upload({"s3Key": key})["statusCode"] == 200
    assert len(reads) == 2
