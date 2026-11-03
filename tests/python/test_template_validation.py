"""Behavioural tests for lambda_utils.template_validation.

Feeds representative WhatsApp template-definition dicts and asserts the exact
rule violations the module encodes, plus acceptance of a well-formed template.
Each malformed case is pinned to the real error string the validator returns, so
a regression in a validator (e.g. dropping the placeholder/example check, the
quick-reply grouping check or the markdown-in-header warning) is caught.

Fixtures are synthetic: no real WABA ids or account data.
"""

from lambda_utils.template_validation import (
    first_error,
    validate_body,
    validate_buttons,
    validate_template,
)


def _well_formed_template():
    return {
        "name": "order_confirmation",
        "language": "en_US",
        "category": "UTILITY",
        "components": [
            {
                "type": "BODY",
                "text": "Hi {{1}}, your order {{2}} is confirmed.",
                "example": {"body_text": [["Asha", "ORD-1001"]]},
            },
            {"type": "FOOTER", "text": "Thank you"},
            {
                "type": "BUTTONS",
                "buttons": [
                    {"type": "QUICK_REPLY", "text": "Track order"},
                    {"type": "QUICK_REPLY", "text": "Contact us"},
                ],
            },
        ],
    }


def test_well_formed_template_is_accepted():
    result = validate_template(_well_formed_template())
    assert result["ok"] is True, result["errors"]
    assert result["errors"] == []


def test_empty_definition_is_rejected():
    result = validate_template({})
    assert result["ok"] is False
    assert "templateDefinition required" in result["errors"]


def test_body_requires_text():
    errors, _ = validate_body({"type": "BODY", "text": ""})
    assert "BODY text is required" in errors


def test_body_with_placeholder_requires_example():
    # A placeholder with no example values is the real rule validate_examples encodes.
    errors, _ = validate_body({"type": "BODY", "text": "Hello {{1}}"})
    assert any("no example values were provided" in e for e in errors)


def test_body_mixed_parameter_styles_rejected():
    errors, _ = validate_body({
        "type": "BODY",
        "text": "Hello {{1}} and {{name}}",
        "example": {"body_text": [["a"]]},
    })
    assert any("mixes positional" in e for e in errors)


def test_missing_body_component_is_rejected():
    template = {
        "name": "no_body",
        "language": "en_US",
        "category": "UTILITY",
        "components": [{"type": "FOOTER", "text": "hi"}],
    }
    result = validate_template(template)
    assert result["ok"] is False
    assert "Template must include a BODY component" in result["errors"]


def test_invalid_category_is_rejected():
    template = _well_formed_template()
    template["category"] = "PROMOTIONAL"
    err = first_error(template)
    assert err is not None
    assert "Invalid category" in err


def test_quick_replies_must_be_contiguous():
    # QUICK_REPLY, URL, QUICK_REPLY interleaves the group -> grouping error.
    buttons = [
        {"type": "QUICK_REPLY", "text": "Yes"},
        {"type": "URL", "text": "Visit", "url": "https://example.test"},
        {"type": "QUICK_REPLY", "text": "No"},
    ]
    errors, _ = validate_buttons(buttons)
    assert any("grouped together" in e for e in errors)


def test_unknown_button_type_is_rejected():
    errors, _ = validate_buttons([{"type": "TELEPORT", "text": "go"}])
    assert any("Unknown button type" in e for e in errors)


def test_markdown_in_body_is_a_warning_not_an_error():
    # The markdown check surfaces a warning; the template stays valid.
    template = _well_formed_template()
    template["components"][0]["text"] = "Hi {{1}}, your *order* {{2}} is confirmed."
    result = validate_template(template)
    assert result["ok"] is True, result["errors"]
    assert any("markdown characters" in w for w in result["warnings"])


def test_otp_button_outside_authentication_is_rejected():
    template = _well_formed_template()
    template["category"] = "UTILITY"
    template["components"][2]["buttons"] = [
        {"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"},
    ]
    result = validate_template(template)
    assert result["ok"] is False
    assert any("OTP button is only allowed on an AUTHENTICATION template" in e
               for e in result["errors"])
