"""Order-details message-template contract tests."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils import template_presets, template_validation  # noqa: E402


def test_order_details_preset_passes_shared_validator():
    definition = template_presets.get_preset("order_details_payment")
    assert definition is not None
    result = template_validation.validate_template(definition)
    assert result["ok"], result["errors"]


def test_order_details_is_utility_only_and_has_fixed_button_copy():
    good = template_presets.get_preset("order_details_payment")
    assert good
    bad_category = dict(good, category="MARKETING")
    result = template_validation.validate_template(bad_category)
    assert not result["ok"]
    assert any("UTILITY" in e for e in result["errors"])

    altered = {**good, "components": [dict(c) for c in good["components"]]}
    buttons = [dict(b) for b in altered["components"][-1]["buttons"]]
    buttons[0]["text"] = "Pay now"
    altered["components"][-1]["buttons"] = buttons
    result = template_validation.validate_template(altered)
    assert not result["ok"]
    assert any("Review and Pay" in e for e in result["errors"])


def test_order_status_preset_carries_utility_subcategory_and_validates():
    definition = template_presets.get_preset('order_status')
    assert definition['category'] == 'UTILITY'
    assert definition['sub_category'] == 'ORDER_STATUS'
    assert template_validation.validate_template(definition)['ok']


def test_order_status_rejects_marketing_and_text_placeholders():
    definition = template_presets.get_preset('order_status')
    definition['category'] = 'MARKETING'
    assert not template_validation.validate_template(definition)['ok']
    definition = template_presets.get_preset('order_status')
    definition['components'][0]['text'] = 'Your order {{1}}'
    assert not template_validation.validate_template(definition)['ok']
