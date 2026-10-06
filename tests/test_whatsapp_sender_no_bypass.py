"""A reply must leave from the phone the customer actually messaged.

outbound-whatsapp used to end its sender resolution with:

    if not meta_phone_id:
        meta_phone_id = '1055232054343117'   # "the working one"

That is a cross-WABA bypass, and none of its three consequences were visible at
the call site:

  1. A customer who messaged Phone 1 was answered from Phone 2 - a number they
     never contacted, which on their side is a message from a stranger.
  2. It leaves the 24-hour customer service window. The window belongs to the
     conversation opened on THAT number, so a free-form reply from the other
     number has no open window: Meta rejects it, or bills a new conversation.
  3. It contradicts the "NEVER cross-WABA" rule asserted elsewhere in this
     codebase, including in the payment handlers, while quietly doing the
     opposite.

These tests assert the refusal. A message that does not go out is a visible bug;
a message from the wrong business number is a support incident.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

SHARED = pathlib.Path(__file__).resolve().parents[1] / "amplify/functions/shared"
HANDLER_PATH = (pathlib.Path(__file__).resolve().parents[1]
                / "amplify/functions/messaging/outbound-whatsapp/handler.py")
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))


def _load():
    """Load under a UNIQUE module name.

    Importing this as plain `handler` collides in sys.modules with every other
    function handler the suite loads, so whichever test ran first wins and this
    file silently tests the wrong module. It passed alone and failed in the full
    run. Same spec_from_file_location pattern as tests/test_outbound_sms.py.
    """
    spec = importlib.util.spec_from_file_location(
        "outbound_whatsapp_sender_handler", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ow = _load()

PHONE1 = "phone-number-id-waba1-direct-1016149501586345"
PHONE2 = "phone-number-id-waba-t-direct-1055232054343117"
WABA2_META = "1055232054343117"


# --------------------------------------------------------------------------
# each phone answers its own conversation
# --------------------------------------------------------------------------

def test_phone1_resolves_to_phone1_not_phone2():
    assert ow._resolve_meta_phone_id(PHONE1) == "1016149501586345"


def test_phone2_resolves_to_phone2():
    assert ow._resolve_meta_phone_id(PHONE2) == WABA2_META


def test_direct_api_id_is_derived_exactly_not_guessed():
    """The Direct API id embeds the Meta phone id, so deriving it is exact.
    This is not a fallback and must keep working for ids outside the map."""
    assert ow._resolve_meta_phone_id(
        "phone-number-id-waba9-direct-1234567890") == "1234567890"


# --------------------------------------------------------------------------
# the bypass must be gone
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "",
    "unknown-phone",
    "phone-number-id-waba1",          # no -direct- segment
    "some-other-system-id",
])
def test_unresolvable_sender_raises_instead_of_defaulting(bad):
    with pytest.raises(ow.UnresolvedSenderPhone):
        ow._resolve_meta_phone_id(bad)


def test_non_numeric_direct_segment_is_refused_not_used_as_a_phone_id():
    """'-direct-' followed by junk must not be handed to Graph as a phone id."""
    with pytest.raises(ow.UnresolvedSenderPhone):
        ow._resolve_meta_phone_id("phone-number-id-waba1-direct-notanumber")


def test_no_unresolved_input_can_ever_yield_waba2():
    """The specific regression: nothing unmappable may resolve to WABA2."""
    for bad in ("", "nope", "phone-number-id-waba1", "x-direct-", "garbage"):
        try:
            got = ow._resolve_meta_phone_id(bad)
        except ow.UnresolvedSenderPhone:
            continue
        assert got != WABA2_META, (
            f"{bad!r} silently resolved to WABA2 - the bypass is back")


def test_the_hardcoded_default_is_not_in_the_resolver_source():
    """Belt and braces: catch a future edit that reintroduces the literal."""
    import inspect
    src = inspect.getsource(ow._resolve_meta_phone_id)
    # The literal may appear in the explanatory docstring, but not in code.
    code = "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith("#")
    )
    body = code.split('"""')[-1]  # everything after the docstring
    assert WABA2_META not in body, (
        "a hardcoded WABA2 phone id is back in the resolver body")


# --------------------------------------------------------------------------
# Direct Send rides on the same resolution, so it inherits the same refusal
# --------------------------------------------------------------------------
#
# Direct Send eligibility is granted by Meta per WABA, so deciding whether to add
# `category: 'utility'` means knowing WHICH WABA this send leaves from. That is
# the same question `_resolve_meta_phone_id` already answers, and `_waba_for_sender`
# deliberately reuses it rather than re-deriving: one place decides which phone a
# send leaves from, and a sender it cannot resolve is not eligible for anything.
#
# Getting this wrong would be worse than the original bypass. A cross-WABA guess
# here does not merely answer from the wrong number, it bills the wrong WABA at
# utility rates and accrues any category-misclassification strike against an
# account that never opted in.

import os
from unittest.mock import patch

WABA1 = "2094615664435155"   # owns PHONE1
WABA2 = "2513394156072604"   # owns PHONE2
FLAG = "DIRECT_SEND_ENABLED_WABAS"


def test_each_sender_resolves_to_its_own_waba():
    assert ow._waba_for_sender(PHONE1) == WABA1
    assert ow._waba_for_sender(PHONE2) == WABA2


@pytest.mark.parametrize("bad", [
    "",
    "unknown-phone",
    "phone-number-id-waba1",
    "phone-number-id-waba1-direct-notanumber",
    "some-other-system-id",
])
def test_an_unresolvable_sender_yields_no_waba_rather_than_a_guess(bad):
    """`''`, never a default. The caller logs `direct_send_waba_unresolved` and
    keeps today's behaviour, because "we do not know which WABA" and "not
    enabled" must have the same answer."""
    assert ow._waba_for_sender(bad) == ""


def test_a_resolvable_but_unmapped_sender_yields_no_waba():
    """`_resolve_meta_phone_id` derives a Meta phone id from the `-direct-`
    suffix exactly, so a ninth WABA's phone resolves fine — but it is not in the
    WABA map, so Direct Send stays off for it until someone adds it."""
    assert ow._resolve_meta_phone_id(
        "phone-number-id-waba9-direct-1234567890") == "1234567890"
    assert ow._waba_for_sender("phone-number-id-waba9-direct-1234567890") == ""


def test_enabling_one_waba_cannot_enable_a_sender_on_the_other():
    """The cross-WABA assertion for Direct Send. With only WABA1 in the
    allowlist, a send leaving from PHONE2 must not be eligible."""
    with patch.dict(os.environ, {FLAG: WABA1}):
        assert ow.direct_send.enabled_for_waba(ow._waba_for_sender(PHONE1)) is True
        assert ow.direct_send.enabled_for_waba(ow._waba_for_sender(PHONE2)) is False


def test_an_unresolvable_sender_is_never_eligible_even_with_both_wabas_enabled():
    with patch.dict(os.environ, {FLAG: f"{WABA1},{WABA2}"}):
        for bad in ("", "nope", "phone-number-id-waba1", "garbage"):
            assert ow.direct_send.enabled_for_waba(ow._waba_for_sender(bad)) is False


def test_the_waba_map_is_the_shared_one_not_a_local_copy():
    """A second copy of this mapping is a second thing to get wrong, so the
    handler binds the shared module's dict rather than restating it."""
    assert ow.META_PHONE_TO_WABA is ow.direct_send.META_PHONE_TO_WABA
