"""`scripts/secrets_access_matrix.py` maps readers from policy documents alone."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "secrets_access_matrix.py"
ARN = "arn:aws:secretsmanager:us-east-1:775261844268:secret:"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("secrets_matrix_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["secrets_matrix_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _doc(actions, resources, effect="Allow"):
    return {"Version": "2012-10-17", "Statement": [
        {"Effect": effect, "Action": actions, "Resource": resources}]}


DOCS = {
    "wecare-checkout-role": [_doc(["secretsmanager:GetSecretValue"],
                                  [ARN + "wecare/razorpay/api-*"])],
    "wecare-digital-lambda-role": [_doc("secretsmanager:*", ARN + "wecare/*")],
    "wecare-reader-role": [_doc(["secretsmanager:DescribeSecret"], ["*"])],
    "wecare-denied-role": [_doc(["secretsmanager:GetSecretValue"], ["*"], effect="Deny")],
}


def test_exact_prefix_and_wildcard_grants_are_readers(mod):
    readers = mod.readers_of(ARN + "wecare/razorpay/api-AbC123", DOCS)
    assert readers == ["wecare-checkout-role", "wecare-digital-lambda-role"]


def test_describe_only_and_deny_statements_are_not_readers(mod):
    readers = mod.readers_of(ARN + "wecare/otp/pepper-XyZ987", DOCS)
    assert readers == ["wecare-digital-lambda-role"]


def test_build_reports_consumers_and_env_keys_without_values(mod, monkeypatch):
    monkeypatch.setattr(mod, "source_references", lambda name: [])
    secrets = [
        {"Name": "wecare/razorpay/api", "ARN": ARN + "wecare/razorpay/api-AbC123",
         "LastAccessedDate": "2026-10-14T00:00:00Z"},
        {"Name": "wecare/old", "ARN": ARN + "wecare/old-Q", "DeletedDate": "2026-10-07"},
        {"Name": "zz/unused", "ARN": "arn:aws:secretsmanager:us-east-1:775261844268:secret:zz/unused-Q"},
    ]
    functions = [{"FunctionName": "wecare-checkout",
                  "Role": "arn:aws:iam::775261844268:role/wecare-checkout-role",
                  "Environment": {"Variables": {"RAZORPAY_API_SECRET": "wecare/razorpay/api",
                                                "OTHER": "not-a-secret-name"}}}]
    rows = {r["name"]: r for r in mod.build(secrets, DOCS, functions)}
    razorpay = rows["wecare/razorpay/api"]
    assert razorpay["action"] == "KEEP_ISOLATED"
    assert razorpay["lambda_consumers"] == ["wecare-checkout"]
    assert razorpay["env_references"] == ["wecare-checkout.RAZORPAY_API_SECRET"]
    assert rows["wecare/old"]["action"] == "SCHEDULED_DELETION"
    unused = rows["zz/unused"]
    assert unused["action"] == "NEEDS_OWNER_REVIEW" and "no IAM reader" in unused["rationale"]
    text = mod.to_markdown(list(rows.values()), "2026-10-14T00:00:00Z")
    assert "not-a-secret-name" not in text
    assert "`wecare/old`" in text.split("## Scheduled for deletion")[1]
