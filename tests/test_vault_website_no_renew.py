"""No second Vault charge through an old website cart intent.

The production website quote and prepare both call the owner-bound Vault
purchase verifier. This test runs the real verifier with only fake tables;
it never sends WhatsApp or creates a payment/order.
"""
import ast
from pathlib import Path
import re
from types import SimpleNamespace
import typing
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = ROOT / "amplify/functions/ecommerce/checkout/handler.py"

class Refused(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class FakeTables:
    def __init__(self, *, intent=None, file=None, entitlement=None):
        self.rows = {
            "stack-wecare-digital-ServiceRequestsTable": intent or {},
            "stack-wecare-digital-SecureFilesTable": file or {},
            "stack-wecare-digital-DownloadGrantsTable": entitlement or {},
        }
        self.reads = []

    def table(self, name):
        outer = self

        class ReadOnlyTable:
            def get_item(self, *, Key, ConsistentRead):
                assert ConsistentRead is True
                outer.reads.append((name, Key))
                return {"Item": outer.rows[name]}

        return ReadOnlyTable()


def identity():
    return SimpleNamespace(customer_id="owner-verified")


def intent():
    return {
        "vaultFileId": "file-exact", "kind": "VAULT",
        "ownerCustomerId": "owner-verified", "status": "OPEN",
        "variantId": "vault-one", "targetRequestId": "FILE#file-exact",
        "vaultOwnerPhone": "919000000001",
    }


def file():
    return {
        "fileId": "file-exact", "ownerCustomerId": "owner-verified",
        "ownerPhone": "919000000001", "status": "active",
    }


def grant():
    return {
        "recordType": "VAULT_ENTITLEMENT", "entitlementState": "ACTIVE",
        "customerId": "owner-verified", "fileId": "file-exact",
        "ownerPhone": "919000000001",
        "paidWindowCount": 1, "accessWindowState": "EXPIRED",
    }


def load_verifier(fake):
    source = CHECKOUT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = [node for node in tree.body
              if isinstance(node, ast.FunctionDef)
              and node.name == "_verify_vault_website_renewal"]
    assert len(target) == 1
    service = SimpleNamespace(
        VAULT="VAULT",
        INTENT_ID_RE=re.compile(r"^[A-Za-z0-9_-]{1,120}$"),
        service_line=lambda items: SimpleNamespace(kind="VAULT",
                                                   variant_id="vault-one"),
    )
    namespace = {
        "customer_auth": SimpleNamespace(CustomerIdentity=object),
        "website_checkout": SimpleNamespace(CheckoutRejected=Refused),
        "service_requests": service, "_table": fake.table,
        "Dict": typing.Dict, "Any": typing.Any,
    }
    exec(compile(ast.Module(body=target, type_ignores=[]), str(CHECKOUT), "exec"),
         namespace)
    return namespace["_verify_vault_website_renewal"]


class VaultWebsiteNoRenewTests(unittest.TestCase):
    def test_never_paid_exact_owned_file_still_passes(self):
        fake = FakeTables(intent=intent(), file=file())
        load_verifier(fake)(identity(), {"serviceIntentId": "intent-01"}, [{}])
        self.assertEqual(len(fake.reads), 3)
        self.assertTrue(all(name.startswith("stack-wecare-digital-")
                            for name, _ in fake.reads))

    def test_expired_entitlement_cannot_be_renewed(self):
        fake = FakeTables(intent=intent(), file=file(), entitlement=grant())
        with self.assertRaises(Refused) as caught:
            load_verifier(fake)(identity(), {"serviceIntentId": "intent-01"}, [{}])
        self.assertEqual(caught.exception.reason, "VAULT_ALREADY_PAID")

    def test_active_entitlement_cannot_be_charged_again(self):
        active = {**grant(), "accessWindowState": "OPEN"}
        fake = FakeTables(intent=intent(), file=file(), entitlement=active)
        with self.assertRaises(Refused) as caught:
            load_verifier(fake)(identity(), {"serviceIntentId": "intent-01"}, [{}])
        self.assertEqual(caught.exception.reason, "VAULT_ALREADY_PAID")

    def test_durable_file_pointer_blocks_when_grant_write_is_delayed(self):
        for column in ("vaultPaymentStatus", "vaultEntitlementId", "vaultAccessGrantId"):
            old = {**file(), column: "PAID" if column == "vaultPaymentStatus" else "grant-1"}
            with self.subTest(column=column):
                with self.assertRaises(Refused) as caught:
                    load_verifier(FakeTables(intent=intent(), file=old))(
                        identity(), {"serviceIntentId": "intent-01"}, [{}])
                self.assertEqual(caught.exception.reason, "VAULT_ALREADY_PAID")

    def test_wrong_owner_refused_before_file_read(self):
        other = {**intent(), "ownerCustomerId": "different"}
        fake = FakeTables(intent=other, file=file())
        with self.assertRaises(Refused) as caught:
            load_verifier(fake)(identity(), {"serviceIntentId": "intent-01"}, [{}])
        self.assertEqual(caught.exception.reason, "VAULT_FILE_BINDING_INVALID")
        self.assertEqual(len(fake.reads), 1)

    def test_ambiguous_grant_rejected_not_resold(self):
        bad = {**grant(), "ownerPhone": "919999999999"}
        with self.assertRaises(Refused) as caught:
            load_verifier(FakeTables(intent=intent(), file=file(),
                                     entitlement=bad))(
                identity(), {"serviceIntentId": "intent-01"}, [{}])
        self.assertEqual(caught.exception.reason, "VAULT_ENTITLEMENT_UNVERIFIED")

    def test_quote_and_checkout_prepare_call_same_gate(self):
        source = CHECKOUT.read_text(encoding="utf-8")
        quote = source[source.index("def _website_quote("):
                       source.index("def _website_prepare(")]
        prepare = source[source.index("def _website_prepare("):]
        self.assertIn("_verify_vault_website_renewal(identity, body, line_items)",
                      quote)
        self.assertIn("_verify_vault_website_renewal(identity, body, line_items)",
                      prepare)
        self.assertNotIn("vault_window.access_state(entitlement", source[
            source.index("def _verify_vault_website_renewal("):
            source.index("def _website_quote(")])


if __name__ == "__main__":
    unittest.main()
