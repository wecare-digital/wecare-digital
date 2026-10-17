"""Synthetic catalog identities for service-path tests.

Production service catalog mappings are intentionally empty until the fresh SKU-first catalog is
created. Tests opt into these fake UUIDs only to exercise generic service logic.
"""
from types import MappingProxyType

PRODUCT = "11111111-1111-4111-8111-111111111111"
SUBMIT = "22222222-2222-4222-8222-222222222222"
AMEND = "33333333-3333-4333-8333-333333333333"
DROP_DOCS = "44444444-4444-4444-8444-444444444444"
VAULT = "55555555-5555-4555-8555-555555555555"
PICKUP = "66666666-6666-4666-8666-666666666666"

KIND_BY_VARIANT = {
    SUBMIT: "SUBMIT_REQUEST",
    AMEND: "REQUEST_AMENDMENT",
    DROP_DOCS: "DROP_DOCS",
    VAULT: "VAULT",
    PICKUP: "REQUEST_PICKUP",
}


def configure(service_requests):
    service_requests.SERVICE_PRODUCT_IDS = frozenset({PRODUCT})
    service_requests.SERVICE_KIND_BY_VARIANT = MappingProxyType(dict(KIND_BY_VARIANT))
    service_requests.SERVICE_VARIANT_BY_KIND = MappingProxyType(
        {kind: variant for variant, kind in KIND_BY_VARIANT.items()})
    service_requests.SERVICE_PURCHASES_ENABLED = True
