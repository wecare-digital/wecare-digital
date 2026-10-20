"""Customer display codes never replace or mutate canonical customer identity."""
from lambda_utils.identity import customer_uuid

UUID = "77f927a4-5ce2-421e-bc1c-3b798c3e7738"


def test_code_is_stable_across_orders_and_customer_detail_changes():
    first = {"customerUuid": UUID, "orderId": "order-one", "customerPhone": "+910000000001"}
    second = {"customerUuid": UUID, "orderId": "order-two", "customerPhone": "+910000000002"}
    code = customer_uuid.display_code(first)
    assert code == customer_uuid.display_code(second)
    assert code.startswith("C-") and len(code) == 14
    assert set(code[2:]) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    assert first["customerUuid"] == second["customerUuid"] == UUID
    assert customer_uuid.from_contact(first) == UUID


def test_missing_or_invalid_identity_never_gets_a_display_code():
    for row in (None, {}, {"customerUuid": ""}, {"customerUuid": "garbage"},
                {"customerUuid": "01a15800-72c0-79f3-acad-251a05025f7a"}):
        assert customer_uuid.display_code(row) == ""


def test_distinct_fixture_customers_have_distinct_display_codes():
    assert customer_uuid.display_code({"customerUuid": UUID}) != customer_uuid.display_code(
        {"customerUuid": "7f3b1c9a-4e21-4d8b-ae55-112233445566"})
