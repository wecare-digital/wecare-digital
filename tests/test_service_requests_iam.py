"""The `wecare-service-requests` role is exactly what it says, and the dry run mutates nothing."""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/provision_service_requests.py"
ACCT = "123456789012"


@pytest.fixture
def prov():
    spec = importlib.util.spec_from_file_location("provision_service_requests_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_policy_has_exact_resources_including_selected_vault_files(prov):
    table = f"arn:aws:dynamodb:us-east-1:{ACCT}:table/stack-wecare-digital-ServiceRequestsTable"
    assert prov.expected_role_policy(ACCT) == {"Version": "2012-10-17", "Statement": [
        {"Sid": "ServiceRequestsRW", "Effect": "Allow",
         "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                    "dynamodb:ConditionCheckItem"], "Resource": [table]},
        {"Sid": "ServiceRequestsByCustomer", "Effect": "Allow", "Action": ["dynamodb:Query"],
         "Resource": [f"{table}/index/customerId-createdAt-index"]},
        {"Sid": "ReadPaidOrderClaims", "Effect": "Allow", "Action": ["dynamodb:GetItem"],
         "Resource": [f"arn:aws:dynamodb:us-east-1:{ACCT}:table/stack-wecare-digital-WixOrderIds"],
         "Condition": {"ForAllValues:StringLike": {"dynamodb:LeadingKeys": [
             "PAYREF#*", "REFERENCE#*", "PAYMENTATTEMPT#*"]}}},
        {"Sid": "RateLimitCounter", "Effect": "Allow", "Action": ["dynamodb:UpdateItem"],
         "Resource": [f"arn:aws:dynamodb:us-east-1:{ACCT}:table/"
                      f"stack-wecare-digital-RateLimitTable"]},
    ]}


def test_nothing_forbidden_is_granted(prov):
    actions = [a for s in prov.expected_role_policy(ACCT)["Statement"] for a in s["Action"]]
    for prefix in ("logs:", "secretsmanager:", "kms:", "lambda:", "s3:", "sns:", "ses:",
                   "sqs:", "iam:", "cognito"):
        assert not any(a.startswith(prefix) for a in actions), prefix
    for verb in ("DeleteItem", "Scan", "BatchWriteItem", "BatchGetItem", "*"):
        assert not any(a.endswith(verb) for a in actions), verb
    text = json.dumps(prov.expected_role_policy(ACCT))
    assert "razorpay" not in text.lower() and "wix/" not in text.lower()
    assert "wecare-digital-lambda-role" not in SCRIPT.read_text()


def test_the_managed_policy_is_only_basic_execution(prov):
    assert prov.expected_managed_policies() == [
        "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"]


def test_every_env_value_is_a_name(prov):
    env = prov.expected_environment()
    assert set(env) == {"SERVICE_REQUESTS_TABLE", "COMMERCE_KEYS_TABLE", "RATE_LIMIT_TABLE",
                        "CUSTOMER_POOL_ID"}
    for value in env.values():
        assert value.startswith(("stack-wecare-digital-", "us-east-1_"))


def test_the_table_has_both_indexes_and_no_ttl(prov):
    table = prov.expected_table_definition()
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    assert {g["IndexName"] for g in table["GlobalSecondaryIndexes"]} == {
        "customerId-createdAt-index", "orderId-index"}
    assert "TimeToLiveSpecification" not in json.dumps(table)


def test_the_handler_defaults_agree_with_the_provisioner(prov):
    source = (ROOT / "amplify/functions/ecommerce/service-requests/handler.py").read_text()
    for value in prov.expected_environment().values():
        if value.startswith("stack-"):
            assert value in source or value in (
                ROOT / "amplify/functions/shared/lambda_utils/ecommerce/"
                "service_request_store.py").read_text()


def test_the_dry_run_makes_no_mutating_call(prov, monkeypatch, capsys):
    calls = []

    class Recorder:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, op):
            def record(**kwargs):
                calls.append((self.name, op))
                if op.startswith(("get_", "describe_", "list_")):
                    from botocore.exceptions import ClientError
                    raise ClientError({"Error": {"Code": "ResourceNotFoundException"}}, op)
                return {}
            return record

    monkeypatch.setattr(prov.boto3, "client", lambda name, **_k: Recorder(name))
    assert prov.main([]) == 0
    mutating = [c for c in calls if not c[1].startswith(("get_", "describe_", "list_"))]
    assert mutating == [], mutating
    assert "dry run: nothing changed" in capsys.readouterr().out


def test_the_deploy_map_knows_the_function():
    text = (ROOT / "scripts/deploy_all_lambdas.py").read_text()
    assert '"wecare-service-requests"' in text and '"ecommerce/service-requests"' in text


def test_vault_file_selection_is_separate_and_exact(prov):
    assert prov.expected_vault_file_policy(ACCT) == {"Version": "2012-10-17", "Statement": [{
        "Sid": "BindSelectedVaultFile", "Effect": "Allow",
        "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
        "Resource": [f"arn:aws:dynamodb:us-east-1:{ACCT}:table/stack-wecare-digital-SecureFilesTable"]}]}
