"""The committed Wix catalog snapshot is Catalog V3, credential-free, and secret-free.

Why this exists
---------------
`scripts/fetch-wix-catalog.js` produced `src/content/wix-catalog.json` from
`stores-reader/v1/products/query` until 2026-09-26. Three things were wrong with that,
and each one is guarded below because each was invisible:

1. **The endpoint was a compatibility shim.** This site runs Catalog V3 - Wix says so
   itself, returning HTTP 428 `CATALOG_V3_CALLING_CATALOG_V1_API` for a real V1 call.
   But `stores-reader/v1` keeps answering 200 on a V3 site, so the wrong version failed
   silently instead of loudly, while `wix-store/handler.py` read the same catalog through
   `stores/v3` in 17 places.

2. **It demanded an admin credential to read public prices.** The script required
   `WIX_API_KEY`, an account-scoped bearer token, and `wecare/wix/headless-api-key` holds
   **0 versions** - so it could not run at all. The catalog is now read with an anonymous
   visitor token minted from the PUBLIC `WIX_CLIENT_ID`, which is the scope a storefront
   page has. Least privilege, and it works with nothing to provision.

3. **`variantCount` was silently wrong.** The V1 reader did not return the variants
   array, so every product recorded `variantCount: 0`. Measured after the port:
   `merchandise` has **10** variants and the other six have 1. A snapshot that reports
   zero variants for a product with ten is worse than one that omits the field.

Verified at the port, old snapshot against new: all seven prices identical both
numerically and as formatted strings, `descriptionHtml` byte-identical on all seven, and
`name`/`visible`/`inStock`/`optionCount`/`mediaCount` unchanged. The only intended
differences are the schema changes asserted here.

These tests read the committed file and the committed script. They make no network call,
so they cannot prove the snapshot is *current* - that is what re-running the script is
for. They prove it has the right shape and leaks nothing.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SNAPSHOT = REPO / "src/content/wix-catalog.json"
SCRIPT = REPO / "scripts/fetch-wix-catalog.js"
WIX_CONFIG = REPO / "src/config/wix.ts"


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text())


@pytest.fixture(scope="module")
def script() -> str:
    return SCRIPT.read_text()


@pytest.fixture(scope="module")
def code() -> str:
    """The script with comments removed.

    Necessary, not fussiness: the header legitimately explains what the old V1 endpoint
    was and why it went, so a naive substring check on the whole file matches the
    explanation and fails. Asserting on prose instead of code would mean the guard breaks
    whenever someone documents the history properly - the opposite of what it is for.

    Block comments are stripped first. Line comments are matched only when `//` is not
    preceded by a colon, so `https://www.wixapis.com` inside a string survives; stripping
    from a bare `//` would truncate every URL and silently empty the code.
    """
    text = re.sub(r"/\*.*?\*/", "", SCRIPT.read_text(), flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", text)


# --- the snapshot -----------------------------------------------------------------


def test_snapshot_declares_catalog_v3(snapshot):
    assert snapshot.get("catalogVersion") == "V3"
    assert "stores/v3" in snapshot.get("source", ""), (
        "the snapshot does not record which API produced it, so a silent regression to "
        "the V1 compatibility reader would leave no trace"
    )


def test_snapshot_records_that_no_credential_was_used(snapshot):
    assert "visitor token" in snapshot.get("source", ""), (
        "source must state the auth scope; an admin-key snapshot can contain hidden "
        "products and is therefore a different artifact"
    )


def test_snapshot_carries_no_credential_or_tenant_identifier(snapshot):
    """The output is committed and ends up in a public bundle.

    Site and account ids are tenant identifiers with no reason to ship, and a token has
    obvious reason not to.
    """
    raw = SNAPSHOT.read_text()
    for forbidden, why in (
        ("IST.", "a Wix API key is an IST.-prefixed JWT"),
        ("access_token", "a visitor token must never be written out"),
        ("refresh_token", "a refresh token must never be written out"),
        ("15f02319-40ff-4288-b8e6-69c791adae5e", "the account id is a tenant identifier"),
        ("fcd82f0c-9572-49c7-acfb-88fb05042ece", "the site id is a tenant identifier"),
    ):
        assert forbidden not in raw, f"{forbidden} is in the snapshot: {why}"


def test_prices_are_decimal_strings_not_floats(snapshot):
    """V3 returns money as a string on purpose; keeping it a string preserves it exactly.

    A float here would be a decision nobody made, inherited from a JSON parser.
    """
    for product in snapshot["products"]:
        price = product["price"]
        assert isinstance(price, str), (
            f"{product['slug']}: price is {type(price).__name__}, expected a decimal "
            f"string. Coercing money to float is how rounding defects start."
        )
        try:
            Decimal(price)
        except InvalidOperation:
            pytest.fail(f"{product['slug']}: price {price!r} is not a valid decimal")


def test_price_range_is_preserved(snapshot):
    """V3 prices are a range. Collapsing to one value misreports variant pricing."""
    for product in snapshot["products"]:
        assert "priceMax" in product, f"{product['slug']} lost the price range"
        assert Decimal(product["price"]) <= Decimal(product["priceMax"])


def test_the_v1_only_fields_are_gone(snapshot):
    """Fields with no V3 equivalent must be absent, not present and empty.

    `discountedPrice` is the dangerous one: V3's `compareAtPriceRange` is the opposite
    idea - the higher struck-through "was" price - so carrying the old name forward would
    invert the meaning at some future call site.
    """
    for product in snapshot["products"]:
        for gone in ("discountedPrice", "collectionIds", "sku"):
            assert gone not in product, (
                f"{product['slug']} still carries the V1 field {gone!r}"
            )


def test_v3_fields_are_present(snapshot):
    required = {
        "categoryIds", "mainCategoryId", "priceMax", "compareAtPrice",
        "infoSectionCount", "modifierCount", "variantCount", "productUrl",
        "currency", "formattedPrice", "descriptionHtml", "inStock",
    }
    for product in snapshot["products"]:
        missing = required - set(product)
        assert not missing, f"{product['slug']} is missing {sorted(missing)}"


def test_product_type_is_upper_case(snapshot):
    """V3 returns PHYSICAL where V1 returned physical.

    Asserted because a case-sensitive comparison against the old lowercase value would
    silently stop matching.
    """
    for product in snapshot["products"]:
        assert product["productType"] == product["productType"].upper()


def test_variant_counts_are_not_all_zero(snapshot):
    """The specific defect the port fixed.

    Under the V1 reader every product reported 0 variants. `merchandise` has 10.
    """
    counts = {p["slug"]: p["variantCount"] for p in snapshot["products"]}
    assert any(c > 0 for c in counts.values()), (
        f"every product reports 0 variants, which is the V1 reader's signature: {counts}"
    )
    assert all(c >= 1 for c in counts.values()), (
        f"a product with no variants at all is not a shape V3 produces: {counts}"
    )


def test_the_description_projection_is_read_from_plain_description(snapshot):
    """Guards the plainDescription vs description trap.

    In V3 `description` is Ricos rich-content NODES and `plainDescription` is the HTML
    string. Reading `description` would put a JSON blob in the UI; reading neither leaves
    every product blank.

    RELAXED FROM "EVERY PRODUCT" TO "AT LEAST ONE", 2026-10-04, for catalogue auto-sync, and
    both halves of the change matter:

      - A PRODUCT WITH NO DESCRIPTION IS A REAL SHAPE, not a fetch bug. It is how a newly
        created Wix product looks before anybody writes copy for it, and `1-test-product` and
        `contribute` are both live in that state today. Requiring copy on every row made a
        legitimate live product fail this suite, and
        `.github/workflows/catalogue-sync.yml` now commits a refreshed snapshot on a schedule -
        so the owner adding a product in Wix would turn CI red with no code change behind it.
        That is the manual step B2 exists to remove.
        `src/content/shop.ts` already synthesises a safe name-based tagline and body for an
        empty description, so the PAGE renders completely; `src/test/ShopCatalogue.test.tsx`
        asserts every product has a non-empty tagline, which is the invariant that protects the
        reader.
      - THE TRAP IS STILL GUARDED, and that is what "at least one" is for. The two failures
        this test was written against are both catalogue-WIDE, not per-product: dropping
        PLAIN_DESCRIPTION from the field projection empties EVERY description, and reading
        `description` puts Ricos JSON in EVERY one. Either still fails here. A single product
        the owner has not written copy for does not.
    """
    described = [p for p in snapshot["products"] if p["descriptionHtml"].strip()]
    assert described, (
        "no product carries a description at all. That is the field-projection failure, not an "
        "unwritten product: V3 omits plainDescription unless PLAIN_DESCRIPTION is in FIELDS."
    )
    for product in described:
        assert not product["descriptionHtml"].lstrip().startswith("{"), (
            f"{product['slug']} description looks like Ricos JSON, not HTML - the "
            f"mapping read `description` instead of `plainDescription`"
        )


def test_slugs_are_unique_and_sorted(snapshot):
    slugs = [p["slug"] for p in snapshot["products"]]
    assert len(set(slugs)) == len(slugs), "duplicate slugs"
    assert slugs == sorted(slugs), "unsorted, so the committed file churns on reorder"


def test_product_count_matches_the_array(snapshot):
    assert snapshot["productCount"] == len(snapshot["products"])


# --- the script -------------------------------------------------------------------


def test_comment_stripping_leaves_real_code(code):
    """Guards the guard.

    If the `code` fixture ever strips too much, every assertion below passes vacuously -
    a substring is trivially absent from an empty string. So prove the code survived.
    """
    assert "async function main" in code

    # Counting the host's occurrences rather than testing `"https://www.wixapis.com" in
    # code`. Same intent -- prove the URL survived comment-stripping so the assertions
    # below are not vacuous -- but a bare substring test against a URL is the shape of
    # `py/incomplete-url-substring-sanitization`, which fires because that shape is how
    # people write BROKEN origin checks (`"good.com" in url` passes for
    # `evil.com/?x=good.com`). Nothing here validates a URL, so the alert was a false
    # positive about the intent while being a fair complaint about the idiom. Counting is
    # also the stronger assertion: it fails if the host disappears AND if a second,
    # unexpected endpoint appears.
    assert code.count("www.wixapis.com") >= 1, (
        "the Wix host was stripped by comment removal, so the code-level assertions "
        "below are vacuous"
    )
    assert len(code) > 1500


def test_script_does_not_require_an_admin_key(code):
    """The whole point of the rewrite.

    `WIX_API_KEY` may appear in prose explaining why it is no longer needed, but not as a
    value the code reads.
    """
    assert "WIX_API_KEY" not in code, (
        "the script reads WIX_API_KEY again. An account-scoped admin bearer token is not "
        "needed to read public product names and prices, and that secret holds 0 "
        "versions so the script would not run."
    )


def test_script_uses_the_v3_search_endpoint(code):
    assert "/stores/v3/products/search" in code
    assert "stores-reader/v1" not in code, (
        "the V1 compatibility reader is back in the code. It answers 200 on a V3 site, "
        "so this regression is silent."
    )


def test_script_uses_cursor_paging_not_offset(code):
    """An offset loop against V3 returns page 1 forever."""
    assert "cursorPaging" in code
    assert not re.search(r"\boffset\b\s*[:=]", code), (
        "offset paging found; V3 dropped it"
    )


def test_script_reads_the_client_id_from_the_committed_config(code):
    """Not a second hardcoded copy, which would eventually drift."""
    assert "WIX_CLIENT_ID" in code
    assert "wix.ts" in code
    client_id = re.search(
        r"export const WIX_CLIENT_ID = '([^']+)'", WIX_CONFIG.read_text())
    assert client_id, "WIX_CLIENT_ID missing from src/config/wix.ts"
    assert client_id.group(1) not in code, (
        "the client id is hardcoded in the script as well as the config; one of the two "
        "will go stale"
    )


def test_script_requests_the_fields_v3_omits_by_default(code):
    """V3 returns no currency, description, url or category info unless asked.

    Without these the snapshot looks populated but renders blank prices and descriptions.
    """
    for field in ("PLAIN_DESCRIPTION", "CURRENCY", "URL", "DIRECT_CATEGORIES_INFO"):
        assert field in code, f"field projection {field} is not requested"


def test_script_refuses_to_write_an_empty_catalog(code):
    """Same reasoning as the sitemap guard: an empty result is a scope or query problem
    far more often than a real change, so the existing snapshot is left untouched."""
    assert "returned 0 products" in code


def test_script_never_writes_the_token_into_the_output(code):
    """The token is minted in memory. It must not reach the snapshot object.

    String CONTENTS are stripped before checking, because the `source` value legitimately
    reads "anonymous visitor token" - that is a description of the auth scope, not a
    reference to the variable. The thing that would actually leak is an identifier, so
    that is what is asserted on.

    The empirical counterpart is `test_snapshot_carries_no_credential_or_tenant_identifier`,
    which scans the committed output itself. This one catches the mistake at the source.
    """
    snapshot_literal = re.search(r"const snapshot = \{(.*?)\n  \};", code, re.S)
    assert snapshot_literal, "could not locate the snapshot object literal"
    body = re.sub(r"'[^']*'", "''", snapshot_literal.group(1))

    for identifier in ("token", "clientId", "Authorization", "access_token"):
        assert not re.search(rf"\b{re.escape(identifier)}\b", body), (
            f"the snapshot literal references {identifier!r} outside a string, so the "
            f"credential would be written to a committed file"
        )
