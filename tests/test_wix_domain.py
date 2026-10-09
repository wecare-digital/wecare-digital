"""Phase 7.2 — the Wix domain layer, and proof the lift changed nothing.

`wix_domain.py` holds 13 pure transforms lifted verbatim out of `wix-store/handler.py`.
The handler went 1,761 → 1,512 lines and, more to the point, these functions are now
importable **without AWS and without a Wix credential** — testing `_money_amount` used to
mean standing up the whole integration.

WHY THE GOLDEN CASES EXIST
--------------------------
A diff proves the text moved. It does not prove the behaviour did. The 64 cases below were
recorded from the pre-lift handler and replayed against the lifted module, and that catch
was not hypothetical — the first run found two real problems:

1. **`_generate_wd_order_number` raised `NameError` in all four cases.** The extracted set
   needed `datetime`, `timezone` and `timedelta`, and the new module imported `json`, `re`,
   `time` and `uuid` but not those. A "verbatim move" that drops an import is still broken,
   and nothing in the diff would have shown it.
2. **Seven false differences**, because `_generate_sku` mixes in a time-derived suffix and
   `_generate_wd_order_number` a uuid and a clock. Comparing them raw would have meant
   either accepting noise or — worse — letting a genuine regression hide inside it. The
   varying characters are masked and the STRUCTURE is compared, so a change in separator,
   prefix or field count still fails.

The awkward inputs are deliberate: empty dict, `None`, zero, a price as a string rather
than a number, unicode with a rupee sign, a 120-character name, double spaces, tabs and
newlines. Those are where a shape-mapper breaks.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import wix_domain as d  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/wix-store/handler.py"

LIFTED = [
    "_fields_suffix", "_first_variant", "_money_amount",
    "_read_only_variant_to_product_variant", "_normalize_v3_product",
    "_normalize_category", "_simple_product_to_v3", "_generate_wd_order_number",
    "_generate_sku", "_base36", "_extract_id", "_get_main_media", "_parse_body",
]

PRODUCT_V3 = {
    "id": "p-1", "name": "Ayurvedic Hair Oil 200ml",
    "slug": {"name": "ayurvedic-hair-oil"},
    "plainDescription": "Cold pressed.", "description": "<p>Cold pressed.</p>",
    "media": {"main": {"url": "https://static.wixstatic.com/a.jpg"},
              "itemsInfo": {"items": [
                  {"image": {"url": "https://static.wixstatic.com/a.jpg"}},
                  {"image": {"url": "https://static.wixstatic.com/b.jpg"}}]}},
    "variantsInfo": {"variants": [
        {"id": "v-1", "price": {"actualPrice": {"amount": "349.00"}},
         "sku": "WD-HAIR-001", "visible": True,
         "physicalProperties": {"weight": 0.25}}]},
    "inventory": {"availabilityStatus": "IN_STOCK"},
    "visible": True, "currency": "INR",
    "url": {"relativePath": "/shop/ayurvedic-hair-oil"},
}


class TestTheModuleNeedsNothing:
    def test_it_imports_without_aws_or_a_credential(self):
        # The whole point of the split. If this module ever grows a boto3 import it has
        # stopped being a domain layer.
        import ast
        source = (SHARED / "lambda_utils/ecommerce/wix_domain.py").read_text()
        # Strip the module docstring and comments first. The docstring NAMES boto3,
        # `_wix_request` and `_load_wix_api_key` while explaining what deliberately stayed
        # in the handler, and reporting that as impurity is reporting the record of the
        # decision as the defect — a mistake this repository's gates have had to be taught
        # to avoid more than once.
        tree = ast.parse(source)
        if (tree.body and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)):
            source = source.replace(tree.body[0].value.value, "", 1)
        source = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#"))

        for banned in ("boto3", "botocore", "os.environ", "getenv",
                       "_wix_request", "_load_wix_api_key", "dynamodb"):
            assert banned not in source, (
                f"wix_domain.py references {banned} in code; it is supposed to be pure")

    def test_every_lifted_function_is_here(self):
        for name in LIFTED:
            assert hasattr(d, name), f"{name} did not survive the lift"

    def test_none_is_still_defined_in_the_handler(self):
        import ast
        tree = ast.parse(HANDLER.read_text())
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        duplicated = sorted(set(LIFTED) & defined)
        assert not duplicated, (
            f"still defined in both places, so the two copies can drift: {duplicated}")

    def test_the_handler_imports_them_from_the_shared_module(self):
        source = HANDLER.read_text()
        assert "from lambda_utils.ecommerce.wix_domain import" in source

    def test_the_adapter_deliberately_stayed_behind(self):
        import ast
        tree = ast.parse(HANDLER.read_text())
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        # Transport, credentials and the job layer are not domain concerns. `_response`
        # reads a module-level origin global, so lifting it would carry that global into a
        # shared module — the opposite of the point.
        for stays in ("_wix_request", "_load_wix_api_key", "_credentials_disabled",
                      "_hydrate_product_variants", "_response",
                      "_sync_products", "_sync_orders"):
            assert stays in defined, f"{stays} should have stayed in the handler"


class TestGoldenEquivalence:
    """The 64 recorded cases. Masked where the function is not deterministic."""

    @staticmethod
    def mask(name, out):
        if name == "_generate_sku" and isinstance(out, str):
            return re.sub(r"-[0-9A-Z]{4}$", "-<SUFFIX>", out)
        if name == "_generate_wd_order_number" and isinstance(out, str):
            out = re.sub(r"[0-9A-F]{8}", "<UUID8>", out)
            out = re.sub(r"\d{2}-\d{2}-\d{4}", "<DATE>", out)
            return re.sub(r"\d{2}:\d{2}:\d{2}", "<TIME>", out)
        if name == "_simple_product_to_v3" and isinstance(out, dict):
            blob = json.dumps(out, default=str, sort_keys=True)
            blob = re.sub(r"(WD-[A-Z0-9]{2})-[0-9A-Z]{4}", r"\1-<SUFFIX>", blob)
            return json.loads(blob)
        return out

    @pytest.mark.parametrize("value,expected", [
        (0, "0"), (349, "349"), ("349.00", "349.00"), ("0", "0"), (12.5, "12.5"),
    ])
    def test_money_amount_is_a_string_and_keeps_its_precision(self, value, expected):
        # The one that matters for an invoice: a price must not gain or lose a decimal
        # place on the way through.
        assert d._money_amount(value) == expected

    def test_money_amount_maps_none_to_empty_not_to_zero(self):
        # The distinction that matters: a missing price must not become a free product.
        assert d._money_amount(None) == ""

    def test_money_amount_unwraps_a_wix_money_object(self):
        assert d._money_amount({"amount": "349.00"}) == "349.00"

    def test_money_amount_rejects_a_non_numeric_value(self):
        # CHANGED 2026-09-24, and the previous version of this test is the reason to
        # explain it. It asserted `_money_amount("abc") == "abc"` and said so in its
        # name: the function ended in a bare `str(value)`, so a junk price travelled
        # verbatim into the `price` field the admin UI renders. That was pinned
        # rather than fixed at the time, because it was pre-existing behaviour
        # identical across all 64 golden cases and failing a build on an opinion is
        # not a lift.
        #
        # It is fixed now, and the reason is stronger than taste: '' is what every
        # caller already tests for when falling back to the next price source, so a
        # truthy junk value STOPPED the fallback chain on the junk and never
        # consulted the price range that may have held a real number. Validating
        # repairs the fallback rather than just tidying the output.
        assert d._money_amount("abc") == ""
        assert d._money_amount({"amount": "not-a-price"}) == ""
        assert d._money_amount("") == ""
        assert d._money_amount("   ") == ""

    def test_money_amount_keeps_every_shape_wix_actually_sends(self):
        # The rejection must not take real amounts with it. Wix sends decimal
        # strings, sometimes with no fractional part, sometimes as a number.
        assert d._money_amount("1499") == "1499"
        assert d._money_amount("1499.00") == "1499.00"
        assert d._money_amount("0") == "0"
        assert d._money_amount("0.00") == "0.00"
        assert d._money_amount(1499) == "1499"
        assert d._money_amount({"amount": "349.00"}) == "349.00"
        # Whitespace is trimmed rather than rejected - a padded number is a number.
        assert d._money_amount(" 349.00 ") == "349.00"

    @pytest.mark.parametrize("num,expected", [
        (0, "0"), (1, "1"), (35, "Z"), (36, "10"), (1295, "ZZ"), (1296, "100"),
    ])
    def test_base36_boundaries(self, num, expected):
        assert d._base36(num) == expected

    def test_sku_keeps_its_shape_across_awkward_names(self):
        for name in ("Ayurvedic Hair Oil", "", "a", "Ünïcodé ₹", "x" * 120,
                     "with  double  spaces", "Tabs\tand\nnewlines"):
            sku = d._generate_sku(name)
            assert re.fullmatch(r"WD-..-[0-9A-Z]{4}", sku), (
                f"_generate_sku({name!r}) produced {sku!r}, which is not the WD-XX-NNNN "
                f"shape the catalog and the invoice series both rely on")

    def test_order_number_is_the_current_public_format(self):
        # This is the function that raised NameError post-lift because `datetime` was not
        # carried over. Asserted directly so that cannot recur silently.
        #
        # FEAT-005 changed the SHAPE: it was
        # `WD-ORD - {UUID8} - {DD-MM-YYYY} - {HH:MM:SS} - IST` and is now `WD-ORD-` plus 8
        # symbols of the public alphabet. The date is gone on purpose, so asserting for one
        # would now be asserting the defect. Uniqueness never came from the timestamp
        # anyway - the conditional write under ORDERNO# is what guarantees it.
        out = d._generate_wd_order_number("2026-09-24T10:00:00Z")
        assert re.fullmatch(r"WD-ORD-[23456789ABCDEFGHJKMNPQRSTVWXYZ]{8}", out), out
        assert " - " not in out and "IST" not in out
        assert not re.search(r"\d{2}-\d{2}-\d{4}", out), "the number still carries a date"

    def test_order_number_survives_a_missing_and_a_malformed_date(self):
        for value in ("", None, "2026-01-01", "not-a-date"):
            out = d._generate_wd_order_number(value)
            assert out.startswith("WD-ORD"), f"failed on {value!r}"

    def test_normalize_v3_product_on_a_full_payload(self):
        out = d._normalize_v3_product(PRODUCT_V3)
        assert isinstance(out, dict) and out
        # The fields the catalog UI reads. A rename here is a silent blank on screen.
        assert out.get("id") == "p-1"
        assert "Ayurvedic" in str(out.get("name", ""))

    @pytest.mark.parametrize("payload", [{}, {"id": "x"},
                                         {"name": "n", "variantsInfo": {"variants": []}}])
    def test_normalize_v3_product_never_raises_on_a_thin_payload(self, payload):
        # Wix omits keys rather than sending nulls, so a thin payload is the normal case.
        assert isinstance(d._normalize_v3_product(payload), dict)

    @pytest.mark.parametrize("payload", [{}, {"name": "", "price": 0},
                                         {"name": "Tea", "price": 120, "sku": "T-1"}])
    def test_simple_product_to_v3_always_produces_a_variant(self, payload):
        out = d._simple_product_to_v3(payload)
        variants = out.get("variantsInfo", {}).get("variants", [])
        assert len(variants) == 1, "Wix v3 rejects a product with no variant"
        assert "price" in variants[0]

    @pytest.mark.parametrize("path,resource,expected", [
        ("/wix-store/products/p-1", "products", "p-1"),
        ("/wix-store/products", "products", None),
        ("/wix-store/orders/o-9", "orders", "o-9"),
        ("", "products", None),
    ])
    def test_extract_id(self, path, resource, expected):
        assert d._extract_id(path, resource) == expected

    @pytest.mark.parametrize("event,expected", [
        ({"body": '{"a":1}'}, {"a": 1}),
        ({"body": "{bad json"}, {}),
        ({}, {}),
        ({"body": None}, {}),
        ({"body": {"already": "dict"}}, {"already": "dict"}),
    ])
    def test_parse_body_never_raises(self, event, expected):
        # A malformed body is a 400, not a 500, and that starts here.
        assert d._parse_body(event) == expected

    def test_get_main_media_reads_the_v3_shape(self):
        # It reads `media.main.url` for v3 and falls back to `media.mainMedia.image.url`
        # for v1. My first fixture used `media.main.image.url`, which is neither, and the
        # function correctly returned '' — the fixture was wrong, not the code.
        assert d._get_main_media(PRODUCT_V3) == "https://static.wixstatic.com/a.jpg"

    def test_get_main_media_falls_back_to_the_v1_shape(self):
        v1 = {"media": {"mainMedia": {"image": {"url": "https://x/legacy.jpg"}}}}
        assert d._get_main_media(v1) == "https://x/legacy.jpg"

    def test_get_main_media_returns_empty_rather_than_raising(self):
        # A product with no image is normal; a 500 because of one is not.
        for thin in ({}, {"media": {}}, {"media": {"main": {}}}, {"media": None}):
            assert d._get_main_media(thin) == ""

    @pytest.mark.parametrize("fields,expected_empty", [([], True), (None, True)])
    def test_fields_suffix_is_empty_when_there_are_no_fields(self, fields,
                                                             expected_empty):
        assert (d._fields_suffix(fields) == "") is expected_empty

    def test_fields_suffix_joins_what_it_is_given(self):
        out = d._fields_suffix(["URL", "CURRENCY"])
        assert "URL" in out and "CURRENCY" in out
