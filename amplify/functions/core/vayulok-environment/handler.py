"""Server-side Google Weather, Air Quality and Routes gateway for public VayuLok.

The browser key used by Maps JavaScript is intentionally NOT accepted here. Weather, Air Quality and Routes are Google Maps Platform web-service APIs; their credential stays in
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
import csv
import io
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
ROUTES_BASE = "https://routes.googleapis.com/directions/v2"

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
        "route_drive",
        "location_context",
    }
)

_COMMON_FIELDS = frozenset({"operation", "latitude", "longitude", "regionCode"})
OPERATION_FIELDS = {
    "location_context": _COMMON_FIELDS | {"buildingCandidate"},
    "air_current": _COMMON_FIELDS,
    "air_grid": _COMMON_FIELDS | {"gridSize"},
    "weather_current": _COMMON_FIELDS,
    "weather_hourly": _COMMON_FIELDS | {"pageToken"},
    "weather_daily": _COMMON_FIELDS,
    "weather_history": _COMMON_FIELDS,
    "weather_alerts": _COMMON_FIELDS,
    "air_forecast": _COMMON_FIELDS,
    "air_history": _COMMON_FIELDS | {"hours", "pageToken"},
    "route_drive": {
        "operation",
        "originLatitude",
        "originLongitude",
        "destinationLatitude",
        "destinationLongitude",
    },
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
    # TRAFFIC_UNAWARE route results are stable enough to reuse for identical endpoints,
    # reducing repeated billable Compute Routes events.
    "route_drive": 6 * 60 * 60,
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
    # HTTP API custom-domain rewrites may still surface the deployed stage prefix
    # (for example /prod/vayulok/environment) in requestContext.http.path. Normalize
    # only the exact requestContext stage prefix so routing stays strict.
    stage = str(rc.get("stage") or "").strip("/")
    if stage and path.startswith(f"/{stage}/"):
        path = path[len(stage) + 1 :]
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


def _route_locations(
    payload: Mapping[str, Any],
) -> tuple[tuple[float, float], tuple[float, float]]:
    origin = {
        "latitude": payload.get("originLatitude"),
        "longitude": payload.get("originLongitude"),
    }
    destination = {
        "latitude": payload.get("destinationLatitude"),
        "longitude": payload.get("destinationLongitude"),
    }
    return _location(origin), _location(destination)


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
    field_mask: str = "",
) -> Dict[str, Any]:
    key = _google_key()
    if not key:
        raise ProviderUnavailable("server Google key unavailable")

    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "X-Goog-Api-Key": key}
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask
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


def _route_drive(payload: Mapping[str, Any]) -> Dict[str, Any]:
    (origin_lat, origin_lng), (destination_lat, destination_lng) = _route_locations(
        payload
    )
    request_body = {
        "origin": {
            "location": {
                "latLng": {"latitude": origin_lat, "longitude": origin_lng}
            }
        },
        "destination": {
            "location": {
                "latLng": {
                    "latitude": destination_lat,
                    "longitude": destination_lng,
                }
            }
        },
        "travelMode": "DRIVE",
        # Keep this on Compute Routes Essentials (India): no traffic-aware routing,
        # tolls, two-wheeler or other higher-SKU features.
        "routingPreference": "TRAFFIC_UNAWARE",
        "computeAlternativeRoutes": False,
        "units": "METRIC",
    }
    return _google_json(
        f"{ROUTES_BASE}:computeRoutes",
        method="POST",
        body=request_body,
        field_mask="routes.duration,routes.distanceMeters",
    )


def _cache_key(operation: str, payload: Mapping[str, Any]) -> str:
    if operation == "route_drive":
        (origin_lat, origin_lng), (destination_lat, destination_lng) = _route_locations(
            payload
        )
        material = {
            "operation": operation,
            "originLatitude": round(origin_lat, 5),
            "originLongitude": round(origin_lng, 5),
            "destinationLatitude": round(destination_lat, 5),
            "destinationLongitude": round(destination_lng, 5),
        }
    else:
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


# Additional environmental sources use the existing gateway, never a browser
# credential or an arbitrary caller-supplied URL. Enable only after the live
# deployment's credentials, provider terms and budget-table permissions are verified.
# All attempted upstream requests consume a reservation, including HTTP failures.
EXTRA_SOURCES = frozenset(
    x.strip() for x in os.environ.get("VAYULOK_EXTENDED_SOURCES", "").split(",")
    if x.strip()
)
EXTRA_BUDGET_TABLE = os.environ.get("VAYULOK_EXTENDED_BUDGET_TABLE", "")
CPCB_SECRET = os.environ.get("VAYULOK_CPCB_SECRET", "")
RATE_TABLE = "stack-wecare-digital-RateLimitTable"
EXTRA_LIMITS = {
    "elevation": (100, 3100),
    "cpcb": (24, 744),
    "pvgis": (250, 7750),
    "solar": (250, 7750),
    "spartan": (12, 372),
}
BUDGET_PREFIX = "nano-climate:environment:"
CPCB_URL = "https://api.data.gov.in/resource/3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69"
PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"
ELEVATION_URL = "https://maps.googleapis.com/maps/api/elevation/json"
BUILDING_INSIGHTS_URL = "https://solar.googleapis.com/v1/buildingInsights:findClosest"
SPARTAN_BASE = "https://spartan-cloud.s3.us-west-2.amazonaws.com/"
# These are the three India site/product combinations verified from the actual
# public S3 listing and CSV headers. The Kanpur product is an estimate, not a
# direct filter mass measurement. No coverage is extrapolated beyond these sites.
SPARTAN_SITES = (
    ("INDH", "Delhi", 28.545, 77.1926,
     "GroupBySite/INDH/FilterBased_ReconstrPM25_INDH.csv", "filter"),
    ("INJA", "Jaipur", 26.90582, 75.80622,
     "GroupBySite/INJA/FilterBased_ReconstrPM25_INJA.csv", "filter"),
    ("INKA", "Kanpur", 26.5128, 80.2316,
     "GroupBySite/INKA/TimeResPM25_DailyEstPM25_INKA.csv", "estimate"),
)
_IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_extra_cache: Dict[str, tuple[float, Any]] = {}
_extra_dynamo = None


class ExtraBudgetExhausted(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a query-string secret or provider API-key header to
        # a redirect destination, even if an upstream response is compromised.
        return None


def _extra_read(url: str, headers: Optional[Mapping[str, str]] = None,
                limit: int = MAX_UPSTREAM_BYTES) -> bytes:
    request = urllib.request.Request(
        url, headers={"Accept": "*/*", **(headers or {})}, method="GET"
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(
            request, timeout=min(GOOGLE_TIMEOUT_SECONDS, 8.0)
        ) as response:
            body = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise ProviderFailure(404 if exc.code == 404 else 502) from None
    except Exception:
        raise ProviderFailure(502) from None
    if len(body) > limit:
        raise ProviderFailure(502)
    return body


def _extra_json(url: str, headers: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    try:
        data = json.loads(_extra_read(url, headers).decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ProviderFailure(502) from None
    if not isinstance(data, dict):
        raise ProviderFailure(502)
    return data


def _reserve_extra(source: str) -> None:
    """Atomic, shared UTC daily AND calendar-month reservations; fail closed.

    The live RateLimit table has string partition key id, no sort key, and
    PAY_PER_REQUEST billing. Use a dedicated prefix and independent attributes.
    No dependence on TTL (currently disabled on the live table). The two
    conditional updates are one DynamoDB transaction; never refund a failure.
    """
    global _extra_dynamo
    if source not in EXTRA_SOURCES or EXTRA_BUDGET_TABLE != RATE_TABLE:
        raise ProviderUnavailable("extended source or budget not configured")
    day_cap, month_cap = EXTRA_LIMITS[source]
    now = dt.datetime.now(dt.timezone.utc)
    windows = (
        ("day:" + now.strftime("%Y-%m-%d"), day_cap),
        ("month:" + now.strftime("%Y-%m"), month_cap),
    )
    items = []
    for window, cap in windows:
        items.append({"Update": {
            "TableName": EXTRA_BUDGET_TABLE,
            "Key": {"id": {"S": BUDGET_PREFIX + source + ":" + window}},
            "UpdateExpression": "SET #count = if_not_exists(#count, :zero) + :one, lastUpdatedAt = :expiry",
            "ConditionExpression": "attribute_not_exists(#count) OR #count < :cap",
            "ExpressionAttributeNames": {"#count": "providerAttempts"},
            "ExpressionAttributeValues": {
                ":zero": {"N": "0"}, ":one": {"N": "1"}, ":cap": {"N": str(cap)},
                # Retain monthly rows well past their active window if TTL is
                # ever re-enabled; never let a live counter expire early.
                ":expiry": {"N": str(int(now.timestamp()) + 93 * 86400)},
            },
        }})
    try:
        if _extra_dynamo is None:
            _extra_dynamo = boto3.client("dynamodb", region_name=REGION)
        _extra_dynamo.transact_write_items(TransactItems=items)
    except Exception as exc:
        # A conditional failure means the limit was reached. Unknown failures,
        # denied access and transaction conflicts are also fail-closed.
        error = getattr(exc, "response", {}) or {}
        if any(r.get("Code") == "ConditionalCheckFailed"
               for r in error.get("CancellationReasons", []) if isinstance(r, dict)):
            raise ExtraBudgetExhausted("provider budget reached") from None
        logger.warning("nano_climate_budget_unavailable source=%s type=%s", source, type(exc).__name__)
        raise ProviderUnavailable("budget unavailable") from None


def _extra_cached(key: str, ttl: int) -> Any:
    item = _extra_cache.get(key)
    return item[1] if item and time.monotonic() - item[0] < ttl else None


def _extra_store(key: str, value: Any) -> None:
    # Only open data products enter this cache. No Elevation or Solar API
    # content is stored here or in a persistent browser/server cache.
    if len(_extra_cache) >= 128 and key not in _extra_cache:
        _extra_cache.pop(next(iter(_extra_cache)))
    _extra_cache[key] = (time.monotonic(), value)


def _finite(value: Any, minimum: float = -math.inf,
            maximum: float = math.inf) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def _extra_distance(lat: float, lng: float, other_lat: float, other_lng: float) -> float:
    a = (math.sin(math.radians(other_lat - lat) / 2) ** 2
         + math.cos(math.radians(lat)) * math.cos(math.radians(other_lat))
         * math.sin(math.radians(other_lng - lng) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _elevation_context(lat: float, lng: float) -> Dict[str, Any]:
    key = _google_key()
    if not key:
        raise ProviderUnavailable("Google server key unavailable")
    _reserve_extra("elevation")
    data = _extra_json(_query(ELEVATION_URL, {
        "locations": f"{lat},{lng}", "key": key,
    }))
    if data.get("status") == "ZERO_RESULTS":
        return {"status": "no_data"}
    rows = data.get("results")
    if data.get("status") != "OK" or not isinstance(rows, list) or len(rows) != 1:
        raise ProviderFailure()
    row = rows[0]
    elevation = _finite(row.get("elevation"), -12000, 10000)
    if elevation is None:
        raise ProviderFailure()
    return {"status": "ok", "elevationM": elevation,
            "resolutionM": _finite(row.get("resolution"), 0)}


def _cpcb_key() -> str:
    if CPCB_SECRET != "wecare/nano-climate/cpcb":
        raise ProviderUnavailable("CPCB secret not configured")
    try:
        data = json.loads(_secrets().get_secret_value(SecretId=CPCB_SECRET).get("SecretString") or "{}")
        key = data.get("api_key") if isinstance(data, dict) else None
        if isinstance(key, str) and key.strip():
            return key.strip()
    except Exception:
        pass
    raise ProviderUnavailable("CPCB API key unavailable")


def _cpcb_snapshot() -> list:
    cached = _extra_cached("cpcb:national", 3600)
    if cached is not None:
        return cached
    key = _cpcb_key()
    _reserve_extra("cpcb")
    # One bounded nationwide snapshot: no caller-controlled filters, no
    # station-by-station fan-out or unbounded pagination.
    response = _extra_json(_query(CPCB_URL, {
        "api-key": key, "format": "json", "limit": 10000, "offset": 0,
    }))
    rows = response.get("records")
    total = _finite(response.get("total"), 0, 10000)
    # Never silently choose a "nearest" station from a truncated snapshot.
    if not isinstance(rows, list) or total is None or total != len(rows) or len(rows) > 10000:
        raise ProviderFailure()
    _extra_store("cpcb:national", rows)
    return rows


def _cpcb_timestamp(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.strptime(value.strip(), "%d-%m-%Y %H:%M:%S").replace(tzinfo=_IST)
    except ValueError:
        return None


def _cpcb_context(lat: float, lng: float, rows: list,
                  now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    stations: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or str(row.get("country", "")).strip().lower() != "india":
            continue
        slat = _finite(row.get("latitude"), 6, 38)
        slng = _finite(row.get("longitude"), 67, 98)
        name = row.get("station")
        city = row.get("city")
        if slat is None or slng is None or not isinstance(name, str) or not name.strip():
            continue
        code = str(row.get("pollutant_id", "")).strip().upper().replace(" ", "")
        if code not in ("PM2.5", "PM10", "PM25"):
            continue
        code = "PM2.5" if code == "PM25" else code
        observed = _cpcb_timestamp(row.get("last_update"))
        average = _finite(row.get("pollutant_avg"), 0)
        if observed is None or average is None:
            continue
        age = (now - observed).total_seconds()
        if age < -300 or age > 48 * 3600:
            continue
        distance = _extra_distance(lat, lng, slat, slng)
        if distance > 25:
            continue
        # The public resource does not guarantee a per-record unit. Display
        # only units explicitly returned; do not turn a source value into AQI.
        supplied_unit = str(row.get("unit") or row.get("pollutant_unit") or "").strip()
        unit = "µg/m³" if supplied_unit.lower().replace(" ", "") in (
            "ug/m3", "µg/m³", "μg/m³", "µg/m3", "microgramspercubicmeter"
        ) else None
        identity = (name.strip()[:200], slat, slng)
        station = stations.setdefault(identity, {
            "station": identity[0], "city": city[:120] if isinstance(city, str) else "",
            "distanceKm": distance, "readings": {},
        })
        reading = {
            "pollutant": code, "average": average, "unit": unit,
            "observedAt": observed.isoformat(), "stale": age > 3 * 3600,
        }
        old = station["readings"].get(code)
        if old is None or observed > dt.datetime.fromisoformat(old["observedAt"]):
            station["readings"][code] = reading
    if not stations:
        return {"status": "no_data"}
    closest = min(stations.values(), key=lambda x: x["distanceKm"])
    return {"status": "ok", "station": closest["station"], "city": closest["city"],
            "distanceKm": round(closest["distanceKm"], 2),
            "readings": list(closest["readings"].values())}


def _pvgis_summary(data: Mapping[str, Any], lat: float, lng: float) -> Dict[str, Any]:
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        raise ProviderFailure()
    totals = outputs.get("totals") or {}
    fixed = totals.get("fixed") or {}
    annual = _finite(fixed.get("E_y"), 0)
    irradiation = _finite(fixed.get("H(i)_y"), 0)
    if annual is None or irradiation is None:
        raise ProviderFailure()
    monthly = []
    for row in (outputs.get("monthly") or {}).get("fixed") or []:
        if not isinstance(row, dict):
            continue
        month = _finite(row.get("month"), 1, 12)
        energy = _finite(row.get("E_m"), 0)
        if month is not None and month.is_integer() and energy is not None:
            monthly.append({"month": int(month), "energyKwh": energy})
    if sorted(x["month"] for x in monthly) != list(range(1, 13)):
        monthly = []
    return {"status": "ok", "annualEnergyKwh": annual,
            "annualIrradianceKwhM2": irradiation, "peakPowerKw": 3,
            "lossPct": 14, "gridLat": lat, "gridLng": lng, "monthly": monthly}


def _pvgis_context(lat: float, lng: float) -> Dict[str, Any]:
    # A ~1 km grid is appropriate for a regional resource estimate; never
    # pass it off as a roof-level survey. PVGIS permits reuse with attribution.
    glat, glng = round(lat, 2), round(lng, 2)
    cache_key = f"pvgis:{glat:.2f}:{glng:.2f}"
    cached = _extra_cached(cache_key, 7 * 86400)
    if cached is not None:
        return cached
    _reserve_extra("pvgis")
    data = _extra_json(_query(PVGIS_URL, {
        "lat": glat, "lon": glng, "peakpower": 3, "loss": 14,
        "optimalinclination": 1, "outputformat": "json",
    }))
    result = _pvgis_summary(data, glat, glng)
    _extra_store(cache_key, result)
    return result


def _solar_summary(data: Mapping[str, Any], lat: float, lng: float) -> Dict[str, Any]:
    center = data.get("center") or {}
    clat = _finite(center.get("latitude"), -90, 90)
    clng = _finite(center.get("longitude"), -180, 180)
    potential = data.get("solarPotential") or {}
    capacity = _finite(potential.get("panelCapacityWatts"), 1)
    configs = potential.get("solarPanelConfigs") or []
    if clat is None or clng is None or capacity is None or not isinstance(configs, list):
        raise ProviderFailure()
    distance = _extra_distance(lat, lng, clat, clng)
    if distance > .075:
        return {"status": "no_data"}
    valid = []
    for row in configs:
        if not isinstance(row, dict):
            continue
        panels = _finite(row.get("panelsCount"), 1)
        energy = _finite(row.get("yearlyEnergyDcKwh"), 0)
        if panels is not None and panels.is_integer() and energy is not None:
            valid.append((int(panels), energy))
    if not valid:
        return {"status": "no_data"}
    panels, energy = max(valid, key=lambda x: x[0])
    imagery = data.get("imageryDate") or {}
    try:
        imagery_date = dt.date(imagery["year"], imagery["month"], imagery["day"]).isoformat()
    except (KeyError, TypeError, ValueError):
        imagery_date = None
    return {"status": "ok", "panels": panels, "panelCapacityW": capacity,
            "annualEnergyDcKwh": energy, "distanceM": round(distance * 1000, 1),
            "imageryDate": imagery_date, "quality": data.get("imageryQuality")}


def _solar_context(lat: float, lng: float) -> Dict[str, Any]:
    # An explicit server-side source enable plus a successful shared budget
    # reservation is mandatory BEFORE the sole permitted Solar API operation.
    key = _google_key()
    if not key:
        raise ProviderUnavailable("Google server key unavailable")
    _reserve_extra("solar")
    return _solar_summary(_extra_json(_query(BUILDING_INSIGHTS_URL, {
        "location.latitude": lat, "location.longitude": lng,
        "requiredQuality": "MEDIUM",
    }), {"X-Goog-Api-Key": key}), lat, lng)


def _spartan_summary(text: str, site: tuple, distance: float) -> Dict[str, Any]:
    code, name, _, _, _, method = site
    # Filter-based product includes a metadata comment preamble. The daily
    # estimate uses a non-comment preamble. Locate the verified CSV header.
    lines = text.splitlines(keepends=True)
    header = next((i for i, line in enumerate(lines) if line.startswith("Site_Code,")), None)
    if header is None:
        raise ProviderFailure()
    latest = None
    today = dt.datetime.now(_IST).date()
    for row in csv.DictReader(io.StringIO("".join(lines[header:]))):
        if row.get("Site_Code") != code:
            continue
        expected = "28101" if method == "filter" else "28108"
        if row.get("Parameter_Code") != expected or str(row.get("Flag") or "").strip():
            continue
        if row.get("Units") != "Micrograms per cubic meter (ug/m3)":
            continue
        value = _finite(row.get("Value"), 0)
        hours = _finite(row.get("Hours_sampled"), .01, 24 * 30)
        if value is None or hours is None:
            continue
        try:
            if method == "filter":
                start = dt.date(int(row["Start_Year_local"]), int(row["Start_Month_local"]), int(row["Start_Day_local"]))
                end = dt.date(int(row["End_Year_local"]), int(row["End_Month_local"]), int(row["End_Day_local"]))
            else:
                start = end = dt.date(int(row["Year_local"]), int(row["Month_local"]), int(row["Day_local"]))
        except (KeyError, TypeError, ValueError):
            continue
        if end < start or end > today:
            continue
        if latest is None or end > latest[0]:
            latest = (end, start, value, hours)
    if latest is None:
        return {"status": "no_data"}
    end, start, value, hours = latest
    return {"status": "ok", "site": name, "siteCode": code,
            "distanceKm": round(distance, 2), "startDate": start.isoformat(),
            "endDate": end.isoformat(), "pm25UgM3": value,
            "hoursSampled": hours, "method": method}


def _spartan_context(lat: float, lng: float) -> Dict[str, Any]:
    nearest = min(SPARTAN_SITES, key=lambda s: _extra_distance(lat, lng, s[2], s[3]))
    distance = _extra_distance(lat, lng, nearest[2], nearest[3])
    if distance > 50:
        return {"status": "no_data"}
    cache_key = "spartan:" + nearest[0]
    text = _extra_cached(cache_key, 24 * 3600)
    if text is None:
        _reserve_extra("spartan")
        text = _extra_read(SPARTAN_BASE + nearest[4], limit=2 * 1024 * 1024).decode("utf-8-sig")
        _extra_store(cache_key, text)
    return _spartan_summary(text, nearest, distance)


def _location_context(lat: float, lng: float, region_code: str,
                      payload: Mapping[str, Any]) -> Dict[str, Any]:
    building = payload.get("buildingCandidate", False)
    if not isinstance(building, bool):
        raise ValueError("buildingCandidate must be boolean")
    india = region_code == "IN" and 6 <= lat <= 38 and 67 <= lng <= 98
    operations = {
        "elevation": lambda: _elevation_context(lat, lng),
        "cpcb": lambda: _cpcb_context(lat, lng, _cpcb_snapshot()) if india else {"status": "no_data"},
        "pvgis": lambda: _pvgis_context(lat, lng),
        "solar": lambda: _solar_context(lat, lng) if building else {"status": "select_building"},
        "spartan": lambda: _spartan_context(lat, lng) if india else {"status": "no_data"},
    }

    def run(source: str) -> tuple[str, Dict[str, Any]]:
        if source not in EXTRA_SOURCES:
            return source, {"status": "disabled"}
        # Fail closed even on a cached open-data read if deployment has not
        # configured the shared budget table. Other providers remain independent.
        if EXTRA_BUDGET_TABLE != RATE_TABLE:
            return source, {"status": "unavailable"}
        try:
            return source, operations[source]()
        except ExtraBudgetExhausted:
            return source, {"status": "budget_limited"}
        except ProviderFailure as exc:
            return source, {"status": "no_data" if exc.status == 404 else "unavailable"}
        except Exception as exc:
            logger.warning("nano_climate_source_unavailable source=%s type=%s", source, type(exc).__name__)
            return source, {"status": "unavailable"}

    # All fixed operations run independently; failure of one provider must
    # never suppress another. The existing HTTP API route throttle is retained.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = dict(pool.map(run, operations))
    return {"sources": results, "latitude": lat, "longitude": lng}


def _dispatch(operation: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    if operation == "route_drive":
        return _route_drive(payload)

    lat, lng = _location(payload)
    region_code = _region_code(payload)

    if operation == "location_context":
        return _location_context(lat, lng, region_code, payload)

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
