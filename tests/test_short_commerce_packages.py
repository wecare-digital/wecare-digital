"""Offline regression tests for the Short Commerce Lambda ZIP preflight.

No AWS client, credentials, network call, payment or WhatsApp message is used.
Run under Python 3.12 with boto3 installed (deploy packager imports it).
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_short_commerce_packages as checker  # noqa: E402


class PackagePreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = {spec.name: spec for spec in checker.deploy.SPECS}
        cls.checkout = cls.specs["wecare-checkout"]
        cls.blob, cls.members = checker.deploy.build_zip(cls.checkout)

    def test_all_three_receivers_package_with_matching_checkout_and_commerce_hashes(self):
        rows = checker.inspect_receivers()
        self.assertEqual(list(checker.RECEIVERS), [row["name"] for row in rows])
        self.assertEqual(rows[0]["code_sha256"], rows[1]["code_sha256"])
        self.assertTrue(all(row["files"] > 0 and row["zip_bytes"] > 0 for row in rows))

    def test_missing_one_unit_module_is_rejected(self):
        members = dict(self.members)
        del members["lambda_utils/ecommerce/short_purchase.py"]
        with self.assertRaisesRegex(ValueError, "short_purchase.py"):
            checker.verify_contents(self.checkout, members)

    def test_modified_one_unit_module_is_rejected(self):
        members = dict(self.members)
        members["lambda_utils/ecommerce/short_purchase.py"] = b"def enabled(): return True\n"
        with self.assertRaisesRegex(ValueError, "differs from source"):
            checker.verify_contents(self.checkout, members)

    def test_invoice_engine_and_fonts_cannot_disappear(self):
        members = dict(self.members)
        del members["invoice_engine.py"]
        with self.assertRaisesRegex(ValueError, "invoice_engine.py"):
            checker.verify_contents(self.checkout, members)
        members = {k: v for k, v in self.members.items() if not k.startswith("fonts/")}
        with self.assertRaisesRegex(ValueError, "font assets"):
            checker.verify_contents(self.checkout, members)

    def test_invalid_packaged_python_is_rejected(self):
        members = dict(self.members)
        members["lambda_utils/syntax_regression.py"] = b"def broken(\n"
        with self.assertRaisesRegex(ValueError, "invalid packaged Python"):
            checker.verify_contents(self.checkout, members)

    def test_checkout_commerce_identity_does_not_depend_on_iteration_order(self):
        with patch.object(checker, "RECEIVERS", tuple(reversed(checker.RECEIVERS))):
            rows = checker.inspect_receivers()
        self.assertEqual("wecare-inbound-whatsapp", rows[0]["name"])
        self.assertEqual({r["name"] for r in rows}, set(checker.RECEIVERS))

    def test_zip_member_map_is_verified(self):
        members = dict(self.members)
        members["handler.py"] = b"replaced"
        with self.assertRaisesRegex(ValueError, "differs from assembled source"):
            checker.verify_zip(self.blob, members, name=self.checkout.name)

    def test_nondeterministic_second_build_fails(self):
        original = checker.deploy.build_zip
        calls_by_name = {}
        def changed_second(spec):
            blob, members = original(spec)
            calls_by_name[spec.name] = calls_by_name.get(spec.name, 0) + 1
            if spec.name == "wecare-checkout" and calls_by_name[spec.name] == 2:
                return blob + b"x", members
            return blob, members
        with patch.object(checker.deploy, "build_zip", side_effect=changed_second):
            with self.assertRaisesRegex(ValueError, "nondeterministic"):
                checker.inspect_receivers()


if __name__ == "__main__":
    unittest.main()
