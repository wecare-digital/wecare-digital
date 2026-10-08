"""The reservation-key table has ONE name, and both payment legs must resolve it the same way.

WHY THIS FILE EXISTS
--------------------
The native WhatsApp payment path spans two Lambdas: `invoice-engine` RESERVES
(`PAYREF#`, `PAYMENTATTEMPT#`, `ORDERNO#`, `REQUESTKEY#`) and `razorpay-webhook` SETTLES by
resolving those same rows. They only join if both address the same physical table.

They did not. `razorpay-webhook` grew a module constant defaulting to
`stack-wecare-digital-CommerceKeys` while `order_keys.commerce_keys_table_name()` -- the single
documented resolver, and what `invoice-engine` uses -- falls back to
`stack-wecare-digital-WixOrderIds`. `CommerceKeys` is **not a provisioned table in this
account**; only `WixOrderIds` and `PaymentAttemptsTable` exist. With `COMMERCE_KEYS_TABLE` absent,
which is its live state, one handler read the reservation from the real table at one call site and
addressed a non-existent table at two others.

The lesson is not "that literal was wrong", it is that a dependency with two spellings inside one
handler cannot be kept consistent by review. So these tests assert the SHAPE -- one resolver, no
second literal, both legs equal -- rather than asserting today's string in a third place.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / 'amplify' / 'functions' / 'shared'
sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import order_keys  # noqa: E402

MANIFEST = ROOT / 'config' / 'lambda-env-manifest.json'
ENV_VAR = 'COMMERCE_KEYS_TABLE'

#: The resolver's own documented fallback, read from the resolver rather than retyped -- a third
#: copy of the string is the defect this file is about.
PROVISIONED = order_keys.commerce_keys_table_name()

#: `order_keys` is the ONE place allowed to name a fallback, because it is the resolver.
RESOLVER_SOURCE = SHARED / 'lambda_utils' / 'ecommerce' / 'order_keys.py'

PAYMENT_HANDLERS = {
    'invoice-engine': ROOT / 'amplify/functions/payments/invoice-engine/handler.py',
    'razorpay-webhook': ROOT / 'amplify/functions/payments/razorpay-webhook/handler.py',
}


def _manifest_functions() -> dict:
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    out = {}
    for name, entry in data['functions'].items():
        env = entry.get('environment', entry) if isinstance(entry, dict) else {}
        if isinstance(env, dict) and ENV_VAR in env:
            out[name] = env[ENV_VAR]
    return out


def _env_get_defaults(path: pathlib.Path, var: str) -> list:
    """Every literal default in `os.environ.get(var, <literal>)` in one module."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == 'get'):
            continue
        # `os.environ.get(...)` -- the receiver is `os.environ`.
        target = func.value
        if not (isinstance(target, ast.Attribute) and target.attr == 'environ'):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != var:
            continue
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            found.append(node.args[1].value)
    return found


# ── the table actually exists ────────────────────────────────────────────────

def test_the_resolver_names_a_table_the_account_actually_provisions():
    """`CommerceKeys` was never provisioned, which is what made the divergence fatal rather than
    merely untidy: the wrong branch does not read stale rows, it raises
    `ResourceNotFoundException` on a money path. Pinned against the names this repo provisions,
    so a rename has to come here."""
    assert PROVISIONED == 'stack-wecare-digital-WixOrderIds'
    assert 'CommerceKeys' not in PROVISIONED


# ── both legs agree ──────────────────────────────────────────────────────────

def test_both_payment_legs_resolve_the_same_keys_table_with_the_env_absent():
    """The live configuration. `COMMERCE_KEYS_TABLE` is NOT set on either function, so the
    defaults are what production runs -- and a reservation written by one leg has to be
    resolvable by the other."""
    assert ENV_VAR not in os.environ or os.environ[ENV_VAR] == PROVISIONED

    resolved = {}
    for label, path in PAYMENT_HANDLERS.items():
        literals = _env_get_defaults(path, ENV_VAR)
        # Either the handler goes through the resolver (no literal at all), or its literal must
        # be the provisioned name. A literal that is neither is the bug.
        assert all(value == PROVISIONED for value in literals), (label, literals)
        resolved[label] = literals[0] if literals else PROVISIONED

    assert len(set(resolved.values())) == 1, resolved


@pytest.mark.parametrize('label', sorted(PAYMENT_HANDLERS))
def test_no_payment_handler_carries_a_second_spelling_of_the_keys_table(label):
    """AST, not text: the comment explaining this rule necessarily contains the retired literal,
    so a textual scan would flag its own explanation."""
    source = PAYMENT_HANDLERS[label].read_text(encoding='utf-8')
    tree = ast.parse(source)
    literals = {node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    table_like = {value for value in literals
                  if value.startswith('stack-wecare-digital-') and 'Keys' in value}
    assert not table_like - {PROVISIONED}, (label, sorted(table_like))


def test_only_the_resolver_names_a_fallback():
    """One home for the default. `order_keys` may name it; a handler may not.

    The resolver's fallback is itself a nested `os.environ.get("WIX_ORDER_IDS_TABLE", ...)`, so
    it is asserted by presence-and-reachability rather than by a literal second argument -- which
    is also the reason a handler cannot reproduce it correctly by hand and should not try.
    """
    resolver_source = RESOLVER_SOURCE.read_text(encoding='utf-8')
    tree = ast.parse(resolver_source)
    reads = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call) and node.args
             and isinstance(node.args[0], ast.Constant) and node.args[0].value == ENV_VAR]
    assert reads, 'the resolver stopped reading the env var'
    assert PROVISIONED in resolver_source, 'the resolver no longer names a provisioned fallback'

    for label, path in PAYMENT_HANDLERS.items():
        assert _env_get_defaults(path, ENV_VAR) == [], label


# ── the manifest says the same thing ─────────────────────────────────────────

def test_every_manifest_entry_names_the_one_provisioned_table():
    """The manifest is the thing that gets PUSHED, so a wrong value here is worse than a wrong
    code default: it overrides the correct resolver on every function at once. Both payment
    entries once read `CommerceKeys` while the four pre-existing entries read `WixOrderIds` --
    four against two is not a convention, it is a typo."""
    declared = _manifest_functions()
    assert declared, 'no function declares the keys table; the assertion below would be vacuous'
    wrong = {name: value for name, value in declared.items() if value != PROVISIONED}
    assert not wrong, wrong


def test_the_manifest_declares_it_for_both_payment_legs():
    """Declared EXPLICITLY, which was the right instinct behind the original change: a default
    name is not an IAM permission, and a silent `AccessDeniedException` inside a `try` on a money
    path is the failure worth naming rather than hiding."""
    declared = _manifest_functions()
    for function in ('wecare-invoice-engine', 'wecare-razorpay-webhook'):
        assert function in declared, function
