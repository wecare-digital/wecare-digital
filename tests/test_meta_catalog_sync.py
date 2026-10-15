"""The ProductsTable -> Meta projection, pinned against the committed snapshot.

PHASE W, FEAT-001. The module under test is pure, so every assertion here runs with no
credential, no network and no AWS client - which is the whole reason the retailer-id contract and
the diff live in a module separate from the Lambda.

THE FIXTURE IS THE REAL CATALOGUE, NOT A HAND-WRITTEN ONE. `src/content/catalog-snapshot.json` is
the committed storefront snapshot that `scripts/build-catalog-snapshot.py` generates from
ProductsTable (10 products, fetched 2026-10-15). Publish eligibility is judged separately on
`tests/fixtures/products-table-20261015.json` through the handler's own `_native_products`, the
read the Lambda actually performs. A hand-written fixture would agree with whatever this module
happened to do.

WHAT THE 21 IS. Ten products are in the snapshot and two are not projected: the Rs.1 test product
(excluded by slug) and Contribute, which the catalogue currently marks hidden (`visible: false`,
`metaEnabled: false`). The other eight give one Meta item per VARIANT:

    Request (services)  5     Kiosk               1     Paperwork    1
    Merchandise        10     Referral Partner    1     Anew         1
                              Guided Resolution   1     File Assist  1

These are measurements rather than choices, so a snapshot refresh that moves one of them fails
here and is reviewed instead of silently changing what the WhatsApp catalogue would carry.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import meta_catalog_sync as sync  # noqa: E402

MODULE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/meta_catalog_sync.py"
SNAPSHOT = ROOT / "src/content/catalog-snapshot.json"

#: Two real ids from the snapshot (the Rs.1 test product and its variant), so the round-trip is
#: tested on values the catalogue actually holds.
TEST_PRODUCT = "121c9d57-2cc9-490b-8eed-66bf7b9c172a"
TEST_VARIANT = "c2edc783-c8fa-4b3e-a922-f7800889e56a"

#: The live retailer-id namespace, read from the module rather than restated, so this file builds
#: every id the way production does.
PREFIX = sync.RETAILER_PREFIX

CONTRIBUTE = sync.CONTRIBUTION_PRODUCT_ID

#: The expected variant count per real product, by slug. Written out rather than derived from the
#: snapshot, because deriving it would make this test agree with any snapshot - including one a
#: bad refresh had emptied.
EXPECTED_ITEMS_BY_SLUG = {
    "wecaredigital-services": 5,
    "merchandise": 10,
    "kiosk": 1,
    "referral-partner": 1,
    "guided-resolution": 1,
    "file-assist": 1,
    "paperwork": 1,
    "anew": 1,
}

EXPECTED_ITEM_COUNT = 21


@pytest.fixture(scope="module")
def products():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["products"]


@pytest.fixture(scope="module")
def desired(products):
    return sync.desired_items(products)


#: Live ProductsTable rows (2026-10-15) limited to what the handler's `_native_products()` reads.
#: Media lives on ProductsTable `imageRefs` (CloudFront), not in the display-only storefront
#: snapshot, so publish eligibility is judged on the native read the Lambda actually performs.
NATIVE_ROWS = ROOT / "tests/fixtures/products-table-20261015.json"
HANDLER = ROOT / "amplify/functions/ecommerce/meta-catalog-sync/handler.py"


@pytest.fixture(scope="module")
def native_products():
    import copy
    import importlib.util
    name = "wecare_meta_catalog_sync_handler_for_catalog_tests"
    spec = importlib.util.spec_from_file_location(name, HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    rows = json.loads(NATIVE_ROWS.read_text(encoding="utf-8"))["items"]
    return module._native_products(scanner=lambda: copy.deepcopy(rows))


# ── 1. the retailer-id contract ──────────────────────────────────────────────


def test_a_retailer_id_round_trips(products):
    """The join key must survive the trip, for every variant of every real product.

    This is the property the whole feature rests on: a WhatsApp order carries
    `product_retailer_id`, and the only way it resolves to a catalogue line is if parsing returns
    the pair that was used to build it.
    """
    pairs = 0
    for product in products:
        if not sync.is_syncable(product):
            continue
        for variant in product.get("variants") or []:
            value = sync.retailer_id(product["id"], variant["id"])
            assert sync.parse_retailer_id(value) == (product["id"], variant["id"])
            pairs += 1
    assert pairs == EXPECTED_ITEM_COUNT


def test_the_retailer_id_shape_is_the_documented_one():
    """`<prefix>:<productId>:<variantId>`. The length is the prefix plus two 36-char UUIDs and the
    two colons, and must stay under Meta's ceiling: the live Meta catalogue and inbound WhatsApp
    orders carry ids of exactly this shape."""
    value = sync.retailer_id(TEST_PRODUCT, TEST_VARIANT)
    assert value == f"{PREFIX}:{TEST_PRODUCT}:{TEST_VARIANT}"
    assert len(value) == len(PREFIX) + 1 + 36 + 1 + 36
    assert len(value) < sync.RETAILER_ID_MAX_LENGTH


def test_new_ids_are_written_provider_neutral_not_wix():
    """New catalogue ids carry the provider-neutral namespace. The owner uses their own site, not
    Wix, so nothing the backend WRITES may stamp a `wix:` id."""
    assert sync.RETAILER_PREFIX == "wecare"
    assert sync.retailer_id(TEST_PRODUCT, TEST_VARIANT).startswith("wecare:")
    assert not sync.retailer_id(TEST_PRODUCT, TEST_VARIANT).startswith("wix:")


def test_legacy_wix_ids_still_resolve_so_in_flight_orders_do_not_break():
    """Items published before the rename carry `wix:` ids, and a WhatsApp order against one echoes
    that back. Until the live Meta catalogue is fully republished under `wecare:`, inbound parsing
    MUST still resolve a legacy id to its ProductsTable line - otherwise an in-flight order fails
    with 'we cannot price this line'. This compatibility is removed once Meta carries no `wix:`
    item."""
    assert "wix" in sync.LEGACY_RETAILER_PREFIXES
    legacy = f"wix:{TEST_PRODUCT}:{TEST_VARIANT}"
    assert sync.parse_retailer_id(legacy) == (TEST_PRODUCT, TEST_VARIANT)
    # and the current namespace parses too
    assert sync.parse_retailer_id(
        f"wecare:{TEST_PRODUCT}:{TEST_VARIANT}") == (TEST_PRODUCT, TEST_VARIANT)


def test_case_is_normalised_so_one_item_cannot_fork_into_two():
    """Meta's retailer id is case-sensitive; the catalogue stores canonical lowercase.

    So an upper-case id arriving from anywhere must land on the SAME retailer id, or the catalogue
    would carry the same variant twice and an order could resolve to either.
    """
    assert (sync.retailer_id(TEST_PRODUCT.upper(), TEST_VARIANT.upper())
            == sync.retailer_id(TEST_PRODUCT, TEST_VARIANT))
    assert (sync.parse_retailer_id(
        f"{PREFIX.upper()}:{TEST_PRODUCT.upper()}:{TEST_VARIANT.upper()}")
            == (TEST_PRODUCT, TEST_VARIANT))


@pytest.mark.parametrize("product_id,variant_id", [
    ("", TEST_VARIANT),
    (None, TEST_VARIANT),
    (TEST_PRODUCT, ""),
    (TEST_PRODUCT, None),
    ("not-a-uuid", TEST_VARIANT),
    (TEST_PRODUCT, "12345"),
    (f"{TEST_PRODUCT}:extra", TEST_VARIANT),
    (TEST_PRODUCT, f"{TEST_VARIANT}:extra"),
    ("121c9d57-2cc9-490b-8eed-66bf7b9c172", TEST_VARIANT),   # one character short
    (123, TEST_VARIANT),
])
def test_a_non_uuid_part_is_refused_rather_than_normalised(product_id, variant_id):
    """Refuse, don't coerce. A nearly-right retailer id creates a Meta item nothing resolves."""
    with pytest.raises(ValueError):
        sync.retailer_id(product_id, variant_id)


@pytest.mark.parametrize("value", [
    "WD-PARTNER-UP",                        # the catalog-builder's free-typed SKU shape
    "htlu35lrs1",                           # the live SKU `inbound-whatsapp-handler` cites
    "",
    None,
    PREFIX,
    f"{PREFIX}:",
    f"{PREFIX}:{TEST_PRODUCT}",                   # prefix, one UUID, no variant
    f"{PREFIX}:{TEST_PRODUCT}:{TEST_VARIANT}:x",  # an extra segment
    f"{PREFIX}:{TEST_PRODUCT}:not-a-uuid",
    f"shop:{TEST_PRODUCT}:{TEST_VARIANT}",  # a different prefix
    f"{TEST_PRODUCT}:{TEST_VARIANT}",       # no prefix at all
    123,
])
def test_anything_that_is_not_ours_parses_to_None(value):
    """`None` is what routes an item into `foreign`, where it is reported and never modified.

    The Meta catalogue is also edited by hand through `catalog-builder.tsx`, so this set is not
    hypothetical: a sync that tidied up what it could not parse would delete someone's work.
    """
    assert sync.parse_retailer_id(value) is None


# ── 2. which rows are syncable ───────────────────────────────────────────────


def test_only_the_test_product_and_hidden_rows_are_excluded(products):
    """Two exclusions and no more: the Rs.1 test product, by slug, and `visible: false`.

    Checked on every committed row and on a row the catalogue has never seen, so an id- or
    slug-based deny-list cannot quietly reappear inside `is_syncable`: any other row is projected
    on its own flags.
    """
    for product in products:
        is_test_product = product["slug"] in sync.TEST_PRODUCT_SLUGS
        assert sync.is_syncable(product) is (
            product.get("visible") is not False and not is_test_product), product["slug"]
        assert sync.is_syncable({**product, "visible": True}) is (not is_test_product)
    assert sync.is_syncable({"id": "00000000-0000-4000-8000-000000000000",
                             "slug": "a-new-product", "visible": True}) is True


def test_the_test_product_is_excluded_by_slug_and_not_by_id():
    """Its real id is reused below as a fixture under neutral slugs, which must stay syncable."""
    assert sync.is_syncable({"id": TEST_PRODUCT, "slug": "1-test-product",
                             "visible": True}) is False
    assert sync.is_syncable({"id": TEST_PRODUCT, "slug": "x", "visible": True}) is True


def test_the_contribution_product_is_retained_but_not_meta_syncable(products):
    """The payment vehicle stays in the snapshot for cart identity, but catalog v2 explicitly
    disables website and Meta publication. A hidden row must therefore remain known without
    becoming a customer-visible WhatsApp catalogue item.
    """
    contribute = next(p for p in products if p["id"] == CONTRIBUTE)
    assert contribute["visible"] is False
    assert contribute["metaEnabled"] is False
    assert sync.is_syncable(contribute) is False
    assert len(contribute["variants"]) == 1


def test_a_hidden_product_is_excluded_but_an_ABSENT_visible_is_not():
    """Identity against `False`, not truthiness. A row read without `visible` must not be hidden:
    treating absence as hidden would empty the catalogue on a shape change rather than fail
    loudly."""
    assert sync.is_syncable({"id": TEST_PRODUCT, "slug": "x", "visible": False}) is False
    assert sync.is_syncable({"id": TEST_PRODUCT, "slug": "x"}) is True
    assert sync.is_syncable({"id": TEST_PRODUCT, "slug": "x", "visible": True}) is True


# ── 3. the desired catalogue ─────────────────────────────────────────────────


def test_the_snapshot_yields_exactly_the_expected_item_count(desired):
    assert len(desired) == EXPECTED_ITEM_COUNT


def test_the_items_are_the_expected_products_and_variant_counts(products, desired):
    by_slug = {product["id"]: product["slug"] for product in products}
    counted: dict = {}
    for item in desired:
        counted[by_slug[item["item_group_id"]]] = counted.get(
            by_slug[item["item_group_id"]], 0) + 1
    assert counted == EXPECTED_ITEMS_BY_SLUG
    assert sum(EXPECTED_ITEMS_BY_SLUG.values()) == EXPECTED_ITEM_COUNT


def test_exactly_the_syncable_products_reach_the_desired_catalogue(products, desired):
    groups = {item["item_group_id"] for item in desired}
    assert groups == {product["id"] for product in products
                      if sync.is_syncable(product) and product.get("variants")}
    assert CONTRIBUTE not in groups
    assert TEST_PRODUCT not in groups


def test_every_item_carries_the_contract_fields(desired):
    for item in desired:
        assert sync.parse_retailer_id(item["retailer_id"]) is not None
        # `item_group_id` IS the product half of the retailer id, which is what lets Meta group a
        # product's variants without a second lookup.
        assert sync.parse_retailer_id(item["retailer_id"])[0] == item["item_group_id"]
        assert item["availability"] in (sync.IN_STOCK, sync.OUT_OF_STOCK)
        assert item["currency"] == "INR"
        assert item["name"]
        assert item["description"]


def test_a_retailer_id_is_unique_per_item(desired):
    ids = [item["retailer_id"] for item in desired]
    assert len(set(ids)) == len(ids)


def test_a_multi_variant_product_carries_its_label_and_a_single_one_does_not(desired):
    merchandise = [i for i in desired
                   if i["item_group_id"] == "eca1540e-0a0e-478d-9aa7-e366be277617"]
    assert len(merchandise) == 10
    assert all(i["name"].startswith("Merchandise - ") for i in merchandise)
    assert len({i["name"] for i in merchandise}) == 10, "ten options must be distinguishable"

    kiosk = next(i for i in desired
                 if i["item_group_id"] == "a12e9e74-e109-4136-a12e-ab49ea6f98c3")
    assert kiosk["name"] == "Kiosk", "a single-variant product must not read 'Kiosk - Standard'"


def test_stock_state_is_projected_and_the_out_of_stock_branch_is_still_pinned(desired):
    """Two halves, because the snapshot carries no out-of-stock row.

    Every variant in the committed snapshot is in stock, the five service variants included. So
    the OUT_OF_STOCK branch has no live example, and it is asserted on a constructed row rather
    than dropped. The mapping is the thing under test; a branch with no test at all is how
    `availability` would quietly start reporting a sold-out item as buyable.
    """
    services = [i for i in desired
                if i["item_group_id"] == "df976a0a-f582-4535-b2e1-d532f348bd27"]
    assert len(services) == 5
    assert all(i["availability"] == sync.IN_STOCK for i in services)
    assert all(i["availability"] == sync.IN_STOCK for i in desired)

    sold_out = sync.desired_items([{
        "id": TEST_PRODUCT, "slug": "x", "name": "X", "price": "1.00",
        "variants": [{"id": TEST_VARIANT, "label": "Standard", "inStock": False}],
    }])[0]
    assert sold_out["availability"] == sync.OUT_OF_STOCK


def test_an_imageless_product_has_NO_image_url_key():
    """Absent rather than empty. An empty string on an update reads to Meta as "clear the image",
    which is a different instruction from "I have nothing to say about the image"."""
    items = sync.desired_items([{
        "id": TEST_PRODUCT, "slug": "imageless", "name": "Imageless", "price": "1.00",
        "variants": [{"id": TEST_VARIANT, "label": "Standard", "inStock": True}],
    }])
    assert all("image_url" not in item for item in items)


def test_an_image_is_carried_through_when_the_row_has_one():
    item = sync.desired_items([{
        "id": TEST_PRODUCT, "slug": "x", "name": "X", "price": "1.00",
        "image": "https://wecare.digital/get/o/public/x.png",
        "variants": [{"id": TEST_VARIANT, "label": "Standard", "inStock": True}],
    }])[0]
    assert item["image_url"] == "https://wecare.digital/get/o/public/x.png"


def test_a_product_with_no_variants_is_skipped_rather_than_guessed_at():
    """There is no variant id to join on, so no retailer id can be formed and no order could ever
    resolve back to the line. Skipping is the only honest answer."""
    assert sync.desired_items([{"id": TEST_PRODUCT, "slug": "x", "name": "X",
                                "price": "1.00", "variants": []}]) == []


def test_meta_payload_drops_the_internal_grouping_field(desired):
    """`product_name` is for `blockers` and the log line. An allowlist projection is what makes it
    impossible to send as a Meta product attribute."""
    payload = sync.meta_payload(desired[0])
    assert "product_name" not in payload
    assert set(payload) <= set(sync.META_ITEM_FIELDS)
    assert payload["retailer_id"] == desired[0]["retailer_id"]


# ── 4. money ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("paise,text", [
    (100, "1.00"),
    (119900, "1199.00"),
    (5, "0.05"),
    (50, "0.50"),
    (99, "0.99"),
    (2499900, "24999.00"),
    (1, "0.01"),
])
def test_a_price_is_composed_from_integer_paise_by_slicing(paise, text):
    assert sync.price_text(paise) == text


def test_the_snapshot_prices_survive_the_round_trip(desired):
    """The three figures a reader can check by eye against the snapshot."""
    prices = {item["item_group_id"]: item["price"] for item in desired}
    assert "121c9d57-2cc9-490b-8eed-66bf7b9c172a" not in prices      # Rs1 test product
    assert prices["a12e9e74-e109-4136-a12e-ab49ea6f98c3"] == "24999.00"  # Kiosk
    assert prices["abfdad33-b853-4aeb-b2f9-fa4051e75928"] == "599.00"    # Anew


@pytest.mark.parametrize("value", ["599.005", "0", "-1", "abc", "", None, "1,199.00"])
def test_a_price_that_is_not_a_whole_positive_number_of_paise_is_refused(value):
    """Fail closed. Rounding a fractional paise would plant the one-paise mismatch the checkout
    comparison exists to refuse."""
    with pytest.raises(ValueError):
        sync.paise_from_major(value)


def test_a_variant_with_no_price_is_refused_in_strict_mode():
    """The mode the Lambda uses. `Contribute` is 100-500 and `Services` 49-350, so falling back to
    the product's price would publish the minimum for every variant - wrong for most of them."""
    row = {"id": CONTRIBUTE, "slug": "contribute", "name": "Contribute", "price": "100.00",
           "variants": [{"id": TEST_VARIANT, "label": "Rs500", "inStock": True}]}
    assert len(sync.desired_items([row])) == 1
    with pytest.raises(ValueError):
        sync.desired_items([row], require_variant_price=True)


def test_a_variant_price_wins_over_the_products(desired):
    items = sync.desired_items([{
        "id": CONTRIBUTE, "slug": "contribute", "name": "Contribute", "price": "100.00",
        "variants": [{"id": TEST_VARIANT, "label": "Rs500", "inStock": True,
                      "pricePaise": 50000}],
    }], require_variant_price=True)
    assert items[0]["price"] == "500.00"


# ── 5. the diff ──────────────────────────────────────────────────────────────


def _meta_row(item: dict, **overrides) -> dict:
    """An existing Meta item that matches one of ours, so only the overrides are a difference."""
    row = {"id": f"meta-{item['retailer_id'][-6:]}", **sync.meta_payload(item)}
    row.update(overrides)
    return row


def test_an_empty_meta_catalogue_means_create_everything(desired):
    plan = sync.diff(desired, [])
    assert plan.counts() == {"create": EXPECTED_ITEM_COUNT, "update": 0,
                             "retire": 0, "foreign": 0}
    assert plan.is_empty is False


def test_a_matching_catalogue_produces_an_empty_plan(desired):
    plan = sync.diff(desired, [_meta_row(item) for item in desired])
    assert plan.counts() == {"create": 0, "update": 0, "retire": 0, "foreign": 0}
    assert plan.is_empty is True


def test_a_formatting_difference_in_the_price_is_not_a_change(desired):
    """Meta can render a price as `Rs1,199.00`. Comparing renderings would report every item as
    changed, forever - so the comparison normalises to an amount first."""
    rows = [_meta_row(item, price=f"\u20b9{item['price']}") for item in desired]
    assert sync.diff(desired, rows).is_empty is True


def test_a_changed_field_lands_in_update_carrying_the_meta_id(desired):
    item = desired[0]
    rows = [_meta_row(i) for i in desired]
    rows[0]["availability"] = sync.OUT_OF_STOCK
    plan = sync.diff(desired, rows)
    assert plan.counts()["update"] == 1
    assert plan.update[0]["retailer_id"] == item["retailer_id"]
    assert plan.update[0]["meta_id"] == rows[0]["id"]


def test_a_REMOVED_variant_is_RETIRED_and_never_deleted(desired):
    """THE ASSERTION THIS FILE EXISTS FOR, alongside the item count.

    A customer's WhatsApp cart holds `product_retailer_id`. Delete the item and the hand-off
    cannot resolve the line at all, which fails at checkout - after the customer has committed.
    Out of stock is a state the whole pipeline already handles.

    `SyncPlan` has no delete bucket, so this is asserted on the plan's SHAPE as well as on the
    behaviour: there is nowhere for a delete to go.
    """
    # An IN-STOCK item, deliberately: the next test covers the already-out-of-stock case, which
    # is correctly skipped, and picking one of those here would pass for the wrong reason.
    removed = next(item for item in desired if item["availability"] == sync.IN_STOCK)
    kept = [item for item in desired if item is not removed]
    plan = sync.diff(kept, [_meta_row(item) for item in desired])

    assert plan.counts()["retire"] == 1
    assert plan.retire[0]["retailer_id"] == removed["retailer_id"]
    assert plan.retire[0]["availability"] == sync.OUT_OF_STOCK

    assert not hasattr(plan, "delete")
    assert "delete" not in {f for f in plan.__dataclass_fields__}
    rendered = json.dumps(plan.counts()) + json.dumps(plan.retire)
    for forbidden in ("delete", "DELETE", "remove"):
        assert forbidden not in rendered


def test_an_already_retired_item_is_not_retired_again(desired):
    """Re-sending it would be a write that changes nothing, and a plan that is never empty is a
    plan nobody reads."""
    gone = next(item for item in desired if item["availability"] == sync.IN_STOCK)
    kept = [item for item in desired if item is not gone]
    rows = [_meta_row(item) for item in desired]
    # Meta already shows it out of stock, which is exactly the state a previous retirement left.
    next(r for r in rows if r["retailer_id"] == gone["retailer_id"])["availability"] = (
        sync.OUT_OF_STOCK)
    plan = sync.diff(kept, rows)
    assert plan.counts()["retire"] == 0
    assert plan.is_empty is True


def test_a_foreign_retailer_id_is_reported_and_never_touched(desired):
    """A hand-made item from the catalog builder. Reported so it is visible, and in none of the
    three action buckets so nothing can be done to it."""
    rows = [_meta_row(item) for item in desired]
    rows.append({"id": "meta-hand-made", "retailer_id": "WD-PARTNER-UP",
                 "name": "Partner upgrade", "availability": sync.IN_STOCK})
    plan = sync.diff(desired, rows)

    assert plan.foreign == ["WD-PARTNER-UP"]
    assert plan.is_empty is True, "`foreign` is a report, not an action"
    touched = plan.create + plan.update + plan.retire
    assert all("WD-PARTNER-UP" != item.get("retailer_id") for item in touched)


def test_a_prefixed_but_malformed_id_is_foreign_rather_than_retired(desired):
    """Ours in intention, unidentifiable in fact. Modifying it blind could overwrite an item we
    cannot name, so it goes to the bucket that does nothing."""
    broken = f"{PREFIX}:not-a-uuid:also-not"
    rows = [{"id": "meta-broken", "retailer_id": broken}]
    plan = sync.diff(desired, rows)
    assert plan.foreign == [broken]
    assert plan.counts()["retire"] == 0


def test_the_plan_fingerprint_is_stable_under_reordering(desired):
    """So two log lines can be compared on one hash rather than by diffing two plans."""
    first = sync.diff(desired, [])
    second = sync.diff(list(reversed(desired)), [])
    assert first.fingerprint() == second.fingerprint()
    assert first.fingerprint() != sync.diff(desired[:-1], []).fingerprint()


# ── 6. the blockers ──────────────────────────────────────────────────────────


#: MEASURED from the native ProductsTable read (the 2026-10-15 fixture): every syncable product
#: carries an `imageRefs` image, so nothing is blocked.
EXPECTED_BLOCKED = []


def test_remaining_imageless_product_is_blocked_and_every_service_item_has_a_picture(
        native_products):
    """Pin the catalogue review gate to the native ProductsTable read.

    Meta rejects imageless items. Every syncable product in the 2026-10-15 ProductsTable read
    carries an image, the Request services product included, so all five service items have a
    picture. The expectation is written out so a future media change is reviewed rather than
    silently changing publish eligibility.
    """
    products = native_products
    desired = sync.desired_items(products, require_variant_price=True)
    assert sync.blockers(desired) == EXPECTED_BLOCKED
    assert len(EXPECTED_BLOCKED) == 0

    syncable = [p for p in products if sync.is_syncable(p)]
    assert len(syncable) == 9

    imageless = sorted(
        p["name"] for p in syncable
        if not str(p.get("image") or "").strip()
    )
    assert imageless == EXPECTED_BLOCKED

    pictured = [p for p in syncable if p["name"] not in EXPECTED_BLOCKED]
    assert len(pictured) == 9
    for product in pictured:
        assert product.get("image"), f"{product['name']} has no native catalog image"

    services = [i for i in desired
                if i["item_group_id"] == "df976a0a-f582-4535-b2e1-d532f348bd27"]
    assert len(services) == 5
    assert all(i.get("image_url") for i in services)

def test_an_item_with_an_image_is_not_blocked():
    items = sync.desired_items([{
        "id": TEST_PRODUCT, "slug": "x", "name": "X", "price": "1.00",
        "image": "https://wecare.digital/get/o/public/x.png",
        "variants": [{"id": TEST_VARIANT, "label": "Standard", "inStock": True}],
    }])
    assert sync.blockers(items) == []


# ── 7. no float, asserted on the AST ────────────────────────────────────────


def test_the_module_contains_no_float_literal_and_no_float_call():
    """R6.1, and the reason is specific rather than stylistic: `0.1 + 0.2` is not `0.3` in binary
    floating point, and a one-paise mismatch against a checkout total must fail closed.

    WALKS THE AST, NOT THE TEXT, because the comments that explain this rule necessarily contain
    the word `float` and a scan of the source would fail on its own documentation.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(f"float literal {node.value!r} at line {node.lineno}")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ("float", "round")):
            offenders.append(f"{node.func.id}() call at line {node.lineno}")
        if (isinstance(node, ast.Name) and node.id == "float"):
            offenders.append(f"reference to float at line {node.lineno}")
    assert not offenders, "; ".join(offenders)


def test_the_module_is_pure_at_import():
    """No boto3, no urllib, no os, no time. Every dependency is an argument.

    Asserted on the imports rather than on behaviour, because the failure mode is subtle: a module
    that reads one environment variable at import is no longer decidable offline, and the
    item-count assertion above would start depending on how the test process was launched.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported == {"__future__", "hashlib", "json", "re", "dataclasses", "decimal", "typing"}


def test_the_module_logs_nothing_at_all():
    """It is handed catalogue data and returns a plan. The cheapest proof it cannot leak anything
    is that it has no logger and no print."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "logger" not in names
    assert "print" not in names


def test_variant_artwork_and_public_product_link_survive_meta_projection():
    product = {
        "id": TEST_PRODUCT, "slug": "wecaredigital-services", "name": "Services",
        "price": "99.00", "image": "https://wecare.digital/get/o/public/shared.png",
        "variants": [{"id": TEST_VARIANT, "label": "Submit Request", "inStock": True,
                      "image": "https://wecare.digital/get/o/public/submit.png"}],
    }
    item = sync.desired_items([product])[0]
    assert item["image_url"] == "https://wecare.digital/get/o/public/submit.png"
    assert sync.meta_payload(item)["url"] == "https://wecare.digital/shop/wecaredigital-services/"
    previous = {**item, "url": "https://wecare.digital/"}
    assert len(sync.diff([item], [previous]).update) == 1


def test_native_meta_projection_respects_product_channel_flag_and_canonical_path():
    import copy
    import importlib.util
    name = "wecare_meta_catalog_sync_handler_channel_test"
    spec = importlib.util.spec_from_file_location(name, HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    rows = [
        {
            "id": TEST_PRODUCT,
            "title": "Published",
            "slug": "published",
            "status": "active",
            "metaEnabled": True,
            "canonicalPath": "/special/published/",
            "currency": "INR",
            "priceMinor": 50000,
            "imageRefs": ["https://wecare.digital/get/o/stream/media/m/wd-catalog-live/kiosk-4096.png"],
            "variants": [{
                "sku": TEST_VARIANT, "label": "Standard", "priceMinor": 50000,
                "inventory": 1,
            }],
        },
        {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "title": "Website only",
            "slug": "website-only",
            "status": "active",
            "metaEnabled": False,
            "currency": "INR",
            "priceMinor": 100,
            "imageRefs": ["https://wecare.digital/get/o/stream/media/m/wd-catalog-live/anew-4096.png"],
            "variants": [{
                "sku": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "label": "Standard", "priceMinor": 100, "inventory": 1,
            }],
        },
    ]
    projected = module._native_products(scanner=lambda: copy.deepcopy(rows))
    assert [row["name"] for row in projected] == ["Published"]
    desired = sync.desired_items(projected, require_variant_price=True)
    assert len(desired) == 1
    assert desired[0]["url"] == "https://wecare.digital/special/published/"


def test_request_variants_use_their_own_locked_catalog_artwork():
    product = {
        "id": sync.SERVICE_PRODUCT_ID,
        "name": "Request",
        "slug": "wecaredigital-services",
        "visible": True,
        "currency": "INR",
        "image": "https://example.invalid/product-fallback.png",
        "variants": [
            {"id": variant_id, "label": copy[0], "inStock": True, "pricePaise": copy[1]}
            for variant_id, copy in [
                ("e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b", ("Submit Request", 9900)),
                ("864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b", ("Request Amendment", 35000)),
                ("db166bc8-a763-41ec-9f65-0f718f18155a", ("Drop Docs", 35000)),
                ("dcff995e-448c-493a-9259-f6a82ccdc2b4", ("Vault", 4900)),
                ("8ee7e325-d772-4452-a993-5c79e927d42b", ("Request Pickup", 55000)),
            ]
        ],
    }
    items = sync.desired_items([product], require_variant_price=True)
    by_variant = {
        sync.parse_retailer_id(item["retailer_id"])[1]: item
        for item in items
    }
    assert len(by_variant) == 5
    for variant_id, expected_image in sync.SERVICE_ARTWORK_BY_VARIANT.items():
        assert by_variant[variant_id]["image_url"] == expected_image
        assert "/wd-catalog-live/" in expected_image
        assert expected_image.endswith("-4096.png")
