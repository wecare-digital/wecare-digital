"""Consolidated Orders service routing and compact clipboard toast.

These are offline code contracts: no customer login, payment, WhatsApp, or AWS calls.
A production deployment separately adds Amplify 301 rules for five retired paths.
Vault exact-file links cannot be covered by a path-only redirect.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RETIRED = {
    "/submit-request": "src/pages/submit-request.tsx",
    "/request-amendment": "src/pages/request-amendment.tsx",
    "/drop-docs": "src/pages/drop-docs.tsx",
    "/request-pickup": "src/pages/request-pickup.tsx",
    "/shipments/track": "src/pages/shipments/track.tsx",
}
SHELF_SLUGS = (
    "submit-request", "request-amendment", "drop-docs",
    "vault", "shipments-track", "request-pickup",
)


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_standalone_marketing_page_files_are_removed_and_not_in_sitemap():
    sitemap = source("scripts/generate-sitemap.js").split(
        "const PUBLIC_EXACT = new Set( [", 1
    )[1].split("] );", 1)[0]
    catalog = json.loads(source("config/public-pages.json"))
    catalog_routes = {entry["path"] for entry in catalog["pages"]}
    for route, page_file in RETIRED.items():
        assert not (ROOT / page_file).exists(), page_file
        assert f"'{route}'" not in sitemap
        assert route not in catalog_routes
    assert "/vault" not in catalog_routes
    assert "'/vault'" not in sitemap
    assert "/orders" in catalog_routes
    assert "'/orders'" in sitemap


def test_retired_routes_redirect_permanently_without_intercepting_vault_files():
    source_code = source("scripts/provision_legacy_redirects.py")
    redirect_block = source_code.split(
        "RETIRED_SERVICE_PAGE_ROUTES = (", 1
    )[1].split(")", 1)[0]
    for route in RETIRED:
        assert f'"{route}"' in redirect_block
    assert '"/vault"' not in redirect_block
    assert '"/shop/shipments-track"' in redirect_block
    shop = source("src/content/shop.ts")
    assert "|| ORDER_HUB_SERVICE_SLUGS.has( String( raw.slug || '' ) );" in shop
    assert "'shipments-track'" in shop
    assert 'for source in (route, route + "/"):' in source_code
    assert 'rules.append({"source": source, "target": "/orders/", "status": "301"})' in source_code
    assert "return desired_redirects() + [dict(rule) for rule in existing if not is_ours(rule)]" in source_code
    assert 'CATCH_ALL_SOURCE = "/<*>"' in source_code


def test_vault_file_links_and_post_signin_restoration_are_not_redirected():
    vault = source("src/pages/vault.tsx")
    app = source("src/pages/_app.tsx")
    assert (ROOT / "src/pages/vault.tsx").is_file()
    assert "queryFileId" in vault
    assert "VAULT_AUTH_RETURN_FILE_KEY" in vault
    assert "VAULT_FILE_ID_PATTERN.test( saved )" in vault
    assert "setRestoredFileId( saved );" in vault
    assert "router.replace( { pathname: '/vault/', query: { file: saved } }" in vault
    assert "return <GetPage targetFileId={ targetFileId } />;" in vault
    assert "void router.replace( '/orders/' );" in vault
    assert "No meta-refresh" in vault
    assert "<meta httpEquiv=" not in vault
    routes = app.split("const CUSTOMER_SERVICE_ROUTES = new Set( [", 1)[1].split(
        "] );", 1
    )[0]
    assert "'/vault'" in routes
    for route in RETIRED:
        assert f"'{route}'" not in routes
    assert "noindex, nofollow" in app
    assert "window.location.replace( '/auth?return=/orders/' );" in source(
        "src/components/orders/OrdersPage.tsx"
    )


def test_shop_service_cards_go_to_orders_and_regeneration_keeps_it_that_way():
    shelf = source("src/content/shopProducts.ts")
    generator = source("scripts/generate_shop_listings.py")
    for slug in SHELF_SLUGS:
        prefix = f"slug:'{slug}',"
        assert prefix in shelf
        card = shelf.split(prefix, 1)[1].split(" },", 1)[0]
        assert "href:'/orders/'" in card, slug
        assert f'"{slug}"' in generator
    assert 'ORDER_HUB_SERVICE_SLUGS: frozenset[str]' in generator
    assert '"href": "/orders/" if slug in ORDER_HUB_SERVICE_SLUGS else url[len(ORIGIN):],' in generator
    assert 'canonicalPath' in source("src/content/catalogSnapshot.ts")
    # Product identities/prices and secure backend actions are intentionally retained.
    service = source("src/config/services.ts")
    for kind in ("SUBMIT_REQUEST", "REQUEST_AMENDMENT", "DROP_DOCS",
                 "VAULT", "REQUEST_PICKUP"):
        assert kind in service
    assert "startRequestService(" in source("src/components/ServiceBuyBox.tsx")


def test_clipboard_toast_is_content_width_while_backend_error_remains_wide():
    orders = source("src/components/orders/OrdersPage.tsx")
    assert 'className="ord-backend-toast ord-copy-toast"' in orders
    assert "setCopyNotice( { kind: 'success', message: 'Copied' } );" in orders
    assert ".ord-backend-toast.ord-copy-toast{" in orders
    assert "inline-size:fit-content;max-inline-size:min(100%,320px);" in orders
    assert "margin:0;padding:8px 12px;" in orders
    assert "inline-size:min(100%,560px);" in orders  # backend error, unchanged
    assert 'role={ copyNotice.kind === \'fallback\' ? \'alert\' : \'status\' }' in orders
    assert "ord-feedback" not in orders
