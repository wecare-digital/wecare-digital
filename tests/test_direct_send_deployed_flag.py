"""The flag value that is actually deployed, asserted end to end on both WABAs.

`tests/test_direct_send_payload.py` already proves `enabled_for_waba` fails closed
and resolves per WABA, using ids it constructs itself. That is the right test for
the parser and the wrong test for a deploy: it would still pass if production
carried a typo, one id, or a semicolon instead of a comma.

This file pins the **exact string set on the two Lambdas** —

    DIRECT_SEND_ENABLED_WABAS = "2094615664435155,2513394156072604"

— copied character for character from what `get-function-configuration` returns at
the `live` alias version, and then drives the real outbound handler with it. So a
reviewer can read `DEPLOYED_FLAG_VALUE` below, compare it to the console, and know
the assertions describe production rather than a hypothetical.

Three things are asserted, in increasing strength:

1. `enabled_for_waba` is True for **both** WABA ids under the deployed value.
2. The sender chain resolves: our phone id -> Meta phone id -> WABA id -> enabled,
   for each of the two senders. This is the lookup the handler actually performs,
   so a correct flag with a broken sender map would still fail here.
3. The real `handler()` outside-window branch, with a plain-text body and no open
   service window, emits a payload carrying top-level `category: 'utility'` for
   **each** WABA — instead of today's 403.

No network, no Meta call, no AWS, no token, no send. `_send_direct_api` is patched
in every case that could otherwise reach the wire, and the assertions are made on
the captured request body. Nothing here contains a secret.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
OUTBOUND_HANDLER = ROOT / "amplify/functions/messaging/outbound-whatsapp/handler.py"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

# ── the deployed value, verbatim ────────────────────────────────────────────
# Read back from the `live` alias version of both functions on 2026-10-06:
#   wecare-outbound-whatsapp      version 50
#   wecare-whatsapp-business-api  version 66
DEPLOYED_FLAG_VALUE = "2094615664435155,2513394156072604"

FLAG = "DIRECT_SEND_ENABLED_WABAS"
WABA1 = "2094615664435155"   # WECARE.DIGITAL
WABA2 = "2513394156072604"   # Manish Agarwal
META_PHONE1 = "1016149501586345"  # +91 93309 94400 -> WABA1
META_PHONE2 = "1055232054343117"  # +91 99033 00044 -> WABA2
SENDER1 = "phone-number-id-waba1-direct-1016149501586345"   # our id -> WABA1
SENDER2 = "phone-number-id-waba-t-direct-1055232054343117"  # our id -> WABA2
RECIPIENT = "+918100640044"  # owner-nominated QA recipient; never actually sent to


def _load_outbound_handler():
    """Load outbound-whatsapp under a UNIQUE module name.

    Every Lambda in this repo names its entrypoint `handler.py`, so a bare
    `from handler import ...` collides in `sys.modules` and whichever file loaded
    first silently wins. Same `spec_from_file_location` pattern as
    `tests/test_direct_send_payload.py`.
    """
    with patch("boto3.client"), patch("boto3.resource"):
        spec = importlib.util.spec_from_file_location(
            "direct_send_deployed_outbound_handler", OUTBOUND_HANDLER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


# ==========================================================================
# 1 — the deployed string enables both WABAs
# ==========================================================================

class TestDeployedValueEnablesBothWabas:

    @pytest.fixture(autouse=True)
    def _mod(self):
        from lambda_utils import direct_send
        self.ds = direct_send

    def test_the_deployed_value_is_exactly_the_two_ids_comma_separated(self):
        """Pin the format too, not just the outcome. `enabled_wabas()` splits on
        a comma and nothing else, so a semicolon or a space-separated list would
        parse to one unusable entry and silently disable both."""
        assert DEPLOYED_FLAG_VALUE == f"{WABA1},{WABA2}"
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            assert self.ds.enabled_wabas() == (WABA1, WABA2)

    def test_waba1_is_enabled_under_the_deployed_value(self):
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            assert self.ds.enabled_for_waba(WABA1) is True

    def test_waba2_is_enabled_under_the_deployed_value(self):
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            assert self.ds.enabled_for_waba(WABA2) is True

    def test_a_third_waba_is_still_off_under_the_deployed_value(self):
        """Enabling both does not turn the allowlist into a pass-through. An id
        nobody listed must stay off, or the flag stops being an allowlist."""
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            assert self.ds.enabled_for_waba("9999999999999999") is False
            assert self.ds.enabled_for_waba("") is False
            assert self.ds.enabled_for_waba(None) is False


# ==========================================================================
# 2 — the sender chain the handler actually walks
# ==========================================================================

class TestSenderChainResolvesToAnEnabledWaba:
    """our phone id -> Meta phone id -> WABA id -> enabled.

    The handler never asks "is Direct Send on"; it asks "is it on for the WABA
    that owns THIS sender". A correct flag with a broken sender map would leave
    the feature off and look enabled, so the chain is asserted rather than the
    flag alone.
    """

    @pytest.fixture(autouse=True)
    def _mod(self):
        from lambda_utils import direct_send
        self.ds = direct_send
        self.h = _load_outbound_handler()

    @pytest.mark.parametrize("sender,meta_phone,waba", [
        (SENDER1, META_PHONE1, WABA1),
        (SENDER2, META_PHONE2, WABA2),
    ])
    def test_each_sender_resolves_to_its_own_enabled_waba(self, sender, meta_phone, waba):
        assert self.h._resolve_meta_phone_id(sender) == meta_phone
        assert self.ds.waba_for_meta_phone(meta_phone) == waba
        assert self.h._waba_for_sender(sender) == waba
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            assert self.ds.enabled_for_waba(self.h._waba_for_sender(sender)) is True

    def test_an_unresolvable_sender_is_still_off_with_both_wabas_enabled(self):
        """`_waba_for_sender` returns `''` rather than guessing, and `''` must not
        match a listed id. Enabling both WABAs must not create a path where an
        unknown sender borrows one of them."""
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            assert self.h._waba_for_sender("not-a-known-sender") == ""
            assert self.ds.enabled_for_waba(self.h._waba_for_sender("not-a-known-sender")) is False


# ==========================================================================
# 3 — the real outside-window branch, per WABA
# ==========================================================================

class TestOutsideWindowBranchAttachesUtilityCategory:
    """Drive `handler()` itself, so the assertion is about the shipped branch.

    The contact carries no `lastInboundMessageAt`, so `_is_within_service_window`
    fails closed and the window is CLOSED — the condition that produces today's
    403. With the deployed flag value the same request must instead reach the wire
    carrying `category: 'utility'`.
    """

    @pytest.fixture(autouse=True)
    def _mod(self):
        self.h = _load_outbound_handler()
        self.sent: list[dict] = []

        # LIVE, so the request reaches `_handle_live_send` rather than the DRY_RUN
        # short-circuit. Nothing leaves the process: `_send_direct_api` is patched.
        self.h.SEND_MODE = 'LIVE'

        def fake_send(phone_number_id, message_json):
            self.sent.append({
                'phoneNumberId': phone_number_id,
                'payload': json.loads(message_json),
            })
            return {'messageId': 'wamid.TEST', 'waId': '918100640044'}

        self.fake_send = fake_send

        # Idempotency check reads MessagesTable; a bare MagicMock would return a
        # truthy `Item` and short-circuit as "already sent".
        table = MagicMock()
        table.get_item.return_value = {}
        self.h.dynamodb = MagicMock()
        self.h.dynamodb.Table.return_value = table

    def _invoke(self, sender):
        contact = {
            'contactId': 'c-1',
            'id': 'c-1',
            'phone': RECIPIENT,
            # No lastInboundMessageAt -> window CLOSED (fails closed).
        }
        event = {
            'requestContext': {'http': {'method': 'POST', 'path': '/wa/send'}},
            'headers': {},
            'body': json.dumps({
                'contactId': 'c-1',
                'content': 'Your order has shipped and will arrive tomorrow.',
                'phoneNumberId': sender,
                'showTyping': False,
            }),
        }
        with patch.object(self.h, 'require_auth', return_value=None), \
             patch.object(self.h, '_get_contact', return_value=contact), \
             patch.object(self.h, '_check_rate_limit', return_value=True), \
             patch.object(self.h, '_store_message_record'), \
             patch.object(self.h, '_emit_delivery_metric'), \
             patch.object(self.h, '_enrich_contact_identity'), \
             patch.object(self.h, '_send_direct_api', side_effect=self.fake_send):
            return self.h.handler(event, None)

    # ── flag OFF: today's refusal, on both senders ──────────────────────────

    @pytest.mark.parametrize("sender", [SENDER1, SENDER2])
    def test_with_the_flag_empty_the_send_is_refused_403(self, sender):
        """The control. Without this, a passing 'utility' assertion below could
        just mean the window check was broken."""
        with patch.dict(os.environ, {FLAG: ""}):
            resp = self._invoke(sender)
        assert resp['statusCode'] == 403
        assert self.sent == [], "a refused send reached the wire"

    # ── flag ON at the deployed value: category utility, both WABAs ─────────

    @pytest.mark.parametrize("sender,waba", [(SENDER1, WABA1), (SENDER2, WABA2)])
    def test_the_deployed_value_sends_utility_instead_of_refusing(self, sender, waba):
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            resp = self._invoke(sender)
        assert resp['statusCode'] == 200, \
            f"outside-window plain text still refused for WABA {waba}"
        assert len(self.sent) == 1
        payload = self.sent[0]['payload']
        assert payload['category'] == 'utility'
        assert payload['type'] == 'text'
        # A SIBLING of `type`, never nested inside `text`.
        assert 'category' not in payload['text']
        assert payload['text']['body'] == \
            'Your order has shipped and will arrive tomorrow.'

    @pytest.mark.parametrize("sender", [SENDER1, SENDER2])
    def test_the_send_leaves_from_the_sender_it_was_asked_to_use(self, sender):
        """Never cross-WABA. Enabling both must not let a send drift to the other
        number — that is a message from a business the customer never contacted."""
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            self._invoke(sender)
        assert self.sent[0]['phoneNumberId'] == sender

    @pytest.mark.parametrize("sender", [SENDER1, SENDER2])
    def test_no_ttl_and_no_template_name_are_added_by_this_path(self, sender):
        """The outside-window fallback sends the body and a category, nothing
        else. `ttl_seconds` and `direct_send_config` belong to the explicit admin
        route, and an unsupported parameter is itself a Meta code 100."""
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}):
            self._invoke(sender)
        payload = self.sent[0]['payload']
        assert 'ttl_seconds' not in payload
        assert 'ttl' not in payload
        assert 'direct_send_config' not in payload


# ==========================================================================
# the fail-closed fallback, with both WABAs enabled
# ==========================================================================

class TestMetaRejectionStillDegradesToTodaysRefusal:
    """A Meta rejection of a Direct Send must look exactly like flag-off.

    This is the property that makes enabling defensible while Meta-side
    onboarding is unverifiable from here: if a WABA is not onboarded, Meta
    refuses the `category` and the customer-facing result must be today's 403,
    not a 500 and not a different message.
    """

    @pytest.fixture(autouse=True)
    def _mod(self):
        self.h = _load_outbound_handler()
        self.h.SEND_MODE = 'LIVE'
        self.stored: list = []
        table = MagicMock()
        table.get_item.return_value = {}
        self.h.dynamodb = MagicMock()
        self.h.dynamodb.Table.return_value = table

    def _invoke_with_meta_error(self, sender, code, details=''):
        import urllib.error
        err = {'code': code, 'message': 'Invalid parameter'}
        if details:
            err['error_data'] = {'details': details}
        body = json.dumps({'error': err}).encode()

        def raising_send(phone_number_id, message_json):
            raise urllib.error.HTTPError(
                'https://graph.facebook.com/x/messages', 400, 'Bad Request', {},
                __import__('io').BytesIO(body))

        contact = {'contactId': 'c-1', 'id': 'c-1', 'phone': RECIPIENT}
        event = {
            'requestContext': {'http': {'method': 'POST', 'path': '/wa/send'}},
            'headers': {},
            'body': json.dumps({
                'contactId': 'c-1',
                'content': 'Your order has shipped.',
                'phoneNumberId': sender,
                'showTyping': False,
            }),
        }
        with patch.dict(os.environ, {FLAG: DEPLOYED_FLAG_VALUE}), \
             patch.object(self.h, 'require_auth', return_value=None), \
             patch.object(self.h, '_get_contact', return_value=contact), \
             patch.object(self.h, '_check_rate_limit', return_value=True), \
             patch.object(self.h, '_store_message_record',
                          side_effect=lambda **kw: self.stored.append(kw)), \
             patch.object(self.h, '_emit_delivery_metric'), \
             patch.object(self.h, '_send_direct_api', side_effect=raising_send):
            return self.h.handler(event, None)

    @pytest.mark.parametrize("sender", [SENDER1, SENDER2])
    def test_not_onboarded_degrades_to_the_403_on_both_wabas(self, sender):
        """Code 100 whose details name the category requirement — Meta's
        not-onboarded answer. Both WABAs must degrade, because onboarding is
        granted per WABA and we cannot verify either from here."""
        resp = self._invoke_with_meta_error(
            sender, 100,
            'Sending messages with the category parameter requires Direct Send.')
        assert resp['statusCode'] == 403
        assert 'Outside 24h service window' in json.loads(resp['body'])['error']
        assert self.stored == [], \
            "a failed row was written; flag-off writes none, so this is not identical"

    @pytest.mark.parametrize("code", [139200, 131064])
    def test_a_meta_restriction_also_degrades_to_the_403(self, code):
        resp = self._invoke_with_meta_error(SENDER1, code)
        assert resp['statusCode'] == 403
        assert self.stored == []

    def test_an_unclassified_100_degrades_to_the_403(self):
        """The details wording is documented, not quoted from a live response, so
        a false negative must still fail closed rather than surface a 500."""
        resp = self._invoke_with_meta_error(SENDER1, 100, 'Invalid parameter')
        assert resp['statusCode'] == 403
        assert self.stored == []

    def test_a_non_direct_send_error_keeps_todays_handling(self):
        """131047 is the ordinary outside-window rejection and is NOT reclassified.
        It falls through to the existing error path — which is the honest limit of
        the fallback and is recorded as such in the verification note."""
        resp = self._invoke_with_meta_error(SENDER1, 131047)
        assert resp['statusCode'] != 200
