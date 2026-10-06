"""`wecare-customer-invoice-role` is the second layer of this route's security boundary.

The first layer is the key condition in the handler. This one is what makes the claim
structural: with `dynamodb:Query` on two INDEX ARNs and no statement on either table itself,
a `Scan` or a `GetItem` for `purchasedSnapshot` is an AccessDeniedException rather than a
code review finding; and with `s3:GetObject` pinned to the gated invoice prefix, this
function cannot read any other object in the bucket and cannot write one anywhere.

Every assertion here is EQUALITY rather than containment. A test that checks the policy
*contains* the statements it wants passes just as happily when a sixth is added, which is
the wrong direction for a document whose whole value is what it leaves out.

WRITTEN FROM SCRATCH FOR THIS SHAPE, not copied from `test_customer_orders_iam.py`, and two
of its assertions are deliberately NOT reused:

  - "nothing is granted on a wildcard resource" cannot hold here. An S3 object-prefix grant
    is inherently `.../*`, so the property worth asserting is that the PREFIX IS PINNED and
    is the gated one - which is what `test_the_s3_grant_is_pinned_to_the_gated_prefix` does.
    A pinned prefix and an open wildcard are different things and that test could not draw
    the distinction.
  - "the rate-limit table is the only bare table ARN" is false here. `InvoiceAssetsTable` is
    addressed on the table because its key `{invoiceId, assetType}` is FULLY SPECIFIED and
    there is nothing an index would narrow, so the rate-limit table is the SECOND bare table
    ARN on this role. That is stated explicitly below rather than left to read as drift.

`tests/test_customer_orders_iam.py` passing completely unchanged is an assertion about this
work rather than about that code: if it needed an edit, the route went on the wrong function.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "provision_customer_invoice.py"
HANDLER = ROOT / "amplify/functions/ecommerce/customer-invoice/handler.py"
ORDERS_SCRIPT = ROOT / "scripts" / "provision_customer_orders.py"

ACCOUNT = "775261844268"

#: Anything that could change data, read a credential, invoke code or message a person, plus
#: the two S3 verbs that would let this function write or delete a rendered invoice. None of
#: these may appear anywhere in the policy.
FORBIDDEN_ACTION_PREFIXES = (
    "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem",
    "dynamodb:Scan", "dynamodb:TransactWriteItems", "dynamodb:ConditionCheckItem",
    "s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:PutObjectAcl",
    "secretsmanager:", "kms:", "cognito-idp:", "lambda:InvokeFunction",
    "sns:", "sqs:", "ses:", "iam:", "sts:",
)


@pytest.fixture(scope="module")
def provisioner():
    spec = importlib.util.spec_from_file_location("provision_customer_invoice", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_customer_invoice"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("provision_customer_invoice", None)


def _statements(provisioner):
    return provisioner.expected_role_policy(ACCOUNT)["Statement"]


def _actions(provisioner):
    actions = []
    for statement in _statements(provisioner):
        actions.extend(statement["Action"])
    return actions


# ── the document, exactly ─────────────────────────────────────────────────────

def test_the_policy_is_exactly_these_five_statements(provisioner):
    """Equality, not containment, so a widening is a FAILURE rather than an unnoticed
    addition. FOUR READS PLUS ONE COUNTER INCREMENT, and the increment is the one most at
    risk of being 'simplified' away on the grounds that the function is read-only."""
    assert provisioner.expected_role_policy(ACCOUNT) == {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "QueryOwnOrdersByCustomer",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-OrderTable/index/customerId-createdAt-index"
                ],
            },
            {
                "Sid": "QueryInvoiceByReference",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-InvoicesTable/index/referenceId-index"
                ],
            },
            {
                "Sid": "ReadInvoiceAsset",
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem"],
                "Resource": [
                    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-InvoiceAssetsTable"
                ],
            },
            {
                "Sid": "SignGatedInvoiceObject",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": ["arn:aws:s3:::wecare-digital-get/secure/stack/invoices/*"],
            },
            {
                "Sid": "RateLimitCounter",
                "Effect": "Allow",
                "Action": ["dynamodb:UpdateItem"],
                "Resource": [
                    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-RateLimitTable"
                ],
            },
        ],
    }


def test_it_is_serialisable_as_an_iam_document(provisioner):
    # `put_role_policy` takes a JSON string; a document holding a non-serialisable value
    # would fail at provision time rather than here.
    assert json.loads(json.dumps(provisioner.expected_role_policy(ACCOUNT)))


# ── the action set ────────────────────────────────────────────────────────────

def test_the_action_set_is_three_read_verbs_and_one_counter_increment(provisioner):
    """EQUALITY. `dynamodb:UpdateItem` being in this list is the point: `check_rate_limit`
    is a `table.update_item` and it FAILS OPEN - an AccessDeniedException is neither a
    ValidationException nor a ResourceNotFoundException, so it logs at WARNING and returns
    True. Drop the grant and this presigning route answers every request unthrottled,
    reporting the cause once per request at a level nobody alarms on. That failure is
    invisible without this assertion."""
    assert sorted(set(_actions(provisioner))) == sorted([
        "dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem", "s3:GetObject"])


@pytest.mark.parametrize("forbidden", FORBIDDEN_ACTION_PREFIXES)
def test_no_write_credential_or_invoke_verb_appears(provisioner, forbidden):
    """The function is incapable of generating an invoice, of advancing the GST sequence, of
    writing or deleting an object under the gated prefix, of charging, of refunding and of
    messaging anyone - and that is a property of the role rather than of the code."""
    for action in _actions(provisioner):
        assert not action.startswith(forbidden), f"{action} is granted and must not be"


def test_the_policy_names_no_secret_in_any_spelling(provisioner):
    rendered = json.dumps(provisioner.expected_role_policy(ACCOUNT)).lower()
    for spelling in ("secretsmanager", "secret:", "getsecretvalue", "wecare/"):
        assert spelling not in rendered


# ── the two order/invoice tables are reachable ONLY through an index ──────────

def test_no_statement_names_the_order_or_invoices_table_without_an_index(provisioner):
    """A resource ARN ending at either table is the shape that makes a later `GetItem` for
    `purchasedSnapshot`, or a `Scan` of every invoice ever raised, succeed."""
    for statement in _statements(provisioner):
        for resource in statement["Resource"]:
            for table in ("stack-wecare-digital-OrderTable",
                          "stack-wecare-digital-InvoicesTable"):
                if table in resource:
                    assert "/index/" in resource, (
                        f"{statement['Sid']} names {table} without an index: {resource}")


def test_the_rate_limit_table_is_the_second_bare_table_arn_not_the_only_one(provisioner):
    """STATED EXPLICITLY rather than copied from `my-orders`' "only bare table ARN" wording,
    which is false here. `InvoiceAssetsTable` is correctly addressed on the table: its key
    `{invoiceId, assetType}` is fully specified, so there is nothing an index would narrow
    and a `GetItem` on a complete key cannot enumerate. These two and no others."""
    bare = [resource for statement in _statements(provisioner)
            for resource in statement["Resource"]
            if resource.startswith("arn:aws:dynamodb") and "/index/" not in resource]
    assert bare == [
        f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/stack-wecare-digital-InvoiceAssetsTable",
        f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/stack-wecare-digital-RateLimitTable",
    ]


def test_the_update_item_grant_cannot_touch_any_row_that_matters(provisioner):
    """`dynamodb:UpdateItem` IS granted, once, and only on the rate-limit counter. If it ever
    reached any of the other three tables this function could rewrite an order, an invoice or
    an asset pointer."""
    for statement in _statements(provisioner):
        if "dynamodb:UpdateItem" not in statement["Action"]:
            continue
        for resource in statement["Resource"]:
            for table in ("OrderTable", "ContactsTable", "InvoicesTable",
                          "InvoiceAssetsTable"):
                assert table not in resource, f"UpdateItem reaches {table}"


# ── the S3 grant: pinned prefix, gated root, nothing public ──────────────────

def test_the_s3_grant_is_pinned_to_the_gated_prefix(provisioner):
    """An object-prefix grant is inherently `.../*`, so the property worth asserting is not
    "no wildcard" but "the prefix is pinned, and it is the gated one"."""
    s3 = [statement for statement in _statements(provisioner)
          if statement["Action"] == ["s3:GetObject"]]
    assert len(s3) == 1
    assert s3[0]["Resource"] == [
        "arn:aws:s3:::wecare-digital-get/secure/stack/invoices/*"]
    for resource in s3[0]["Resource"]:
        assert resource.startswith("arn:aws:s3:::wecare-digital-get/secure/stack/invoices/")
        # Exactly one wildcard, and it is the trailing object segment - not a bucket-wide
        # grant and not a second wildcard somewhere in the prefix.
        assert resource.count("*") == 1
        assert resource.endswith("/*")


def test_no_statement_reaches_the_public_root(provisioner):
    """`o/` is served by CloudFront WITHOUT authentication. A rendered invoice carries a
    name, an address, an amount and a GSTIN, and the prefix moved off `o/` on 2026-09-30 for
    exactly that reason. Nothing on this role may reach back."""
    rendered = json.dumps(provisioner.expected_role_policy(ACCOUNT))
    assert "/o/" not in rendered
    for statement in _statements(provisioner):
        for resource in statement["Resource"]:
            assert not resource.startswith("arn:aws:s3:::wecare-digital-get/o/")


def test_it_creates_no_bucket_and_names_only_the_one_that_exists(provisioner):
    assert provisioner.MEDIA_BUCKET == "wecare-digital-get"
    assert provisioner.INVOICE_PREFIX == "secure/stack/invoices/"
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("create_bucket", "wecare-difital-get"):
        assert forbidden not in source


# ── names are one string in several places, and they must agree ──────────────

def test_the_policys_names_equal_the_handlers_defaults(provisioner):
    """The provisioner owns the names; the handler defaults to the same literals. Nothing
    else asserts these tables and indexes are meant to exist, so a rename in one place would
    otherwise surface as a 503 in production rather than as a red test."""
    source = HANDLER.read_text(encoding="utf-8")
    for variable, value in (
        ("ORDERS_TABLE", provisioner.ORDERS_TABLE),
        ("ORDERS_BY_CUSTOMER_INDEX", provisioner.ORDERS_BY_CUSTOMER_INDEX),
        ("INVOICES_TABLE", provisioner.INVOICES_TABLE),
        ("INVOICES_BY_REFERENCE_INDEX", provisioner.INVOICES_BY_REFERENCE_INDEX),
        ("INVOICE_ASSETS_TABLE", provisioner.INVOICE_ASSETS_TABLE),
        ("RATE_LIMIT_TABLE", provisioner.RATE_LIMIT_TABLE),
        ("MEDIA_BUCKET", provisioner.MEDIA_BUCKET),
    ):
        assert f'"{variable}", "{value}"' in source, (
            f"the handler does not default {variable} to {value!r}")


def test_the_order_index_name_agrees_with_the_script_that_owns_it(provisioner):
    """`provision_customer_orders.py` CREATES `customerId-createdAt-index`; this function
    only reads it. Two scripts naming one index is exactly the drift worth pinning, and this
    script deliberately has no `update_table` call of its own."""
    orders = importlib.util.spec_from_file_location(
        "provision_customer_orders_for_invoice_test", ORDERS_SCRIPT)
    module = importlib.util.module_from_spec(orders)
    orders.loader.exec_module(module)
    assert provisioner.ORDERS_BY_CUSTOMER_INDEX == module.ORDERS_BY_CUSTOMER_INDEX
    assert provisioner.ORDERS_TABLE == module.ORDERS_TABLE
    assert provisioner.RATE_LIMIT_TABLE == module.RATE_LIMIT_TABLE
    # Read off the AST, not the text: this script's own docstring says it has no
    # `update_table` call, so a substring sweep would fail on the sentence that makes the
    # promise. Only code is in scope.
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "update_table" not in called
    assert "create_bucket" not in called
    assert "put_object" not in called


def test_the_table_name_is_singular(provisioner):
    """`OrderTable`, not `OrdersTable`. The env var is plural and the table is not, and
    getting it wrong is a ResourceNotFoundException that reads as a missing index."""
    assert provisioner.ORDERS_TABLE == "stack-wecare-digital-OrderTable"
    assert "OrdersTable" not in json.dumps(provisioner.expected_role_policy(ACCOUNT))


# ── the invoke grant ─────────────────────────────────────────────────────────

def test_the_invoke_grant_is_alias_qualified_and_route_specific(provisioner):
    """A function-level statement does not authorise an invoke of an alias, and the symptom
    is a 500 with no Lambda log line at all because the function is never entered."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Qualifier=LIVE_ALIAS" in source
    assert provisioner.LIVE_ALIAS == "live"
    assert provisioner.ROUTE_KEY == "POST /ecommerce/my-invoice"
    # The source ARN names the one route, with no wildcard and no namespace prefix another
    # session's route could grow into.
    provisioner._account_id_cache = ACCOUNT
    assert provisioner.source_arn() == (
        f"arn:aws:execute-api:us-east-1:{ACCOUNT}:zllr9lrg7j/prod/POST/ecommerce/my-invoice")
    assert "*" not in provisioner.source_arn()
    assert provisioner.statement_id() == "apigateway-invoke-post-ecommerce-my-invoice"


def test_it_is_a_separate_role_from_the_order_list(provisioner):
    """The whole argument for a second function. If these ever became one role, the four
    grants above would land on the function that serves the hot list path."""
    assert provisioner.ROLE_NAME == "wecare-customer-invoice-role"
    assert provisioner.ROLE_NAME != "wecare-customer-orders-role"
    assert provisioner.FUNCTION_NAME == "wecare-customer-invoice"


# ── the environment carries names, never values ──────────────────────────────

def test_every_environment_value_is_a_name(provisioner):
    env = provisioner.expected_environment()
    assert set(env) == {
        "ORDERS_TABLE", "ORDERS_BY_CUSTOMER_INDEX", "INVOICES_TABLE",
        "INVOICES_BY_REFERENCE_INDEX", "INVOICE_ASSETS_TABLE", "RATE_LIMIT_TABLE",
        "MEDIA_BUCKET", "CUSTOMER_POOL_ID",
    }
    # No value here can enable anything, and none is a credential.
    rendered = json.dumps(env).lower()
    for spelling in ("secret", "token", "key_id", "password", "rzp_", "sk_"):
        assert spelling not in rendered
    # The CUSTOMER pool, deliberately not the staff pool.
    assert env["CUSTOMER_POOL_ID"] == "us-east-1_46ULYuukt"
