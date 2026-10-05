"""The Places proxy sends its credential in a HEADER, and no URL can carry it.

WHY THIS FILE EXISTS. `whatsapp-templates`' two Places proxies used to build
`...&key={key}` into the URL they called. Today's value is a referrer-restricted
browser key, which Google's own model treats as public; the moment
`scripts/provision_maps_server_key.py --create` lands a key with NO application
restriction in `wecare/google/cloud`, the same two URLs start carrying a credential
that is usable by anyone who holds it - into Google's access logs, into any request
tracing, and (via the `except Exception as e` paths) into a 502 body and a log line.

So these tests pin the transport, not the feature: the key appears only in
`X-Goog-Api-Key`, the host is `places.googleapis.com`, and the response bodies the
browser already parses are byte-identical in shape to the legacy ones.

No live Google or AWS call is made. `_get_gmaps_key` is patched and `urlopen` is a
stub that captures the `Request` object.
"""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/messaging/whatsapp-templates/handler.py"

KEY = "server-test-key"


def _strip_comments(source: str) -> str:
    """Drop `#` comments and docstrings, as tests/test_one_google_key.py does."""
    without_docstrings = re.sub(r'"""[\s\S]*?"""', "", source)
    return "\n".join(
        line.split("#", 1)[0] for line in without_docstrings.splitlines()
    )


@pytest.fixture
def mod():
    name = "whatsapp_templates_handler_places"
    for extra in (
        str(ROOT / "amplify/functions/shared"),
        str(HANDLER.parent),
    ):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    spec = importlib.util.spec_from_file_location(name, HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    # The module-level `origin` the response helpers read.
    module.origin = "https://wecare.digital"
    module._gmaps_key_cache["key"] = KEY
    yield module
    sys.modules.pop(name, None)


class _Response:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._payload


def _capture(mod, payload):
    """Patch urlopen with a stub that records the Request and answers `payload`."""
    captured = {}

    def open_stub(request, timeout=None):
        captured["request"] = request
        return _Response(payload)

    return captured, patch.object(mod.urllib.request, "urlopen", side_effect=open_stub)


def _refuse(mod, code, body):
    def open_stub(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, code, "Forbidden", {}, io.BytesIO(body)
        )

    return patch.object(mod.urllib.request, "urlopen", side_effect=open_stub)


AUTOCOMPLETE_OK = {
    "suggestions": [
        {
            "placePrediction": {
                "placeId": "place-abc",
                "text": {"text": "12 Park Street, Kolkata"},
            }
        }
    ]
}

DETAILS_OK = {
    "location": {"latitude": 22.5532, "longitude": 88.3519},
    "displayName": {"text": "Park Street"},
    "formattedAddress": "12 Park Street, Kolkata, West Bengal",
}


def test_autocomplete_sends_the_key_in_a_header_and_never_in_a_url(mod):
    captured, patched = _capture(mod, AUTOCOMPLETE_OK)
    with patch.object(mod, "_get_gmaps_key", return_value=KEY), patched:
        resp = mod._places_autocomplete("12 Park Street", session_token="tok-1")

    req = captured["request"]
    assert "key=" not in req.full_url.lower()
    assert KEY not in req.full_url
    assert req.get_header("X-goog-api-key") == KEY
    assert req.full_url == "https://places.googleapis.com/v1/places:autocomplete"
    assert req.get_method() == "POST"
    # Autocomplete (New) is the documented exception: no field mask.
    assert req.get_header("X-goog-fieldmask") is None
    # The session token travels in the BODY for Autocomplete (New).
    assert json.loads(req.data.decode()) == {
        "input": "12 Park Street",
        "sessionToken": "tok-1",
    }

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["predictions"] == [
        {"description": "12 Park Street, Kolkata", "placeId": "place-abc"}
    ]
    assert body["status"] == "OK"


def test_place_details_sends_the_key_in_a_header_and_never_in_a_url(mod):
    captured, patched = _capture(mod, DETAILS_OK)
    with patch.object(mod, "_get_gmaps_key", return_value=KEY), patched:
        resp = mod._place_details("place-abc", session_token="tok-1")

    req = captured["request"]
    assert "key=" not in req.full_url.lower()
    assert KEY not in req.full_url
    assert req.get_header("X-goog-api-key") == KEY
    assert req.full_url.startswith("https://places.googleapis.com/v1/places/place-abc")
    assert req.get_method() == "GET"
    # A field mask IS required on Place Details (New).
    assert req.get_header("X-goog-fieldmask") == "location,displayName,formattedAddress"
    # The session token is a billing-session identifier, not a credential, and is a
    # query parameter on this method.
    assert "sessionToken=tok-1" in req.full_url

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["place"] == {
        "latitude": 22.5532,
        "longitude": 88.3519,
        "name": "Park Street",
        "address": "12 Park Street, Kolkata, West Bengal",
    }
    assert body["status"] == "OK"


def test_an_empty_suggestion_list_is_still_zero_results_not_a_refusal(mod):
    captured, patched = _capture(mod, {"suggestions": []})
    with patch.object(mod, "_get_gmaps_key", return_value=KEY), patched:
        resp = mod._places_autocomplete("nowhere at all")

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["predictions"] == []
    # ZERO_RESULTS is a real answer to a query that matched nothing, and
    # _google_status_problem must keep treating it as success.
    assert body["status"] == "ZERO_RESULTS"


def test_a_place_with_no_location_stays_ok_but_is_logged(mod, caplog):
    """A 200 carrying no `location` must not be silent.

    The legacy call echoed Google's own `status` here, so a degenerate answer had
    somewhere to report itself. The translated shape hardcodes `OK` - deliberately,
    because `status` is part of the body the caller already reads, and ZERO_RESULTS
    would not change the HTTP outcome anyway (`_google_status_problem` treats it as
    success). So the diagnosis belongs in the log, and this pins that it is there.
    """
    captured, patched = _capture(mod, {"displayName": {"text": "Park Street"}})
    with caplog.at_level("WARNING"), patch.object(
        mod, "_get_gmaps_key", return_value=KEY
    ), patched:
        resp = mod._place_details("place-abc")

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    # Shape preserved exactly: still OK, still the same four keys.
    assert body["status"] == "OK"
    assert body["place"] == {
        "latitude": None, "longitude": None,
        "name": "Park Street", "address": "",
    }
    assert "place_details_no_location" in caplog.text
    assert KEY not in caplog.text


REFERRER_REFUSAL = (
    b'{"error":{"message":"API keys with referer restrictions cannot be used with '
    b'this API","details":[{"reason":"API_KEY_HTTP_REFERRER_BLOCKED"}]}}'
)


@pytest.mark.parametrize("call", ["autocomplete", "details"])
def test_a_refused_credential_is_a_502_with_the_referrer_diagnosis(mod, call):
    """A refusal must not arrive looking like "no addresses matched"."""
    with patch.object(mod, "_get_gmaps_key", return_value=KEY), _refuse(
        mod, 403, REFERRER_REFUSAL
    ):
        if call == "autocomplete":
            resp = mod._places_autocomplete("12 Park Street")
        else:
            resp = mod._place_details("place-abc")

    assert resp["statusCode"] == 502
    body = json.loads(resp["body"])
    assert "referrer-restricted BROWSER key" in json.dumps(body)
    assert KEY not in json.dumps(body)


def test_the_handler_source_builds_no_key_query_parameter():
    """Source-level, so the defect cannot be reintroduced by a new call site.

    Comments and docstrings are stripped first, the same way
    tests/test_one_google_key.py does it: the comment explaining why `&key=` is
    forbidden necessarily contains `&key=`, and banning the string outright would
    mean deleting the explanation that justifies the rule.
    """
    code = _strip_comments(HANDLER.read_text(encoding="utf-8"))
    assert "&key=" not in code
    assert "?key=" not in code
    # And there is no keyless GET helper left for a new call site to reuse.
    assert "def _http_get_json" not in code
