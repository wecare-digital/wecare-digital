"""Contract tests for the public VayuLok environmental gateway.

No live AWS or Google request is made. The tests pin the security boundary:
our browser may choose one named operation and India coordinates, but cannot
choose an upstream URL, key, provider request body, or unbounded fan-out.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/core/vayulok-environment/handler.py"


@pytest.fixture
def mod():
    name = "vayulok_environment_handler"
    spec = importlib.util.spec_from_file_location(name, HANDLER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module._key_cache.update({"loaded": True, "key": "server-test-key"})
    yield module
    sys.modules.pop(name, None)


def event(body=None, *, origin="https://wecare.digital", method="POST"):
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    return {
        "rawPath": "/vayulok/environment",
        "requestContext": {
            "http": {"method": method, "path": "/vayulok/environment"}
        },
        "headers": headers,
        "body": json.dumps(body or {}),
    }


def body(resp):
    return json.loads(resp["body"] or "{}")


@pytest.mark.parametrize(
    "origin",
    [
        "https://wecare.digital",
        "https://www.wecare.digital",
        "https://preview.wecare.digital",
    ],
)
def test_wecare_https_origins_are_allowed(mod, origin):
    assert mod._origin_allowed(event(origin=origin))


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "",
        "http://wecare.digital",
        "https://evil.example",
        "https://wecare.digital.evil.example",
        "https://wecare.digital:444",
    ],
)
def test_other_origins_are_refused(mod, origin):
    assert not mod._origin_allowed(event(origin=origin))


def test_off_origin_request_stops_before_dispatch_or_secret_read(mod):
    with patch.object(mod, "_dispatch") as dispatch, patch.object(
        mod, "_google_key"
    ) as key:
        resp = mod.handler(
            event(
                {
                    "operation": "weather_current",
                    "latitude": 19.076,
                    "longitude": 72.8777,
                },
                origin="https://evil.example",
            ),
            None,
        )
    assert resp["statusCode"] == 403
    dispatch.assert_not_called()
    key.assert_not_called()


def test_only_named_operations_are_admitted(mod):
    resp = mod.handler(
        event(
            {
                "operation": "https://weather.googleapis.com/v1/anything",
                "latitude": 19.076,
                "longitude": 72.8777,
            }
        ),
        None,
    )
    assert resp["statusCode"] == 400
    assert body(resp)["error"] == "invalid_request"


@pytest.mark.parametrize(
    ("lat", "lng"),
    [(0, 72.8), (45, 72.8), (19, 50), (19, 120)],
)
def test_coordinates_are_bounded_to_the_product_india_box(mod, lat, lng):
    with patch.object(mod, "_google_json") as upstream:
        resp = mod.handler(
            event(
                {
                    "operation": "weather_current",
                    "latitude": lat,
                    "longitude": lng,
                }
            ),
            None,
        )
    assert resp["statusCode"] == 400
    upstream.assert_not_called()


def test_weather_request_is_server_owned_and_has_no_key_in_url(mod):
    with patch.object(mod, "_google_json", return_value={"ok": True}) as upstream:
        result = mod._dispatch(
            "weather_current", {"latitude": 19.076, "longitude": 72.8777}
        )
    assert result == {"ok": True}
    url = upstream.call_args.args[0]
    assert url.startswith(
        "https://weather.googleapis.com/v1/currentConditions:lookup?"
    )
    assert "location.latitude=19.076" in url
    assert "location.longitude=72.8777" in url
    assert "key=" not in url.lower()


def test_google_key_is_sent_in_header_not_query_string(mod):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return b'{"ok":true}'

    def open_stub(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    with patch.object(mod.urllib.request, "urlopen", side_effect=open_stub):
        result = mod._google_json(
            "https://weather.googleapis.com/v1/currentConditions:lookup"
        )

    assert result == {"ok": True}
    req = captured["request"]
    assert "server-test-key" not in req.full_url
    assert req.get_header("X-goog-api-key") == "server-test-key"


def test_air_grid_is_server_generated_and_capped_at_25(mod):
    seen = []

    def sample(lat, lng):
        seen.append((lat, lng))
        return {"indexes": [{"aqi": 42}]}

    with patch.object(mod, "_air_current", side_effect=sample):
        result = mod._dispatch(
            "air_grid",
            {"latitude": 19.076, "longitude": 72.8777, "gridSize": 5},
        )
    assert len(result["samples"]) == 25
    assert len(seen) == 25


def test_air_grid_accepts_only_the_two_v8_grid_sizes(mod):
    with patch.object(mod, "_air_current") as upstream:
        with pytest.raises(ValueError, match="gridSize"):
            mod._dispatch(
                "air_grid",
                {"latitude": 19.076, "longitude": 72.8777, "gridSize": 25},
            )
    upstream.assert_not_called()


def test_air_forecast_is_fixed_to_96_hours(mod):
    with patch.object(mod, "_google_json", return_value={}) as upstream:
        mod._dispatch(
            "air_forecast", {"latitude": 19.076, "longitude": 72.8777}
        )
    request_body = upstream.call_args.kwargs["body"]
    assert request_body["pageSize"] == 96
    start = mod.dt.datetime.fromisoformat(
        request_body["period"]["startTime"].replace("Z", "+00:00")
    )
    end = mod.dt.datetime.fromisoformat(
        request_body["period"]["endTime"].replace("Z", "+00:00")
    )
    assert end - start == mod.dt.timedelta(hours=96)


@pytest.mark.parametrize("hours", [24, 168, 720])
def test_air_history_allows_only_ui_ranges(mod, hours):
    with patch.object(mod, "_google_json", return_value={}) as upstream:
        mod._dispatch(
            "air_history",
            {"latitude": 19.076, "longitude": 72.8777, "hours": hours},
        )
    assert upstream.call_args.kwargs["body"]["hours"] == hours


def test_air_history_rejects_arbitrary_cost_range(mod):
    with patch.object(mod, "_google_json") as upstream:
        with pytest.raises(ValueError, match="history range"):
            mod._dispatch(
                "air_history",
                {"latitude": 19.076, "longitude": 72.8777, "hours": 8760},
            )
    upstream.assert_not_called()


def test_missing_server_key_degrades_to_503_without_exposing_detail(mod):
    mod._key_cache.update({"loaded": True, "key": ""})
    resp = mod.handler(
        event(
            {
                "operation": "weather_current",
                "latitude": 19.076,
                "longitude": 72.8777,
            }
        ),
        None,
    )
    assert resp["statusCode"] == 503
    assert body(resp) == {"error": "provider_unavailable"}


def test_preflight_never_reaches_provider(mod):
    with patch.object(mod, "_dispatch") as dispatch:
        resp = mod.handler(event(method="OPTIONS"), None)
    assert resp["statusCode"] == 204
    dispatch.assert_not_called()


def test_secret_is_lazy_not_read_at_import(mod):
    # A module-level secret read would freeze credentials into a warm container
    # before the first actual request and makes rotation/debugging harder.
    assert mod._secret_client is None
