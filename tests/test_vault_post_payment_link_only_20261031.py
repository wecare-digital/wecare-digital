"""Regression: a paid Vault download is a dynamic link, never a WhatsApp PDF attachment.

Exercises the production _prepare_and_send function with synthetic, owner-bound
table/Cognito values. No AWS connection, Meta send, or money is involved.
"""
import ast
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PAID_VAULT = (
    ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py"
)
TEMPLATES = ROOT / "amplify/functions/shared/lambda_utils/whatsapp_templates.py"

FILE_ID = "doc-synthetic-owner-bound"
CUSTOMER_ID = "00000000-0000-4000-8000-000000000123"
PHONE = "+919988776655"


def _function(path: Path, function_name: str, namespace: dict):
    source = ast.parse(path.read_text(encoding="utf-8"))
    target = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    exec(compile(ast.Module(body=[target], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[function_name]


def _template_builder():
    header = (
        "https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png"
    )
    builder = _function(
        TEMPLATES, "download_send_fields",
        {"DOWNLOAD": SimpleNamespace(name="wecare_default_download"),
         "VAULT_HEADER_IMAGE": header},
    )
    return builder, header


class FakeRequests:
    def __init__(self):
        self.notification = {}

    def get_item(self, **_kwargs):
        return {"Item": dict(self.notification)}


class FakeContacts:
    def query(self, **_kwargs):
        return {"Items": [{"id": "synthetic-contact"}]}

    def get_item(self, **_kwargs):
        # A recently active WhatsApp chat previously triggered the extra PDF
        # branch; this remains a positive regression case for link-only sends.
        return {"Item": {
            "id": "synthetic-contact",
            "checkoutCustomerId": CUSTOMER_ID,
            "isDeleted": False,
            "deletedAt": None,
            "lastInboundMessageAt": 1793423670,
        }}


class FakeDB:
    def __init__(self, requests):
        self.requests = requests

    def Table(self, name):
        if name == "stack-wecare-digital-ServiceRequestsTable":
            return self.requests
        if name == "synthetic-contacts":
            return FakeContacts()
        return object()


class FakeCognito:
    def list_users(self, **_kwargs):
        return {"Users": [{"Enabled": True, "Attributes": [
            {"Name": "phone_number", "Value": PHONE},
            {"Name": "phone_number_verified", "Value": "true"},
        ]}]}


def test_paid_pdf_has_one_dynamic_access_vault_send_even_after_recent_reply():
    requests = FakeRequests()
    db = FakeDB(requests)
    send_calls = []
    windows = []
    sleeps = []
    log_events = []
    header_builder, header = _template_builder()
    row = {
        "customerId": CUSTOMER_ID, "requestId": "REQ#synthetic-1",
        "publicRequestId": "WD-REQ-SYNTHETIC-1",
    }
    file_row = {
        "fileId": FILE_ID, "deliverable": "pdf",
        "deliveryKey": "private/document/never-whatsapp.pdf",
        "originalFilename": "private-original.pdf",
    }
    grant = {"grantId": "grant-synthetic-1", "ownerPhone": PHONE[1:]}

    def send_once(table, service_row, key, _lambda_client, payload):
        assert table is requests
        assert service_row == row
        if table.notification.get(key) == "ACCEPTED":
            return True
        table.notification[key] = "ACCEPTED"
        send_calls.append((key, payload))
        return True

    def open_window(_lambda_client, grant_id):
        windows.append(grant_id)
        return True, "window_open:1"

    namespace = {
        "boto3": SimpleNamespace(resource=lambda _name: db,
                                  client=lambda _name: FakeCognito()),
        "vault_access": SimpleNamespace(
            grant_access=lambda *_args: (row, file_row, grant),
            FILES_TABLE="synthetic-files", GRANTS_TABLE="synthetic-grants"),
        "customer_auth": SimpleNamespace(
            CUSTOMER_POOL_ID="synthetic-pool",
            is_cognito_subject=lambda value: value == CUSTOMER_ID),
        "shared_tables": SimpleNamespace(
            contacts_table_name=lambda: "synthetic-contacts"),
        "whatsapp_templates": SimpleNamespace(download_send_fields=header_builder),
        "WABA1_SENDER": "phone-number-id-waba1-direct-synthetic",
        "TEMPLATE_IMAGE_HEADER": {
            "templateHeaderMedia": header, "templateHeaderType": "image"},
        "_send_once": send_once,
        "_open_paid_window": open_window,
        "_POST_RECEIPT_ACCESS_GAP_SECONDS": 4,
        "time": SimpleNamespace(time=lambda: 1793423690,
                                sleep=lambda seconds: sleeps.append(seconds)),
        "log_event": lambda *_args, **kwargs: log_events.append(kwargs),
        "logger": object(),
    }
    deliver = _function(PAID_VAULT, "_prepare_and_send", namespace)
    event = {"paymentAttemptId": "attempt-synthetic",
             "referenceId": "WD-PAY-SYNTHETIC",
             "orderId": "order-synthetic"}

    first = deliver(event, object())
    assert first["outcome"] == "VAULT_READY"
    assert first["windowOpened"] is True
    assert windows == [grant["grantId"]]
    assert sleeps == [4]
    assert len(send_calls) == 1
    key, payload = send_calls[0]
    assert key == "vaultNotificationStatus"
    assert payload["isTemplate"] is True
    assert payload["templateName"] == "wecare_default_download"
    assert payload["templateHeaderMedia"] == header
    assert payload["templateHeaderType"] == "image"
    assert payload["templateUrlButton"] == {"index": 0, "suffix": FILE_ID}
    assert payload["contactId"] == "synthetic-contact"
    # No raw media, temporary S3 URL, original filename or source storage key
    # is allowed in the automatic WhatsApp delivery payload.
    assert not any(k in payload for k in (
        "mediaFile", "mediaFileName", "mediaType", "document", "content", "link"
    ))
    assert file_row["deliveryKey"] not in str(payload)
    assert file_row["originalFilename"] not in str(payload)

    again = deliver(event, object())
    assert again["outcome"] == "VAULT_READY"
    assert again["windowOpened"] is False
    assert len(send_calls) == 1
    assert windows == [grant["grantId"]]
    assert sleeps == [4]


def test_paid_vault_contract_stays_separate_from_drop_docs_upload():
    vault = PAID_VAULT.read_text(encoding="utf-8")
    launcher = (
        ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/"
        "paid_submit_request.py"
    ).read_text(encoding="utf-8")
    templates = TEMPLATES.read_text(encoding="utf-8")
    assert "whatsapp_templates.download_send_fields(file['fileId'])" in vault
    assert "vaultNotificationStatus" in vault
    assert "vaultDocumentStatus" not in vault
    assert "mediaFileName" not in vault
    assert "if candidate.get('kind') == 'VAULT':" in launcher
    assert "if candidate.get('kind') == service_requests.DROP_DOCS:" in launcher
    assert "from .paid_vault import prepare_and_send as vault_send" in launcher
    assert "from .paid_drop_docs import prepare_and_send as drop_docs_send" in launcher
    assert "name=\"wecare_default_download\"" in templates
    assert "name=\"_dropdoc_flow\"" in templates
