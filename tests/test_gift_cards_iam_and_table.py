"""Gift-card provisioning contracts.

These tests pin the one execution role, the table's single KMS consumer, the pepper secret,
and the five HTTP routes.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

TABLE_SCRIPT = ROOT / "scripts" / "provision_gift_cards_table.py"
ROLES_SCRIPT = ROOT / "scripts" / "provision_gift_cards_roles.py"
ROUTES_SCRIPT = ROOT / "scripts" / "provision_gift_card_routes.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_only_native_gift_card_role_is_provisioned():
    roles = _load(ROLES_SCRIPT, "gift_roles_native")
    assert roles.ROLES == (
        (roles.GIFT_CARDS_ROLE, roles.GIFT_CARDS_POLICY,
         roles.gift_cards_policy, roles.GIFT_CARDS_FUNCTION),
    )
    assert roles.GIFT_CARDS_ROLE == "wecare-gift-cards-role"


def test_native_role_reads_exactly_one_secret_the_pepper():
    """The only secret the role may read is the store's own pepper secret id."""
    from lambda_utils.ecommerce import gift_card_store

    roles = _load(ROLES_SCRIPT, "gift_roles_policy")
    policy = roles.gift_cards_policy("arn:aws:kms:us-east-1:775261844268:key/test")
    secret_resources = [
        resource
        for statement in policy["Statement"]
        if any(action.startswith("secretsmanager:") for action in statement["Action"])
        for resource in statement["Resource"]
    ]
    assert secret_resources == [
        "arn:aws:secretsmanager:us-east-1:775261844268:secret:"
        f"{gift_card_store.SECRET_ID}-*"
    ]
    secret_actions = sorted({action for statement in policy["Statement"]
                             for action in statement["Action"]
                             if action.startswith("secretsmanager:")})
    assert secret_actions == ["secretsmanager:GetSecretValue"]


def test_table_key_policy_has_one_native_consumer():
    table = _load(TABLE_SCRIPT, "gift_table_native")
    assert table.CONSUMER_ROLES == ("wecare-gift-cards-role",)
    policy = table.key_policy()
    consumer = next(s for s in policy["Statement"]
                    if s["Sid"] == "GiftCardRolesViaDynamoDBOnly")
    assert consumer["Principal"]["AWS"] == [
        "arn:aws:iam::775261844268:role/wecare-gift-cards-role"
    ]
    assert consumer["Condition"]["StringEquals"]["kms:ViaService"] ==         "dynamodb.us-east-1.amazonaws.com"


def test_routes_expose_only_the_five_native_endpoints():
    routes = _load(ROUTES_SCRIPT, "gift_routes_native")
    assert routes.PLAN == (
        (routes.GIFT_CARDS_FUNCTION, routes.OWN_ROUTE_KEYS,
         "gift-cards*", "Gift-card issuance and balance"),
    )
    assert set(routes.OWN_ROUTE_KEYS) == {
        "POST /gift-cards",
        "GET /gift-cards/{giftCardId}",
        "GET /gift-cards",
        "POST /gift-cards/{giftCardId}/disable",
        "POST /gift-cards/balance",
    }
