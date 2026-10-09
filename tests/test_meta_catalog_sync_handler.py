"""`wecare-meta-catalog-sync`: the plan is computed, and NOTHING is written to Meta.

PHASE W, FEAT-001. The property under test is a conjunction, and the second half is the one worth
the file:

    a trigger (webhook invoke or schedule)   -> the full catalogue is re-read and a plan logged
    either gate closed                       -> ZERO Meta write calls are even CONSTRUCTED

The Meta catalogue is customer-visible: an item created here appears in WhatsApp. So every case
below asserts on the recorded CALLS rather than on the response - a function that reported
`dryRun: true` after already upserting would pass a response-only test. `writes == []` is the
assertion.

NO NETWORK AND NO AWS, ANYWHERE. The three injection points (`wix_requester`, `graph_requester`,
`secret_reader`) are keyword-only and resolve inside the handler, so a fake reaches them. They are
deliberately NOT parameter defaults: a default is bound at definition time, and in
`wix-catalog-webhook` that exact mistake made a test meant to simulate a missing credential read
the live one from Secrets Manager instead and report success.
"""

from __future__ import annotations

import ast
from decimal import Decimal
import importlib.util
import json
import logging
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils.ecommerce import meta_catalog_sync as sync  # noqa: E402

HANDLER = ROOT / "amplify/functions/ecommerce/meta-catalog-sync/handler.py"
SNAPSHOT = ROOT / "src/content/wix-catalog.json"

#: A token-SHAPED placeholder, assembled so the file contains no issuer-prefixed literal. Its only
#: job is to be non-empty: nothing in this file asserts anything about its value.
FAKE_TOKEN = "not-a-real-" + "meta-token-value"

MODULE_NAME = "wecare_meta_catalog_sync_handler"


def _load():
    """Load the handler BY PATH under a unique module name, never `import handler`.

    This repo has 64 files called `handler.py`, so `sys.modules["handler"]` is one slot contended
    by all of them, and a module-level `import handler` binds whichever got there first.
    `tests/test_handler_import_isolation.py` is the gate that caught that.
    """
    spec = importlib.util.spec_from_file_location(MODULE_NAME, HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


receiver = _load()


@pytest.fixture(autouse=True)
def gates_closed(monkeypatch):
    """Both flags ABSENT in this process, which exercises the handler's OWN defaults.

    Not the same thing as the deployed configuration, and the difference is deliberate: the
    function ships with `META_CATALOG_SYNC_ENABLED="false"` and `META_CATALOG_SYNC_DRY_RUN="true"`
    written out explicitly, so an audit can tell a closed gate from an unconfigured one. Both
    spellings are off - `_enabled()` requires the value to be in `_TRUE` - and
    `test_the_manifest_records_both_gates_at_their_safe_values` is what pins the shipped pair.
    Deleting them here means the code is proven safe even if a deploy ever drops a key.

    Autouse, so a test has to opt in to an enabling value explicitly and no test can inherit one
    from the developer's shell.
    """
    monkeypatch.delenv("META_CATALOG_SYNC_ENABLED", raising=False)
    monkeypatch.delenv("META_CATALOG_SYNC_DRY_RUN", raising=False)
    monkeypatch.delenv("META_CATALOG_ID", raising=False)


@pytest.fixture(scope="module")
def snapshot_products():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["products"]


class FakeWix:
    """Serves the committed snapshot through the two live V3 endpoints, with their own envelopes.

    Rebuilding the live payload shape (`actualPriceRange.minValue.amount`, `plainDescription`,
    `media.itemsInfo.items`, and variants from a SECOND endpoint) rather than handing the handler
    the slim snapshot directly is the point: `_slim_product` and `_wix_variants` are the code that
    would break on a shape change, so a fake that skipped them would test nothing.
    """

    def __init__(self, products):
        self.products = products
        self.calls: list = []

    def __call__(self, endpoint, body):
        self.calls.append({"endpoint": endpoint, "body": body})
        if endpoint == receiver.WIX_SEARCH_ENDPOINT:
            return {"products": [{
                "id": p["id"],
                "name": p["name"],
                "slug": p["slug"],
                "visible": p.get("visible", True),
                "currency": p.get("currency") or "INR",
                "plainDescription": p.get("descriptionHtml") or "",
                "actualPriceRange": {"minValue": {"amount": p.get("price")}},
                "media": {"itemsInfo": {"items": [
                    {"image": {"url": v["image"]}}
                    for v in p.get("variants") or [] if v.get("image")
                ] or ([{"image": {"url": p["image"]}}] if p.get("image") else [])}},
            } for p in self.products]}
        if endpoint == receiver.WIX_VARIANTS_ENDPOINT:
            rows = []
            for product in self.products:
                for variant in product.get("variants") or []:
                    rows.append({
                        "variantId": variant["id"],
                        "visible": True,
                        "productData": {"productId": product["id"]},
                        "optionChoices": [
                            {"optionChoiceNames": {"choiceName": variant["label"]}}],
                        "inventoryStatus": {"inStock": variant.get("inStock") is True},
                        # The ONLY source of a per-variant price, which is why the handler makes
                        # this second call at all.
                        "price": {"actualPrice": {"amount": (
                            format(Decimal(variant["pricePaise"]) / 100, ".2f")
                            if "pricePaise" in variant else product.get("price"))}},
                        "media": {"image": {"url": variant["image"]}} if variant.get("image") else {},
                    })
            return {"variants": rows}
        raise AssertionError(f"unexpected Wix endpoint: {endpoint}")


class FakeGraph:
    """Records every Graph call. `writes == []` is what most of this file asserts."""

    def __init__(self, items=None, error=None):
        self.items = list(items or [])
        self.error = error
        self.calls: list = []

    def __call__(self, path, *, method="GET", params=None, payload=None,
                 token="", app_secret=""):
        self.calls.append({"path": path, "method": method, "params": dict(params or {}),
                           "payload": payload})
        if self.error:
            return {"error": self.error}
        if method == "GET":
            return {"data": self.items, "paging": {}}
        return {"handles": ["batch-1"]}

    @property
    def writes(self):
        """Anything that is not a read. A write is a method other than GET or a payload."""
        return [call for call in self.calls
                if call["method"] != "GET" or call["payload"] is not None]

    @property
    def reads(self):
        return [call for call in self.calls if call not in self.writes]


def reader_for(token=FAKE_TOKEN, *, field="access_token"):
    """A secret reader, and a record of whether it was called."""
    calls: list = []

    def read(secret_id):
        calls.append(secret_id)
        return {field: token} if token else {}

    read.calls = calls
    return read


def run(wix, graph, reader=None, event=None):
    return receiver.handler(
        event if event is not None else {"source": "wix-webhook", "entityId": "prod-1"},
        None, wix_requester=wix, graph_requester=graph,
        secret_reader=reader or reader_for())


# ── 1. the gates ─────────────────────────────────────────────────────────────


def test_with_the_enable_flag_ABSENT_nothing_is_written(snapshot_products):
    """The shipped configuration. 24 items to create, and not one request constructed."""
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = run(wix, graph)

    assert answer["ok"] is True
    assert answer["enabled"] is False
    assert answer["dryRun"] is True
    assert answer["applied"] == 0
    assert answer["counts"] == {"create": 24, "update": 0, "retire": 0, "foreign": 0}
    assert graph.writes == []


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "FLASE", "maybe", "True "])
def test_only_an_explicit_true_enables_anything(snapshot_products, monkeypatch, value):
    """Absent, empty or anything unrecognised is OFF. `"True "` is in the list because it is
    stripped and lowercased before the comparison, so it DOES enable - which is why it is
    asserted rather than assumed; a surprise in either direction here is a production surprise.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", value)
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = run(wix, graph)
    assert answer["enabled"] is (value.strip().lower() == "true")
    # Dry run is still on regardless, so nothing is written either way.
    assert answer["dryRun"] is True
    assert graph.writes == []


def test_with_the_enable_flag_ON_and_dry_run_DEFAULTED_still_nothing_is_written(
        snapshot_products, monkeypatch):
    """The two gates are independent. Flipping one is not enough, which is the point of two."""
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = run(wix, graph)

    assert answer["enabled"] is True
    assert answer["dryRun"] is True
    assert answer["applied"] == 0
    assert graph.writes == []


@pytest.mark.parametrize("value", ["", "true", "1", "yes", "flase", "FALSE "])
def test_dry_run_switches_off_only_on_an_explicit_false(snapshot_products, monkeypatch, value):
    """Asymmetric with the enable flag ON PURPOSE: a typo must leave dry run ON.

    `"FALSE "` does switch it off - it is stripped and lowercased - and is included so the
    boundary is written down rather than discovered.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", value)
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = run(wix, graph)
    still_dry = value.strip().lower() not in ("false", "0", "no", "off")
    assert answer["dryRun"] is still_dry
    assert (graph.writes == []) is still_dry


def test_both_gates_open_is_the_only_path_that_writes(snapshot_products, monkeypatch):
    """Recorded so the gate's effect is proven rather than asserted by its absence.

    NOTHING IN THE REPOSITORY SETS THESE VALUES: `config/lambda-env-manifest.json` carries both at
    their safe defaults and no provisioner or deploy script changes them. This test opens them in
    its own process only, against a fake.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = run(wix, graph)

    assert answer["dryRun"] is False
    assert answer["applied"] == 24
    assert len(graph.writes) == 1
    write = graph.writes[0]
    assert write["method"] == "POST"
    assert write["path"].endswith("/items_batch")
    methods = {request["method"] for request in write["payload"]["requests"]}
    assert methods == {"UPDATE"}, "there is no DELETE method anywhere in this function"


def test_manifest_and_provisioner_preserve_owner_scoped_rollout():
    manifest = json.loads((ROOT / "config/lambda-env-manifest.json").read_text())
    entry = manifest["functions"]["wecare-meta-catalog-sync"]
    provisioner = _load_provisioner()
    for key in ("META_CATALOG_SYNC_ENABLED", "META_CATALOG_SYNC_DRY_RUN",
                "META_CATALOG_SYNC_VARIANT_IDS", "META_CATALOG_SYNC_FORCE_OUT_OF_STOCK"):
        assert entry[key] == provisioner.ENVIRONMENT[key]
    assert entry["META_CATALOG_SYNC_ENABLED"] == "false"
    assert entry["META_CATALOG_SYNC_DRY_RUN"] == "true"
    assert entry["META_CATALOG_SYNC_FORCE_OUT_OF_STOCK"] == "true"
    assert set(entry["META_CATALOG_SYNC_VARIANT_IDS"].split(",")) == {
        "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b", "864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b", "db166bc8-a763-41ec-9f65-0f718f18155a", "dcff995e-448c-493a-9259-f6a82ccdc2b4"}


def _load_provisioner():
    """`scripts/provision_meta_catalog_sync.py` by path, under its own module name.

    Imported lazily inside the one test that needs it: the script imports boto3 at module scope,
    and making that a cost every other test in this file pays would be a change to this file's
    "no network and no AWS, anywhere" property for no benefit. Loading it creates no client.
    """
    path = ROOT / "scripts/provision_meta_catalog_sync.py"
    spec = importlib.util.spec_from_file_location(
        "wecare_provision_meta_catalog_sync_for_manifest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_an_empty_plan_writes_nothing_even_with_both_gates_open(
        snapshot_products, monkeypatch):
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    wix = FakeWix(snapshot_products)
    desired = sync.desired_items(
        json.loads(SNAPSHOT.read_text(encoding="utf-8"))["products"])
    existing = [{"id": f"m{n}", **sync.meta_payload(item)}
                for n, item in enumerate(desired)]
    graph = FakeGraph(items=existing)

    answer = run(wix, graph)
    assert answer["counts"] == {"create": 0, "update": 0, "retire": 0, "foreign": 0}
    assert answer["applied"] == 0
    assert graph.writes == []


# ── 2. a foreign item is reported and never sent ─────────────────────────────


def test_a_foreign_retailer_id_is_reported_and_never_included_in_any_request(
        snapshot_products, monkeypatch):
    """The Meta catalogue is also edited by hand through `catalog-builder.tsx` - the live SKU
    `htlu35lrs1` is cited in `inbound-whatsapp-handler`. A sync that tidied up what it did not
    recognise would delete someone's work, so a foreign id appears in the report and in no
    request, with both gates open.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    wix = FakeWix(snapshot_products)
    graph = FakeGraph(items=[
        {"id": "meta-hand-made", "retailer_id": "WD-PARTNER-UP", "name": "Partner upgrade",
         "availability": "in stock"},
        {"id": "meta-sku", "retailer_id": "htlu35lrs1", "name": "A hand-made item",
         "availability": "in stock"},
    ])

    answer = run(wix, graph)

    assert answer["counts"]["foreign"] == 2
    assert answer["counts"]["retire"] == 0
    rendered = json.dumps([call["payload"] for call in graph.writes])
    assert "WD-PARTNER-UP" not in rendered
    assert "htlu35lrs1" not in rendered


# ── 3. the credential ────────────────────────────────────────────────────────


def test_the_secret_is_read_INSIDE_the_handler_and_not_at_import(monkeypatch):
    """A module-scope read is cached for the life of a warm sandbox, so a rotation would not take
    effect until every sandbox recycled - the defect fixed in `payments/razorpay-webhook` on
    2026-09-19.

    Proven by importing the module with a `boto3.client` factory that RAISES: the import has to
    succeed, which it can only do if no client is constructed at module scope.
    """
    import boto3

    def exploding(*args, **kwargs):
        raise AssertionError("boto3.client must not be called at import time")

    monkeypatch.setattr(boto3, "client", exploding)
    spec = importlib.util.spec_from_file_location(f"{MODULE_NAME}_reimport", HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)          # must not raise
    assert module.META_TOKEN_SECRET == "wecare/meta-system-user-token"


def test_the_reader_is_called_once_per_invocation(snapshot_products):
    reader = reader_for()
    run(FakeWix(snapshot_products), FakeGraph(), reader)
    assert reader.calls == ["wecare/meta-system-user-token"]


def test_a_missing_token_refuses_and_reads_nothing(snapshot_products):
    """Fail closed. A sync that cannot authenticate must do nothing - not a partial read, which
    would look like an empty Meta catalogue and plan 24 creates.
    """
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = run(wix, graph, reader_for(token=""))

    assert answer["ok"] is False
    assert answer["reason"] == "unconfigured"
    assert answer["dryRun"] is True
    assert graph.calls == []
    assert wix.calls == []


def test_a_secret_read_failure_is_a_refusal_rather_than_a_crash(snapshot_products, monkeypatch):
    """`_read_secret` returns `{}` on any failure, so the real body runs here and its own except
    clause is the thing under test. Patching `_read_secret` would be testing the test."""
    import boto3

    def exploding(*args, **kwargs):
        raise RuntimeError("ResourceNotFoundException")

    monkeypatch.setattr(boto3, "client", exploding)
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = receiver.handler({"source": "schedule"}, None,
                              wix_requester=wix, graph_requester=graph)

    assert answer["ok"] is False
    assert answer["reason"] == "unconfigured"
    assert graph.writes == []


# ── 4. the read is never narrowed, and a read failure never becomes a write ──


def test_a_webhook_invoke_and_a_schedule_are_treated_identically(snapshot_products):
    """A verified event means "the catalogue moved", and re-reading the whole thing is the right
    answer whatever the envelope said - the same reason `wix-catalog-webhook` ignores `entityId`.
    So a change in Wix's event shape can cost a log field and can never cost a missed item.
    """
    outcomes = []
    for event in [
        {"source": "wix-webhook", "entityId": "prod-1"},
        {"source": "aws.events", "detail-type": "Scheduled Event", "detail": {}},
        {},
        None,
        {"source": "wix-webhook"},
    ]:
        wix, graph = FakeWix(snapshot_products), FakeGraph()
        answer = run(wix, graph, event=event)
        outcomes.append(answer["counts"])
        # The entity id must not reach the Wix request as a filter.
        search = next(c for c in wix.calls if c["endpoint"] == receiver.WIX_SEARCH_ENDPOINT)
        assert "prod-1" not in json.dumps(search["body"])
    assert outcomes == [outcomes[0]] * len(outcomes)


def test_a_wix_failure_does_not_become_a_write(snapshot_products, monkeypatch):
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")

    def boom(endpoint, body):
        raise OSError("connection reset")

    graph = FakeGraph()
    answer = run(boom, graph)
    assert answer["ok"] is False
    assert answer["reason"] == "read_failed"
    assert answer["dryRun"] is True
    assert graph.writes == []


def test_a_META_read_failure_does_not_become_a_write(snapshot_products, monkeypatch):
    """The dangerous direction. A short or failed read of the existing catalogue makes every item
    look absent, so a tolerated failure would plan - and with both gates open, send - 24 creates
    against a catalogue that already has them.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    wix = FakeWix(snapshot_products)
    graph = FakeGraph(error={"status": 500})

    answer = run(wix, graph)
    assert answer["ok"] is False
    assert answer["reason"] == "read_failed"
    assert graph.writes == []


def test_a_variant_without_a_price_refuses_rather_than_publishing_the_products(
        snapshot_products, monkeypatch):
    """`require_variant_price=True` on the live path. `Contribute` is 100-500 and
    `WECARE.DIGITAL Services` 49-350, so the product-level price is the minimum and would be wrong
    for most variants - a wrong price in a customer-visible catalogue, not a cosmetic defect.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")

    class Priceless(FakeWix):
        def __call__(self, endpoint, body):
            result = super().__call__(endpoint, body)
            if endpoint == receiver.WIX_VARIANTS_ENDPOINT:
                for row in result["variants"]:
                    row.pop("price", None)
            return result

    graph = FakeGraph()
    answer = run(Priceless(snapshot_products), graph)
    assert answer["ok"] is False
    assert answer["reason"] == "read_failed"
    assert graph.writes == []


# ── 5. the log line ──────────────────────────────────────────────────────────


def test_the_plan_log_line_carries_the_counts_and_no_credential(snapshot_products, monkeypatch):
    """One structured line. Every field is a public commerce identifier or a count - product ids,
    retailer ids and catalog ids are public, and there is no personal data on this path, so
    nothing is masked and nothing needs to be.
    """
    lines = []
    monkeypatch.setattr(receiver.logger, "info", lambda line: lines.append(line))
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    run(wix, graph)

    planned = next(json.loads(line) for line in lines
                   if json.loads(line).get("event") == "meta_catalog_sync_planned")
    assert planned["catalogId"] == "1457045652952851"
    assert planned["source"] == "wix-webhook"
    assert planned["entityId"] == "prod-1"
    assert planned["create"] == 24
    assert planned["blocked"] == 9  # The service product now has verified artwork.
    assert "WECARE.DIGITAL Services" not in planned["blockedProducts"]
    assert planned["enabled"] is False
    assert planned["dryRun"] is True
    assert planned["planHash"]
    for line in lines:
        assert FAKE_TOKEN not in line


def test_the_target_catalogue_is_configuration_and_not_a_literal(snapshot_products, monkeypatch):
    """Another catalog must be reachable without a code change (plan D3).

    The default is now the ONE shared `wecare_shop` catalog `1457045652952851`, used by both
    WABAs. The id below is arbitrary and appears nowhere in the code path, so seeing it come back
    as the plan target AND reach the Graph read path is what proves `META_CATALOG_ID` is
    configuration rather than a literal.
    """
    monkeypatch.setenv("META_CATALOG_ID", "9999999999999999")
    wix, graph = FakeWix(snapshot_products), FakeGraph()
    answer = run(wix, graph)
    assert answer["catalogId"] == "9999999999999999"
    assert graph.reads[0]["path"].startswith("9999999999999999/")


# ── 6. structural guarantees, asserted by AST ───────────────────────────────


def test_no_secret_appears_in_a_logging_expression():
    """Not "is not logged" - must not APPEAR in the expression.

    CodeQL's `py/clear-text-logging-sensitive-data` tracks taint across function boundaries and has
    already failed this build twice over a ternary on a key's truthiness. Reducing a secret to a
    boolean does not launder it, so no logger call here may mention a token or a secret value at
    all.
    """
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if not (isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue
        rendered = ast.dump(node)
        for forbidden in ("'token'", "id='token'", "'app_secret'", "appsecret_proof",
                          "'access_token'", "'SecretString'"):
            assert forbidden not in rendered, f"a logger call references {forbidden}"


def test_no_credential_reading_function_is_a_default_argument():
    """A default argument is bound at DEFINITION time, so patching the module attribute would have
    no effect - and in `wix-catalog-webhook` that made a test meant to simulate a missing GitHub
    token read the real credential from Secrets Manager and report success."""
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        defaults = list(node.args.defaults) + [
            d for d in node.args.kw_defaults if d is not None]
        for default in defaults:
            assert not (isinstance(default, ast.Name) and default.id.startswith("_read")), (
                f"{node.name} binds {default.id} as a default argument")


def test_boto3_is_not_imported_at_module_scope():
    """It is imported INSIDE `_read_secret` on purpose, so importing this handler costs no AWS
    client and no credential resolution."""
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "boto3" not in imported


def test_the_handler_contains_no_delete_verb_at_all():
    """A retired item is an availability change, never a delete, because a customer's WhatsApp
    cart holds the retailer id and a deleted item cannot be resolved at checkout.

    WALKS THE AST, not the text: the comments that explain this rule necessarily contain the word
    `delete`, so a substring scan of the file would fail on its own documentation.
    """
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"), filename=str(HANDLER))
    code_strings = []
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            code_strings.append(node.attr)
        elif isinstance(node, ast.Name):
            code_strings.append(node.id)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docstrings):
            code_strings.append(node.value)

    haystack = "\n".join(code_strings).lower()
    for forbidden in ("delete", "destroy"):
        assert forbidden not in haystack, f"the sync must not reference {forbidden} in code"


def test_the_handler_declares_no_graph_version_of_its_own():
    """`lambda_utils.meta_version` is the one source; `tests/test_meta_version.py` enforces it
    fleet-wide and this asserts it at the point of introduction rather than two files away."""
    text = HANDLER.read_text(encoding="utf-8")
    assert "from lambda_utils.meta_version import" in text
    assert "META_API_VERSION =" not in text
    assert "graph.facebook.com/v" not in text


def test_wix_variant_media_is_preserved_for_each_meta_item():
    product_id = "df976a0a-f582-4535-b2e1-d532f348bd27"
    rows = [
        {"variantId": "e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b",
         "productData": {"productId": product_id},
         "optionChoices": [{"optionChoiceNames": {"choiceName": "Submit Request"}}],
         "price": {"actualPrice": {"amount": "99.00"}},
         "media": {"image": {"url": "https://static.wixstatic.com/media/submit.png"}}},
        {"variantId": "dcff995e-448c-493a-9259-f6a82ccdc2b4",
         "productData": {"productId": product_id},
         "optionChoices": [{"optionChoiceNames": {"choiceName": "Vault"}}],
         "price": {"actualPrice": {"amount": "49.00"}},
         "media": {"url": "https://static.wixstatic.com/media/vault.png"}},
    ]
    variants = receiver._wix_variants(lambda endpoint, body: {"variants": rows}, [product_id])
    items = sync.desired_items([{"id": product_id, "slug": "wecaredigital-services",
                                "variants": variants[product_id]}], require_variant_price=True)
    assert [i["image_url"] for i in items] == [
        "https://static.wixstatic.com/media/submit.png",
        "https://static.wixstatic.com/media/vault.png"]
    assert [i["price"] for i in items] == ["99.00", "49.00"]
    assert [i["url"] for i in items] == ["https://wecare.digital/submit-request/", "https://wecare.digital/vault/"]


def test_choice_artwork_overrides_stale_variant_index_media():
    product_id = "df976a0a-f582-4535-b2e1-d532f348bd27"
    variant_id = "dcff995e-448c-493a-9259-f6a82ccdc2b4"
    def request(endpoint, body):
        if endpoint == receiver.WIX_SEARCH_ENDPOINT:
            return {"products": [{
                "id": product_id, "slug": "wecaredigital-services",
                "media": {"itemsInfo": {"items": []}},
                "options": [{"id": "service", "choicesSettings": {"choices": [{
                    "choiceId": "vault", "linkedMedia": [{"image": {"url": "https://static.wixstatic.com/media/vault.png"}}]
                }]}}]
            }]}
        return {"variants": [{
            "variantId": variant_id, "productData": {"productId": product_id},
            "optionChoices": [{"optionChoiceIds": {"optionId": "service", "choiceId": "vault"}}],
            "price": {"actualPrice": {"amount": "49.00"}},
            "media": {"image": {"url": "https://static.wixstatic.com/media/submit.png"}}
        }]}
    rows = receiver._wix_products(request)
    item = sync.desired_items(rows, require_variant_price=True)[0]
    assert item["image_url"] == "https://static.wixstatic.com/media/vault.png"


def test_scoped_rollout_never_retires_unselected_variants(snapshot_products, monkeypatch):
    all_items = sync.desired_items(snapshot_products)
    wanted = sync.parse_retailer_id(all_items[0]["retailer_id"])[1]
    monkeypatch.setenv("META_CATALOG_SYNC_VARIANT_IDS", wanted)
    monkeypatch.setenv("META_CATALOG_SYNC_FORCE_OUT_OF_STOCK", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    graph = FakeGraph(items=all_items[1:])
    answer = run(FakeWix(snapshot_products), graph)
    assert answer["counts"]["create"] == 1
    assert answer["counts"]["retire"] == 0
    payload = graph.writes[0]["payload"]
    assert payload["allow_upsert"] is True
    assert payload["item_type"] == "PRODUCT_ITEM"
    assert payload["requests"][0]["data"]["availability"] == "out of stock"


def test_inspection_does_not_write_when_sync_is_enabled(snapshot_products, monkeypatch):
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    graph = FakeGraph()
    answer = receiver.handler({"inspect": True}, None, wix_requester=FakeWix(snapshot_products),
                              graph_requester=graph, secret_reader=lambda name: {"access_token": FAKE_TOKEN})
    assert answer["readOnly"] is True
    assert len(answer["desiredItems"]) == 24
    assert graph.writes == []


def test_batch_uses_feed_fields_and_currency_price(snapshot_products):
    plan = sync.diff(sync.desired_items(snapshot_products), [])
    for request in receiver._batch_requests(plan):
        data = request["data"]
        assert data["id"] == request["retailer_id"]
        assert data["title"]
        assert data["link"].startswith("https://wecare.digital/")
        assert data["price"].endswith(" INR")
        assert not ({"retailer_id", "name", "url", "image_url", "currency"} & data.keys())


def test_validation_response_without_handle_is_not_success(snapshot_products):
    plan = sync.diff(sync.desired_items(snapshot_products), [])
    status = [{"errors": [{"message": "Duplicate retailer_id in batch api call - ."}]}]
    answer = receiver._apply(plan, lambda *a, **k: {"validation_status": status},
                             token=FAKE_TOKEN, app_secret="", catalog_id="test")
    assert answer["ok"] is False
    assert answer["applied"] == 0
    assert answer["validationStatus"] == status


# ── 7. F-1 diagnostic hygiene: the refusal says WHY ──────────────────────────
#
# A `read_failed` that reports only `errorType: RuntimeError` makes a 403, a 400, a 429, a 500 and
# a DNS failure indistinguishable, and those call for opposite operator actions - 403 is "re-grant
# the asset", 429 is "back off". And `applied: 0` on its own is ambiguous across five return arms,
# three of which stated no `reason` at all, so the live `ENABLED=false, DRY_RUN=true` arm reported
# a bare zero.
#
# These are the only tests in this file that assert on log-record CONTENTS. `get_logger`
# (`lambda_utils/logging.py:17`) returns a plain stdlib logger - no handler of its own and
# `propagate` untouched - so records reach the root logger `caplog` attaches to. The logger name
# comes off the module object, never a hardcoded guess: the rig loads the handler by path under
# MODULE_NAME, so its `__name__` is that, not `handler`.


def _read_failed_record(caplog):
    """The one `meta_catalog_sync_read_failed` line, parsed."""
    records = [json.loads(record.getMessage()) for record in caplog.records
               if record.getMessage().startswith("{")]
    failures = [row for row in records if row.get("event") == "meta_catalog_sync_read_failed"]
    assert len(failures) == 1, f"expected one read_failed line, got {len(failures)}"
    return failures[0]


def test_a_read_failure_reports_the_graph_status(snapshot_products, monkeypatch, caplog):
    """403 and 500 must not look the same, and the status must be read off the exception rather
    than parsed out of its prose - `lambda_utils.wix_ecom.http_error` is the pattern.

    Both gates OPEN, so this is also the dangerous configuration: a read failure still refuses and
    still constructs no write.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    caplog.set_level(logging.ERROR, logger=receiver.logger.name)
    wix, graph = FakeWix(snapshot_products), FakeGraph(error={"status": 403})

    answer = run(wix, graph)
    assert answer["ok"] is False
    assert answer["reason"] == "read_failed"
    assert graph.writes == []

    record = _read_failed_record(caplog)
    assert record["graphStatus"] == 403
    assert record["errorType"] == "MetaCatalogReadError"
    # The Graph response BODY is never carried and never logged: it echoes the request, and this
    # request's one header is a credential.
    for key, value in record.items():
        assert "Bearer" not in str(value), f"{key} carries an Authorization header"
        assert FAKE_TOKEN not in str(value), f"{key} carries the token"


def test_a_transport_failure_reports_the_kind_and_no_status(
        snapshot_products, monkeypatch, caplog):
    """A DNS or TLS failure never reached HTTP, so it has no status. Reporting the exception KIND
    is what separates it from a Graph refusal; inventing a status would be worse than none.
    """
    monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
    monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
    caplog.set_level(logging.ERROR, logger=receiver.logger.name)
    wix, graph = FakeWix(snapshot_products), FakeGraph(error={"type": "URLError"})

    answer = run(wix, graph)
    assert answer["reason"] == "read_failed"
    assert graph.writes == []

    record = _read_failed_record(caplog)
    assert record["graphErrorKind"] == "URLError"
    assert record["graphStatus"] is None


def _invoke_applied_zero_arm(arm, snapshot_products, monkeypatch):
    """Drive exactly one of the five `applied: 0` return arms of the handler."""
    wix = FakeWix(snapshot_products)
    if arm == "unconfigured":
        return run(wix, FakeGraph(), reader=reader_for(token=None))
    if arm == "read_failed":
        return run(wix, FakeGraph(error={"status": 500}))
    if arm == "read_only_inspect":
        return run(wix, FakeGraph(), event={"inspect": True})
    if arm == "disabled":
        # Both gates absent, which is the shipped configuration.
        return run(wix, FakeGraph())
    if arm == "dry_run":
        monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
        monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "true")
        return run(wix, FakeGraph())
    if arm == "nothing_to_apply":
        monkeypatch.setenv("META_CATALOG_SYNC_ENABLED", "true")
        monkeypatch.setenv("META_CATALOG_SYNC_DRY_RUN", "false")
        desired = sync.desired_items(
            json.loads(SNAPSHOT.read_text(encoding="utf-8"))["products"])
        existing = [{"id": f"m{n}", **sync.meta_payload(item)}
                    for n, item in enumerate(desired)]
        return run(wix, FakeGraph(items=existing))
    raise AssertionError(f"unknown arm: {arm}")


@pytest.mark.parametrize("arm", [
    "unconfigured", "read_failed", "read_only_inspect", "disabled", "dry_run",
    "nothing_to_apply",
])
def test_every_applied_zero_arm_states_its_reason(arm, snapshot_products, monkeypatch):
    """`reason` is TOTAL over the `applied: 0` surface, so a zero is never read alone.

    Six cases over five arms: `disabled` and `dry_run` come out of the SAME return, which is why
    that one derives its reason from `enabled` instead of hard-coding either word. The sixth
    return in the handler (the `batchHandle` readback) has no `applied` key at all and is out of
    scope.
    """
    answer = _invoke_applied_zero_arm(arm, snapshot_products, monkeypatch)
    assert answer["applied"] == 0
    assert answer["reason"] == arm
