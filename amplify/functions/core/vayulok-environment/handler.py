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
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Mapping, Optional, Tuple

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
GOOGLE_SECRET_NAME = os.environ.get(
    "VAYULOK_GOOGLE_SECRET", "wecare/google-maps-server"
)
GOOGLE_SECRET_FIELDS: Tuple[str, ...] = tuple(
    part.strip()
    for part in os.environ.get(
        "VAYULOK_GOOGLE_SECRET_FIELDS", "api_key,unified_google_api_key"
    ).split(",")
    if part.strip()
)
GOOGLE_TIMEOUT_SECONDS = float(os.environ.get("VAYULOK_GOOGLE_TIMEOUT", "10"))
MAX_REQUEST_BYTES = int(os.environ.get("VAYULOK_MAX_REQUEST_BYTES", "8192"))
MAX_UPSTREAM_BYTES = int(
    os.environ.get("VAYULOK_MAX_UPSTREAM_BYTES", str(6 * 1024 * 1024))
)

INDIA_BOUNDS = {
    "north": 37.6,
    "south": 6.4,
    "west": 68.1,
    "east": 97.4,
}

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
        "air_forecast",
        "air_history",
    }
)

_secret_client = None
_key_cache: Dict[str, Any] = {"loaded": False, "key": ""}


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
    if not (INDIA_BOUNDS["south"] <= lat <= INDIA_BOUNDS["north"]):
        raise ValueError("latitude outside VayuLok India bounds")
    if not (INDIA_BOUNDS["west"] <= lng <= INDIA_BOUNDS["east"]):
        raise ValueError("longitude outside VayuLok India bounds")
    return lat, lng


def _page_token(payload: Mapping[str, Any]) -> str:
    value = payload.get("pageToken")
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid pageToken")
    return value


def _history_hours(payload: Mapping[str, Any]) -> int:
    value = payload.get("hours", 24)
    if isinstance(value, bool):
        raise ValueError("invalid history range")
    try:
        hours = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid history range") from exc
    if hours not in (24, 168, 720):
        raise ValueError("history range must be 24, 168 or 720 hours")
    return hours


def _grid_size(payload: Mapping[str, Any]) -> int:
    value = payload.get("gridSize", 5)
    if value not in (3, 5):
        raise ValueError("gridSize must be 3 or 5")
    return int(value)


def _google_key() -> str:
    if _key_cache["loaded"]:
        return _key_cache["key"]

    key = ""
    resolved_from = ""
    failure = ""
    try:
        raw = _secrets().get_secret_value(SecretId=GOOGLE_SECRET_NAME)
        data = json.loads(raw.get("SecretString") or "{}")
        if isinstance(data, dict):
            for field in GOOGLE_SECRET_FIELDS:
                value = str(data.get(field) or "").strip()
                if value:
                    key = value
                    resolved_from = field
                    break
        if not key:
            failure = "no_candidate_field"
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

    _key_cache.update({"loaded": True, "key": key})
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


def _air_current(lat: float, lng: float) -> Dict[str, Any]:
    return _google_json(
        f"{AIR_BASE}/currentConditions:lookup",
        method="POST",
        body={
            "location": {"latitude": lat, "longitude": lng},
            "extraComputations": [
                "POLLUTANT_CONCENTRATION",
                "LOCAL_AQI",
                "HEALTH_RECOMMENDATIONS",
                "DOMINANT_POLLUTANT_CONCENTRATION",
            ],
            "languageCode": "en",
            "universalAqi": True,
        },
    )


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
        # Edge cells can cross the product bounds when the selected point sits
        # exactly on the border. Clamp rather than ask Google outside India.
        cell_lat = min(max(cell_lat, INDIA_BOUNDS["south"]), INDIA_BOUNDS["north"])
        cell_lng = min(max(cell_lng, INDIA_BOUNDS["west"]), INDIA_BOUNDS["east"])
        try:
            data = _air_current(cell_lat, cell_lng)
            return {"latitude": cell_lat, "longitude": cell_lng, "data": data}
        except ProviderFailure:
            return {"latitude": cell_lat, "longitude": cell_lng, "data": None}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        samples = list(pool.map(one, cells))
    return {"samples": samples}


def _dispatch(operation: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    lat, lng = _location(payload)

    if operation == "air_current":
        return _air_current(lat, lng)

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

    if operation == "air_forecast":
        now = dt.datetime.now(dt.timezone.utc)
        start = now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
        end = start + dt.timedelta(hours=96)
        return _google_json(
            f"{AIR_BASE}/forecast:lookup",
            method="POST",
            body={
                "location": {"latitude": lat, "longitude": lng},
                "period": {
                    "startTime": start.isoformat().replace("+00:00", "Z"),
                    "endTime": end.isoformat().replace("+00:00", "Z"),
                },
                "pageSize": 96,
                "universalAqi": True,
                "customLocalAqis": [{"regionCode": "IN", "aqi": "ind_cpcb"}],
                "extraComputations": [
                    "LOCAL_AQI",
                    "POLLUTANT_CONCENTRATION",
                    "DOMINANT_POLLUTANT_CONCENTRATION",
                ],
                "languageCode": "en",
            },
        )

    if operation == "air_history":
        hours = _history_hours(payload)
        token = _page_token(payload)
        request_body: Dict[str, Any] = {
            "location": {"latitude": lat, "longitude": lng},
            "hours": hours,
            "pageSize": min(100, hours),
            "universalAqi": True,
            "customLocalAqis": [{"regionCode": "IN", "aqi": "ind_cpcb"}],
            "extraComputations": ["LOCAL_AQI", "POLLUTANT_CONCENTRATION"],
            "languageCode": "en",
        }
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
        return _response(event, 200, _dispatch(operation, payload))
    except ValueError as exc:
        return _response(
            event, 400, {"error": "invalid_request", "detail": str(exc)}
        )
    except ProviderUnavailable:
        return _response(event, 503, {"error": "provider_unavailable"})
    except ProviderFailure as exc:
        return _response(event, exc.status, {"error": "provider_failed"})
