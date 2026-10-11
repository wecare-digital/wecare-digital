"""The checkout provisioning contract, pinned so a later edit has to be deliberate.

Why these assertions and not others
-----------------------------------
`scripts/provision_checkout.py` creates a function on the live payment path. Three of its
properties are the difference between "deployed and inert" and "deployed and chargeable", and
none of them is visible from reading the handler:

1. **The gate is absent from the environment the script sets.** Not `"false"` - absent. A key
   that exists is a key someone can flip with one `update-function-configuration`; an absent key
   plus two empty readiness inputs means two separate owner actions are required.
2. **The integration targets the `live` alias, and the invoke permission is qualified to it.** A
   function-level permission does not authorise an alias invoke, and the failure is a 500 with no
   Lambda log line at all - the function is never entered, so there is nothing to debug.
3. **The role grants no Razorpay credential read.** `razorpay_orders.RAZORPAY_SECRET_ID` defaults
   to `wecare/razorpay/api`, but nothing in the handler's import closure reaches it, so granting
   the read would widen privilege for code that cannot run.

The route-key list is pinned as an exact tuple rather than a membership check, because the
interesting failure is an ADDED route - a `{proxy+}` or a `GET` would widen the public surface
past the two consumers that exist.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "provision_checkout.py"
TEMPLATE = ROOT / "amplify" / "infra" / "checkout.json"


@pytest.fixture(scope="module")
def provisioner():
    spec = importlib.util.spec_from_file_location("provision_checkout", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["provision_checkout"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("provision_checkout", None)


# ── the gate ──────────────────────────────────────────────────────────────────

def test_the_initiation_flag_is_absent_not_false(provisioner):
    """Absent, so enabling it is an addition rather than an edit of an existing value."""
    env = provisioner.expected_environment()
    assert "CHECKOUT_INITIATION_ENABLED" not in env


def test_both_readiness_inputs_are_empty(provisioner):
    """The second, independent block. `payment_readiness.evaluate` returns
    CONFIGURATION_UNVERIFIED on an empty configuration name or MID, so flipping the gate alone
    still cannot produce a payable message."""
    env = provisioner.expected_environment()
    assert env["EXPECTED_CONFIGURATION_NAME"] == ""
    assert env["EXPECTED_PROVIDER_MID"] == ""


def test_no_environment_value_looks_like_a_credential(provisioner):
    """Secret NAMES only. The manifest this feeds is committed to the repository."""
    env = provisioner.expected_environment()
    assert env["WIX_API_KEY_SECRET"] == "wecare/wix/headless-api-key"
    issuer_shapes = ("rzp_live_", "rzp_test_", "sk-", "AIza", "ghp_", "xoxb-",
                     "AKIA", "ASIA", "sk_live_", "-----BEGIN")
    for key, value in env.items():
        for shape in issuer_shapes:
            assert shape not in value, f"{key} carries an issuer-shaped value"


# ── routes and the alias-qualified invoke ─────────────────────────────────────

def test_exactly_five_route_keys_and_no_proxy(provisioner):
    """Five since 2026-10-08, and the fifth is the only GET.

    `GET /ecommerce/service-prices` is the anonymous live-price read the four public service
    pages make before a visitor has signed in. It is allow-listed by name in
    `scripts/audit_route_auth.py` and in `tests/test_route_auth_enforcement.py` -- two edits in
    two files, which is the gate on exempting a route from authentication. The method matters as
    much as the path, so the per-key assertion below is method-aware rather than being relaxed
    to "any method": a POST to this path must stay behind `require_customer`.
    """
    assert provisioner.ROUTE_KEYS == (
        "POST /ecommerce/checkout",
        "POST /ecommerce/checkout/status",
        "POST /ecommerce/prepare-checkout",
        "POST /ecommerce/verify-callback",
        "GET /ecommerce/service-prices",
    )
    public = {"GET /ecommerce/service-prices"}
    for key in provisioner.ROUTE_KEYS:
        assert "{" not in key, f"{key} is a greedy/path-parameter route"
        assert key.startswith("GET " if key in public else "POST "), \
            f"{key} widens the surface past its intended method"


def test_the_one_anonymous_route_carries_its_own_throttle(provisioner):
    """The bound on Wix reads that does not depend on the edge continuing to cache.

    A cache MISS on the anonymous price read costs eight Wix calls (`get` + `estimate` per
    variant) on the SAME API key the live checkout prices real baskets with, so anonymous traffic
    here can induce provider throttling that reaches the payment path. The `/api/*` edge WAS
    measured caching a `public, max-age` response on 2026-10-08, which keeps origin volume to
    roughly one fill per PoP per minute -- but that is someone else's configuration and an
    Amplify rewrite edit would remove it with nothing in this repo noticing.

    Pinned as exact numbers rather than "a throttle exists", because the interesting regression is
    a loosened cap, and pinned on the PRICE route specifically: the other four require a session.
    """
    assert provisioner.PRICE_ROUTE_KEY == "GET /ecommerce/service-prices"
    assert provisioner.PRICE_ROUTE_KEY in provisioner.ROUTE_KEYS
    assert provisioner.ROUTE_THROTTLE_RATE == 5.0
    assert provisioner.ROUTE_THROTTLE_BURST == 10
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def ensure_route_throttle(" in source
    # Applied in the same run that creates the route, and read back by --verify rather than
    # assumed: a throttle nobody checks is a throttle that quietly goes missing.
    assert "ensure_route_throttle(args.dry_run)" in source
    assert "is not throttled at" in source


def test_the_throttle_write_sends_only_its_own_route_key(provisioner):
    """`UpdateStage` MERGES RouteSettings and VALIDATES the merged map, so sending another
    route's key is how one script drops a throttle another owns. Only `PRICE_ROUTE_KEY` is ever
    written, and a stale key for a deleted route is REPORTED rather than deleted here --
    `deploy_mcp_server` owns `DeleteRouteSettings` and the argument for why removal is safe."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "RouteSettings={PRICE_ROUTE_KEY: wanted}" in source
    assert "delete_route_settings" not in source
    assert "deploy_mcp_server" in source


def test_the_shared_stage_is_not_declared_in_the_template(provisioner):
    """The throttle is a stage setting and the `prod` stage is shared by every other route on the
    API, so the template takes the API as a PARAMETER and must not claim the stage. The route's
    metadata records where the cap lives instead, so the IaC is not silent about it."""
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    types = {name: body.get("Type") for name, body in template["Resources"].items()}
    assert "AWS::ApiGatewayV2::Stage" not in types.values()
    throttle = template["Resources"]["ServicePricesRoute"]["Metadata"]["WECARE::Throttle"]
    recorded = " ".join(throttle)
    assert "5 rps" in recorded and "10 burst" in recorded
    assert "provision_checkout.py" in recorded


def test_the_integration_targets_the_live_alias(provisioner):
    """`:live`, not `$LATEST`. The 58 aliased functions in this fleet all work this way, and
    `lambda-snapstart-deploy` steering requires the alias to be what production invokes."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def function_arn(" in source
    assert 'f"{arn}:{LIVE_ALIAS}" if qualified else arn' in source
    assert 'IntegrationType="AWS_PROXY"' in source
    assert 'PayloadFormatVersion="2.0"' in source
    assert "function_arn(qualified=True)" in source


def test_the_invoke_permission_is_qualified_to_the_alias(provisioner):
    """Every `add_permission` call is alias-qualified and takes its SourceArn from `source_arn()`.

    Asserted over the AST rather than by looking for one spelling: the scope lives in
    `source_arn()`, and a test that insists on the literal `SourceArn=source_arn()` fails when the
    value is hoisted to a local even though the property is unchanged. What must not be possible is
    an unqualified statement, or a SourceArn assembled somewhere other than `source_arn()`.
    """
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    grants = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "add_permission"]
    assert grants, "the provisioner grants no invoke permission at all"

    for call in grants:
        kwargs = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
        assert kwargs.get("Qualifier") == "LIVE_ALIAS", \
            f"line {call.lineno}: a function-level statement does not authorise an alias invoke"
        assert kwargs.get("Principal") == "'apigateway.amazonaws.com'"
        arn, sid = kwargs.get("SourceArn"), kwargs.get("StatementId")
        owner = next(f for f in ast.walk(tree)
                     if isinstance(f, ast.FunctionDef)
                     and f.lineno <= call.lineno <= (f.end_lineno or call.lineno))
        # A local is fine, as long as it is bound to the two helpers that own scope and identity.
        # Tuple targets are paired element-wise off the AST rather than by splitting the unparsed
        # text, which cannot be done safely once a value contains a comma of its own.
        bound = {}
        for assign in (n for n in ast.walk(owner) if isinstance(n, ast.Assign)):
            for target in assign.targets:
                if isinstance(target, ast.Tuple) and isinstance(assign.value, ast.Tuple) \
                        and len(target.elts) == len(assign.value.elts):
                    for element, value in zip(target.elts, assign.value.elts):
                        bound[ast.unparse(element)] = ast.unparse(value)
                else:
                    bound[ast.unparse(target)] = ast.unparse(assign.value)
        assert arn.startswith("source_arn(") or bound.get(arn, "").startswith("source_arn("), \
            f"line {call.lineno}: SourceArn={arn} does not come from source_arn()"
        assert sid.startswith("route_statement_id(") \
            or bound.get(sid, "").startswith("route_statement_id("), \
            f"line {call.lineno}: StatementId={sid} does not come from route_statement_id()"


def test_the_source_arn_holds_no_wildcard_at_all(provisioner, monkeypatch):
    """Narrowed twice on 2026-10-01, and the second step is the one that matters.

    `{API_ID}/*/*` authorised any stage and any method/path on this API - scoped to one API, so
    never a wildcard over the account, but 360 routes wider than the two that exist. The obvious
    replacement was the prefix `prod/POST/ecommerce/*`, and it was measured to be insufficient:
    another session had already added `POST /ecommerce/customer-session`, so the prefix matched a
    third route belonging to a different function. A prefix is a namespace somebody else can grow
    into.

    So: one statement per route key, each carrying that route's exact ARN. Asserted on the rendered
    value, so an edit that keeps the shape and widens the scope still fails.
    """
    monkeypatch.setattr(provisioner, "_account_id_cache", "775261844268")
    assert provisioner.API_ID == "zllr9lrg7j"
    assert provisioner.STAGE == "prod"

    rendered = {key: provisioner.source_arn(key) for key in provisioner.ROUTE_KEYS}
    assert rendered == {
        "POST /ecommerce/checkout":
            "arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/POST/ecommerce/checkout",
        "POST /ecommerce/checkout/status":
            "arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/POST/ecommerce/"
            "checkout/status",
        "POST /ecommerce/prepare-checkout":
            "arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/POST/ecommerce/"
            "prepare-checkout",
        "POST /ecommerce/verify-callback":
            "arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/POST/ecommerce/"
            "verify-callback",
        # The anonymous price read. Its ARN pins GET: the statement authorises API Gateway to
        # invoke this function for GET on this one path and for nothing else, so the public
        # exemption cannot silently widen to POST at the permission layer either.
        "GET /ecommerce/service-prices":
            "arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/GET/ecommerce/"
            "service-prices",
    }
    for key, arn in rendered.items():
        assert "*" not in arn, f"{key} -> {arn} still carries a wildcard"

    # And the sibling route another session owns must NOT be covered by any of them.
    foreign = ("arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/POST/"
               "ecommerce/customer-session")
    assert foreign not in rendered.values()
    assert not any(foreign.startswith(arn.rstrip("*")) and arn.endswith("*")
                   for arn in rendered.values())


def test_one_statement_id_per_route_and_they_are_distinct(provisioner):
    ids = [provisioner.route_statement_id(k) for k in provisioner.ROUTE_KEYS]
    assert ids == ["apigateway-invoke-post-ecommerce-checkout",
                   "apigateway-invoke-post-ecommerce-checkout-status",
                   "apigateway-invoke-post-ecommerce-prepare-checkout",
                   "apigateway-invoke-post-ecommerce-verify-callback",
                   "apigateway-invoke-get-ecommerce-service-prices"]
    assert len(set(ids)) == len(ids), "two routes would share one statement"
    # Lambda accepts [a-zA-Z0-9-_]+ only; a '/' or ' ' here is a ValidationException at runtime.
    for sid in ids:
        assert all(c.isalnum() or c in "-_" for c in sid), sid
    assert not set(ids) & set(provisioner.LEGACY_STATEMENT_IDS)


def test_the_narrowing_adds_before_it_removes(provisioner):
    """`add_permission` cannot edit a statement, and remove-then-add under one id leaves a window
    where the routes resolve to a target API Gateway is not authorised to invoke - a 500 with no
    Lambda log line. So the narrow statements carry NEW ids, and the superseded ones come off only
    after they are in place."""
    assert provisioner.LEGACY_STATEMENT_IDS == (
        "apigateway-invoke-checkout", "apigateway-invoke-checkout-ecommerce")
    body = SCRIPT.read_text(encoding="utf-8") \
        .split("def ensure_invoke_permission")[1].split("\ndef ")[0]
    assert body.index("add_permission(") < body.index("remove_permission("), \
        "a superseded statement comes off before the narrow ones go on"


def test_verify_reads_every_invoke_statement_back(provisioner):
    """A missing statement, one scoped wider than its route, a superseded one left behind, or an
    EXTRA one nobody here created must all FAIL rather than be inferred from the routes existing."""
    body = SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    assert "live_policy_statements()" in body
    assert "LEGACY_STATEMENT_IDS" in body
    assert "_statement_source_arn(" in body
    assert "route_statement_id(" in body
    assert "unexpected" in body, "an extra statement would pass unnoticed"


def test_route_creation_never_deletes_or_retargets(provisioner):
    """Additive only. 359 pre-existing routes belong to other functions."""
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("delete_route", "delete_integration", "update_route",
                      "update_integration", "delete_function", "delete_alias"):
        assert forbidden not in source, f"provisioner calls {forbidden}"


# ── IAM: least privilege, and what it deliberately omits ──────────────────────

def _policy(provisioner) -> dict:
    """The inline policy document exactly as the provisioner intends to reconcile it."""
    return provisioner.expected_role_policy("775261844268")


def test_the_role_reads_only_the_two_canonical_provider_secrets(provisioner):
    """Website checkout now reaches razorpay_orders, so the API secret read is intentional.

    The webhook signing secret is deliberately absent: checkout creates/verifies API payments,
    while the webhook Lambda alone verifies webhook signatures.
    """
    secrets = [r for s in _policy(provisioner)["Statement"]
               if "secretsmanager:GetSecretValue" in s["Action"] for r in s["Resource"]]
    assert sorted(secrets) == sorted([
        "arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/wix/headless-api-key-*",
        "arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/razorpay/api-*",
    ])
    assert "wecare/razorpay-webhook" not in json.dumps(_policy(provisioner))


# ── A2.4: the invoke grant, in BOTH of its homes ──────────────────────────────
#
# `wecare-checkout-role` is defined TWICE — here in the provisioner's `expected_role_policy()`
# and in `amplify/infra/checkout.json`'s `CheckoutRole` — and the two have already drifted apart
# once. These are the only offline catch for that class of regression.

EXPECTED_INVOKE_ARNS = sorted([
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-whatsapp-business-api",
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-whatsapp-business-api:live",
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-outbound-whatsapp",
    "arn:aws:lambda:us-east-1:775261844268:function:wecare-outbound-whatsapp:live",
])


def _checkout_role_policy() -> dict:
    """The CloudFormation copy of the same inline policy, unwrapped to the document."""
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    policy = template["Resources"]["CheckoutRole"]["Properties"]["Policies"][0]
    document = dict(policy["PolicyDocument"])
    document["PolicyName"] = policy["PolicyName"]
    return document


def _normalise(resource) -> str:
    """`Fn::Sub` with the two pseudo-parameters resolved, so the two homes are comparable."""
    if isinstance(resource, dict):
        resource = resource["Fn::Sub"]
    return (str(resource).replace("${AWS::Region}", "us-east-1")
            .replace("${AWS::AccountId}", "775261844268"))


def _statement(policy: dict, sid: str) -> dict:
    return next(s for s in policy["Statement"] if s["Sid"] == sid)


def test_the_invoke_grant_names_the_outbound_sender_in_the_provisioner(provisioner):
    """Without this grant the in-chat send raises `AccessDeniedException` — and for the catalog
    leg it does so AFTER the attempt, the reference and the one-shot claim are written, surfacing
    as a 500 that looks like a Meta problem.

    Four ARNs, NO wildcard. This is a widening of a least-privilege policy by one function and
    its alias, on a role used by one function; it grants no new data access and no ability to
    charge.
    """
    statement = _statement(_policy(provisioner), "InvokeWhatsAppSender")
    assert statement["Action"] == ["lambda:InvokeFunction"]
    assert sorted(statement["Resource"]) == EXPECTED_INVOKE_ARNS
    assert not any("*" in arn for arn in statement["Resource"])


def test_the_invoke_grant_names_the_outbound_sender_in_cloudformation():
    statement = _statement(_checkout_role_policy(), "InvokeWhatsAppSender")
    assert statement["Action"] == ["lambda:InvokeFunction"]
    assert sorted(_normalise(r) for r in statement["Resource"]) == EXPECTED_INVOKE_ARNS
    assert not any("*" in _normalise(r) for r in statement["Resource"])


def test_the_two_homes_agree_on_the_invoke_grant(provisioner):
    """Pinned EQUAL, because whichever home is applied last wins."""
    script = sorted(_statement(_policy(provisioner), "InvokeWhatsAppSender")["Resource"])
    template = sorted(_normalise(r) for r in
                      _statement(_checkout_role_policy(), "InvokeWhatsAppSender")["Resource"])
    assert script == template


def test_the_two_homes_agree_on_every_statement(provisioner):
    """The two definitions of `wecare-checkout-role` carry the SAME statement set — no drift.

    Owner ruling (resolved): `amplify/infra/checkout.json` previously carried a
    `CouponAndGiftCardRedemption` statement granting the role GetItem/PutItem/UpdateItem/DeleteItem
    on `CouponsTable` and `GiftCardsTable` that `expected_role_policy()` did not. Because both
    documents use the same `PolicyName` (`CheckoutLeastPrivilege`) and `ensure_role` calls
    `put_role_policy` (replace, not merge), running the provisioner would have STRIPPED that
    statement from the live role.

    Verified before resolving: the checkout function closure references neither table — coupons and
    gift cards on the website path are Wix-authoritative (`wixGiftCardRedeemPaise`, `wix-giftcard-spi`,
    `gift_card_settlement`), and the only functions touching the legacy `CouponsTable`/`GiftCardsTable`
    are `wix-giftcard-spi` and the shared `coupon_store`/`gift_card_store` modules — NOT this role.
    So the grant was a stale over-grant, not a needed permission. The owner's resolution is to drop
    the stale statement from `checkout.json` (least-privilege), making the two homes agree, so the
    provisioner can be run safely without removing anything the role actually uses.

    What this test buys going forward: ANY divergence — a statement in one home and not the other,
    in EITHER direction — fails, so the two cannot silently drift apart again.
    """
    script_sids = {s["Sid"] for s in _policy(provisioner)["Statement"]}
    template_sids = {s["Sid"] for s in _checkout_role_policy()["Statement"]}
    assert template_sids - script_sids == set(), (
        "a statement-level drift appeared between the two definitions of "
        "wecare-checkout-role; reconcile it or record it here with a reason")
    assert script_sids - template_sids == set(), (
        "a statement-level drift appeared between the two definitions of "
        "wecare-checkout-role; reconcile it or record it here with a reason")
    # Same PolicyName in both, which is WHY any drift matters: the provisioner replaces, it does
    # not merge.
    assert _checkout_role_policy()["PolicyName"] == "CheckoutLeastPrivilege"
    assert 'PolicyName="CheckoutLeastPrivilege"' in SCRIPT.read_text(encoding="utf-8")


def test_the_environment_holds_secret_names_not_values(provisioner):
    env = provisioner.expected_environment()
    assert env["RAZORPAY_SECRET_ID"] == "wecare/razorpay/api"
    assert env["WIX_API_KEY_SECRET"] == "wecare/wix/headless-api-key"
    assert env["CONTACTS_TABLE"] == "stack-wecare-digital-ContactsTable"
    assert env["ORDERS_TABLE"] == "stack-wecare-digital-OrderTable"


# ── the Wix order write-back switch ───────────────────────────────────────────
#
# `finalization.accept_paid` runs on this function's verify-callback leg and is the single place a
# paid order is pushed to the Wix Orders list. Whether it writes is decided by
# `lambda_utils/ecommerce/wix_writeback.is_enabled()`, which is AND of four env conditions. The
# provisioner's job is to make the switch DEPLOYED-AND-INERT: the keys exist, but turning writes on
# is a deliberate two-value edit, not something a routine provisioner run can do. These assertions
# pin that posture so a later edit that flips it has to be intentional.

def test_the_writeback_switches_are_present_but_empty(provisioner):
    """Empty, not absent, and not truthy. Present so enabling is an edit of a known key; empty so
    `is_enabled()` returns False and no paid order reaches Wix until an owner flips them."""
    env = provisioner.expected_environment()
    for key in ("WIX_WRITEBACK_ENABLED", "WIX_ECOM_WRITE_CONFIRMED"):
        assert key in env, f"{key} must be declared so enabling it is a value edit"
        assert env[key] == "", f"{key} must seed empty — a non-empty seed turns Wix writes on"
    assert provisioner.WIX_WRITEBACK_SWITCH_KEYS == (
        "WIX_WRITEBACK_ENABLED", "WIX_ECOM_WRITE_CONFIRMED")


def test_the_writeback_switches_are_presence_only_for_verify(provisioner):
    """The two switches join the readiness inputs as presence-only keys, so an owner who flips one
    to a truthy value is legitimate drift that `--verify` tolerates and `reconcile_environment`
    never clobbers."""
    assert provisioner.PRESENCE_ONLY_KEYS == (
        provisioner.READINESS_KEYS + provisioner.WIX_WRITEBACK_SWITCH_KEYS)
    for key in provisioner.WIX_WRITEBACK_SWITCH_KEYS:
        assert key in provisioner.PRESENCE_ONLY_KEYS


def test_the_write_contract_is_the_fixed_required_constant(provisioner):
    """The contract string is a constant, not a switch: on its own it enables nothing, so it is
    set to the exact value `wix_writeback.is_enabled()` requires and value-checked by `--verify`.
    Pinned equal to the module's own `WRITE_CONTRACT` so the two cannot drift apart."""
    env = provisioner.expected_environment()
    assert env["WIX_CART_V2_WRITE_CONTRACT"] == "cart-v2-external-v1"
    assert provisioner.WIX_CART_V2_WRITE_CONTRACT == "cart-v2-external-v1"
    assert env["WIX_SITE_ID"] == "c993128b-26be-41cd-9fcd-904abe23462f"


def test_reconcile_seeds_the_switches_only_when_absent(provisioner):
    """`reconcile_environment` adds a presence-only switch when it is MISSING, but never overwrites
    an owner-set value. Asserted over the source so no account is touched."""
    body = SCRIPT.read_text(encoding="utf-8").split(
        "def reconcile_environment")[1].split("\ndef ")[0]
    assert "k not in PRESENCE_ONLY_KEYS and current.get(k) != v" in body
    assert "for k in PRESENCE_ONLY_KEYS:" in body
    assert "if k not in current:" in body


def test_readiness_set_message_is_only_for_gate_off(provisioner):
    """Do not report the gate as OFF when CHECKOUT_INITIATION_ENABLED is actually truthy."""
    body = SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    assert 'if not readiness_empty and initiation not in ("1", "true", "yes", "on"):' in body


def test_the_role_cannot_delete_checkout_evidence(provisioner):
    """Payment attempts, commerce-key reservations and internal orders are evidence.

    None may be deleted by checkout. The Wix-native coupon/gift-card path has no custom hold table
    in this role, so there is no legitimate DeleteItem grant here at all.
    """
    statements = _policy(provisioner)["Statement"]
    evidence = {
        "arn:aws:dynamodb:us-east-1:775261844268:table/"
        "stack-wecare-digital-PaymentAttemptsTable",
        "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-WixOrderIds",
        "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-OrderTable",
    }
    for statement in statements:
        assert "dynamodb:DeleteItem" not in statement.get("Action", []), (
            f"statement {statement.get('Sid')!r} grants DeleteItem on checkout evidence")

    resources = {
        resource
        for statement in statements
        for resource in statement.get("Resource", [])
    }
    assert evidence <= resources, "all three checkout evidence tables must remain explicitly named"

    actions = {a for s in statements for a in s["Action"]}
    assert actions >= {"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"}


def test_existing_role_is_reconciled_instead_of_short_circuited(provisioner):
    """The live failure mode: an old role exists, but its inline policy is behind the code."""
    import ast
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("def ensure_role")[1].split("\ndef ")[0]
    tree = ast.parse("def ensure_role" + body)

    put_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "put_role_policy"
    ]
    assert put_calls, "an existing checkout role is never reconciled"

    early_exists_returns = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Constant)
        and n.value.value == "exists"
    ]
    assert not early_exists_returns, "ensure_role still returns before repairing inline-policy drift"


def test_the_role_names_only_the_checkout_tables_and_contact_index(provisioner):
    """Checkout owns three writable tables plus the read-only Contacts phone index.

    Coupons and gift cards are Wix-authoritative for the website path. Their legacy custom tables
    belong to separate functions/roles and must not be granted to checkout merely to satisfy a
    historical verifier.
    """
    tables = [r for s in _policy(provisioner)["Statement"]
              for r in s["Resource"] if ":table/" in r]
    prefix = "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-"
    assert sorted(tables) == sorted([
        prefix + "PaymentAttemptsTable",
        prefix + "WixOrderIds",
        prefix + "OrderTable",
        prefix + "ContactsTable/index/phone-index"])
    assert not any("CouponsTable" in table or "GiftCardsTable" in table for table in tables)
    for table in tables:
        assert not table.endswith("*"), f"{table} is a wildcard over the fleet's tables"


def test_the_role_holds_no_cognito_permission(provisioner):
    """`customer_auth.authenticate` calls GetUser with the CUSTOMER'S OWN access token, which
    authorises itself. An IAM grant here would be privilege the function cannot use."""
    assert "cognito" not in json.dumps(_policy(provisioner)).lower()


def test_the_shared_fleet_role_is_never_touched(provisioner):
    """`wecare-digital-lambda-role` is shared by ~65 functions. A statement added for checkout
    would widen every one of them.

    Asserted over the AST rather than the text, for the same reason
    `tests/test_payment_vocabulary_at_decision_points.py` walks the AST: the comment explaining
    why the shared role must not be touched necessarily contains its name. A text search makes
    the explanation indistinguishable from the offence.
    """
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))

    # Docstrings are `ast.Constant` nodes too, so they have to come out explicitly - the very
    # prose explaining this rule mentions the role it forbids, which is the trap the AST was
    # supposed to avoid.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = (node.body or [None])[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))

    offenders = [f"line {n.lineno}: string literal names the shared role"
                 for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)
                 and id(n) not in docstrings
                 and "wecare-digital-lambda-role" in n.value]
    assert not offenders, "\n  ".join(offenders)

    # The property that actually matters: every RoleName the script passes is checkout's own.
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        for kw in call.keywords:
            if kw.arg == "RoleName":
                rendered = ast.unparse(kw.value)
                assert rendered in ("ROLE_NAME", "'wecare-checkout-role'"), \
                    f"line {call.lineno}: RoleName={rendered}"
    assert provisioner.ROLE_NAME == "wecare-checkout-role"


# ── the grant report reports, and never grants ────────────────────────────────

def test_the_grant_report_only_simulates(provisioner):
    """`report_required_grants` must never repair what it finds. An agent that widens a role to
    clear its own finding has removed the finding, not the risk."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("def report_required_grants")[1].split("\ndef ")[0]
    assert "simulate_principal_policy" in body
    for forbidden in ("put_role_policy", "attach_role_policy", "put_user_policy",
                      "create_policy", "put_group_policy"):
        assert forbidden not in body, f"the grant report calls {forbidden}"


# ── and what it reports has to reach the exit code ────────────────────────────

class _FakeIam:
    """Just enough IAM to drive `report_required_grants` without touching an account.

    The real IAM API returns one `EvaluationResult` per ACTION when multiple resources are
    simulated, with the per-resource decisions nested under `ResourceSpecificResults`. The fake
    deliberately models that shape so a verifier that reads only top-level `EvalResourceName`
    fails this suite instead of failing only in production.

    The default is "allowed unless the pair is one `_EXPECTED_DENY` withholds", so the baseline
    fake models a CORRECTLY provisioned role. `decisions` overrides by action or by (action, table
    name) pair.
    """

    def __init__(self, *, decisions=None, simulate_error=None, role_error=None,
                 expected_deny=None):
        self.decisions = decisions or {}
        self.simulate_error = simulate_error
        self.role_error = role_error
        #: `None` means "fill this in from the script's own `_EXPECTED_DENY`", which the
        #: `grant_report` fixture does. An explicit empty set models a role that was widened.
        self.expected_deny = expected_deny

    def get_role(self, RoleName):  # noqa: N803 - boto3 casing
        if self.role_error:
            raise self.role_error
        return {"Role": {"Arn": f"arn:aws:iam::775261844268:role/{RoleName}"}}

    def _decision(self, action: str, arn: str) -> str:
        name = arn.rsplit("/", 1)[1]
        if (action, name) in self.decisions:
            return self.decisions[(action, name)]
        if action in self.decisions:
            return self.decisions[action]
        return "implicitDeny" if (action, name) in (self.expected_deny or ()) else "allowed"

    def simulate_principal_policy(self, **kwargs):  # noqa: N803
        if self.simulate_error:
            raise self.simulate_error
        return {"EvaluationResults": [
            {
                "EvalActionName": action,
                "EvalDecision": "implicitDeny",
                "EvalResourceName":
                    "arn:aws:dynamodb:${Region}:${Account}:${ResourceType}/${ResourcePath}",
                "ResourceSpecificResults": [
                    {
                        "EvalResourceName": arn,
                        "EvalResourceDecision": self._decision(action, arn),
                    }
                    for arn in kwargs["ResourceArns"]
                ],
            }
            for action in kwargs["ActionNames"]
        ]}



def _client_error(code: str):
    from botocore.exceptions import ClientError
    return ClientError({"Error": {"Code": code, "Message": code}}, "Simulate")


@pytest.fixture
def grant_report(provisioner, monkeypatch):
    """`report_required_grants` with IAM and STS stubbed out."""
    monkeypatch.setattr(provisioner, "_account_id_cache", "775261844268")

    def _run(fake, members):
        if fake.expected_deny is None:
            # Default to modelling a CORRECTLY provisioned role: the pairs the inline policy
            # withholds come back denied, which is the answer `_EXPECTED_DENY` expects.
            fake.expected_deny = provisioner._EXPECTED_DENY
        monkeypatch.setattr(provisioner, "iam", lambda: fake)
        return provisioner.report_required_grants(members)
    return _run


_CLEAN_MEMBERS = {
    "handler.py": b"from lambda_utils import a\n",
    "lambda_utils/__init__.py": b"",
    "lambda_utils/a.py": b"table.update_item(ConditionExpression='attribute_not_exists(pk)')\n",
}
_TRANSACTING_MEMBERS = {
    "handler.py": b"from lambda_utils import a\n",
    "lambda_utils/__init__.py": b"",
    "lambda_utils/a.py": b"client.transact_write_items(TransactItems=[])\n",
}


def test_a_measured_and_sufficient_role_reports_no_problem(grant_report):
    """The baseline: ConditionCheckItem denied, nothing in the closure needs it."""
    fake = _FakeIam(decisions={"dynamodb:ConditionCheckItem": "implicitDeny"})
    assert grant_report(fake, _CLEAN_MEMBERS) == []


def test_a_required_grant_is_returned_so_verify_can_fail_on_it(grant_report):
    """The defect this test exists for: the finding used to PRINT and the script exited 0, so the
    day a TransactWriteItems call enters the closure the operator gets a function missing a
    permission and a gate reporting success. Latent is not harmless - it is wrong in exactly the
    circumstance the check was written for."""
    fake = _FakeIam(decisions={"dynamodb:ConditionCheckItem": "implicitDeny"})
    problems = grant_report(fake, _TRANSACTING_MEMBERS)
    assert problems, "a REQUIRED GRANT must be returned, not only printed"
    assert any("ConditionCheckItem" in p for p in problems)
    assert any("lambda_utils/a.py" in p for p in problems), \
        "the finding must name the call site, or it is not actionable"


def test_an_unmeasured_simulation_is_a_problem_not_a_pass(grant_report):
    """A run that measured nothing must not be indistinguishable from one that measured
    everything and found nothing."""
    fake = _FakeIam(simulate_error=_client_error("AccessDenied"))
    problems = grant_report(fake, _CLEAN_MEMBERS)
    assert problems and "NOT MEASURED" in problems[0]
    assert "AccessDenied" in problems[0]


def test_an_unreadable_role_is_a_problem_not_a_pass(grant_report):
    fake = _FakeIam(role_error=_client_error("NoSuchEntity"))
    problems = grant_report(fake, _CLEAN_MEMBERS)
    assert problems and "NOT MEASURED" in problems[0]


def test_an_unmeasured_import_closure_is_not_read_as_not_required(grant_report):
    """`members=None` means the package could not be rebuilt. The old code treated that as the
    empty list - "measured, needs nothing" - which is a different fact."""
    fake = _FakeIam(decisions={"dynamodb:ConditionCheckItem": "implicitDeny"})
    problems = grant_report(fake, None)
    assert problems and "NOT JUDGED" in problems[0]


def test_a_denied_action_the_inline_policy_grants_is_a_problem(grant_report):
    """GetItem/PutItem/UpdateItem are granted outright by CheckoutLeastPrivilege. A deny means the
    live role is not what this script wrote, and the function cannot record a payment attempt."""
    fake = _FakeIam(decisions={"dynamodb:PutItem": "implicitDeny",
                               "dynamodb:ConditionCheckItem": "implicitDeny"})
    problems = grant_report(fake, _CLEAN_MEMBERS)
    assert any("dynamodb:PutItem" in p for p in problems)


# ── the verdict is keyed on the PAIR, because one action now has two right answers ──

def test_the_verdict_is_keyed_on_the_action_and_the_resource(provisioner):
    """AWS nests the real per-resource decisions; the provisioner must retain that pair key."""
    assert "dynamodb:DeleteItem" in provisioner._SIMULATED_ACTIONS
    assert provisioner._EXPECTED_DENY == {
        ("dynamodb:DeleteItem", provisioner.PAYMENT_ATTEMPTS_TABLE),
        ("dynamodb:DeleteItem", provisioner.COMMERCE_KEYS_TABLE),
        ("dynamodb:DeleteItem", provisioner.ORDERS_TABLE)}

    body = SCRIPT.read_text(encoding="utf-8") \
        .split("def report_required_grants")[1].split("\ndef ")[0]
    assert "ResourceSpecificResults" in body
    assert "EvalResourceDecision" in body
    assert "_EXPECTED_DENY" in body


def test_a_correctly_provisioned_role_passes_with_delete_item_withheld_everywhere(grant_report):
    """All checkout-owned rows are evidence; DeleteItem is correctly denied on all three tables."""
    fake = _FakeIam(decisions={
        "dynamodb:ConditionCheckItem": "implicitDeny",
        "dynamodb:DeleteItem": "implicitDeny",
    })
    assert grant_report(fake, _CLEAN_MEMBERS) == []


def test_delete_item_becoming_allowed_on_an_evidence_table_is_reported(grant_report):
    """Widening DeleteItem on any checkout-owned table is a verifier failure."""
    fake = _FakeIam(
        decisions={
            "dynamodb:ConditionCheckItem": "implicitDeny",
            "dynamodb:DeleteItem": "allowed",
        },
        expected_deny=frozenset(),
    )
    # Override the fake's baseline so its explicit action decision is returned for every resource.
    problems = grant_report(fake, _CLEAN_MEMBERS)
    assert any("dynamodb:DeleteItem" in p and "PaymentAttemptsTable" in p for p in problems)
    assert any("dynamodb:DeleteItem" in p and "WixOrderIds" in p for p in problems)
    assert any("dynamodb:DeleteItem" in p and "OrderTable" in p for p in problems)


def test_verify_adds_the_grant_report_to_its_own_problem_list(provisioner):
    """The one-line fix, pinned as a PROPERTY rather than as one spelling of the call.

    `verify()` called `report_required_grants(...)` and dropped the return value, so a
    REQUIRED GRANT printed while the function returned 0. Asserting the exact source line was how
    this test was first written, and it broke the moment the argument changed from the local export
    to the live artifact - a strictly better call, wrongly reported as a regression. What matters is
    that the return value reaches `problems`, whatever it is passed.
    """
    import ast
    body = SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    tree = ast.parse("def verify(" + body)
    extended = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "extend"
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "problems"
        and any(isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                and arg.func.id == "report_required_grants" for arg in node.args)]
    assert extended, "report_required_grants' return value never reaches `problems`"
    bare = [node for node in ast.walk(tree)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "report_required_grants"]
    assert not bare, "report_required_grants is called for its print side effect again"
    # And the exit code is still driven by that list.
    assert "if problems:" in body and "return 1" in body


def test_condition_check_item_is_judged_on_the_import_closure(provisioner):
    """Scoped to what the handler can actually reach, not to the 112-file ZIP.

    `build_zip` ships the whole `lambda_utils` tree without pruning, so `crm/service.py` and
    `notifications/store.py` are present and both use `TransactWriteItems`. Neither is imported
    by checkout. Judging on the ZIP reported a `ConditionCheckItem` grant the function can never
    need - and a report that cries wolf is one nobody reads.
    """
    members = {
        "handler.py": b"from lambda_utils import a\n",
        "lambda_utils/__init__.py": b"",
        "lambda_utils/a.py": b"x = 1\n",
        "lambda_utils/unreached.py": b"client.transact_write_items()\n",
    }
    closure = provisioner.import_closure(members)
    assert "lambda_utils/a.py" in closure
    assert "lambda_utils/unreached.py" not in closure
    assert provisioner._package_needs_transactions(members) == []

    members["lambda_utils/a.py"] = b"client.transact_write_items()\n"
    assert provisioner._package_needs_transactions(members) != []


# ── packaging must be validated before the function is created ────────────────

def test_the_package_is_validated_before_create(provisioner):
    """`deploy_all_lambdas.py` validates only AFTER `get_function_configuration` succeeds, so for
    an absent function it takes the `awaiting_provisioning` branch and never validates. An
    unresolved import would therefore first appear as a cold-start `Unable to import module` on a
    real customer request."""
    source = SCRIPT.read_text(encoding="utf-8")
    build_at = source.index("zip_bytes, members, errors, warnings = build_package")
    create_at = source.index("print(f\"Lambda: {ensure_function(")
    assert build_at < create_at, "the package is built after the create call"
    assert "if report_package(zip_bytes, members, errors, warnings):\n        return 1" in source


def test_packaging_is_delegated_so_the_two_scripts_cannot_drift(provisioner):
    """One packer. This script creates the function; deploy_all_lambdas.py updates it forever
    after. Two packers meant the first package and every later one were assembled differently."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "dal.build_zip(spec)" in source
    assert "dal.validate(spec, members, frozenset())" in source
    assert 'dal.validate_handler(members, "handler.handler")' in source
    assert "_zip_package" not in source, "the private packer is back"


def test_source_root_lets_a_clean_archive_be_packaged(provisioner):
    """The shared working tree is routinely dirty with other sessions' edits. A package built
    from it ships a handler whose siblings are stale."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--source-root"' in source
    body = source.split("def _deploy_module")[1].split("\ndef ")[0]
    # The globals must be re-pointed BEFORE a Spec is built: Spec.__init__ resolves its source
    # from the module-level FUNCTIONS at construction time.
    assert body.index("module.FUNCTIONS = functions") < body.index("return module")
    assert "dal.Spec(FUNCTION_NAME" in source.split("def build_package")[1]


def _synthetic_root(base):
    """A directory `is_repo_root` accepts, with nothing else in it."""
    handler = base / "amplify" / "functions" / "ecommerce" / "checkout" / "handler.py"
    handler.parent.mkdir(parents=True)
    handler.write_text("def handler(e, c):\n    return None\n")
    return base


def test_verify_defaults_to_the_deploy_export_not_the_working_tree(
        provisioner, tmp_path, monkeypatch):
    """`--verify` is a statement ABOUT the deployed artifact. Defaulting its closure to the working
    tree meant the verdict could be about a package nobody deployed - and in this repo that tree
    routinely carries three other sessions' uncommitted edits, all of which build_zip packages."""
    export = _synthetic_root(tmp_path / "deploy-export")
    monkeypatch.setattr(provisioner, "DEPLOY_SOURCE_ROOT", export)

    root, why = provisioner.resolve_source_root(None, prefer_deploy_export=True)
    assert root == export.resolve()
    assert "deploy export" in why

    # A provisioning run packages what the operator points it at, and says which that is.
    root, why = provisioner.resolve_source_root(None, prefer_deploy_export=False)
    assert root == provisioner.ROOT
    assert "WORKING TREE" in why


def test_an_explicit_source_root_always_wins(provisioner, tmp_path, monkeypatch):
    export = _synthetic_root(tmp_path / "deploy-export")
    given = _synthetic_root(tmp_path / "given")
    monkeypatch.setattr(provisioner, "DEPLOY_SOURCE_ROOT", export)
    root, why = provisioner.resolve_source_root(str(given), prefer_deploy_export=True)
    assert root == given.resolve()
    assert "command line" in why


def test_a_missing_deploy_export_falls_back_and_says_so(provisioner, tmp_path, monkeypatch):
    """`.scratch/` is gitignored, so on a fresh checkout the export is simply absent. Falling back
    is right; falling back silently is not - the verdict would read as being about the artifact."""
    monkeypatch.setattr(provisioner, "DEPLOY_SOURCE_ROOT", tmp_path / "does-not-exist")
    root, why = provisioner.resolve_source_root(None, prefer_deploy_export=True)
    assert root == provisioner.ROOT
    assert "WORKING TREE" in why and "not the deployed artifact" in why


def test_the_verdict_is_never_anonymous(provisioner):
    """Every source a verdict could come from is named in the output.

    Finding that the closure was judged from the wrong tree is only possible if the tree is named.
    There are now TWO sources to name, not one: the comparison build (`source_note`) and the
    artifact the verdict is actually scoped to (the `live_members` note, carrying its CodeSha256).
    Asserted as "both are printed" rather than on either exact wording, because the wording changed
    once already - the label used to read `grant report closure:` when the closure was all it
    described.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    verify_body = source.split("def verify(")[1].split("\ndef ")[0]
    prints = [ast.unparse(node) for node in ast.walk(ast.parse("def verify(" + verify_body))
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "print"]
    assert any("source_note" in p for p in prints), \
        "the comparison package's source root is never printed"
    assert any("deployed_note" in p for p in prints), \
        "the live artifact the verdict is scoped to is never printed"
    assert any("deployed_sha" in p for p in prints), \
        "the live artifact is named without its CodeSha256, so it cannot be identified later"
    main_body = source.split("def main(")[1]
    assert "source_note=why" in main_body
    assert 'print(f"source root: {why}")' in main_body


# ── the IaC declaration matches what the script creates ───────────────────────

def test_the_template_declares_the_same_routes_the_script_creates(provisioner):
    """`ROUTE_KEYS` and the template, held equal rather than at a fixed count.

    The original of this test pinned four literal POST routes, and the mismatch it caught was not
    cosmetic: the template is the declaration of record and two of the routes the script grants
    had no declaration at all -- including POST /ecommerce/verify-callback, which is the route a
    paying browser returns to. Derived from `ROUTE_KEYS` now, because the fifth route arriving on
    2026-10-08 (`GET /ecommerce/service-prices`) showed that a fixed list has to be edited in
    two places to express one fact; the property worth asserting is that the two AGREE.
    """
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    keys = sorted(r["Properties"]["RouteKey"] for r in template["Resources"].values()
                  if r["Type"] == "AWS::ApiGatewayV2::Route")
    assert keys == sorted(provisioner.ROUTE_KEYS)
    # The method vocabulary is still pinned literally: exactly one GET, and it is the public
    # price read. Anything else arriving as a GET on this function is a widening to notice.
    assert [key for key in keys if key.startswith("GET ")] == \
        ["GET /ecommerce/service-prices"]


def test_the_template_keeps_the_gate_absent():
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    env = (template["Resources"]["CheckoutFunction"]["Properties"]
           ["Environment"]["Variables"])
    assert "CHECKOUT_INITIATION_ENABLED" not in env
    assert env["EXPECTED_CONFIGURATION_NAME"] == ""
    assert env["EXPECTED_PROVIDER_MID"] == ""


def test_the_template_qualifies_every_invoke_permission(provisioner):
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    permissions = {name: r["Properties"] for name, r in template["Resources"].items()
                   if r["Type"] == "AWS::Lambda::Permission"}
    assert len(permissions) == len(provisioner.ROUTE_KEYS), \
        "one statement per route - see WhyOneStatementPerRoute"
    for name, permission in permissions.items():
        assert permission["Qualifier"] == "live", name
        assert permission["Principal"] == "apigateway.amazonaws.com", name
        assert "SourceArn" in permission, \
            f"{name}: an unscoped permission lets any API invoke this"


def test_the_template_matches_the_route_arns_the_script_grants(provisioner, monkeypatch):
    """The template is the declaration of record. If it still carried `/*/*` after the script was
    narrowed, the record would describe a grant nobody holds."""
    monkeypatch.setattr(provisioner, "_account_id_cache", "775261844268")
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    declared = sorted(r["Properties"]["SourceArn"]["Fn::Sub"]
                      for r in template["Resources"].values()
                      if r["Type"] == "AWS::Lambda::Permission")
    # The template parameterises region/account/api; render the script's ARNs the same way.
    wanted = sorted(
        provisioner.source_arn(key)
        .replace("us-east-1", "${AWS::Region}", 1)
        .replace("775261844268", "${AWS::AccountId}", 1)
        .replace(provisioner.API_ID, "${ApiId}", 1)
        for key in provisioner.ROUTE_KEYS)
    assert declared == wanted
    for arn in declared:
        assert "*" not in arn.replace("${", ""), f"{arn} carries a wildcard"


def test_the_template_is_not_wired_into_the_amplify_backend():
    """HTTP API zllr9lrg7j is not CloudFormation-managed, and backend.ts states the Python
    Lambdas are not managed by Amplify Gen 2. Importing this template into `defineBackend` would
    create a second API and put a live payment function under a stack that can delete it."""
    backend = (ROOT / "amplify" / "backend.ts").read_text(encoding="utf-8")
    assert "infra/checkout" not in backend
    assert "checkout.json" not in backend


def test_the_manifest_records_the_function_without_the_gate():
    """The GATE here is the `CHECKOUT_INITIATION_ENABLED` feature flag, and it is gone:
    initiation is always on, so there is no variable that can switch it off.

    The two readiness identifiers are the opposite case and are asserted LIVE. They are not a
    switch - they are EXPECTATIONS compared against a live provider readback, so setting them
    produces a refusal when they disagree and never a send that skipped a check. They must equal
    the invoice engine's and the boundary gate's own expectations, which
    `tests/test_whatsapp_payments_are_template_only.py` pins across all three functions.
    """
    manifest = json.loads(
        (ROOT / "config" / "lambda-env-manifest.json").read_text(encoding="utf-8"))
    entry = manifest["functions"]["wecare-checkout"]
    assert "CHECKOUT_INITIATION_ENABLED" not in entry
    assert entry["EXPECTED_CONFIGURATION_NAME"] == "WECAREDIGITAL"
    assert entry["EXPECTED_PROVIDER_MID"] == "acc_TTFSyolquKEZEy"
    assert entry["WIX_API_KEY_SECRET"] == "wecare/wix/headless-api-key"
    assert manifest["_functions"] == len(manifest["functions"])
    assert manifest["_variables"] == sum(len(v) for v in manifest["functions"].values())


# ── the closure must follow relative imports ──────────────────────────────────
#
# The IAM verdict is scoped to `import_closure`, so anything the walker cannot see is a module the
# grant report reasons as if it were absent. It used to do `if node.level: continue`, discarding
# every `from .x import y` edge - 35 of them in `lambda_utils`, one inside this very closure. The
# verdict was unchanged, but the failure direction is the dangerous one: a relatively-imported
# module that opens a transaction yields a false "grant not required" with a green verifier.

def test_a_relative_import_is_followed_into_the_closure(provisioner):
    members = {
        "handler.py": b"from lambda_utils import a\n",
        "lambda_utils/__init__.py": b"",
        "lambda_utils/a.py": b"from .b import THING\n",
        "lambda_utils/b.py": b"THING = 1\n",
    }
    closure = provisioner.import_closure(members)
    assert "lambda_utils/b.py" in closure, \
        "a `from .b import ...` edge was dropped, so b.py is invisible to the IAM verdict"


def test_a_transaction_behind_a_relative_import_is_still_found(provisioner):
    """The exact false negative the old walker produced: the needle is one relative hop away."""
    members = {
        "handler.py": b"from lambda_utils import a\n",
        "lambda_utils/__init__.py": b"",
        "lambda_utils/a.py": b"from .b import go\n",
        "lambda_utils/b.py": b"def go():\n    client.transact_write_items(TransactItems=[])\n",
    }
    assert provisioner._package_needs_transactions(members) != [], \
        "a TransactWriteItems reached only by a relative import must still require the grant"


def test_a_parent_relative_import_resolves_one_level_up(provisioner):
    members = {
        "handler.py": b"from lambda_utils.ecommerce import a\n",
        "lambda_utils/__init__.py": b"",
        "lambda_utils/ecommerce/__init__.py": b"",
        "lambda_utils/ecommerce/a.py": b"from ..shared_thing import X\n",
        "lambda_utils/shared_thing.py": b"X = 1\n",
    }
    closure = provisioner.import_closure(members)
    assert "lambda_utils/shared_thing.py" in closure


def test_relative_import_resolution_cases(provisioner):
    """Unit-level, because the arithmetic is the part that is easy to get wrong by one.

    A package's `__init__.py` is INSIDE its package, so `from .x import y` there resolves to a
    sibling of the `__init__`, not to a sibling of the package directory.
    """
    resolve = provisioner.resolve_relative_import
    assert resolve("lambda_utils/template_ttl.py", "whatsapp_types", 1) == \
        "lambda_utils.whatsapp_types"
    assert resolve("lambda_utils/ecommerce/a.py", "b", 1) == "lambda_utils.ecommerce.b"
    assert resolve("lambda_utils/ecommerce/a.py", "b", 2) == "lambda_utils.b"
    assert resolve("lambda_utils/ecommerce/__init__.py", "money", 1) == \
        "lambda_utils.ecommerce.money"
    assert resolve("lambda_utils/a.py", None, 1) == "lambda_utils"
    # Climbing above the package root returns "" rather than raising mid-verdict.
    assert resolve("lambda_utils/a.py", "x", 4) == ""


def test_a_bare_from_dot_import_does_not_crash_the_walk(provisioner):
    """`from . import sibling` has `module=None`, which the non-relative branch skips. It must be
    followed, not treated as unparseable."""
    members = {
        "handler.py": b"from lambda_utils import a\n",
        "lambda_utils/__init__.py": b"from . import b\n",
        "lambda_utils/a.py": b"x = 1\n",
        "lambda_utils/b.py": b"y = 1\n",
    }
    assert "lambda_utils/b.py" in provisioner.import_closure(members)


# ── the grant report must describe the DEPLOYED bytes ─────────────────────────
#
# Every package-derived conclusion once described a local export while the alias pointed at a
# version another session had published. The import validation, the closure and therefore the
# ConditionCheckItem verdict all described v1; v2 had never had its imports walked. If a later
# version wired `razorpay_orders` in, the role would be missing a Razorpay secret read and nothing
# would have said so.

def test_verify_scopes_the_grant_report_to_the_live_artifact(provisioner):
    """Not the `members` argument, which is only a comparison build."""
    import ast
    body = SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    tree = ast.parse("def verify(" + body)
    passed = [arg.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "report_required_grants"
              for arg in node.args if isinstance(arg, ast.Name)]
    assert passed == ["deployed"], \
        f"the grant report is scoped to {passed}, not to the downloaded live artifact"
    assert "live_members()" in body, "verify() never reads the deployed artifact back"


def test_an_unreadable_live_artifact_is_a_problem_not_a_pass(provisioner):
    """Same discipline as the simulate and closure cases: unmeasured is not a pass. `live_members`
    returning `None` must reach `problems`, and must reach `report_required_grants` as `None` so it
    reports NOT JUDGED rather than silently falling back to the local export."""
    body = SCRIPT.read_text(encoding="utf-8").split("def verify(")[1].split("\ndef ")[0]
    assert "if deployed is None:" in body
    assert "could not be measured" in body


def test_the_presigned_download_url_is_never_printed_or_stored(provisioner):
    """`get_function` returns a presigned S3 URL carrying an `X-Amz-Signature`, so it is
    credential-shaped material. secret-handling.md: it must not appear in a log line, an argument
    or any logging expression. It is fetched in-process and discarded."""
    body = SCRIPT.read_text(encoding="utf-8").split("def live_members(")[1].split("\ndef ")[0]
    for node in ast.parse("def live_members(" + body).body[0].body:
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "print"):
                continue
            rendered = " ".join(ast.unparse(a) for a in call.args)
            assert "location" not in rendered.lower(), \
                f"the presigned URL reaches a print: {rendered}"
    assert "location" not in body.split("except Exception")[1].split("return")[0].lower(), \
        "the download failure message must not carry the URL"


def test_the_live_artifact_is_validated_with_the_fleets_own_checker(provisioner):
    """`validate_members` must reuse `deploy_all_lambdas.validate`, so the bytes in production are
    held to the identical import rule as the bytes in a build - not to a second implementation that
    can drift from it."""
    body = SCRIPT.read_text(encoding="utf-8").split(
        "def validate_members(")[1].split("\ndef ")[0]
    assert "_deploy_module" in body and "dal.validate(" in body
    assert "dal.validate_handler(" in body


# ── verify() drives its own expectations, and fails on the dangerous state ─────

class _FakeLambdaForVerify:
    def __init__(self, env, statements):
        self.env, self.statements = env, statements

    def get_function(self, **kwargs):  # noqa: N803
        return {"Configuration": {"CodeSha256": "sha"}, "Code": {"Location": "https://x/y"}}

    def get_alias(self, **kwargs):  # noqa: N803
        return {"FunctionVersion": "2"}

    def get_function_configuration(self, **kwargs):  # noqa: N803
        return {"Environment": {"Variables": dict(self.env)}}

    def get_policy(self, **kwargs):  # noqa: N803
        return {"Policy": json.dumps({"Statement": self.statements})}


class _FakeApiForVerify:
    def __init__(self, integration_uri, route_settings=None):
        self.uri = integration_uri
        self.route_settings = route_settings

    def get_integrations(self, **kwargs):  # noqa: N803
        return {"Items": [{"IntegrationId": "zkb6lxe", "IntegrationUri": self.uri}]}

    def get_routes(self, **kwargs):  # noqa: N803
        return {"Items": [{"RouteKey": key, "RouteId": f"r{n}",
                           "Target": "integrations/zkb6lxe"}
                          for n, key in enumerate(_ROUTE_KEYS_FOR_FAKE)]}

    def get_stage(self, **kwargs):  # noqa: N803
        return {"RouteSettings": self.route_settings if self.route_settings is not None
                else dict(_ROUTE_SETTINGS_FOR_FAKE),
                "DefaultRouteSettings": {"ThrottlingRateLimit": 10000.0}}


_ROUTE_KEYS_FOR_FAKE: tuple = ()
_ROUTE_SETTINGS_FOR_FAKE: dict = {}


@pytest.fixture
def verify_run(provisioner, monkeypatch):
    """Run the real `verify()` against stubbed AWS. Returns (exit_code, printed, problems)."""
    global _ROUTE_KEYS_FOR_FAKE, _ROUTE_SETTINGS_FOR_FAKE
    _ROUTE_KEYS_FOR_FAKE = provisioner.ROUTE_KEYS
    _ROUTE_SETTINGS_FOR_FAKE = {provisioner.PRICE_ROUTE_KEY: {
        "ThrottlingRateLimit": provisioner.ROUTE_THROTTLE_RATE,
        "ThrottlingBurstLimit": provisioner.ROUTE_THROTTLE_BURST}}
    monkeypatch.setattr(provisioner, "_account_id_cache", "775261844268")

    def _run(env_overrides=None, drop=(), route_settings=None):
        env = dict(provisioner.expected_environment())
        env.update(env_overrides or {})
        for key in drop:
            env.pop(key, None)
        statements = [
            {"Sid": provisioner.route_statement_id(key),
             "Condition": {"ArnLike": {"AWS:SourceArn": provisioner.source_arn(key)}}}
            for key in provisioner.ROUTE_KEYS]
        monkeypatch.setattr(provisioner, "lam",
                            lambda: _FakeLambdaForVerify(env, statements))
        monkeypatch.setattr(provisioner, "api",
                            lambda: _FakeApiForVerify(provisioner.function_arn(qualified=True),
                                                      route_settings=route_settings))
        monkeypatch.setattr(provisioner, "live_members",
                            lambda *a, **k: ({"handler.py": b""}, "sha", "1 file"))
        monkeypatch.setattr(provisioner, "validate_members", lambda *a, **k: ([], []))
        monkeypatch.setattr(provisioner, "report_required_grants", lambda members: [])
        monkeypatch.setattr(provisioner, "import_closure", lambda members, entry="handler.py": set())
        return provisioner.verify(members=None)
    return _run


def test_verify_passes_on_the_state_this_script_provisions(verify_run):
    """The baseline, so a failure below is attributable to the override and not to the harness."""
    assert verify_run() == 0


@pytest.mark.parametrize("settings", [
    {},                                                                    # no cap at all
    {"GET /ecommerce/service-prices": {"ThrottlingRateLimit": 5000.0,
                                       "ThrottlingBurstLimit": 10}},       # loosened rate
    {"GET /ecommerce/service-prices": {"ThrottlingRateLimit": 5.0,
                                       "ThrottlingBurstLimit": 10000}},    # loosened burst
    {"POST /ecommerce/checkout": {"ThrottlingRateLimit": 5.0,
                                  "ThrottlingBurstLimit": 10}},            # capped the wrong route
])
def test_verify_fails_when_the_anonymous_route_is_not_capped(verify_run, settings):
    """An uncapped anonymous route is a real finding, so `--verify` has to fail on it rather than
    print it. The loosened cases matter as much as the missing one: the regression that costs
    something is a widened limit, not a deleted setting."""
    assert verify_run(route_settings=settings) == 1


def test_verify_fails_on_a_wrong_wix_site_id(verify_run):
    """The hand-enumerated key list omitted WIX_SITE_ID, so a wrong Wix site id on live passed
    verification. The list is now derived from `expected_environment()`, which is the only version
    of this check that cannot drift out of date as keys are added."""
    assert verify_run({"WIX_SITE_ID": "00000000-0000-0000-0000-000000000000"}) == 1


def test_every_non_readiness_key_is_actually_checked(provisioner, verify_run):
    """Stated over the whole key set rather than over one example, so a future key added to
    `expected_environment` is covered the day it is added."""
    for key, want in provisioner.expected_environment().items():
        # Presence-only keys (readiness inputs + the two Wix write-back switches) are tolerated at
        # any value by design, so a wrong value does not — and must not — fail verify. Every OTHER
        # key is value-checked, which is what this test guards.
        if key in provisioner.PRESENCE_ONLY_KEYS:
            continue
        assert verify_run({key: f"wrong-{want}-x"}) == 1, f"{key} is not verified on live"


def test_a_readiness_key_is_checked_for_presence_not_for_an_empty_value(provisioner, verify_run):
    """Presence-only, and both halves of that matter.

    An owner filling these in from a live Meta/Razorpay read is legitimate drift from what this
    script writes, so a non-empty value must not be an env MISMATCH - it is reported by the
    readiness check instead, with the right explanation. A missing key is a different fault:
    `payment_readiness` has nothing to evaluate.
    """
    for key in provisioner.READINESS_KEYS:
        assert verify_run(drop=(key,)) == 1, f"{key} absent from live is not reported"
    # Present-but-empty is the provisioned state, and must stay clean.
    assert verify_run() == 0


def test_the_gate_being_on_is_a_problem(verify_run):
    assert verify_run({"CHECKOUT_INITIATION_ENABLED": "true"}) == 1


def test_readiness_set_with_the_gate_off_is_a_problem(verify_run):
    """The state the evidence document singles out and the verifier used to PRINT.

    The gate is the LAST check in `handler._create`. The measured order is
    `wix_ecom.create_checkout` (a live Wix write) -> currency compare -> `payment_readiness`
    -> `allocate_payment_reference` -> `put_item` on PaymentAttemptsTable -> `if not
    INITIATION_ENABLED`. While readiness is empty it refuses early and the table stays at 0 rows.
    The moment an owner fills the readiness values in with the flag still off, every authenticated
    `action=create` performs a live Wix write and writes an attempt row before refusing. No money
    moves, but "gate off" has stopped meaning "inert", and an operator who set those values
    expecting inertness deserves a non-zero exit rather than a note.
    """
    assert verify_run({"EXPECTED_CONFIGURATION_NAME": "some-config"}) == 1
    assert verify_run({"EXPECTED_PROVIDER_MID": "some-mid"}) == 1
    assert verify_run({"EXPECTED_CONFIGURATION_NAME": "c", "EXPECTED_PROVIDER_MID": "m"}) == 1


def test_readiness_set_with_the_gate_on_is_still_a_problem(verify_run):
    """Both conditions report; neither masks the other."""
    assert verify_run({"EXPECTED_CONFIGURATION_NAME": "c",
                       "CHECKOUT_INITIATION_ENABLED": "true"}) == 1
