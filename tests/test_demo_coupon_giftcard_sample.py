"""`scripts/demo_coupon_giftcard_sample.py`'s anti-rot enforcer.

Design reference: `.agents/tasks/wix-coupon-giftcard-sample-20261002/design.md` revision 8, §7.

A TEST rather than a new CI step, for three reasons: the existing `python -m pytest -q` already
collects it, it inherits the harness's containment, and a failure is a named assertion instead
of a scrollback. No workflow file is modified.

The demo is run IN-PROCESS through `main(["--json", "--no-colour"])`, which is why `main`
returns its exit code rather than calling `sys.exit` itself.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import sys
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from lambda_utils import wix_ecom  # noqa: E402
from lambda_utils.ecommerce import wix_gift_cards as wg  # noqa: E402

DEMO = ROOT / "scripts/demo_coupon_giftcard_sample.py"
PLACEHOLDER_API_KEY = "wix-admin-key-PLACEHOLDER-not-a-credential"
REFERENCE = "wd-gc-sample-2026-10-02"


class _UnexpectedAwsUse(BaseException):
    pass


class _ExplodesOnAttributeAccess:
    def __getattr__(self, name):
        raise _UnexpectedAwsUse(f"this test touched boto3.{name}")


@pytest.fixture
def demo(monkeypatch):
    """Load the script by path - this repository's existing pattern for a script under test."""
    monkeypatch.setitem(wix_ecom._key_cache, "key", PLACEHOLDER_API_KEY)
    monkeypatch.setitem(sys.modules, "boto3", _ExplodesOnAttributeAccess())
    spec = importlib.util.spec_from_file_location("demo_under_test", DEMO)
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_the_demo_runs_offline_and_reports_four_legs_and_no_mismatches(demo, capsys):
    code = demo.main(["--json", "--no-colour"])
    captured = capsys.readouterr()
    assert code == 0, captured.out

    # `--json`'s contract is MACHINE-READABLE STDOUT AND NOTHING ELSE, so the whole of stdout
    # has to parse. A stray print would make the transcript unusable to a consumer.
    transcript = json.loads(captured.out)
    assert captured.err == ""

    # Four, not three: the INVOICE leg joined the walk-through when the invoice surface was bound
    # to the one coupon authority and the one gift-card authority. It is the leg that shows the
    # apply ORDER - coupon into the fee basis, gift card off the final total - which no other leg
    # exercises, because no other leg has a total to apply tender against.
    assert len(transcript["legs"]) == 4
    assert [leg["leg"] for leg in transcript["legs"]] == [
        "coupon", "wix-giftcard", "our-giftcard", "invoice"]
    assert transcript["mismatchCount"] == 0
    assert transcript["awsCallsAttempted"] == 0
    assert transcript["secretsManagerClientBuilt"] is False

    # Corroborated from OUTSIDE the demo, rather than by the demo agreeing with itself.
    assert wix_ecom._secrets is None


def _event_system(module_name: str, path: tuple):
    """Resolve a live botocore event system the same way the demo's `_HOOK_PATHS` does."""
    target = sys.modules[module_name]
    for attribute in path:
        target = getattr(target, attribute)
    return target


def test_an_aws_call_during_a_leg_fails_the_run_rather_than_being_counted_afterwards(
        demo, monkeypatch, capsys):
    """THE mutation test for the containment, and the reason the printed `0` means anything.

    The count used to be produced by a function that created the counter and registered the hook
    in the same call, invoked after every leg had finished - so `0` was true by construction and
    this test would have passed with the hook absent. Here a leg emits exactly the event botocore
    emits as a request leaves the process, and the run must FAIL, which is design §4.3's wording:
    a call that would leave the process fails the demo rather than being tallied afterwards.
    """
    original = demo._leg_our_giftcard

    def leg_that_touches_aws(args):
        _event_system("lambda_utils.rate_limit",
                      ("dynamodb", "meta", "client", "meta", "events")).emit(
                          "before-send", request=None)
        return original(args)  # pragma: no cover - the emit above never returns

    monkeypatch.setattr(demo, "_leg_our_giftcard", leg_that_touches_aws)
    code = demo.main(["--json", "--no-colour"])
    captured = capsys.readouterr().out

    assert code == 1
    assert "CONTRACT FAILURE: UnexpectedAwsCall" in captured
    # And it was counted as well as refused, so the two readings agree.
    assert demo._count_aws_calls() == 1
    # No transcript was printed, so a failed run cannot be mistaken for a clean one.
    assert '"legs"' not in captured


def test_the_aws_refusal_hook_is_armed_before_the_first_leg(demo, monkeypatch, capsys):
    """The MOMENT of arming, which the test above cannot see and two legs depend on entirely.

    `test_an_aws_call_during_a_leg_...` emits from inside leg 3, by which point `_leg_coupon`
    has re-armed after its handler import, so it passes whether or not `_install_containment`
    armed anything. `_leg_wix_giftcard` and `_leg_our_giftcard` never re-arm, so for
    `--leg wix-giftcard` the containment-time arming is the ONLY hook there will ever be - and
    `_arm_aws_refusal` swallows a module missing from `sys.modules` with `continue`, so if
    either path stopped arriving transitively the arming would silently become a no-op while
    `_render` still printed "ARMED BEFORE leg 1".

    Measured two ways, because each misses what the other catches:

    1. Both `_HOOK_PATHS` targets RESOLVE on a bare import of the demo and nothing else, so
       `_arm_aws_refusal` has two live event systems to register on at containment time. This
       is the half that fails if an import stops being transitive.
    2. The hook is LIVE inside `--leg wix-giftcard`, per path, so a neutralised
       `_arm_aws_refusal` is caught rather than inferred. This is the half that fails if the
       arming moves back after the legs.
    """
    for module_name, _path in demo._HOOK_PATHS:
        assert module_name in sys.modules, f"{module_name} no longer arrives transitively"

    # Registers on the REAL session-lifetime clients, so it is disarmed in a `finally` - a
    # permanently-raising handler left behind hands an uncatchable BaseException to any later
    # test that used those clients for real.
    armed = demo._arm_aws_refusal([])
    try:
        assert len(armed) == len(demo._HOOK_PATHS) == 2, "an event system failed to resolve"
    finally:
        demo._disarm_aws_refusal(armed)
    assert armed == []

    original = demo._leg_wix_giftcard
    for module_name, path in demo._HOOK_PATHS:
        def leg_that_touches_aws(transport, args, _module=module_name, _path=path):
            _event_system(_module, _path).emit("before-send", request=None)
            return original(transport, args)  # pragma: no cover - the emit never returns

        monkeypatch.setattr(demo, "_leg_wix_giftcard", leg_that_touches_aws)
        # This leg imports no handler and re-arms nothing, so reaching the refusal at all
        # proves the arming happened in `_install_containment`.
        code = demo.main(["--json", "--no-colour", "--leg", "wix-giftcard"])
        captured = capsys.readouterr().out

        assert code == 1, f"{module_name} ran unhooked: {captured}"
        assert "CONTRACT FAILURE: UnexpectedAwsCall" in captured
        assert demo._count_aws_calls() == 1
        assert '"legs"' not in captured


def test_the_demo_puts_back_every_global_it_touched(demo):
    """`urlopen`, `boto3`, the key cache and BOTH event hooks, restored in a `finally`.

    `urlopen` used to be left as a drained `WixTransport`, so any later call raised
    `UnexpectedWixCall` - a `BaseException` that escapes every `except Exception` in the tree -
    and named the wrong module while doing it. The hooks used to be left registered on
    session-lifetime clients, accumulating one handler per `main()` call.
    """
    urlopen_before = urllib.request.urlopen
    boto3_before = sys.modules.get("boto3")
    key_before = wix_ecom._key_cache.get("key")

    assert demo.main(["--json", "--no-colour"]) == 0

    assert urllib.request.urlopen is urlopen_before
    assert sys.modules.get("boto3") is boto3_before
    assert wix_ecom._key_cache.get("key") == key_before

    # The hooks are gone: emitting the event the demo refuses now does nothing at all.
    for module_name, path in demo._HOOK_PATHS:
        _event_system(module_name, path).emit("before-send", request=None)

    # Twice over, because the accumulation defect only showed on repeated runs.
    assert demo.main(["--json", "--no-colour"]) == 0
    assert urllib.request.urlopen is urlopen_before
    for module_name, path in demo._HOOK_PATHS:
        _event_system(module_name, path).emit("before-send", request=None)


def test_the_transcript_carries_no_clear_idempotency_key_either(demo, capsys):
    """The key is masked, because in THIS demo it would hand over the code.

    `idempotency_key` is not bearer value and production could print it in full - it shares
    nothing with the HMAC-keyed `card_code`. But leg 2 derives its code with the unkeyed
    `demo_code`, and both expose the SAME sha256 digest of the same reference, so a clear key
    yields the masked code by stripping decoration and upper-casing. Masking only the code would
    have been true of the string and false of the information.
    """
    assert demo.main(["--json", "--no-colour"]) == 0
    rendered = capsys.readouterr().out
    key = wg.idempotency_key(reference_id=REFERENCE)
    shared_digest = key[len("wd-gc-"):][:16]

    assert key not in rendered
    assert shared_digest and shared_digest not in rendered
    assert shared_digest.upper() not in rendered
    # The LENGTH is still reported, which is the fact a reviewer needs about Wix's 100 ceiling.
    assert f'"idempotencyKeyLength": {len(key)}' in rendered

    assert demo.main(["--no-colour", "--leg", "wix-giftcard"]) == 0
    plain = capsys.readouterr().out
    assert key not in plain
    assert shared_digest not in plain and shared_digest.upper() not in plain


def test_the_transcript_carries_no_clear_bearer_code_and_no_credential(demo, capsys):
    """The clear gift-card code and the credential are both absent from the whole transcript.

    The masking is a HABIT for the day the adapter is wired; what makes the demo safe offline is
    that the transport is stubbed unconditionally, so every code is a fixture placeholder. Both
    facts are asserted so neither is assumed.
    """
    assert demo.main(["--json", "--no-colour"]) == 0
    rendered = capsys.readouterr().out
    assert wg.demo_code(reference_id=REFERENCE) not in rendered
    assert wg.card_code(reference_id=REFERENCE, pepper="any-pepper") not in rendered
    assert PLACEHOLDER_API_KEY not in rendered
    for issuer in ("rzp_live_", "sk-", "AIza", "ghp_", "xoxb-", "AKIA", "ASIA", "sk_live_",
                   "ksk_", "PRIVATE KEY"):
        assert issuer not in rendered

    # The secret is referenced by NAME in the rendered form, which is the correct disclosure.
    assert demo.main(["--no-colour", "--leg", "wix-giftcard"]) == 0
    plain = capsys.readouterr().out
    assert "wecare/wix/headless-api-key" in plain
    assert "<redacted" in plain
    assert wg.demo_code(reference_id=REFERENCE) not in plain


@pytest.mark.parametrize("leg", ["coupon", "wix-giftcard", "our-giftcard", "invoice"])
def test_each_leg_runs_on_its_own(demo, capsys, leg):
    assert demo.main(["--json", "--no-colour", "--leg", leg]) == 0
    transcript = json.loads(capsys.readouterr().out)
    assert [entry["leg"] for entry in transcript["legs"]] == [leg]
    assert transcript["mismatchCount"] == 0


@pytest.mark.parametrize("argv,reason", [
    (["--value-paise", "100", "--redeem-paise", "200"], "redeem above value"),
    (["--value-paise", "0"], "a card worth nothing"),
    (["--redeem-paise", "0"], "a redemption of nothing"),
    (["--value-paise", "250050", "--redeem-paise", "250000"], "residual below the minimum leg"),
    (["--coupon-money-off-paise", "12345"], "not a whole number of rupees"),
    (["--coupon-money-off-paise", "0"], "a discount of nothing"),
    (["--reference-id", ""], "an empty reference"),
    (["--coupon-code", "not a code!"], "the store's own code rule"),
    (["--leg", "nonexistent"], "argparse choices"),
])
def test_a_usage_error_exits_two(demo, argv, reason):
    """`2` for every usage error, so a misuse is never mistaken for a contract failure (`1`)."""
    with pytest.raises(SystemExit) as exit_info:
        demo.main(["--json", "--no-colour"] + argv)
    assert exit_info.value.code == 2, reason


def test_the_demo_imports_the_shared_stubs_rather_than_private_copies():
    """ONE stub, TWO callers. A private copy inside `scripts/` is the drift this prevents.

    Nothing in `tests/` ships in a Lambda package, so importing from there costs nothing at
    deploy time - `scripts/deploy_all_lambdas.py` packages per-function sources under
    `amplify/`.
    """
    tree = ast.parse(DEMO.read_text(encoding="utf-8"), filename=str(DEMO))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert "coupon_fake_dynamo" in imported
    assert "wix_transport_stub" in imported
    # And it reimplements neither.
    assert not (ROOT / "scripts/coupon_fake_dynamo.py").exists()
    assert not (ROOT / "scripts/wix_transport_stub.py").exists()


def test_the_demo_makes_no_payment_state_decision():
    """It imports no payment vocabulary and asserts nothing about a payment status.

    A demonstration that decided a payment state would be a second decision site for the one
    vocabulary that must have exactly one.
    """
    tree = ast.parse(DEMO.read_text(encoding="utf-8"), filename=str(DEMO))
    modules = {(node.module or "") for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names}
    assert not [name for name in modules if "payment_status" in name]
    assert not [name for name in modules if "payment_attempt" in name]


def test_the_invoice_leg_shows_the_coupon_before_the_fee_and_the_card_after_the_total(
        demo, capsys):
    """The one leg that demonstrates the APPLY ORDER, asserted on the transcript's own figures.

    A coupon is a price change and a gift card is tender, so they enter at different points and
    the difference is not cosmetic: if the gift card were netted into the collection instead, the
    convenience fee and its GST would be computed on a smaller figure and the invoice would
    under-report tax on every gift-card order. The transcript carries both the discounted and the
    undiscounted fee precisely so that ordering is visible rather than asserted in prose.
    """
    assert demo.main(["--json", "--no-colour", "--leg", "invoice"]) == 0
    leg = json.loads(capsys.readouterr().out)["legs"][0]

    # 1. The coupon reduced the collection the fee is charged on.
    assert leg["discountedCollectionPaise"] == (leg["collectionPaise"]
                                                - leg["couponDiscountPaise"])
    assert leg["conveniencePaise"] < leg["undiscountedConveniencePaise"]

    # 2. The quote reconciles exactly, in integer paise.
    assert leg["authoritativeTotalPaise"] == (leg["discountedCollectionPaise"]
                                              + leg["conveniencePaise"]
                                              + leg["convenienceGstPaise"])

    # 3. The card came off THAT total, and the identity holds exactly.
    assert leg["redemptionPaise"] + leg["payablePaise"] == leg["authoritativeTotalPaise"]
    assert leg["requiresGateway"] is True

    # And nothing was debited: an unpaid invoice must never burn a customer's balance.
    assert leg["redemptionPaise"] == leg["cardBalancePaise"]
    assert leg["holdIdempotent"] is True
    assert set(leg["evidence"]) == {"giftCardCodeHash", "giftCardRequiredPaise",
                                    "giftCardRedeemedPaise"}

    # Every figure is an integer number of paise. No float reaches this transcript.
    for key in ("collectionPaise", "couponDiscountPaise", "discountedCollectionPaise",
                "conveniencePaise", "convenienceGstPaise", "authoritativeTotalPaise",
                "cardBalancePaise", "redemptionPaise", "payablePaise"):
        assert type(leg[key]) is int, key


def test_the_invoice_leg_prints_no_gift_card_code(demo, capsys):
    """The card is a bearer secret. Only `****` plus its last four may appear."""
    assert demo.main(["--no-colour", "--leg", "invoice"]) == 0
    plain = capsys.readouterr().out
    assert demo.DEMO_PEPPER not in plain
    masked = [line for line in plain.splitlines() if "card " in line and "****" in line]
    assert masked, "the card line is rendered"
