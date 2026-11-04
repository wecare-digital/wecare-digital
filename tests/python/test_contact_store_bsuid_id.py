"""Deterministic contact-id derivation for BSUID (phone-absent) senders.

A WhatsApp username adopter can reach the business with no phone number, only a
business-scoped user id (BSUID). `contact_store.deterministic_bsuid_id` gives such a
sender a stable, collision-free contact id so concurrent inbound webhooks never mint
two rows for the same person (the failure mode when the id falls through to a random
UUID while the `bsuid-index` GSI is still catching up).
"""

from lambda_utils import contact_store


def test_bsuid_id_strips_meta_formatting_and_prefixes_wab():
    # Meta BSUID format: country code, a period, then alphanumerics.
    assert contact_store.deterministic_bsuid_id("US.13491208655302741918") == "wab US13491208655302741918".replace(" ", "")


def test_bsuid_id_handles_parent_bsuid_with_ent_segment():
    # Parent BSUIDs carry an extra `ENT` segment: US.ENT.1181...
    assert contact_store.deterministic_bsuid_id("US.ENT.11815799212886844830") == "wabUSENT11815799212886844830"


def test_bsuid_id_is_deterministic():
    a = contact_store.deterministic_bsuid_id("US.13491208655302741918")
    b = contact_store.deterministic_bsuid_id("US.13491208655302741918")
    assert a == b and a != ""


def test_bsuid_id_never_collides_with_phone_id():
    # `wa{digits}` is the phone convention; `wab...` must never equal it.
    phone_id = contact_store.deterministic_id("+919330994400")
    bsuid_id = contact_store.deterministic_bsuid_id("IN.919330994400")
    assert phone_id == "wa919330994400"
    assert bsuid_id.startswith("wab")
    assert phone_id != bsuid_id


def test_bsuid_id_empty_or_punctuation_only_returns_blank():
    assert contact_store.deterministic_bsuid_id("") == ""
    assert contact_store.deterministic_bsuid_id(None) == ""
    assert contact_store.deterministic_bsuid_id("...") == ""


def test_phone_deterministic_id_unchanged():
    # Guard the sibling rule the BSUID id mirrors.
    assert contact_store.deterministic_id("+91 93309 94400") == "wa919330994400"
    assert contact_store.deterministic_id("") == ""
