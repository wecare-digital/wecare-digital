"""The short-link lifecycle contract: deactivate is reversible, retire is a one-way door.

Why each group here is the group
--------------------------------
A short link has already been printed, messaged and QR-coded by the time an operator wants it
gone, so the module exists to make the safe action (take it down, keep the record and the
clicks) the easy one and the destructive action (never resolve again) a deliberate terminal
move that cannot be undone by accident.

  VOCABULARY     exactly three states and six attachment kinds, so a stray word cannot become a
                 fourth state that no transition rule covers.
  RESOLUTION     only ACTIVE redirects; a legacy row with only `active` still resolves correctly;
                 INACTIVE and RETIRED both fall to the fallback.
  TRANSITIONS    ACTIVE <-> INACTIVE is reversible, RETIRED is a sink, and a no-op is allowed.
  ATTACHMENT     an unknown kind degrades to `general` rather than raising on a total path.

The module imports no boto3, so these pin the policy directly rather than through a fake table.
"""

from __future__ import annotations

import ast
import os
import sys

import pytest

SHARED = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "amplify", "functions", "shared")
)
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

from lambda_utils import short_link_lifecycle as sl  # noqa: E402


# ── vocabulary ───────────────────────────────────────────────────────────────────────────

def test_there_are_exactly_three_states():
    assert sl.STATES == {sl.STATE_ACTIVE, sl.STATE_INACTIVE, sl.STATE_RETIRED}
    assert (sl.STATE_ACTIVE, sl.STATE_INACTIVE, sl.STATE_RETIRED) == ("ACTIVE", "INACTIVE", "RETIRED")


def test_there_are_exactly_six_attachment_kinds():
    assert sl.RELATED_TYPES == {
        "general", "customer", "campaign", "order", "invoice", "service",
    }


@pytest.mark.parametrize("raw,expected", [
    ("active", "ACTIVE"), (" Inactive ", "INACTIVE"), ("RETIRED", "RETIRED"),
    ("", "ACTIVE"), (None, "ACTIVE"), ("junk", "ACTIVE"), (123, "ACTIVE"),
])
def test_canonical_state_never_raises_and_defaults_active(raw, expected):
    assert sl.canonical_state(raw) == expected


# ── resolution ───────────────────────────────────────────────────────────────────────────

def test_only_active_resolves():
    assert sl.is_resolvable({"lifecycleState": "ACTIVE"})
    assert not sl.is_resolvable({"lifecycleState": "INACTIVE"})
    assert not sl.is_resolvable({"lifecycleState": "RETIRED"})


def test_a_legacy_row_with_only_active_true_resolves():
    """Rows written before the lifecycle existed carry only `active`. A truthy/absent `active`
    is ACTIVE so an old working link does not suddenly stop resolving."""
    assert sl.is_resolvable({"active": True})
    assert sl.is_resolvable({})  # absent active defaults to on
    assert sl.state_from_record({}) == "ACTIVE"


def test_a_legacy_row_with_active_false_is_inactive_not_retired():
    """A bare boolean can only mean ACTIVE or INACTIVE; RETIRED is a deliberate decision nothing
    legacy ever recorded, so it must never be inferred from `active == False`."""
    assert sl.state_from_record({"active": False}) == "INACTIVE"
    assert not sl.is_resolvable({"active": False})


def test_explicit_lifecycle_state_wins_over_the_legacy_flag():
    """If a drifted row says active=True but lifecycleState=INACTIVE, the lifecycle wins and the
    link stops resolving — the whole reason the redirect asks is_resolvable, not active."""
    assert sl.state_from_record({"active": True, "lifecycleState": "INACTIVE"}) == "INACTIVE"
    assert not sl.is_resolvable({"active": True, "lifecycleState": "INACTIVE"})


# ── transitions ──────────────────────────────────────────────────────────────────────────

def test_active_and_inactive_are_reversible():
    assert sl.can_transition("ACTIVE", "INACTIVE")
    assert sl.can_transition("INACTIVE", "ACTIVE")


def test_both_can_be_retired():
    assert sl.can_transition("ACTIVE", "RETIRED")
    assert sl.can_transition("INACTIVE", "RETIRED")


def test_retired_is_terminal():
    assert not sl.can_transition("RETIRED", "ACTIVE")
    assert not sl.can_transition("RETIRED", "INACTIVE")


def test_retired_to_retired_is_an_idempotent_noop():
    """A repeat retire must not be refused as an illegal transition; it is simply a no-op."""
    assert sl.can_transition("RETIRED", "RETIRED")
    assert sl.can_transition("ACTIVE", "ACTIVE")


def test_active_flag_is_kept_in_sync_with_state():
    assert sl.active_flag_for("ACTIVE") is True
    assert sl.active_flag_for("INACTIVE") is False
    assert sl.active_flag_for("RETIRED") is False


# ── attachment ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("customer", "customer"), (" ORDER ", "order"), ("Invoice", "invoice"),
    ("service", "service"), ("campaign", "campaign"),
    ("", "general"), (None, "general"), ("nonsense", "general"), ({}, "general"),
])
def test_canonical_related_type_defaults_to_general(raw, expected):
    assert sl.canonical_related_type(raw) == expected


# ── the module is a policy module ────────────────────────────────────────────────────────

def test_the_module_imports_no_boto3():
    """It decides policy over injected values, so it needs no AWS client or credential — the
    same contract the other lambda_utils policy modules hold. Walked with ast rather than
    searched as text so the docstring's own mention of boto3 does not trip it."""
    with open(os.path.join(SHARED, "lambda_utils", "short_link_lifecycle.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert "boto3" not in imported
    assert "botocore" not in imported
