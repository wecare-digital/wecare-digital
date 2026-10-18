"""India address + GST place-of-supply resolution (provider-neutral).

The India subdivision table, `india_subdivision`, `gst_state_code` and `UnmappableAddress` are
the GST place-of-supply logic the AWS-native checkout pricing depends on.
`to_delivery_address` validates and normalizes the delivery shape that the website payability
gate (`payment_address.assert_payable`) checks.

THE OWNED SHAPE AND THE DELIVERY SHAPE
--------------------------------------
`lambda_utils.identity.address` is the owned shape (`addressLine1`, `city`, `state`,
`postalCode`, `countryCode`, ...). The normalized delivery shape uses different names
(`country`, `subdivision`, `addressLine`) and, critically, a different *type* for the one
field that decides tax.

THE FIELD THAT DECIDES TAX, AND WHY THIS MODULE REFUSES RATHER THAN GUESSES
---------------------------------------------------------------------------
`subdivision` is an ISO 3166-2 code (`IN-WB`), not a name (`West Bengal`). In India the
delivery address IS the place of supply: it decides whether a supply is intra-state
(CGST + SGST) or inter-state (IGST). Seller GSTIN `19AAFFW7196L1Z8` is state code 19, West
Bengal -- see `checkout_pricing.SELLER_GSTIN`.

So a wrong or missing subdivision does not produce an error. It produces a *plausible total
with the wrong tax split*, on an invoice carrying a real GSTIN, and that total is what gets
charged. That is strictly worse than a failed checkout, which is why there is no default
subdivision, no "unknown state" fallback and no partial address: `to_delivery_address` either
produces a complete, resolvable address or raises.

The India table below is therefore an exact lookup, not a fuzzy match. A state this table does
not recognise is a refusal that names the value, so the fix is to add the mapping rather than
to let an unrecognised state through with the tax quietly wrong.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from lambda_utils.identity import address as owned_address

#: ISO 3166-2 subdivision codes for India, with the GST state code each one carries.
#:
#: Two values per entry on purpose. The ISO code is the delivery shape's `subdivision`; the GST
#: state code is the two-digit prefix of a GSTIN, and it is what decides intra- versus
#: inter-state supply. Keeping them in one table means the two can never disagree about the
#: same state.
#:
#: 28 states and 8 union territories. Keys are lowercase for lookup; the canonical name is not
#: stored because nothing here renders a state -- `identity.address.full_address` already owns
#: the printed form.
INDIA_SUBDIVISIONS: Dict[str, tuple] = {
    "jammu and kashmir": ("IN-JK", "01"),
    "himachal pradesh": ("IN-HP", "02"),
    "punjab": ("IN-PB", "03"),
    "chandigarh": ("IN-CH", "04"),
    "uttarakhand": ("IN-UT", "05"),
    "haryana": ("IN-HR", "06"),
    "delhi": ("IN-DL", "07"),
    "rajasthan": ("IN-RJ", "08"),
    "uttar pradesh": ("IN-UP", "09"),
    "bihar": ("IN-BR", "10"),
    "sikkim": ("IN-SK", "11"),
    "arunachal pradesh": ("IN-AR", "12"),
    "nagaland": ("IN-NL", "13"),
    "manipur": ("IN-MN", "14"),
    "mizoram": ("IN-MZ", "15"),
    "tripura": ("IN-TR", "16"),
    "meghalaya": ("IN-ML", "17"),
    "assam": ("IN-AS", "18"),
    "west bengal": ("IN-WB", "19"),
    "jharkhand": ("IN-JH", "20"),
    "odisha": ("IN-OR", "21"),
    "chhattisgarh": ("IN-CT", "22"),
    "madhya pradesh": ("IN-MP", "23"),
    "gujarat": ("IN-GJ", "24"),
    "dadra and nagar haveli and daman and diu": ("IN-DH", "26"),
    "maharashtra": ("IN-MH", "27"),
    "karnataka": ("IN-KA", "29"),
    "goa": ("IN-GA", "30"),
    "lakshadweep": ("IN-LD", "31"),
    "kerala": ("IN-KL", "32"),
    "tamil nadu": ("IN-TN", "33"),
    "puducherry": ("IN-PY", "34"),
    "andaman and nicobar islands": ("IN-AN", "35"),
    "telangana": ("IN-TG", "36"),
    "andhra pradesh": ("IN-AP", "37"),
    "ladakh": ("IN-LA", "38"),
}

#: Spellings that appear in real data and in Google Places output, mapped to the table key.
#: Deliberately a small, explicit alias list rather than fuzzy matching: "Punjab" the Indian
#: state and "Punjab" the Pakistani province are not the same place of supply, and a fuzzy
#: matcher cannot be trusted with a tax decision.
INDIA_ALIASES: Dict[str, str] = {
    "orissa": "odisha",
    "pondicherry": "puducherry",
    "nct of delhi": "delhi",
    "national capital territory of delhi": "delhi",
    "new delhi": "delhi",
    "dadra and nagar haveli": "dadra and nagar haveli and daman and diu",
    "daman and diu": "dadra and nagar haveli and daman and diu",
    "andaman and nicobar": "andaman and nicobar islands",
    "jammu & kashmir": "jammu and kashmir",
    "tamilnadu": "tamil nadu",
}

#: An already-canonical ISO 3166-2 code, for the case where the profile stored one directly.
_ISO_SUBDIVISION_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")


class UnmappableAddress(ValueError):
    """The owned address cannot be converted into a complete delivery address.

    Raised instead of emitting a partial address. A price computed against an incomplete
    address still returns a number, and that number would be wrong rather than absent, which
    is the failure this whole module exists to prevent.
    """


def india_subdivision(state: Any) -> tuple:
    """`(iso_code, gst_state_code)` for an Indian state name, or raise `UnmappableAddress`.

        india_subdivision('West Bengal')  -> ('IN-WB', '19')
        india_subdivision('Orissa')       -> ('IN-OR', '21')
    """
    key = " ".join(str(state or "").split()).lower().replace("&", "and")
    key = " ".join(key.split())
    key = INDIA_ALIASES.get(key, key)
    resolved = INDIA_SUBDIVISIONS.get(key)
    if resolved is None:
        # Stored CRM profiles also use ISO subdivisions and their two-letter suffix.
        # Derive accepted codes from the same tax/delivery table; never guess a state.
        code = key.upper()
        iso_code = code if code.startswith("IN-") else "IN-" + code
        resolved = next((value for value in INDIA_SUBDIVISIONS.values()
                         if value[0] == iso_code), None)
    if resolved is None:
        raise UnmappableAddress(
            f"no ISO 3166-2 subdivision is mapped for the Indian state {str(state or '')!r}. "
            f"The subdivision is the place of supply and decides the CGST/SGST versus IGST "
            f"split, so this refuses rather than pricing the supply with the wrong tax. "
            f"Add the state to INDIA_SUBDIVISIONS."
        )
    return resolved


def to_delivery_address(owned: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an owned structured address into the normalized delivery-address shape.

    Field mapping:

        countryCode   -> country       (ISO 3166-1 alpha-2)
        state         -> subdivision   (ISO 3166-2, resolved not guessed)
        city          -> city
        postalCode    -> postalCode
        addressLine1  -> addressLine
        addressLine2  -> addressLine2

    The owned address is normalised first, so this inherits `identity.address`'s own minimum
    (`addressLine1`, `city`, `postalCode`) rather than re-stating it. Raises
    `UnmappableAddress` when the subdivision cannot be resolved; for countries other than
    India the profile must already carry an ISO 3166-2 code, because this module has no table
    for them and inventing one would repeat the India mistake elsewhere.
    """
    try:
        normalized = owned_address.normalize_address(owned)
    except owned_address.InvalidAddress as error:
        raise UnmappableAddress(f"owned address is not usable: {error}") from None

    country = (normalized.get("countryCode") or "").upper()
    if len(country) != 2 or not country.isalpha():
        raise UnmappableAddress("owned address has no ISO 3166-1 alpha-2 country code")

    raw_state = normalized.get("state") or ""
    if country == owned_address.DEFAULT_COUNTRY_CODE:
        subdivision, _gst = india_subdivision(raw_state)
    elif _ISO_SUBDIVISION_RE.match(raw_state.upper()) and raw_state.upper().startswith(country):
        subdivision = raw_state.upper()
    else:
        raise UnmappableAddress(
            f"country {country} needs an ISO 3166-2 subdivision on the profile; got "
            f"{raw_state!r}. No subdivision table exists for this country, and guessing one "
            f"would put the tax treatment at risk the same way it would for India."
        )

    out = {"country": country, "subdivision": subdivision,
           "city": normalized["city"], "postalCode": normalized["postalCode"],
           "addressLine": normalized["addressLine1"]}
    if normalized.get("addressLine2"):
        out["addressLine2"] = normalized["addressLine2"]
    return out


def gst_state_code(owned: Dict[str, Any]) -> Optional[str]:
    """The two-digit GST state code for an owned Indian address, or `None` outside India.

    Separate from `to_delivery_address` because it answers a different question: checkout computes the
    *supply* tax from the address it is given, while `checkout_pricing.compute_quote` needs
    `intra_state` for the GST on OUR convenience fee. Both derive from the same place of
    supply, so they are resolved from one table rather than two.
    """
    try:
        normalized = owned_address.normalize_address(owned)
    except owned_address.InvalidAddress as error:
        # Normalised to this module's own error. A caller should have one
        # exception type to handle: leaking `InvalidAddress` from here and `UnmappableAddress`
        # from `to_delivery_address` for the same bad input would mean two except clauses for one
        # failure, and whichever was forgotten would surface as a 500.
        raise UnmappableAddress(f"owned address is not usable: {error}") from None
    if (normalized.get("countryCode") or "").upper() != owned_address.DEFAULT_COUNTRY_CODE:
        return None
    return india_subdivision(normalized.get("state"))[1]


__all__ = [
    "INDIA_SUBDIVISIONS",
    "INDIA_ALIASES",
    "UnmappableAddress",
    "india_subdivision",
    "to_delivery_address",
    "gst_state_code",
]
