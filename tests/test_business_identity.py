"""Seller / importer identity parity."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify" / "functions" / "shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from lambda_utils.ecommerce import business_identity as bi  # noqa: E402


def test_invoice_and_meta_importer_share_the_same_business_identity():
    invoice = bi.invoice_identity()
    importer = bi.meta_importer_fields()
    assert invoice["name"] == importer["importer_name"] == "WECARE.DIGITAL"
    assert invoice["legal_name"] == "WECARE.DIGITAL BHARATWORKS"
    assert invoice["gstin"] == "19AAFFW7196L1Z8"
    assert importer["country_of_origin"] == "India"
    address = importer["importer_address"]
    assert address["address_line1"] == bi.ADDRESS_LINE1
    assert address["city"] == bi.CITY == "Kolkata"
    assert address["postal_code"] == bi.POSTAL_CODE == "700012"
    assert address["country_code"] == "IN"
    assert bi.ADDRESS_LINE1 in invoice["address"]
