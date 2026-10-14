"""AWS-native gift-card provisioning contracts.

The provider SPI was retired. These tests pin the surviving native role, table,
KMS consumer, pepper secret, and five HTTP routes.
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
    assert not hasattr(roles, "SPI_ROLE")
    assert not hasattr(roles, "SPI_FUNCTION")


def test_native_role_reads_only_the_neutral_pepper_secret():
    roles = _load(ROLES_SCRIPT, "gift_roles_policy")
    policy = roles.gift_cards_policy("arn:aws:kms:us-east-1:775261844268:key/test")
    resources = [
        r
        for statement in policy["Statement"]
        for r in statement.get("Resource", [])
    ]
    joined = "\n".join(resources)
    assert "wecare/prod/security/giftcard-pepper" in joined
    assert "wecare/wix/" not in joined


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
    source = ROUTES_SCRIPT.read_text(encoding="utf-8")
    assert "/wix-giftcards/" not in source
    assert "wecare-wix-giftcard-spi" not in source


def test_retired_spi_source_is_absent():
    assert not (ROOT / "amplify/functions/ecommerce/wix-giftcard-spi/handler.py").exists()
    assert not (
        ROOT / "amplify/functions/shared/lambda_utils/ecommerce/gift_card_spi_auth.py"
    ).exists()
