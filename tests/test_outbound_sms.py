"""outbound-sms is AWS-only, and says so when asked for anything else.

AWS End User Messaging is the only SMS transport. The properties pinned here:

  * the only sender is `lambda_utils.comms.get_sms_service()`; the module builds no
    AWS client but DynamoDB and holds no network endpoint of its own
  * any `provider` other than AWS is REFUSED, not silently upgraded to AWS
  * a raw `dltTemplateId` is validated against the approved map
  * India with no approved template produces 422 and no send
  * a send failure is a failure - there is no second provider
"""
import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
HANDLER_PATH = ROOT / "amplify" / "functions" / "messaging" / "outbound-sms" / "handler.py"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))


def _load_handler():
    spec = importlib.util.spec_from_file_location("outbound_sms_handler", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_handler()


class _Result:
    def __init__(self, *, success=True, error="", error_code="",
                 provider_message_id="prov-1", region="us-east-1", is_india=False):
        self.success = success
        self.error = error
        self.error_code = error_code
        self.provider_message_id = provider_message_id
        self.message_id = "mid"
        self.provider = "aws-end-user-messaging"
        self.dry_run = False

        class _Route:
            def __init__(self):
                self.region = region
                self.is_india = is_india

            def as_dict(self):
                return {"region": region, "isIndia": is_india}

        class _Dlt:
            template_id = "1007277993798259629"
            sender_id = "WDBEEP"
            ok = True
            error = ""

            def as_dict(self):
                return {"templateId": "1007277993798259629"}

        self.route = _Route()
        self.dlt = _Dlt()

    def as_dict(self):
        return {"success": self.success, "provider": self.provider}


class _FakeService:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or _Result()

    def send_sms(self, phone, content, **kwargs):
        self.calls.append({"phone": phone, "content": content, **kwargs})
        return self.result


@pytest.fixture
def wired(mod, monkeypatch):
    """Handler with the SMS service and the message store stubbed out."""
    service = _FakeService()
    monkeypatch.setattr(mod, "get_sms_service", lambda: service)
    stored = []
    monkeypatch.setattr(mod, "put_message", lambda **kw: stored.append(kw))
    monkeypatch.setattr(mod, "_get_contact", lambda cid: {"phone": "+919903300044"})
    mod._stored = stored
    return mod, service, stored


def _post(mod, body):
    return mod.handler({
        "requestContext": {"http": {"method": "POST", "path": "/sms/send"}},
        "rawPath": "/sms/send",
        "headers": {"origin": "https://app.wecare.digital"},
        "body": json.dumps(body),
    }, None)


def _body(response):
    return json.loads(response["body"])


# --------------------------------------------------------------------------
# the only transport is the shared AWS SMS service
# --------------------------------------------------------------------------
def _tree():
    return ast.parse(HANDLER_PATH.read_text())


def test_the_only_aws_client_built_here_is_dynamodb():
    """Contact lookups. Sending is not done with a client of this module's own."""
    built = sorted(
        (node.func.attr, node.args[0].value)
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "boto3"
    )
    assert built == [("resource", "dynamodb")]


def test_every_send_goes_through_the_shared_sms_service():
    sends = [node for node in ast.walk(_tree())
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "send_sms"]
    assert len(sends) == 1, "exactly one send call site"
    receiver = sends[0].func.value
    assert isinstance(receiver, ast.Call) and getattr(receiver.func, "id", "") == "get_sms_service"


def test_the_module_holds_no_network_endpoint():
    """A transport needs somewhere to send to; this module names nowhere."""
    literals = [node.value for node in ast.walk(_tree())
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    for value in literals:
        assert "://" not in value, value


def test_the_service_imported_is_the_shared_comms_one(mod):
    from lambda_utils import comms
    assert mod.get_sms_service is comms.get_sms_service


# --------------------------------------------------------------------------
# a provider other than AWS is refused, not silently upgraded
# --------------------------------------------------------------------------
@pytest.mark.parametrize("provider", ["unsupported", "alternate", "legacy", "custom"])
def test_unsupported_provider_is_refused(wired, provider):
    mod, service, _ = wired
    response = _post(mod, {"phoneNumber": "+919903300044", "content": "hi",
                           "provider": provider})
    assert response["statusCode"] == 422
    assert _body(response)["errorCode"] == "UNSUPPORTED_PROVIDER"
    # and critically: nothing was sent
    assert service.calls == []


def test_unknown_provider_is_refused(wired):
    mod, service, _ = wired
    response = _post(mod, {"phoneNumber": "+919903300044", "content": "hi",
                           "provider": "twilio"})
    assert response["statusCode"] == 422
    assert _body(response)["errorCode"] == "UNSUPPORTED_PROVIDER"
    assert service.calls == []


@pytest.mark.parametrize("provider", ["aws", "", "aws-end-user-messaging"])
def test_aws_and_absent_provider_proceed(wired, provider):
    mod, service, _ = wired
    body = {"phoneNumber": "+18444891209", "content": "hi"}
    if provider:
        body["provider"] = provider
    response = _post(mod, body)
    assert response["statusCode"] == 200
    assert len(service.calls) == 1


# --------------------------------------------------------------------------
# a raw dltTemplateId is validated, not trusted
# --------------------------------------------------------------------------
def test_approved_raw_template_id_maps_to_its_key(wired):
    mod, service, _ = wired
    response = _post(mod, {"phoneNumber": "+919903300044", "content": "hi",
                           "dltTemplateId": "1007277993798259629"})
    assert response["statusCode"] == 200
    assert service.calls[0]["dlt_template_key"] == "ivr-default"


def test_unapproved_raw_template_id_is_refused(wired):
    mod, service, _ = wired
    response = _post(mod, {"phoneNumber": "+919903300044", "content": "hi",
                           "dltTemplateId": "9999999999999999999"})
    assert response["statusCode"] == 422
    assert _body(response)["errorCode"] == "UNAPPROVED_DLT_TEMPLATE"
    assert service.calls == []


def test_template_key_is_passed_through(wired):
    mod, service, _ = wired
    _post(mod, {"phoneNumber": "+919903300044", "content": "hi",
                "dltTemplateKey": "wd_order"})
    assert service.calls[0]["dlt_template_key"] == "wd_order"


def test_template_key_wins_over_legacy_id(wired):
    mod, service, _ = wired
    _post(mod, {"phoneNumber": "+919903300044", "content": "hi",
                "dltTemplateKey": "wd_order",
                "dltTemplateId": "1007277993798259629"})
    assert service.calls[0]["dlt_template_key"] == "wd_order"


# --------------------------------------------------------------------------
# missing DLT is the caller's problem (422), not a server fault (500)
# --------------------------------------------------------------------------
def test_missing_dlt_template_returns_422_and_stores_failure(mod, monkeypatch):
    service = _FakeService(_Result(success=False, error="no approved template",
                                   error_code="MISSING_DLT_TEMPLATE", is_india=True,
                                   region="ap-south-1"))
    monkeypatch.setattr(mod, "get_sms_service", lambda: service)
    stored = []
    monkeypatch.setattr(mod, "put_message", lambda **kw: stored.append(kw))
    response = _post(mod, {"phoneNumber": "+919903300044", "content": "hi"})
    assert response["statusCode"] == 422
    assert _body(response)["errorCode"] == "MISSING_DLT_TEMPLATE"
    assert stored and stored[0]["status"] == "failed"


def test_provider_error_returns_502_not_500(mod, monkeypatch):
    service = _FakeService(_Result(success=False, error="throttled",
                                   error_code="ThrottlingException"))
    monkeypatch.setattr(mod, "get_sms_service", lambda: service)
    monkeypatch.setattr(mod, "put_message", lambda **kw: None)
    response = _post(mod, {"phoneNumber": "+18444891209", "content": "hi"})
    assert response["statusCode"] == 502


def test_failure_does_not_attempt_a_second_provider(mod, monkeypatch):
    """There is no fallback chain any more."""
    service = _FakeService(_Result(success=False, error="boom", error_code="X"))
    monkeypatch.setattr(mod, "get_sms_service", lambda: service)
    monkeypatch.setattr(mod, "put_message", lambda **kw: None)
    _post(mod, {"phoneNumber": "+919903300044", "content": "hi"})
    assert len(service.calls) == 1


# --------------------------------------------------------------------------
# request validation
# --------------------------------------------------------------------------
def test_missing_destination_is_400(wired):
    mod, _, _ = wired
    assert _post(mod, {"content": "hi"})["statusCode"] == 400


def test_missing_content_is_400(wired):
    mod, _, _ = wired
    assert _post(mod, {"phoneNumber": "+18444891209"})["statusCode"] == 400


def test_invalid_json_is_400(mod):
    response = mod.handler({
        "requestContext": {"http": {"method": "POST"}},
        "body": "{not json",
    }, None)
    assert response["statusCode"] == 400


def test_options_preflight_is_200(mod):
    response = mod.handler({"requestContext": {"http": {"method": "OPTIONS"}}}, None)
    assert response["statusCode"] == 200


def test_unknown_contact_is_404(mod, monkeypatch):
    monkeypatch.setattr(mod, "get_sms_service", lambda: _FakeService())
    monkeypatch.setattr(mod, "_get_contact", lambda cid: {})
    response = _post(mod, {"contactId": "nope", "content": "hi"})
    assert response["statusCode"] == 404


# --------------------------------------------------------------------------
# message types outside the AWS vocabulary are mapped, not rejected
# --------------------------------------------------------------------------
@pytest.mark.parametrize("other", ["SERVICE_IMPLICIT", "SERVICE_EXPLICIT", "junk"])
def test_other_message_types_map_to_transactional(wired, other):
    mod, service, _ = wired
    _post(mod, {"phoneNumber": "+919903300044", "content": "hi",
                "dltTemplateKey": "ivr-default", "messageType": other})
    assert service.calls[0]["message_type"] == "TRANSACTIONAL"


def test_promotional_is_preserved(wired):
    mod, service, _ = wired
    _post(mod, {"phoneNumber": "+18444891209", "content": "hi",
                "messageType": "PROMOTIONAL"})
    assert service.calls[0]["message_type"] == "PROMOTIONAL"


# --------------------------------------------------------------------------
# the stored row reports AWS, and never a relabelled provider
# --------------------------------------------------------------------------
def test_successful_send_stores_the_aws_provider(wired):
    mod, _, stored = wired
    _post(mod, {"phoneNumber": "+18444891209", "content": "hi"})
    assert stored[0]["provider"] == "aws-end-user-messaging"
    assert stored[0]["status"] == "sent"
