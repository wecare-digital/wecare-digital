"""Server-side Google Weather and Air Quality gateway for public VayuLok.

The browser key used by Maps JavaScript is intentionally NOT accepted here. Weather
and Air Quality are Google Maps Platform web-service APIs; their credential stays in
AWS Secrets Manager and is sent to Google in the x-goog-api-key header.

Public route:
  POST /vayulok/environment

The route exposes a fixed operation allowlist. A caller cannot supply an upstream URL,
host, HTTP method, API key, field mask, or arbitrary Google request body. Coordinates are
restricted to the same India bounds as the VayuLok map. Browser Origin is checked before
any secret read or provider request; API Gateway adds a second per-route throttle.
"""

from __future__ import annotations

import base64
import concurrent.futures
import datetime as dt
import json
import logging
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
GOOGLE_SECRET_NAME = os.environ.get(
    "VAYULOK_GOOGLE_SECRET", "wecare/google/cloud"
)
GOOGLE_SECRET_FIELD = (
    os.environ.get("VAYULOK_GOOGLE_SECRET_FIELD", "api_key").strip() or "api_key"
)
GOOGLE_TIMEOUT_SECONDS = float(os.environ.get("VAYULOK_GOOGLE_TIMEOUT", "10"))
KEY_CACHE_TTL_SECONDS = max(
    0.0, float(os.environ.get("VAYULOK_KEY_CACHE_TTL", "300"))
)
MAX_REQUEST_BYTES = int(os.environ.get("VAYULOK_MAX_REQUEST_BYTES", "8192"))
MAX_UPSTREAM_BYTES = int(
    os.environ.get("VAYULOK_MAX_UPSTREAM_BYTES", str(6 * 1024 * 1024))
)

WORLD_BOUNDS = {
    "north": 90.0,
    "south": -90.0,
    "west": -180.0,
    "east": 180.0,
}

# Google Weather public-alert coverage, maintained server-side so the browser does not
# need a deploy when provider coverage changes. India intentionally remains unsupported.
WEATHER_ALERT_REGION_CODES = frozenset(
    {
        "AT","AU","BA","BE","BG","BR","CH","CI","CO","CY","CZ","DE","DK","EC","EE","ES",
        "FI","FR","GB","GH","GR","HR","HU","IE","IS","IT","JM","JP","KR","LT","LU","LV",
        "MG","MK","MX","NL","NO","NZ","PH","PL","PT","RO","RS","SB","SE","SG","SI","SK",
        "TH","TW","US","VN",
    }
)

WEATHER_BASE = "https://weather.googleapis.com/v1"
AIR_BASE = "https://airquality.googleapis.com/v1"

OPERATIONS = frozenset(
    {
        "air_current",
        "air_grid",
        "weather_current",
        "weather_hourly",
        "weather_daily",
        "weather_history",
        "weather_alerts",
        "air_forecast",
        "air_history",
    }
)

_COMMON_FIELDS = frozenset({"operation", "latitude", "longitude", "regionCode"})
OPERATION_FIELDS = {
    "air_current": _COMMON_FIELDS,
    "air_grid": _COMMON_FIELDS | {"gridSize"},
    "weather_current": _COMMON_FIELDS,
    "weather_hourly": _COMMON_FIELDS | {"pageToken"},
    "weather_daily": _COMMON_FIELDS,
    "weather_history": _COMMON_FIELDS,
    "weather_alerts": _COMMON_FIELDS,
    "air_forecast": _COMMON_FIELDS,
    "air_history": _COMMON_FIELDS | {"hours", "pageToken"},
}

_secret_client = None
_key_cache: Dict[str, Any] = {"loaded": False, "key": "", "loaded_at": 0.0}
_response_cache: Dict[str, Dict[str, Any]] = {}

CACHE_TTLS = {
    "air_current": 15 * 60,
    "weather_current": 15 * 60,
    "weather_hourly": 30 * 60,
    "weather_daily": 30 * 60,
    "weather_history": 6 * 60 * 60,
    "weather_alerts": 5 * 60,
    "air_forecast": 30 * 60,
    "air_history": 60 * 60,
}


class ProviderUnavailable(RuntimeError):
    pass


class ProviderFailure(RuntimeError):
    def __init__(self, status: int = 502) -> None:
        super().__init__("provider failure")
        self.status = status


def _secrets():
    global _secret_client
    if _secret_client is None:
        _secret_client = boto3.client("secretsmanager", region_name=REGION)
    return _secret_client


def _request_origin(event: Mapping[str, Any]) -> str:
    headers = event.get("headers") or {}
    return str(headers.get("origin") or headers.get("Origin") or "").strip()


def _origin_allowed(event: Mapping[str, Any]) -> bool:
    origin = _request_origin(event)
    if not origin:
        return False
    try:
        parsed = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return host == "wecare.digital" or host.endswith(".wecare.digital")


def _response(event: Mapping[str, Any], status: int, body: Any) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "POST,OPTIONS",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Vary": "Origin",
    }
    if _origin_allowed(event):
        headers["Access-Control-Allow-Origin"] = _request_origin(event)
    return {
        "statusCode": status,
        "headers": headers,
        "body": "" if status == 204 else json.dumps(body, ensure_ascii=False),
    }


def _method_path(event: Mapping[str, Any]) -> tuple[str, str]:
    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    method = str(http.get("method") or event.get("httpMethod") or "GET").upper()
    path = str(http.get("path") or event.get("rawPath") or event.get("path") or "/")
    return method, path.rstrip("/") or "/"


def _body(event: Mapping[str, Any]) -> Dict[str, Any]:
    raw: Any = event.get("body") or "{}"
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("body must be JSON")
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("request body too large")
    if event.get("isBase64Encoded"):
        try:
            encoded = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 body") from exc
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("request body too large")
    try:
        parsed = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON body") from exc
    if not isinstance(parsed, dict):
        raise ValueError("body must be an object")
    return parsed


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _location(payload: Mapping[str, Any]) -> tuple[float, float]:
    lat = _number(payload.get("latitude"), "latitude")
    lng = _number(payload.get("longitude"), "longitude")
    if not (WORLD_BOUNDS["south"] <= lat <= WORLD_BOUNDS["north"]):
        raise ValueError("latitude outside world bounds")
    if not (WORLD_BOUNDS["west"] <= lng <= WORLD_BOUNDS["east"]):
        raise ValueError("longitude outside world bounds")
    return lat, lng


def _region_code(payload: Mapping[str, Any]) -> str:
    value = payload.get("regionCode")
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise ValueError("regionCode must be a string")
    value = value.strip().upper()
    if len(value) != 2 or not value.isalpha():
        raise ValueError("regionCode must be a 2-letter country code")
    return value


def _local_aqi_override(region_code: str) -> Dict[str, Any]:
    return (
        {"customLocalAqis": [{"regionCode": "IN", "aqi": "ind_cpcb"}]}
        if region_code == "IN"
        else {}
    )


def _page_token(payload: Mapping[str, Any]) -> str:
    value = payload.get("pageToken")
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid pageToken")
    return value


def _history_hours(payload: Mapping[str, Any]) -> int:
    value = payload.get("hours", 24)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid history range")
    numeric = float(value)
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError("invalid history range")
    hours = int(numeric)
    if hours not in (24, 168, 720):
        raise ValueError("history range must be 24, 168 or 720 hours")
    return hours


def _grid_size(payload: Mapping[str, Any]) -> int:
    value = payload.get("gridSize", 5)
    if value not in (3, 5):
        raise ValueError("gridSize must be 3 or 5")
    return int(value)


def _validate_payload_fields(operation: str, payload: Mapping[str, Any]) -> None:
    allowed = OPERATION_FIELDS[operation]
    unexpected = sorted(str(key) for key in payload.keys() if key not in allowed)
    if unexpected:
        raise ValueError(f"unexpected field(s): {', '.join(unexpected)}")


def _google_key() -> str:
    now = time.monotonic()
    if _key_cache["loaded"]:
        age = now - float(_key_cache.get("loaded_at") or 0.0)
        if age < KEY_CACHE_TTL_SECONDS:
            return _key_cache["key"]
        _key_cache.update({"loaded": False, "key": "", "loaded_at": 0.0})

    key = ""
    resolved_from = ""
    failure = ""
    try:
        raw = _secrets().get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        data = json.loads(raw.get("SecretString") or "{}")
        if isinstance(data, dict):
            value = str(data.get(GOOGLE_SECRET_FIELD) or "").strip()
            if value:
                key = value
                resolved_from = GOOGLE_SECRET_FIELD
        if not key:
            failure = "missing_server_key_field"
    except Exception as exc:
        failure = type(exc).__name__

    if failure:
        logger.warning(
            json.dumps({"event": "vayulok_google_key_unavailable", "reason": failure})
        )
    elif resolved_from:
        logger.info(
            json.dumps(
                {"event": "vayulok_google_key_resolved", "field": resolved_from}
            )
        )

    # SUCCESS ONLY. Caching the failure path turned one transient GetSecretValue
    # throttle - or a single AccessDeniedException during the provisioning window,
    # before kms:Decrypt is in place - into a warm container that answers 503
    # provider_unavailable for the rest of its life, with no retry. Leaving the
    # cache untouched on failure costs one extra Secrets Manager read per request
    # while the fault lasts and recovers on its own when it clears.
    #
    # The read-side check above stays `_key_cache["loaded"]` rather than a
    # truthiness test on the key: test_missing_server_key_degrades_to_503_without_
    # exposing_detail seeds {"loaded": True, "key": ""} to pin the 503 without a
    # boto3 call, and a truthiness check would send that test to the network.
    if key:
        _key_cache.update({"loaded": True, "key": key, "loaded_at": now})
    return key


def _query(url: str, params: Mapping[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return url + "?" + urllib.parse.urlencode(clean)


def _google_json(
    url: str,
    *,
    method: str = "GET",
    body: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    key = _google_key()
    if not key:
        raise ProviderUnavailable("server Google key unavailable")

    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "X-Goog-Api-Key": key}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=GOOGLE_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_UPSTREAM_BYTES + 1)
    except urllib.error.HTTPError as exc:
        logger.warning(
            json.dumps({"event": "vayulok_google_http_error", "status": int(exc.code)})
        )
        raise ProviderFailure(502) from None
    except Exception as exc:
        logger.warning(
            json.dumps(
                {
                    "event": "vayulok_google_transport_error",
                    "errorType": type(exc).__name__,
                }
            )
        )
        raise ProviderFailure(502) from None

    if len(raw) > MAX_UPSTREAM_BYTES:
        logger.warning(
            json.dumps(
                {"event": "vayulok_google_response_too_large", "bytes": len(raw)}
            )
        )
        raise ProviderFailure(502)

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderFailure(502) from None
    if not isinstance(parsed, dict):
        raise ProviderFailure(502)
    return parsed


def _air_current(lat: float, lng: float, region_code: str = "") -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "location": {"latitude": lat, "longitude": lng},
        # POLLUTANT_ADDITIONAL_INFO keeps the current pollutant Sources / Effects popovers.
        "extraComputations": [
            "POLLUTANT_CONCENTRATION",
            "LOCAL_AQI",
            "HEALTH_RECOMMENDATIONS",
            "DOMINANT_POLLUTANT_CONCENTRATION",
            "POLLUTANT_ADDITIONAL_INFO",
        ],
        "languageCode": "en",
        "universalAqi": True,
    }
    body.update(_local_aqi_override(region_code))
    return _google_json(f"{AIR_BASE}/currentConditions:lookup", method="POST", body=body)


def _air_grid(lat: float, lng: float, grid_size: int) -> Dict[str, Any]:
    # Resolve once before worker threads so the first grid request cannot race four
    # Secrets Manager reads on a cold container.
    if not _google_key():
        raise ProviderUnavailable("server Google key unavailable")

    # The client chooses only 3x3 vs 5x5. Span, cell coordinates, provider request
    # body and max 25 samples are server-owned, so one public call cannot be turned
    # into an arbitrary fan-out proxy.
    span = 0.04
    half = (grid_size - 1) / 2
    cells = [
        (
            lat + ((row - half) / max(1, half)) * span,
            lng + ((col - half) / max(1, half)) * span,
        )
        for row in range(grid_size)
        for col in range(grid_size)
    ][:25]

    def one(cell: tuple[float, float]) -> Dict[str, Any]:
        cell_lat, cell_lng = cell
        # Clamp edge cells to valid world coordinates.
        cell_lat = min(max(cell_lat, WORLD_BOUNDS["south"]), WORLD_BOUNDS["north"])
        cell_lng = min(max(cell_lng, WORLD_BOUNDS["west"]), WORLD_BOUNDS["east"])
        try:
            data = _air_current(cell_lat, cell_lng)
            return {"latitude": cell_lat, "longitude": cell_lng, "data": data}
        except ProviderFailure:
            return {"latitude": cell_lat, "longitude": cell_lng, "data": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        samples = list(pool.map(one, cells))
    return {"samples": samples}


def _cache_key(operation: str, payload: Mapping[str, Any]) -> str:
    material = {
        "operation": operation,
        "latitude": round(float(payload.get("latitude")), 4),
        "longitude": round(float(payload.get("longitude")), 4),
        "regionCode": str(payload.get("regionCode") or "").upper(),
        "hours": payload.get("hours"),
        "pageToken": payload.get("pageToken") or "",
    }
    return json.dumps(material, sort_keys=True, separators=(",", ":"))


def _cached_dispatch(operation: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    ttl = CACHE_TTLS.get(operation, 0)
    key = _cache_key(operation, payload)
    now = time.monotonic()
    cached = _response_cache.get(key)
    if ttl and cached and now - float(cached.get("ts") or 0.0) < ttl:
        return cached["data"]
    data = _dispatch(operation, payload)
    if ttl:
        _response_cache[key] = {"ts": now, "data": data}
    return data


def _dispatch(operation: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    lat, lng = _location(payload)
    region_code = _region_code(payload)

    if operation == "air_current":
        return _air_current(lat, lng, region_code)

    if operation == "air_grid":
        return _air_grid(lat, lng, _grid_size(payload))

    if operation == "weather_current":
        return _google_json(
            _query(
                f"{WEATHER_BASE}/currentConditions:lookup",
                {
                    "location.latitude": lat,
                    "location.longitude": lng,
                    "unitsSystem": "METRIC",
                },
            )
        )

    if operation == "weather_hourly":
        token = _page_token(payload)
        return _google_json(
            _query(
                f"{WEATHER_BASE}/forecast/hours:lookup",
                {
                    "location.latitude": lat,
                    "location.longitude": lng,
                    "hours": 48,
                    "pageSize": 24,
                    "unitsSystem": "METRIC",
                    "languageCode": "en",
                    "pageToken": token,
                },
            )
        )

    if operation == "weather_daily":
        return _google_json(
            _query(
                f"{WEATHER_BASE}/forecast/days:lookup",
                {
                    "location.latitude": lat,
                    "location.longitude": lng,
                    "days": 10,
                    "pageSize": 10,
                    "unitsSystem": "METRIC",
                    "languageCode": "en",
                },
            )
        )

    if operation == "weather_history":
        return _google_json(
            _query(
                f"{WEATHER_BASE}/history/hours:lookup",
                {
                    "location.latitude": lat,
                    "location.longitude": lng,
                    "hours": 24,
                    "pageSize": 24,
                    "unitsSystem": "METRIC",
                    "languageCode": "en",
                },
            )
        )

    if operation == "weather_alerts":
        if region_code and region_code not in WEATHER_ALERT_REGION_CODES:
            return {
                "weatherAlerts": [],
                "regionCode": region_code,
                "alertStatus": "unsupported",
            }
        data = _google_json(
            _query(
                f"{WEATHER_BASE}/publicAlerts:lookup",
                {
                    "location.latitude": lat,
                    "location.longitude": lng,
                    "languageCode": "en",
                },
            )
        )
        rows = data.get("weatherAlerts")
        data["alertStatus"] = "active" if isinstance(rows, list) and rows else "none"
        return data

    if operation == "air_forecast":
        now = dt.datetime.now(dt.timezone.utc)
        start = now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
        # 95h, not 96h: forecast:lookup rejects an exactly-96-hour period with HTTP 400
        # "time period is not supported". 95h still returns ~96 hourly rows. Matches the
        # browser path in src/components/VayuLokLive.tsx. (Measured: 96h => 400, 95h => 200.)
        end = start + dt.timedelta(hours=95)
        request_body: Dict[str, Any] = {
            "location": {"latitude": lat, "longitude": lng},
            "period": {
                "startTime": start.isoformat().replace("+00:00", "Z"),
                "endTime": end.isoformat().replace("+00:00", "Z"),
            },
            "pageSize": 96,
            "universalAqi": True,
            "extraComputations": [
                "LOCAL_AQI",
                "POLLUTANT_CONCENTRATION",
                "DOMINANT_POLLUTANT_CONCENTRATION",
                "POLLUTANT_ADDITIONAL_INFO",
            ],
            "languageCode": "en",
        }
        request_body.update(_local_aqi_override(region_code))
        return _google_json(
            f"{AIR_BASE}/forecast:lookup",
            method="POST",
            body=request_body,
        )

    if operation == "air_history":
        hours = _history_hours(payload)
        token = _page_token(payload)
        request_body: Dict[str, Any] = {
            "location": {"latitude": lat, "longitude": lng},
            "hours": hours,
            "pageSize": min(100, hours),
            "universalAqi": True,
            "extraComputations": [
                "LOCAL_AQI",
                "POLLUTANT_CONCENTRATION",
                "DOMINANT_POLLUTANT_CONCENTRATION",
                "POLLUTANT_ADDITIONAL_INFO",
            ],
            "languageCode": "en",
        }
        request_body.update(_local_aqi_override(region_code))
        if token:
            request_body["pageToken"] = token
        return _google_json(
            f"{AIR_BASE}/history:lookup", method="POST", body=request_body
        )

    raise ValueError("unsupported operation")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:  # noqa: ARG001
    method, path = _method_path(event)
    if path != "/vayulok/environment":
        return _response(event, 404, {"error": "not_found"})

    if method == "OPTIONS":
        if not _origin_allowed(event):
            return _response(event, 403, {"error": "origin_not_allowed"})
        return _response(event, 204, {})

    if method != "POST":
        return _response(event, 405, {"error": "method_not_allowed"})

    # Before _body(), _google_key() and _dispatch(): an off-origin request cannot
    # make us read a secret or spend a provider request.
    if not _origin_allowed(event):
        return _response(event, 403, {"error": "origin_not_allowed"})

    try:
        payload = _body(event)
        operation = payload.get("operation")
        if not isinstance(operation, str) or operation not in OPERATIONS:
            raise ValueError("unsupported operation")
        _validate_payload_fields(operation, payload)
        return _response(event, 200, _cached_dispatch(operation, payload))
    except ValueError as exc:
        return _response(
            event, 400, {"error": "invalid_request", "detail": str(exc)}
        )
    except ProviderUnavailable:
        return _response(event, 503, {"error": "provider_unavailable"})
    except ProviderFailure as exc:
        return _response(event, exc.status, {"error": "provider_failed"})
