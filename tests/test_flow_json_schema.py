"""Every Flow JSON in the tree is structurally valid, and the review flow matches its handler.

WHY THIS IS A LOCAL CHECK
-------------------------
Meta only validates Flow JSON as a side effect of creating the Flow on a WABA, and creating
or publishing a Flow is owner-only work under `01-standing-authorization.md`. So the build
loop cannot reach Meta's validator without doing the one thing it must not do. This pins
`scripts/validate_flow_json.py` instead, and every report citing it has to say "local
structural check", not "validated by Meta".

THE SECOND HALF IS THE ONE THAT WILL ACTUALLY CATCH SOMETHING
-------------------------------------------------------------
`handle_init` in `flows/leave_review.py` supplies an `order_ref` for the REVIEW_FORM screen
whenever attribution is enabled. If a later edit drops the declaration from the JSON, the
caption references a field the screen does not declare, which is the `Missing dynamic data
... in the data model for screen` class of error Meta raises when the Flow is created. If an
edit drops the fallback from `handle_init`, the screen renders a blank line. Neither failure
shows up in the validator, because each file is internally consistent on its own. So the
JSON and the handler are asserted against each other.

WHAT THIS FILE CANNOT SEE, AND WHY IT MATTERS HERE
--------------------------------------------------
It compares the repo's JSON against the repo's handler. It cannot see the version PUBLISHED
on Meta, which is the version a live `/flow-data` response is actually answered against.
That blind spot is the reason the handler gates `order_ref` behind
`REVIEW_ATTRIBUTION_ENABLED` rather than relying on a test: the gate holds the response
shape still across the gap between the Lambda deploy and the owner's publish, which no
local check can measure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLOWS = ROOT / "amplify" / "functions" / "messaging" / "whatsapp-business-api" / "flows"
SCRIPTS = ROOT / "scripts"

for _path in (str(SCRIPTS),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from validate_flow_json import flow_files, validate_flow  # noqa: E402

LEAVE_REVIEW = FLOWS / "leave-review-flow-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestEveryFlowJsonIsValid:
    @pytest.mark.parametrize("path", flow_files(FLOWS), ids=lambda p: p.name)
    def test_it_passes_the_structural_check(self, path: Path):
        problems = validate_flow(_load(path))
        assert problems == [], f"{path.name}: " + "; ".join(problems)

    def test_the_validator_is_actually_looking_at_files(self):
        """A validator pointed at an empty directory passes everything vacuously."""
        assert len(list(flow_files(FLOWS))) >= 15


class TestTheValidatorCanFail:
    """A check that never fails is decoration. Each rule is shown rejecting its own defect."""

    def test_a_dangling_routing_target_is_caught(self):
        doc = _load(LEAVE_REVIEW)
        doc["routing_model"]["REVIEW_FORM"] = ["TYPO_SCREEN"]
        assert any("TYPO_SCREEN" in p for p in validate_flow(doc))

    def test_an_undeclared_data_reference_is_caught(self):
        doc = _load(LEAVE_REVIEW)
        del doc["screens"][0]["data"]["order_ref"]
        assert any("order_ref" in p for p in validate_flow(doc))

    def test_a_missing_example_is_caught(self):
        doc = _load(LEAVE_REVIEW)
        del doc["screens"][0]["data"]["order_ref"]["__example__"]
        assert any("__example__" in p for p in validate_flow(doc))

    def test_a_form_field_with_no_component_is_caught(self):
        doc = _load(LEAVE_REVIEW)
        for child in doc["screens"][0]["layout"]["children"]:
            if child.get("name") == "rating":
                child["name"] = "renamed_rating"
        assert any("form.rating" in p for p in validate_flow(doc))

    def test_an_unreachable_terminal_screen_is_caught(self):
        doc = _load(LEAVE_REVIEW)
        doc["routing_model"]["REVIEW_FORM"] = []
        problems = validate_flow(doc)
        assert any("unreachable" in p for p in problems)

    def test_no_terminal_screen_is_caught(self):
        doc = _load(LEAVE_REVIEW)
        for screen in doc["screens"]:
            screen.pop("terminal", None)
        assert any("terminal" in p for p in validate_flow(doc))

    def test_a_single_screen_flow_needs_no_routing_model(self):
        """postpay-flow-v1.json is exactly this, and it is live. The rule must allow it."""
        doc = {
            "version": "7.3",
            "screens": [{
                "id": "ONLY", "terminal": True,
                "layout": {"type": "SingleColumnLayout", "children": []},
            }],
        }
        assert validate_flow(doc) == []

    def test_two_screens_without_a_routing_model_is_caught(self):
        doc = _load(LEAVE_REVIEW)
        del doc["routing_model"]
        assert any("routing_model" in p for p in validate_flow(doc))


class TestTheReviewFlowAndItsHandlerAgree:
    def test_the_review_screen_declares_order_ref_with_an_example(self):
        form = _load(LEAVE_REVIEW)["screens"][0]
        assert form["id"] == "REVIEW_FORM"
        assert "order_ref" in form["data"], "handle_init supplies order_ref; the screen must declare it"
        assert form["data"]["order_ref"]["type"] == "string"
        assert form["data"]["order_ref"]["__example__"]

    def test_the_caption_renders_it(self):
        layout = json.dumps(_load(LEAVE_REVIEW)["screens"][0]["layout"])
        assert "${data.order_ref}" in layout

    def test_the_caption_is_unconditional_so_it_cannot_render_empty(self):
        """Once `order_ref` is in play, `handle_init` always supplies a non-empty value.

        That is why the caption needs no If/visibility construct, and asserting it here is
        what stops someone "tidying" the fallback away and leaving a blank line on screen.

        "In play" is the qualifier, and `_attribution_enabled` is what decides it: with the
        flag off the key is OMITTED rather than blanked, so the response stays key-for-key
        what the currently published Flow version expects. See `TestTheFlowSideIsGated` in
        `tests/test_review_attribution.py` for why that gate exists.
        """
        source = (FLOWS / "leave_review.py").read_text(encoding="utf-8")
        assert "UNATTRIBUTED_LABEL" in source
        assert "screen_data['order_ref']" in source
        assert "if _attribution_enabled():" in source

    def test_the_rating_dropdown_still_offers_exactly_one_to_five(self):
        """The handler clamps to 1-5; the screen must not offer anything else."""
        form = _load(LEAVE_REVIEW)["screens"][0]
        ids = {r["id"] for r in form["data"]["ratings"]["__example__"]}
        assert ids == {"1", "2", "3", "4", "5"}
