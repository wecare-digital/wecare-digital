"""SmsRegionResolver - the single place that decides which AWS region sends an SMS.

Spec §5: "Do not scatter region decisions across Lambda functions."

    India      -> ap-south-1     (AWS_SMS_REGION_INDIA)
    everything -> us-east-1      (AWS_SMS_REGION_DEFAULT)

An explicit override is supported because region choice is not purely a function
of the destination: sender-ID registration, origination-identity availability and
country-specific capabilities are per-region facts. §5 requires the override for
exactly that case.

Why India is a separate region at all
-------------------------------------
Indian A2P traffic must carry the TRAI DLT entity id and an approved template id
via `DestinationCountryParameters`, and must originate from the DLT-registered
sender id. This is regional: India traffic cannot be DLT-compliant merely
because a sender ID is present as a source-code default.

Historical registration observations are NOT proof of current readiness. On
2026-11-02 a fresh DescribeSenderIds in both ap-south-1 and us-east-1 returned
zero sender identities, and 13 post-call SMS records had ResourceNotFound for
WDBEEP. Automated call SMS must stay off until the current account's registered
WDBEEP sender is verified in ap-south-1, with valid DLT entity/content templates.
Do not provision a substitute identity or silently route Indian traffic elsewhere.
"""
from __future__ import annotations

import os
from typing import Optional

from . import numbers

# Region names are configuration, not constants, per §5.
INDIA_REGION = os.environ.get("AWS_SMS_REGION_INDIA", "ap-south-1")
DEFAULT_REGION = os.environ.get("AWS_SMS_REGION_DEFAULT", "us-east-1")


class SmsRoute:
    """The resolved decision for one destination. Immutable by convention."""

    __slots__ = ("region", "is_india", "iso_country", "requires_dlt", "reason")

    def __init__(self, region: str, is_india: bool, iso_country: Optional[str],
                 requires_dlt: bool, reason: str) -> None:
        self.region = region
        self.is_india = is_india
        self.iso_country = iso_country
        self.requires_dlt = requires_dlt
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (f"SmsRoute(region={self.region!r}, is_india={self.is_india}, "
                f"requires_dlt={self.requires_dlt}, reason={self.reason!r})")

    def as_dict(self) -> dict:
        return {
            "region": self.region,
            "isIndia": self.is_india,
            "isoCountry": self.iso_country,
            "requiresDlt": self.requires_dlt,
            "reason": self.reason,
        }


def resolve(phone_e164: str, override_region: str = "") -> SmsRoute:
    """Decide the sending region for one destination.

    `override_region` wins, but it does NOT change whether DLT is required.
    DLT is a property of the destination country, not of the region a caller
    picked, so forcing us-east-1 for an Indian number still demands DLT
    parameters - and will still be refused by the DLT gate if none is mapped.
    Letting an override silently drop DLT would turn a routing preference into a
    regulatory breach.
    """
    india = numbers.is_india(phone_e164)
    iso = numbers.iso_country(phone_e164)

    if override_region:
        return SmsRoute(region=override_region, is_india=india, iso_country=iso,
                        requires_dlt=india,
                        reason=f"explicit override to {override_region}")

    if india:
        return SmsRoute(region=INDIA_REGION, is_india=True, iso_country=iso,
                        requires_dlt=True,
                        reason=f"destination is India -> {INDIA_REGION}")

    return SmsRoute(region=DEFAULT_REGION, is_india=False, iso_country=iso,
                    requires_dlt=False,
                    reason=f"destination is not India -> {DEFAULT_REGION} (default)")
