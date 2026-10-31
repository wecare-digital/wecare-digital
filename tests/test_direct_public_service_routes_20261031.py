"""Read-only release contracts for direct public customer service URLs.

Offline source regression only; does not access AWS, WhatsApp, authentication or money.
Run against a checkout of the complete branch, before the public pages and
Amplify 301 removals are released as a single customer-facing change.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

SERVICE_URLS = {
    "/submit-request": "src/pages/submit-request.tsx",
    "/request-amendment": "src/pages/request-amendment.tsx",
    "/drop-docs": "src/pages/drop-docs.tsx",
    "/vault": "src/pages/vault.tsx",
    "/request-pickup": "src/pages/request-pickup.tsx",
    "/shipments/track": "src/pages/shipments/track.tsx",
    "/leave-review": "src/pages/leave-review.tsx",
    "/subscribe": "src/pages/subscribe.tsx",
}


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class DirectPublicServiceRoutesTests(unittest.TestCase):
    def test_each_public_page_exists_and_is_not_an_orders_redirect(self):
        for url, path in SERVICE_URLS.items():
            with self.subTest(url=url):
                body = source(path)
                self.assertTrue(body)
                self.assertNotIn("router.replace( '/orders/' )", body)
                self.assertNotIn("window.location.assign( '/orders/' )", body)
                self.assertNotIn("httpEquiv=\"refresh\"", body)
                self.assertNotIn("import Layout", body)
                self.assertNotIn("useAuthenticator", body)

    def test_header_and_orders_offer_real_direct_routes(self):
        header = source("src/components/Header.tsx")
        menu = source("src/components/orders/OrderActionsMenu.tsx")
        for url in SERVICE_URLS:
            canonical = url + "/"
            with self.subTest(url=url):
                self.assertIn("href: '" + canonical + "'", header)
                self.assertIn("href: '" + canonical + "'", menu)
        self.assertNotIn("stashCustomerMenuAction(", header)
        self.assertIn("onInvite( sendAction )", menu)

    def test_public_sitemap_and_machine_catalog_agree(self):
        app = source("src/pages/_app.tsx")
        sitemap = source("scripts/generate-sitemap.js")
        generator = source("scripts/generate-public-pages.js")
        catalog = json.loads(source("config/public-pages.json"))
        paths = [entry["path"] for entry in catalog["pages"]]
        for route in SERVICE_URLS:
            with self.subTest(route=route):
                self.assertEqual(paths.count(route), 1)
                self.assertIn("'" + route + "': { name:", app)
                self.assertIn("'" + route + "'", sitemap)
        self.assertNotIn("NON_INDEXABLE_CUSTOMER_ROUTES", generator)
        self.assertIn("assign( entry, 'services' );", generator)

    def test_customer_request_pages_reuse_authentic_whatsapp_entry(self):
        from_content = source("src/content/customerservice.ts")
        shared = source("src/components/DirectServiceEntry.tsx")
        product = source("src/components/ProductPage.tsx")
        self.assertIn("whatsappServiceLink( product.slug )", product)
        self.assertIn("whatsappServiceLink( kind )", shared)
        self.assertNotIn("sendCustomerMenuAction(", shared)
        for kind in ("submit-request", "request-amendment", "drop-docs", "vault", "request-pickup"):
            self.assertIn("slug: '" + kind + "'", from_content)

    def test_private_file_link_stays_owner_and_payment_verified(self):
        vault = source("src/pages/vault.tsx")
        get = source("src/components/get/GetPage.tsx")
        self.assertIn("customerserviceBySlug( 'vault' )", vault)
        self.assertIn("GetPage targetFileId={ queryFileId }", vault)
        self.assertIn("VAULT_FILE_ID_PATTERN.test( queryFileId )", vault)
        self.assertIn("router.replace( '/404' )", vault)
        self.assertIn("window.location.replace( '/404' )", get)
        self.assertIn("redeemSecureFileDownload", get)
        self.assertIn("result.failure.status === 401", get)
        self.assertIn("api.requestMySecureFilePayment", get)

    def test_amp_redirect_provisioner_removes_orders_301_only_after_deploy(self):
        script = source("scripts/provision_legacy_redirects.py")
        self.assertIn("PUBLIC_SERVICE_PAGE_ROUTES", script)
        self.assertIn("verify_exported_service_assets()", script)
        self.assertIn("def desired_redirects()", script)
        self.assertIn("return []", script)
        self.assertIn("RETIRED_CONTENT_ROUTES", script)
        self.assertNotIn('"target": "/orders/", "status": "301"', script)
        self.assertIn("catch_all_problem", script)
        self.assertIn("blog_merges()", script)
        self.assertIn("rollback.write_text", script)
        self.assertIn("client.update_app(appId=APP_ID, customRules=new_rules)", script)

    def test_vault_no_file_whatsapp_reply_uses_new_public_submit_page(self):
        catalog = source("amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py")
        self.assertIn("SUBMIT_NEW_REQUEST_MESSAGE", catalog)
        self.assertIn("https://wecare.digital/submit-request/", catalog)
        self.assertIn("_send(client, row, content=SUBMIT_NEW_REQUEST_MESSAGE)", catalog)
        self.assertIn("if state != 'UNPAID':", catalog)
        self.assertIn("return _send_access(client, row, file['fileId'])", catalog)


if __name__ == "__main__":
    unittest.main()
