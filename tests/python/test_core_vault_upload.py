"""Vault direct upload: the declared size is required, capped and signed into the presigned
PUT, and confirm deletes bytes it rejects. Functions are executed from the handler source
with fake collaborators; presigning uses fake credentials and makes no network call."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / "amplify/functions/core/secure-files/handler.py"
FUNCTIONS = {"_upload_init", "_upload_confirm", "_meta_media_limit", "_safe_extension"}
PREFIX = "secure/d/public/valut/"
MB = 1024 * 1024


def _nodes():
    out = []
    for node in ast.parse(HANDLER.read_text()).body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            out.append(node)
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and getattr(node.targets[0], "id", "") == "_META_MEDIA_RULES"):
            out.append(node)
    return out


class Files:
    def __init__(self):
        self.rows = {}
        self.updates = []

    def put_item(self, Item):
        self.rows[Item["fileId"]] = dict(Item)

    def get_item(self, Key, ConsistentRead=False):
        row = self.rows.get(Key["fileId"])
        return {"Item": dict(row)} if row else {}

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        values = kwargs["ExpressionAttributeValues"]
        row = self.rows[kwargs["Key"]["fileId"]]
        row["status"] = values.get(":rejected") or values.get(":active")


class S3:
    def __init__(self, head=None, delete_error=None, signer=None):
        self.head = head or {}
        self.delete_error = delete_error
        self.signer = signer
        self.presigned = []
        self.deleted = []

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.presigned.append(Params)
        if self.signer:
            return self.signer.generate_presigned_url(op, Params=Params, ExpiresIn=ExpiresIn)
        return "https://upload.example.test/signed"

    def head_object(self, Bucket, Key):
        return dict(self.head)

    def delete_object(self, Bucket, Key):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(Key)


def vault(s3, files):
    warnings = []

    class Refused(Exception):
        pass

    def normalise_phone(value):
        if not value:
            raise ValueError("phone")
        return "+" + str(value).lstrip("+")

    cognito = SimpleNamespace(admin_get_user=lambda **kw: {
        "Enabled": True, "UserAttributes": [{"Name": "sub", "Value": "owner-sub"},
                                            {"Name": "phone_number", "Value": "+919000000001"}]})
    env = {
        "Dict": dict, "Any": object, "json": json, "os": __import__("os"),
        "time": __import__("time"), "uuid": __import__("uuid"), "ClientError": ClientError,
        "cors_response": lambda code, body, origin: {"statusCode": code, "body": body},
        "_decimal_safe": lambda value: value,
        "_vault_direct_upload_enabled": lambda: True,
        "normalise_phone": normalise_phone, "mask_phone": lambda phone: "masked",
        "_ensure_customer_user": lambda phone, name: "user-1", "UnsafeWabaStamp": Refused,
        "_cognito_client": lambda: cognito, "CUSTOMER_POOL_ID": "pool",
        "MAX_UPLOAD_BYTES": 100 * MB, "VAULT_UPLOAD_PREFIX": PREFIX,
        "FILES_TABLE": "files", "_table": lambda name: files,
        "WORKSPACE_VAULT_RECORD_VERSION": 2, "_s3_client": lambda: s3, "BUCKET": "bucket",
        "UPLOAD_URL_TTL": 900,
        "logger": SimpleNamespace(info=lambda *a: None, warning=warnings.append),
    }
    exec(compile(ast.Module(body=_nodes(), type_ignores=[]), str(HANDLER), "exec"), env)
    return env, warnings


def init_event(**overrides):
    body = {"name": "Customer", "mobile": "919000000001", "originalFilename": "doc.pdf",
            "contentType": "application/pdf", "sizeBytes": 2048, **overrides}
    return {"body": json.dumps(body), "_auth": {"username": "staff-1"}}


@pytest.mark.parametrize("size", [None, 0, -5, "abc", [], "1.5"])
def test_init_requires_a_declared_size(size):
    s3, files = S3(), Files()
    env, _ = vault(s3, files)
    response = env["_upload_init"](init_event(sizeBytes=size), "origin")
    assert response["statusCode"] == 400 and response["body"]["error"] == "SIZE_REQUIRED"
    assert files.rows == {} and s3.presigned == []


def test_init_caps_the_declared_size_at_the_media_limit():
    s3, files = S3(), Files()
    env, _ = vault(s3, files)
    response = env["_upload_init"](init_event(sizeBytes=100 * MB + 1), "origin")
    assert response["statusCode"] == 413 and response["body"]["limitBytes"] == 100 * MB
    image = env["_upload_init"](init_event(originalFilename="p.png", contentType="image/png",
                                           sizeBytes=5 * MB + 1), "origin")
    assert image["statusCode"] == 413 and image["body"]["limitBytes"] == 5 * MB
    assert files.rows == {} and s3.presigned == []


def test_init_signs_the_declared_size_into_the_put():
    s3, files = S3(), Files()
    env, _ = vault(s3, files)
    response = env["_upload_init"](init_event(sizeBytes="4096"), "origin")
    assert response["statusCode"] == 201
    params = s3.presigned[0]
    assert params["ContentLength"] == 4096 and params["IfNoneMatch"] == "*"
    assert params["ContentType"] == "application/pdf" and params["Key"].startswith(PREFIX)
    assert files.rows[response["body"]["fileId"]]["sizeBytes"] == 4096


def test_real_presigned_put_signs_content_length(monkeypatch):
    import os
    import boto3
    from botocore.client import Config
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", os.devnull)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", os.devnull)
    signer = boto3.session.Session(
        aws_access_key_id="AKIAFAKEFAKEFAKEFAKE", aws_secret_access_key="fake" * 10,
        region_name="us-east-1").client("s3", config=Config(signature_version="s3v4"))
    s3, files = S3(signer=signer), Files()
    env, _ = vault(s3, files)
    url = env["_upload_init"](init_event(), "origin")["body"]["uploadUrl"]
    signed = parse_qs(urlsplit(url).query)["X-Amz-SignedHeaders"][0].split(";")
    assert {"content-length", "content-type", "if-none-match"} <= set(signed)


def pending(files, key=PREFIX + "wecare-digital-f1.pdf", filename="doc.pdf"):
    files.rows["f1"] = {"fileId": "f1", "s3Key": key, "status": "pending",
                        "originalFilename": filename, "contentType": "application/pdf"}


def test_confirm_deletes_an_oversized_object_it_rejects():
    s3, files = S3(head={"ContentLength": 100 * MB + 1, "ContentType": "application/pdf"}), Files()
    pending(files)
    env, _ = vault(s3, files)
    response = env["_upload_confirm"]("f1", "origin")
    assert response["statusCode"] == 413 and files.rows["f1"]["status"] == "rejected"
    assert s3.deleted == [PREFIX + "wecare-digital-f1.pdf"]


def test_confirm_deletes_an_object_of_the_wrong_type():
    s3, files = S3(head={"ContentLength": 10, "ContentType": "text/html"}), Files()
    pending(files)
    env, _ = vault(s3, files)
    assert env["_upload_confirm"]("f1", "origin")["statusCode"] == 415
    assert s3.deleted == [PREFIX + "wecare-digital-f1.pdf"]


def test_confirm_rejection_stands_when_the_delete_is_refused():
    denied = ClientError({"Error": {"Code": "AccessDenied"}}, "DeleteObject")
    s3 = S3(head={"ContentLength": 100 * MB + 1, "ContentType": "application/pdf"},
            delete_error=denied)
    files = Files()
    pending(files)
    env, warnings = vault(s3, files)
    assert env["_upload_confirm"]("f1", "origin")["statusCode"] == 413
    assert files.rows["f1"]["status"] == "rejected"
    kept = [json.loads(w) for w in warnings if "vault_upload_rejected_object_kept" in w]
    assert kept == [{"event": "vault_upload_rejected_object_kept", "fileId": "f1",
                     "error": "AccessDenied"}]


def test_confirm_keeps_a_valid_object():
    s3, files = S3(head={"ContentLength": 2048, "ContentType": "application/pdf"}), Files()
    pending(files)
    env, _ = vault(s3, files)
    response = env["_upload_confirm"]("f1", "origin")
    assert response["statusCode"] == 200 and response["body"]["status"] == "active"
    assert s3.deleted == []
