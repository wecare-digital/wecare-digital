"""`wecare-customer-orders-role` is the second layer of the order-list security boundary.

The first layer is the key condition in the handler. This one is what makes the claim structural:
with `dynamodb:Query` on the INDEX ARN and no statement on the order table itself, a `Scan` or a
`GetItem` for `purchasedSnapshot` is an AccessDeniedException rather than a code review finding.

Every assertion here is EQUALITY rather than containment. A test that checks the policy *contains*
the three statements it wants passes just as happily when a fourth is added, which is the wrong
direction for a document whose whole value is what it leaves out.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "provision_customer_orders.py"
HANDLER = ROOT / "amplify/functions/ecommerce/customer-orders/handler.py"

ACCOUNT = "775261844268"

#: Anything that could change data, read a credential, invoke code or message a person. None of
#: these may appear anywhere in the policy.
FORBIDDEN_ACTION_PREFIXES = (
    "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem",
    "dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Scan",
    "dynamodb:TransactWriteItems", "dynamodb:ConditionCheckItem",
    "secretsmanager:", "kms:", "cognito-idp:", "lambda:InvokeFunction",
    "sns:", "sqs:", "ses:", "s3:", "iam:", "sts:",
)


@pytest.fixture(scope="module")
def provisioner():
    spec = importlib.util.spec_from_file_location("provision_customer_orders", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_customer_orders"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("provision_customer_orders", None)


def _statements(provisioner):
    return provisioner.expected_role_policy(ACCOUNT)["Statement"]


def _actions(provisioner):
    actions = []
    for statement in _statements(provisioner):
        actions.extend(statement["Action"])
    return actions


# ── the document, exactly ─────────────────────────────────────────────────────

def test_the_policy_is_exactly_these_three_statements(provisioner):
    """Equality, not containment, so a widening is a FAILURE rather than an unnoticed addition."""
    assert provisioner.expected_role_policy(ACCOUNT) == {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "QueryOwnOrdersByCustomer",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                # TWO index ARNs and still ONE verb. The second is `customerId-createdAt-v2-index`,
                # which carries `channel` in its projection - a GSI projection is immutable, so it
                # is a new index rather than a widened one, and the grant has to exist before the
                # function's `ORDERS_BY_CUSTOMER_INDEX` is repointed onto it. v1 keeps its grant
                # because v1 keeps serving until that repoint happens.
                "Resource": [
                    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-OrderTable/index/customerId-createdAt-index",
                    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-OrderTable/index/customerId-createdAt-v2-index",
                ],
            },
            {
                "Sid": "ReadOwnContactProfile",
                "Effect": "Allow",
                "Action": ["dynamodb:Query"],
                "Resource": [
                    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-ContactsTable/index/phone-index"
                ],
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
    # `put_role_policy` takes a JSON string; a document holding a non-serialisable value would
    # fail at provision time rather than here.
    assert json.loads(json.dumps(provisioner.expected_role_policy(ACCOUNT)))


# ── the order table is reachable ONLY through the index ───────────────────────

def test_no_statement_names_the_order_table_without_an_index(provisioner):
    """The whole point of the first statement. A resource ARN ending at the table would grant the
    action on the table AND on nothing else useful - but more importantly it is the shape that
    makes a later `GetItem` for `purchasedSnapshot` succeed."""
    for statement in _statements(provisioner):
        for resource in statement["Resource"]:
            if "stack-wecare-digital-OrderTable" in resource:
                assert "/index/" in resource, (
                    f"{statement['Sid']} names the order table without an index: {resource}")


def test_the_rate_limit_table_is_the_only_bare_table_arn(provisioner):
    """`check_rate_limit` is one atomic increment on a fully specified key, so it is addressed on
    the table and needs no index - and it is the ONLY resource that may be."""
    bare = [resource for statement in _statements(provisioner)
            for resource in statement["Resource"] if "/index/" not in resource]
    assert bare == [f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                    f"stack-wecare-digital-RateLimitTable"]


def test_nothing_is_granted_on_a_wildcard_resource(provisioner):
    for statement in _statements(provisioner):
        for resource in statement["Resource"]:
            assert "*" not in resource, f"{statement['Sid']} grants on a wildcard: {resource}"


# ── what it cannot do ─────────────────────────────────────────────────────────

def test_the_action_set_is_two_read_verbs_and_one_counter_increment(provisioner):
    assert sorted(set(_actions(provisioner))) == ["dynamodb:Query", "dynamodb:UpdateItem"]


@pytest.mark.parametrize("forbidden", FORBIDDEN_ACTION_PREFIXES)
def test_no_write_credential_or_invoke_verb_appears(provisioner, forbidden):
    """The function is incapable of writing an order, of charging, of refunding and of messaging
    anyone, and that is a property of the role rather than of the code."""
    for action in _actions(provisioner):
        assert not action.startswith(forbidden), f"{action} is granted and must not be"


def test_the_update_item_grant_cannot_touch_order_or_contact_rows(provisioner):
    """`dynamodb:UpdateItem` IS granted, once, and only on the rate-limit counter. If it ever
    reached either of the other two tables this function could rewrite an order."""
    for statement in _statements(provisioner):
        if "dynamodb:UpdateItem" not in statement["Action"]:
            continue
        for resource in statement["Resource"]:
            assert "OrderTable" not in resource
            assert "ContactsTable" not in resource


def test_the_policy_names_no_secret_in_any_spelling(provisioner):
    rendered = json.dumps(provisioner.expected_role_policy(ACCOUNT)).lower()
    for spelling in ("secretsmanager", "secret:", "getsecretvalue", "wecare/"):
        assert spelling not in rendered


# ── the index name is one string in two places, and they must agree ───────────

def test_the_policys_index_name_equals_the_handlers_constant(provisioner):
    """The provisioner owns the name; the handler defaults to the same literal.

    Nothing outside this script knows the index is meant to exist -
    `scripts/check_data_model_drift.py` does not assert a DescribeTable for the order table - so a
    rename in one place would otherwise surface as a 503 in production rather than as a red test.
    """
    source = HANDLER.read_text(encoding="utf-8")
    name = provisioner.ORDERS_BY_CUSTOMER_INDEX
    assert f'"ORDERS_BY_CUSTOMER_INDEX", "{name}"' in source, (
        f"the handler does not default ORDERS_BY_CUSTOMER_INDEX to {name!r}")
    # The handler's DEFAULT stays v1, because the serving index is still v1 and a default is what
    # answers when the env var is absent. The repoint is a deliberate, separately-gated step.
    assert provisioner.SERVING_INDEX == name
    granted = [resource for statement in _statements(provisioner)
               for resource in statement["Resource"] if "OrderTable" in resource]
    assert granted == [f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                       f"stack-wecare-digital-OrderTable/index/{name}",
                       f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/"
                       f"stack-wecare-digital-OrderTable/index/"
                       f"{provisioner.ORDERS_BY_CUSTOMER_INDEX_V2}"]


def test_the_table_name_is_singular(provisioner):
    """`OrderTable`, not `OrdersTable`. The env var is plural and the table is not, and getting it
    wrong is a ResourceNotFoundException that reads as a missing index."""
    assert provisioner.ORDERS_TABLE == "stack-wecare-digital-OrderTable"
    assert "OrdersTable" not in json.dumps(provisioner.expected_role_policy(ACCOUNT))


# ── the index definition itself ───────────────────────────────────────────────

def test_the_index_is_customer_partitioned_and_date_sorted(provisioner):
    assert provisioner.INDEX_DEFINITION["KeySchema"] == [
        {"AttributeName": "customerId", "KeyType": "HASH"},
        {"AttributeName": "createdAt", "KeyType": "RANGE"},
    ]


def test_the_projection_is_include_and_excludes_the_purchased_snapshot(provisioner):
    """`ALL` would project the frozen cart - tens of kilobytes including a delivery address -
    into a second copy of the data. `INCLUDE` is data minimisation enforced by the storage layer,
    and the IAM grant above makes it structural rather than a promise."""
    projection = provisioner.INDEX_DEFINITION["Projection"]
    assert projection["ProjectionType"] == "INCLUDE"
    assert projection["NonKeyAttributes"] == [
        "orderNumber", "referenceId", "amountPaise", "currency", "paymentStatus"]
    assert "purchasedSnapshot" not in projection["NonKeyAttributes"]
    assert "snapshotHash" not in projection["NonKeyAttributes"]


def test_the_key_attributes_are_not_repeated_in_the_projection(provisioner):
    """`UpdateTable` rejects the duplication: the three key attributes are projected
    automatically."""
    attributes = provisioner.INDEX_DEFINITION["Projection"]["NonKeyAttributes"]
    for key in ("customerId", "createdAt", "orderId"):
        assert key not in attributes


# ── the second index, which exists because the first one's projection is frozen ──

def test_the_second_index_is_an_addition_and_the_first_is_untouched(provisioner):
    """THE WHOLE REASON THERE ARE TWO. A GSI projection is immutable after creation, so carrying
    `channel` to `/orders` means a new index; widening v1 would mean deleting and recreating the
    index every order list is served from, leaving every customer's history partial for the
    length of a backfill. v1's definition is asserted unchanged, by equality, right here."""
    assert provisioner.ORDERS_BY_CUSTOMER_INDEX_V2 == "customerId-createdAt-v2-index"
    assert provisioner.ORDERS_BY_CUSTOMER_INDEX != provisioner.ORDERS_BY_CUSTOMER_INDEX_V2
    assert provisioner.INDEX_DEFINITION["IndexName"] == "customerId-createdAt-index"
    assert provisioner.INDEX_DEFINITION["Projection"]["NonKeyAttributes"] == [
        "orderNumber", "referenceId", "amountPaise", "currency", "paymentStatus"]


def test_the_second_index_has_the_same_keys_so_the_repoint_is_not_a_behaviour_change(provisioner):
    assert (provisioner.INDEX_DEFINITION_V2["KeySchema"]
            == provisioner.INDEX_DEFINITION["KeySchema"])


def test_the_second_index_projects_exactly_the_first_plus_channel(provisioner):
    projection = provisioner.INDEX_DEFINITION_V2["Projection"]
    assert projection["ProjectionType"] == "INCLUDE"
    assert projection["NonKeyAttributes"] == [
        "orderNumber", "referenceId", "amountPaise", "currency", "paymentStatus", "channel"]
    # Still minimised. `purchasedSnapshot` is the frozen cart including a delivery address, and
    # keeping a second copy of it out of the index is what the Query-only grant makes structural.
    assert "purchasedSnapshot" not in projection["NonKeyAttributes"]
    assert "snapshotHash" not in projection["NonKeyAttributes"]
    for key in ("customerId", "createdAt", "orderId"):
        assert key not in projection["NonKeyAttributes"]


def test_the_env_repoint_is_deferred_behind_an_active_check(provisioner):
    """`SERVING_INDEX` is still v1 and the move is its own command. A Query against a CREATING
    index raises ResourceNotFoundException, which this handler answers with a 503 and no partial
    list - so a repoint performed a moment early takes every order history down for a backfill."""
    assert provisioner.SERVING_INDEX == provisioner.ORDERS_BY_CUSTOMER_INDEX
    assert (provisioner.expected_environment()["ORDERS_BY_CUSTOMER_INDEX"]
            == provisioner.ORDERS_BY_CUSTOMER_INDEX)
    # The override exists, and it is the only way the v2 name reaches the environment.
    assert (provisioner.expected_environment(
        provisioner.ORDERS_BY_CUSTOMER_INDEX_V2)["ORDERS_BY_CUSTOMER_INDEX"]
        == provisioner.ORDERS_BY_CUSTOMER_INDEX_V2)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def repoint_serving_index" in source
    assert "--repoint-serving-index" in source
    # The refusal is a status comparison against ACTIVE inside that function, not a comment.
    body = source[source.index("def repoint_serving_index"):]
    body = body[:body.index("\ndef ")]
    assert 'status != "ACTIVE"' in body
    assert "REFUSED" in body


def test_the_second_index_is_created_and_is_not_a_mutation_of_the_first(provisioner):
    """`update_table` may only ever CREATE here. An `Update` or a `Delete` on a GSI in this script
    would be the delete-and-recreate the module docstring refuses to perform silently."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert '{"Create": INDEX_DEFINITION_V2}' in source
    assert '{"Create": INDEX_DEFINITION}' in source
    assert '"Delete":' not in source
    assert '"Update": INDEX_DEFINITION' not in source


def test_the_invoke_grant_is_alias_qualified_and_route_specific(provisioner):
    """A function-level statement does not authorise an invoke of an alias, and the symptom is a
    500 with no Lambda log line at all because the function is never entered."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'Qualifier=LIVE_ALIAS' in source
    assert provisioner.LIVE_ALIAS == "live"
    assert provisioner.ROUTE_KEY == "POST /ecommerce/my-orders"
    # The source ARN names the one route, with no wildcard and no namespace prefix another
    # session's route could grow into.
    provisioner._account_id_cache = ACCOUNT
    assert provisioner.source_arn() == (
        f"arn:aws:execute-api:us-east-1:{ACCOUNT}:zllr9lrg7j/prod/POST/ecommerce/my-orders")
    assert provisioner.statement_id() == "apigateway-invoke-post-ecommerce-my-orders"
