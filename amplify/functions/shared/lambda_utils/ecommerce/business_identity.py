"""Canonical WECARE.DIGITAL seller and India importer identity.

One source for the legal identity printed on GST invoices and projected into Meta Order Details
items. Keep presentation-specific shapes in small projection functions so callers cannot drift by
copying the address or legal name.
"""
from __future__ import annotations

import os
from typing import Any, Dict

BRAND = "WECARE.DIGITAL"
LEGAL_NAME = "WECARE.DIGITAL BHARATWORKS"
GSTIN = os.environ.get("COMPANY_GSTIN", "19AAFFW7196L1Z8")
PAN = os.environ.get("COMPANY_PAN", "AAFFW7196L")
EMAIL = "one@wecare.digital"
PHONE = "+91 93309 94400"
WEBSITE = "https://wecare.digital"

ADDRESS_LINE1 = "The W.B.S.I.D.C. Building, Unit 1/20, 81/2/7, Phears Ln"
CITY = "Kolkata"
STATE_CODE = "WB"
POSTAL_CODE = "700012"
COUNTRY_CODE = "IN"
COUNTRY_NAME = "India"


def invoice_identity() -> Dict[str, str]:
    return {
        "name": BRAND,
        "legal_name": LEGAL_NAME,
        "gstin": GSTIN,
        "pan": PAN,
        "address": f"{ADDRESS_LINE1}, {CITY}, {STATE_CODE} {POSTAL_CODE}",
        "email": EMAIL,
        "phone": PHONE,
        "website": WEBSITE,
    }


def meta_importer_fields() -> Dict[str, Any]:
    """Fields permitted on an India Order Details line item."""
    return {
        "country_of_origin": COUNTRY_NAME,
        "importer_name": BRAND,
        "importer_address": {
            "address_line1": ADDRESS_LINE1,
            "city": CITY,
            "zone_code": STATE_CODE,
            "postal_code": POSTAL_CODE,
            "country_code": COUNTRY_CODE,
        },
    }


__all__ = [
    "ADDRESS_LINE1", "BRAND", "CITY", "COUNTRY_CODE", "COUNTRY_NAME", "EMAIL", "GSTIN",
    "LEGAL_NAME", "PAN", "PHONE", "POSTAL_CODE", "STATE_CODE", "WEBSITE",
    "invoice_identity", "meta_importer_fields",
]
