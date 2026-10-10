"""`wecare-customer-profile-role` is the only role in the fleet that may link a contact.

The identity claim is a WRITE performed on the strength of a verified phone number, so the
interesting question about this role is not what it can do but what it cannot. The audit grant
added for the claim is `PutItem` on the audit log and nothing else: append-only, so this function
can record who linked which contact and can neither read the log back nor amend an entry.

Assertions are by `Sid` and by EQUALITY of each action set, because a document whose value is what
it leaves out is not tested by checking that it contains what it needs.

`scripts/provision_customer_profile.py::ensure_role` now reconciles the inline policy even when
the role already exists, so a re-run closes IAM drift instead of silently leaving the deployed
role without a newly required narrow grant. Without the audit grant `record_audit` fails open and
the identity link can still happen unaudited, so source and live IAM must remain aligned. The last
three tests drive `ensure_role` through a stub IAM and pin BOTH branches plus the dry run, because
a grant that is asserted in this file and never applied to the role is a grant that does not
exist.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "provision_customer_profile.py"
HANDLER = ROOT / "amplify/functions/auth/customer-profile/handler.py"

ACCOUNT = "775261844268"

#: Anything that could delete data, scan a table, move a file or message a person. None of these
#: may appear anywhere in the policy.
FORBIDDEN_ACTIONS = (
    "dynamodb:Scan", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem",
    "dynamodb:DeleteTable", "dynamodb:UpdateTable",
    "s3:", "sns:", "sqs:", "ses:", "iam:", "sts:", "kms:",
    "lambda:InvokeFunction",
)


@pytest.fixture(scope="module")
def provisioner():
    spec = importlib.util.spec_from_file_location("provision_customer_profile", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_customer_profile"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("provision_customer_profile", None)


def _statements(provisioner):
    return provisioner.expected_role_policy(ACCOUNT)["Statement"]


def _by_sid(provisioner):
    return {statement["Sid"]: statement for statement in _statements(provisioner)}


def _actions(provisioner):
    return [action for statement in _statements(provisioner) for action in statement["Action"]]


# ── the new audit grant ──────────────────────────────────────────────────────

def test_the_audit_grant_is_put_item_only_and_names_only_the_audit_table(provisioner):
    """One verb, one table. `PutItem` alone is append-only: no `GetItem`/`Query` to read other
    functions' audit records back, and no `UpdateItem` to rewrite one already written."""
    statement = _by_sid(provisioner)["WriteIdentityClaimAudit"]
    assert statement["Effect"] == "Allow"
    assert statement["Action"] == ["dynamodb:PutItem"]
    assert statement["Resource"] == [
        f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/stack-wecare-digital-AuditLogsTable"]


def test_the_granted_audit_table_is_the_one_the_helper_actually_writes_to(provisioner):
    """The ARN and `lambda_utils.audit`'s default are two copies of one name. If they drift the
    claim is unaudited and nothing fails loudly, because `record_audit` fails open."""
    sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
    from lambda_utils import audit

    assert provisioner.AUDIT_LOG_TABLE == audit.AUDIT_TABLE


def test_no_other_statement_names_the_audit_table(provisioner):
    for statement in _statements(provisioner):
        if statement["Sid"] == "WriteIdentityClaimAudit":
            continue
        assert "AuditLogsTable" not in json.dumps(statement["Resource"])


# ── the contacts grant is unchanged by the claim ─────────────────────────────

def test_the_contacts_grant_is_exactly_the_four_verbs_it_already_had(provisioner):
    """The conditional claim write needs `UpdateItem` and `Query`, both of which were already
    here. So the claim adds NO permission on contact rows, and this equality is what says so."""
    statement = _by_sid(provisioner)["ContactsUpsert"]
    assert set(statement["Action"]) == {
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"}
    assert statement["Resource"] == [
        f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/stack-wecare-digital-ContactsTable",
        f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/stack-wecare-digital-ContactsTable/index/*",
    ]


def test_the_policy_is_exactly_these_five_statements(provisioner):
    """Equality on the `Sid` set, so a sixth statement is a failure rather than an unnoticed
    addition."""
    assert sorted(_by_sid(provisioner)) == [
        "ContactsUpsert", "ReadEmailProof", "ReadOtpPepper", "ValidateCustomerToken",
        "WriteIdentityClaimAudit",
    ]


# ── what it cannot do ────────────────────────────────────────────────────────

@pytest.mark.parametrize("forbidden", FORBIDDEN_ACTIONS)
def test_no_destructive_or_messaging_verb_appears(provisioner, forbidden):
    for action in _actions(provisioner):
        assert not action.startswith(forbidden), f"{action} is granted and must not be"


def test_every_wildcard_resource_is_one_of_three_bounded_shapes(provisioner):
    """Three wildcards exist and each one is bounded by what precedes it.

    `cognito-idp:GetUser` is called with an access token and authorises the CALLER's own session,
    so it cannot name a user ARN at all. The pepper's `-*` is Secrets Manager's own six-character
    random suffix, which is not known until the secret is created. `ContactsTable/index/*` is
    that table's own indexes and nothing else. Anything outside these three is a widening.
    """
    for statement in _statements(provisioner):
        for resource in statement["Resource"]:
            if "*" not in resource:
                continue
            sid = statement["Sid"]
            assert sid in ("ValidateCustomerToken", "ReadOtpPepper", "ContactsUpsert"), \
                f"{sid} grants on a wildcard: {resource}"
            if sid == "ContactsUpsert":
                assert resource.endswith("ContactsTable/index/*")
            if sid == "ReadOtpPepper":
                assert resource.endswith(":secret:wecare/otp/pepper-*")
            if sid == "ValidateCustomerToken":
                assert resource == "*" and statement["Action"] == ["cognito-idp:GetUser"]


def test_the_role_cannot_read_a_secret_other_than_the_otp_pepper(provisioner):
    secrets = [resource for statement in _statements(provisioner)
               for resource in statement["Resource"] if "secretsmanager" in resource]
    assert secrets == [
        f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:wecare/otp/pepper-*"]


def test_it_is_serialisable_as_an_iam_document(provisioner):
    assert json.loads(json.dumps(provisioner.expected_role_policy(ACCOUNT)))


# ── the document the script applies is the document asserted here ───────────

def test_there_is_exactly_one_builder_for_this_document(provisioner):
    """The whole value of lifting the policy out of `ensure_role`: one builder, so a statement
    cannot be asserted in this file and omitted at provision time.

    This used to also grep the script for the literal call expression, which broke the moment
    `ensure_role` hoisted the `json.dumps(...)` into a local - a true statement about the code
    that a source-text match reads as a regression. The three tests below assert the same thing
    properly, by running `ensure_role` against a stub IAM and comparing the document it writes.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("def expected_role_policy") == 1
    assert source.count("put_role_policy(") == 2, \
        "one call per ensure_role branch; a third would be a second document to keep in step"


class FakeIam:
    """Just enough IAM to tell the two `ensure_role` branches apart, and to record every write."""

    def __init__(self, role_exists):
        self._role_exists = role_exists
        self.calls = []

    def get_role(self, **kwargs):
        self.calls.append(("get_role", kwargs))
        if self._role_exists:
            return {"Role": {"Arn": "arn:aws:iam::%s:role/%s" % (ACCOUNT, kwargs["RoleName"])}}
        raise ClientError({"Error": {"Code": "NoSuchEntity", "Message": "absent"}}, "GetRole")

    def create_role(self, **kwargs):
        self.calls.append(("create_role", kwargs))
        self._role_exists = True
        return {"Role": {"Arn": "arn"}}

    def attach_role_policy(self, **kwargs):
        self.calls.append(("attach_role_policy", kwargs))

    def put_role_policy(self, **kwargs):
        self.calls.append(("put_role_policy", kwargs))


@pytest.fixture
def iam_stub(provisioner, monkeypatch):
    def install(role_exists):
        fake = FakeIam(role_exists)
        monkeypatch.setattr(provisioner, "iam", lambda: fake)
        monkeypatch.setattr(provisioner, "account_id", lambda: ACCOUNT)
        return fake

    return install


#: The inline policy's name, spelled once here. Both `ensure_role` branches must write THIS
#: name, or a reconcile would leave the stale document attached under the old one.
POLICY_NAME = "CustomerProfileLeastPrivilege"


def _policy_writes(fake):
    return [kwargs for name, kwargs in fake.calls if name == "put_role_policy"]


def test_an_existing_role_has_its_inline_policy_reconciled(provisioner, iam_stub):
    """THE finding this test exists for. The deployed role predates the audit statement, so a
    provision run that skips `put_role_policy` leaves the claim unaudited for ever - and nothing
    complains, because `record_audit` and the handler's wrapper both fail open."""
    fake = iam_stub(role_exists=True)
    assert provisioner.ensure_role(False) == "reconciled"
    writes = _policy_writes(fake)
    assert len(writes) == 1
    assert writes[0]["PolicyName"] == POLICY_NAME
    document = json.loads(writes[0]["PolicyDocument"])
    assert document == provisioner.expected_role_policy(ACCOUNT)
    assert {statement["Sid"] for statement in document["Statement"]} >= {
        "WriteIdentityClaimAudit"}
    assert not [name for name, _ in fake.calls if name == "create_role"]


def test_a_dry_run_against_an_existing_role_writes_nothing(provisioner, iam_stub):
    fake = iam_stub(role_exists=True)
    assert provisioner.ensure_role(True) == "would reconcile policy"
    assert _policy_writes(fake) == []


def test_creating_the_role_applies_the_identical_document(provisioner, iam_stub):
    """One builder, both branches: a create and a reconcile cannot drift apart."""
    fake = iam_stub(role_exists=False)
    assert provisioner.ensure_role(False) == "created"
    writes = _policy_writes(fake)
    assert len(writes) == 1
    assert json.loads(writes[0]["PolicyDocument"]) == provisioner.expected_role_policy(ACCOUNT)
    assert writes[0]["PolicyName"] == POLICY_NAME


def test_the_claim_writes_through_the_shared_audit_helper(provisioner):
    """The zip packages `handler.py` plus `lambda_utils`, so the helper has to come from the
    shared layer rather than be re-implemented in the function."""
    source = HANDLER.read_text(encoding="utf-8")
    assert "from lambda_utils.audit import record_audit" in source
    assert "identity.claim" in source and "identity.claim_refused" in source
