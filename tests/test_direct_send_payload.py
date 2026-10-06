"""Direct Send: the flag fails closed, and phase 1's four defects stay fixed.

Direct Send sends a business-initiated utility or authentication message without a
pre-created template: the same `POST /{phone_id}/messages`, the same Cloud API body,
plus a top-level `category`. Omitting `category` is Meta's own definition of a
service message, which is what makes "flag empty" byte-identical to today.

What these tests pin, and why each one matters:

* **The flag fails closed, per WABA.** Eligibility is granted by Meta per WABA, so
  enabling WABA1 must not enable WABA2. An allowlist of ids has no state that can
  disagree with itself, and unknown input is off by construction.
* **`ttl_seconds`, not `ttl`** (D1). Phase 1 sent `ttl`, and an unsupported
  parameter is itself a code 100 — so every TTL send failed with an error that
  looked like something else.
* **Per-category TTL bounds** (D2). Authentication caps at 900. The old single
  30..43200 check accepted values Meta refuses.
* **Code 100 is the not-onboarded gate** (D3). Phase 1 keyed `betaGated` on
  139200/131064, which are the post-misuse restriction. The one failure this whole
  surface exists to explain was therefore returned as a bare "Invalid parameter"
  with no hint and `betaGated: false`.
* **The removed sample upload answers 410, not 400** (D4). Dispatch matches on
  `'/direct-send' in path`, so deleting the branch would have let the path fall
  through to `_direct_send` and answer `400 phoneId required` — a silent misroute.
* **The smoke lockdown reaches this surface too** (G1). `whatsapp-business-api`
  imported no `live_smoke`, so `_direct_send` could reach a real recipient while
  smoke mode claimed nothing could.

No network, no Meta call, no AWS. The Graph client is patched in every case that
could otherwise reach one, and no test contains a token or any secret value.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT / "amplify/functions/shared"
BIZ_HANDLER = ROOT / "amplify/functions/messaging/whatsapp-business-api/handler.py"

if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

WABA1 = "2094615664435155"  # WECARE.DIGITAL
WABA2 = "2513394156072604"  # Manish Agarwal
PHONE1 = "1016149501586345"  # +91 93309 94400 -> WABA1
PHONE2 = "1055232054343117"  # +91 99033 00044 -> WABA2
QA_NUMBER = "+918100640044"  # owner-nominated QA recipient
FLAG = "DIRECT_SEND_ENABLED_WABAS"


def _load_biz_handler():
    """Load whatsapp-business-api under a UNIQUE module name.

    Every Lambda in this repo names its entrypoint `handler.py`, so a bare
    `from handler import ...` collides in sys.modules and whichever file loaded
    first silently wins. Same spec_from_file_location pattern as
    tests/test_whatsapp_sender_no_bypass.py.
    """
    with patch("boto3.client"), patch("boto3.resource"):
        spec = importlib.util.spec_from_file_location(
            "direct_send_business_api_handler", BIZ_HANDLER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


# ==========================================================================
# the flag — fails closed, and resolves per WABA
# ==========================================================================

class TestEnabledForWaba:

    @pytest.fixture(autouse=True)
    def _mod(self):
        from lambda_utils import direct_send
        self.ds = direct_send

    def test_unset_is_off_for_both_wabas(self):
        env = {k: v for k, v in os.environ.items() if k != FLAG}
        with patch.dict(os.environ, env, clear=True):
            assert self.ds.enabled_for_waba(WABA1) is False
            assert self.ds.enabled_for_waba(WABA2) is False

    def test_empty_string_is_off_for_both_wabas(self):
        with patch.dict(os.environ, {FLAG: ""}):
            assert self.ds.enabled_for_waba(WABA1) is False
            assert self.ds.enabled_for_waba(WABA2) is False

    def test_enabling_waba1_does_not_enable_waba2(self):
        """The per-WABA assertion. Eligibility is granted per WABA, so one id in
        the list must not switch the other on — that would send WABA2's traffic
        into a guaranteed error."""
        with patch.dict(os.environ, {FLAG: WABA1}):
            assert self.ds.enabled_for_waba(WABA1) is True
            assert self.ds.enabled_for_waba(WABA2) is False

    def test_enabling_waba2_does_not_enable_waba1(self):
        with patch.dict(os.environ, {FLAG: WABA2}):
            assert self.ds.enabled_for_waba(WABA2) is True
            assert self.ds.enabled_for_waba(WABA1) is False

    def test_both_ids_enables_both(self):
        with patch.dict(os.environ, {FLAG: f"{WABA1},{WABA2}"}):
            assert self.ds.enabled_for_waba(WABA1) is True
            assert self.ds.enabled_for_waba(WABA2) is True

    def test_whitespace_and_empty_entries_are_tolerated(self):
        with patch.dict(os.environ, {FLAG: f"  {WABA1} , , {WABA2}  ,"}):
            assert self.ds.enabled_for_waba(WABA1) is True
            assert self.ds.enabled_for_waba(WABA2) is True

    def test_whitespace_only_value_is_off(self):
        with patch.dict(os.environ, {FLAG: "   ,  , "}):
            assert self.ds.enabled_for_waba(WABA1) is False
            assert self.ds.enabled_for_waba(WABA2) is False

    @pytest.mark.parametrize("waba", ["", None, "   ", "9999999999", "waba1"])
    def test_unknown_or_falsy_waba_fails_closed(self, waba):
        """Even with both real ids enabled, anything else is off."""
        with patch.dict(os.environ, {FLAG: f"{WABA1},{WABA2}"}):
            assert self.ds.enabled_for_waba(waba) is False

    def test_a_listed_id_with_surrounding_whitespace_still_matches(self):
        with patch.dict(os.environ, {FLAG: WABA1}):
            assert self.ds.enabled_for_waba(f"  {WABA1} ") is True


class TestWabaForMetaPhone:

    @pytest.fixture(autouse=True)
    def _mod(self):
        from lambda_utils import direct_send
        self.ds = direct_send

    def test_each_phone_maps_to_its_own_waba(self):
        assert self.ds.waba_for_meta_phone(PHONE1) == WABA1
        assert self.ds.waba_for_meta_phone(PHONE2) == WABA2

    @pytest.mark.parametrize("bad", ["", None, "1234567890", "nope"])
    def test_unknown_phone_returns_empty_never_a_guess(self, bad):
        """Empty, not a default. Answering from the wrong WABA is a support
        incident and billing from the wrong WABA lands on someone else."""
        assert self.ds.waba_for_meta_phone(bad) == ""


# ==========================================================================
# TTL bounds — D1 and D2
# ==========================================================================

class TestTtlBounds:

    @pytest.fixture(autouse=True)
    def _mod(self):
        from lambda_utils import direct_send
        self.ds = direct_send

    def test_direct_send_bounds_are_not_template_ttl_bounds(self):
        """These are two different fields. Direct Send's `ttl_seconds` allows a
        utility value up to 30 days; the template's own `message_send_ttl_seconds`
        caps utility at 12 hours. Sharing one table would make one of them wrong."""
        from lambda_utils import template_ttl  # noqa: F401  (import proves it exists)
        from lambda_utils.whatsapp_types import TTL_BOUNDS as TEMPLATE_BOUNDS
        assert self.ds.TTL_BOUNDS["utility"] == (30, 2592000)
        assert TEMPLATE_BOUNDS != self.ds.TTL_BOUNDS

    @pytest.mark.parametrize("cat,value", [
        ("utility", 30), ("utility", 2592000), ("utility", 3600),
        ("authentication", 30), ("authentication", 900), ("authentication", 600),
        ("service", 30), ("service", 43200),
    ])
    def test_in_range_values_are_accepted(self, cat, value):
        assert self.ds.validate_ttl_seconds(cat, value) is None

    @pytest.mark.parametrize("cat,value", [
        ("utility", 29), ("utility", 2592001),
        ("authentication", 29), ("authentication", 901),
        ("service", 43201),
    ])
    def test_out_of_range_values_are_rejected(self, cat, value):
        assert self.ds.validate_ttl_seconds(cat, value) is not None

    def test_authentication_error_names_900_not_utilitys_maximum(self):
        """A 901 on authentication must be told about 900. Naming utility's
        2592000 here would send the operator looking for the wrong problem."""
        err = self.ds.validate_ttl_seconds("authentication", 901)
        assert "900" in err
        assert "2592000" not in err

    @pytest.mark.parametrize("bad", ["abc", None, "", [1]])
    def test_non_integer_is_rejected(self, bad):
        assert self.ds.validate_ttl_seconds("utility", bad) is not None

    def test_unknown_category_is_rejected(self):
        assert self.ds.validate_ttl_seconds("marketing", 60) is not None


# ==========================================================================
# error classification — D3
# ==========================================================================

class TestClassifyError:

    @pytest.fixture(autouse=True)
    def _mod(self):
        from lambda_utils import direct_send
        self.ds = direct_send

    def test_100_with_direct_send_category_details_is_not_onboarded(self):
        details = ("Sending messages with the category parameter requires Direct "
                   "Send. Use an approved template instead.")
        assert self.ds.classify_error(100, details) == self.ds.NOT_ONBOARDED
        assert self.ds.classify_error("100", details) == self.ds.NOT_ONBOARDED

    def test_the_details_matcher_is_tolerant_of_wording(self):
        """The exact wording is documented, not quoted from a live response, so the
        matcher is two lowercased tokens rather than a fixed string. A false
        negative degrades to other_100, which logs everything and falls back —
        the same customer-facing outcome."""
        for details in (
            "direct send is required for this category",
            "The CATEGORY field requires DIRECT SEND access",
            "categories other than service require Direct Send",
        ):
            assert self.ds.classify_error(100, details) == self.ds.NOT_ONBOARDED

    def test_100_for_another_reason_is_other_100_not_the_gate(self):
        assert self.ds.classify_error(100, "Invalid parameter") == self.ds.OTHER_100
        assert self.ds.classify_error(100, "") == self.ds.OTHER_100
        assert self.ds.classify_error(100, None) == self.ds.OTHER_100

    @pytest.mark.parametrize("code", [139200, "139200", 131064, "131064"])
    def test_139200_and_131064_are_restricted_not_not_onboarded(self, code):
        """The correction at the heart of D3: these are the post-misuse
        restriction, a different condition with a different fix."""
        assert self.ds.classify_error(code, "") == self.ds.RESTRICTED

    @pytest.mark.parametrize("code", [131047, 132001, 4, None, "", 500])
    def test_non_direct_send_codes_classify_as_empty(self, code):
        """Empty means "keep today's handling", so an ordinary send failure is
        never rerouted through the Direct Send fallback."""
        assert self.ds.classify_error(code, "anything") == ""

    @pytest.mark.parametrize("code", ["100", "132021", "131000", "132015",
                                      "139200", "131064"])
    def test_every_documented_code_has_a_hint(self, code):
        assert self.ds.ERROR_HINTS.get(code)

    def test_the_100_hint_points_at_error_data_details(self):
        assert "error_data.details" in self.ds.ERROR_HINTS["100"]

    def test_the_restricted_hints_do_not_claim_to_be_the_onboarding_gate(self):
        """139200's hint must not say "not enabled" — that was phase 1's wording
        and it is what sent operators to the wrong remedy."""
        assert "not onboarded" not in self.ds.ERROR_HINTS["139200"].lower()
        assert "restricted" in self.ds.ERROR_HINTS["139200"].lower()


# ==========================================================================
# _direct_send — the corrected payload builder (P2-A)
# ==========================================================================

class TestDirectSendPayload:

    @pytest.fixture(autouse=True)
    def _mod(self):
        self.h = _load_biz_handler()
        self.calls = []

        def fake_graph(path, method='GET', payload=None, **kwargs):
            self.calls.append({'path': path, 'method': method, 'payload': payload})
            return {'messages': [{'id': 'wamid.TEST'}]}

        self.fake_graph = fake_graph

    def _send(self, body, graph=None):
        with patch.object(self.h, '_graph_api', side_effect=graph or self.fake_graph):
            return self.h._direct_send(PHONE1, body)

    @staticmethod
    def _body(resp):
        return json.loads(resp['body'])

    # ── D1: the field is ttl_seconds ────────────────────────────────────────

    def test_ttl_is_sent_as_ttl_seconds_not_ttl(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility',
                           'text': 'Your order has shipped', 'ttlSeconds': 600})
        assert resp['statusCode'] == 200
        sent = self.calls[0]['payload']
        assert sent['ttl_seconds'] == 600
        assert 'ttl' not in sent, "phase 1's `ttl` key is back; Meta rejects it as a 100"

    def test_no_ttl_key_at_all_when_none_requested(self):
        self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'})
        sent = self.calls[0]['payload']
        assert 'ttl_seconds' not in sent
        assert 'ttl' not in sent

    def test_category_is_a_top_level_sibling_of_type(self):
        self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'})
        sent = self.calls[0]['payload']
        assert sent['category'] == 'utility'
        assert sent['type'] == 'text'
        assert 'category' not in sent['text']

    # ── D2: per-category bounds ─────────────────────────────────────────────

    def test_authentication_ttl_901_is_refused_before_any_graph_call(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'authentication',
                           'text': 'Your code is 123456', 'ttlSeconds': 901})
        assert resp['statusCode'] == 400
        assert '900' in self._body(resp)['error']
        assert self.calls == [], "a locally-invalid TTL reached Meta"

    def test_authentication_ttl_900_is_accepted(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'authentication',
                           'text': 'Your code is 123456', 'ttlSeconds': 900})
        assert resp['statusCode'] == 200
        assert self.calls[0]['payload']['ttl_seconds'] == 900

    def test_utility_ttl_30_days_is_accepted(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility',
                           'text': 'hi', 'ttlSeconds': 2592000})
        assert resp['statusCode'] == 200
        assert self.calls[0]['payload']['ttl_seconds'] == 2592000

    def test_utility_ttl_above_30_days_is_refused(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility',
                           'text': 'hi', 'ttlSeconds': 2592001})
        assert resp['statusCode'] == 400
        assert self.calls == []

    def test_non_integer_ttl_is_refused_locally(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility',
                           'text': 'hi', 'ttlSeconds': 'soon'})
        assert resp['statusCode'] == 400
        assert self.calls == []

    # ── preserved phase-1 behaviour ─────────────────────────────────────────

    def test_marketing_is_refused_locally_and_never_reaches_meta(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'marketing', 'text': 'Sale!'})
        assert resp['statusCode'] == 400
        assert self.calls == []

    @pytest.mark.parametrize("name", ["Order_Update", "order update", "order-update",
                                      "ORDER", "order!", "x" * 513])
    def test_bad_template_name_is_refused(self, name):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi',
                           'templateName': name})
        assert resp['statusCode'] == 400
        assert self.calls == []

    def test_good_template_name_lands_in_direct_send_config(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi',
                           'templateName': 'order_shipment_update'})
        assert resp['statusCode'] == 200
        assert self.calls[0]['payload']['direct_send_config'] == {
            'template_name': 'order_shipment_update'}

    def test_template_name_is_utility_only(self):
        """Business-named templates are not supported for authentication."""
        resp = self._send({'to': QA_NUMBER, 'category': 'authentication',
                           'text': 'Your code is 123456',
                           'templateName': 'otp_code'})
        assert resp['statusCode'] == 400
        assert 'utility' in self._body(resp)['error'].lower()
        assert self.calls == []

    def test_body_over_1024_chars_is_refused(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'x' * 1025})
        assert resp['statusCode'] == 400
        assert self.calls == []

    def test_more_than_ten_reply_buttons_is_refused(self):
        buttons = [{'type': 'reply', 'text': f'b{i}', 'id': f'b{i}'} for i in range(11)]
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi',
                           'buttons': buttons})
        assert resp['statusCode'] == 400
        assert self.calls == []

    def test_more_than_two_cta_url_buttons_is_refused(self):
        buttons = [{'type': 'url', 'text': f'b{i}', 'url': 'https://e.com'}
                   for i in range(3)]
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi',
                           'buttons': buttons})
        assert resp['statusCode'] == 400
        assert self.calls == []

    def test_missing_recipient_is_refused(self):
        resp = self._send({'category': 'utility', 'text': 'hi'})
        assert resp['statusCode'] == 400
        assert self.calls == []

    # ── D3: the error surface ───────────────────────────────────────────────

    def _error_graph(self, code, details='', nested=False):
        err = {'code': code, 'message': 'Invalid parameter'}
        if details:
            err['error_data'] = {'details': details}

        def graph(path, method='GET', payload=None, **kwargs):
            self.calls.append({'path': path, 'payload': payload})
            return {'error': {'error': err} if nested else err}
        return graph

    def test_code_100_with_category_details_sets_betaGated(self):
        details = 'The category parameter requires Direct Send on this account.'
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'},
                          graph=self._error_graph(100, details))
        body = self._body(resp)
        assert body['betaGated'] is True, \
            "the not-onboarded gate is code 100; this is defect D3"
        assert body['restricted'] is False
        assert body['directSendHint']

    def test_code_100_with_nested_envelope_still_classifies(self):
        details = 'This category requires Direct Send.'
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'},
                          graph=self._error_graph(100, details, nested=True))
        assert self._body(resp)['betaGated'] is True

    @pytest.mark.parametrize("code", [139200, 131064])
    def test_139200_and_131064_set_restricted_not_betaGated(self, code):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'},
                          graph=self._error_graph(code))
        body = self._body(resp)
        assert body['restricted'] is True
        assert body['betaGated'] is False, \
            "a restriction is being reported as 'not onboarded' again"
        assert body['directSendHint']

    def test_plain_100_is_neither_gate_nor_restriction(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'},
                          graph=self._error_graph(100, 'Invalid parameter'))
        body = self._body(resp)
        assert body['betaGated'] is False
        assert body['restricted'] is False

    @pytest.mark.parametrize("code", [132021, 131000, 132015])
    def test_async_codes_carry_their_hint(self, code):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'},
                          graph=self._error_graph(code))
        assert self._body(resp)['directSendHint']

    def test_an_unrelated_code_gets_no_direct_send_hint(self):
        resp = self._send({'to': QA_NUMBER, 'category': 'utility', 'text': 'hi'},
                          graph=self._error_graph(131047))
        body = self._body(resp)
        assert body['directSendHint'] is None
        assert body['betaGated'] is False
        assert body['restricted'] is False


# ==========================================================================
# D4 — the removed sample upload
# ==========================================================================

class TestSamplesEndpointGone:

    @pytest.fixture(autouse=True)
    def _mod(self):
        self.h = _load_biz_handler()

    def test_the_sample_upload_function_no_longer_exists(self):
        assert not hasattr(self.h, '_direct_send_upload_sample')

    def test_nothing_posts_to_message_samples_any_more(self):
        """`/{waba_id}/message_samples` appears in none of Meta's Direct Send
        documentation and could not be corroborated, so phase 2 must not call it."""
        src = BIZ_HANDLER.read_text()
        code_lines = [ln for ln in src.splitlines()
                      if not ln.lstrip().startswith('#')]
        code = "\n".join(code_lines)
        assert "_graph_api(f'{waba_id}/message_samples'" not in code
        assert 'message_samples' not in code.replace(
            "'/{waba_id}/message_samples is not a documented Meta endpoint'", '')

    def test_samples_path_answers_410_not_a_misrouted_400(self, monkeypatch):
        """Dispatch matches on `'/direct-send' in path`, so a deleted branch would
        fall through to `_direct_send` and answer `400 phoneId required`. An
        explicit gone-with-a-reason is the correct answer."""
        monkeypatch.setattr(self.h, 'require_auth', lambda *a, **k: None)
        called = []
        monkeypatch.setattr(self.h, '_direct_send',
                            lambda *a, **k: called.append(a) or {'statusCode': 200})
        event = {
            'requestContext': {'http': {'method': 'POST',
                                        'path': '/wa-business/direct-send/samples'}},
            'headers': {},
            'body': json.dumps({'wabaId': WABA1, 'text': 'sample'}),
        }
        resp = self.h.handler(event, None)
        assert resp['statusCode'] == 410
        assert called == [], "the samples path fell through to _direct_send"
        body = json.loads(resp['body'])
        assert 'removed' in body


# ==========================================================================
# G1 — the smoke lockdown now covers this surface too
# ==========================================================================

class TestDirectSendSmokeLockdown:
    """`whatsapp-business-api` imported no `live_smoke`, so `_direct_send` could
    reach a real recipient while smoke mode claimed no branch could. A latent hole
    in a lockdown is still a hole: the guarantee is absolute, and one branch broke
    it."""

    @pytest.fixture(autouse=True)
    def _mod(self):
        self.h = _load_biz_handler()
        self.calls = []

        def fake_graph(path, method='GET', payload=None, **kwargs):
            self.calls.append(path)
            return {'messages': [{'id': 'wamid.TEST'}]}

        self.fake_graph = fake_graph

    def _send(self, to):
        with patch.object(self.h, '_graph_api', side_effect=self.fake_graph):
            return self.h._direct_send(
                PHONE1, {'to': to, 'category': 'utility', 'text': 'hello'})

    def test_smoke_mode_refuses_a_non_qa_recipient_at_the_wire(self):
        with patch.dict(os.environ, {'WA_LIVE_SMOKE_TEST': 'true',
                                     'WA_QA_RECIPIENT': QA_NUMBER}):
            resp = self._send('+919812345678')
        assert resp['statusCode'] == 403
        assert self.calls == [], "a smoke-mode send reached the Graph API"

    def test_smoke_mode_allows_the_qa_recipient(self):
        with patch.dict(os.environ, {'WA_LIVE_SMOKE_TEST': 'true',
                                     'WA_QA_RECIPIENT': QA_NUMBER}):
            resp = self._send(QA_NUMBER)
        assert resp['statusCode'] == 200
        assert len(self.calls) == 1

    def test_formatting_differences_do_not_defeat_the_match(self):
        with patch.dict(os.environ, {'WA_LIVE_SMOKE_TEST': 'true',
                                     'WA_QA_RECIPIENT': QA_NUMBER}):
            resp = self._send('918100640044')
        assert resp['statusCode'] == 200

    def test_smoke_mode_without_a_qa_recipient_blocks_everything(self):
        """An operator who enables the mode and forgets the recipient gets no
        sends at all, which is visible immediately."""
        env = {k: v for k, v in os.environ.items() if k != 'WA_QA_RECIPIENT'}
        env['WA_LIVE_SMOKE_TEST'] = 'true'
        with patch.dict(os.environ, env, clear=True):
            resp = self._send(QA_NUMBER)
        assert resp['statusCode'] == 403
        assert self.calls == []

    def test_normal_operation_is_unaffected(self):
        """The flag is a lockdown, not a permission: with it off, nothing changes."""
        env = {k: v for k, v in os.environ.items() if k != 'WA_LIVE_SMOKE_TEST'}
        with patch.dict(os.environ, env, clear=True):
            resp = self._send('+919812345678')
        assert resp['statusCode'] == 200
        assert len(self.calls) == 1

    def test_the_refusal_does_not_log_the_number(self):
        """A masked suffix, never the recipient."""
        with patch.dict(os.environ, {'WA_LIVE_SMOKE_TEST': 'true',
                                     'WA_QA_RECIPIENT': QA_NUMBER}):
            with patch.object(self.h.logger, 'error') as err:
                self._send('+919812345678')
        logged = " ".join(str(c) for c in err.call_args_list)
        assert '919812345678' not in logged
