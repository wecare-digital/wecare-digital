"""
Standardized CORS headers and HTTP response formatting.

Usage:
    from lambda_utils.response import cors_response, options_response

    def handler(event, context):
        if event.get('requestContext', {}).get('http', {}).get('method') == 'OPTIONS':
            return options_response()
        return cors_response(200, {'message': 'OK'})
"""

import json
from typing import Any, Dict, Optional

# Allowed origins — production only (use APP_ENV=development for localhost)
import os as _os

# ORDER MATTERS: cors_headers() falls back to ALLOWED_ORIGINS[0] when the request
# origin is not allowed, so the first entry is the canonical host. It used to be
# retired legacy frontend host, which now 301s to the apex - a redirect is not a usable
# Access-Control-Allow-Origin value, because the browser compares it to the actual
# request origin and never follows it. The apex is first for that reason.
#
# retired legacy frontend host was removed when the hostname was retired: Amplify serves
# the apex directly, and the subdomain was a 301 to it.
# app.wecare.digital was removed on 2026-09-28 when that host was retired: the bucket,
# the CloudFront distribution (ERCXSFDL0VM8X) and the DNS record were all deleted, so the
# origin is NXDOMAIN. An allow-list entry for a hostname nobody resolves is a standing
# offer to whoever can next claim the name - the same reasoning that removed
# retired legacy frontend host above.
_PROD_ORIGINS = [
    'https://wecare.digital',
    'https://www.wecare.digital',
]

ALLOWED_ORIGINS = (
    _PROD_ORIGINS + ['http://localhost:3000']
    if _os.environ.get('APP_ENV', 'production') != 'production'
    else _PROD_ORIGINS
)

DEFAULT_METHODS = 'GET,POST,PUT,DELETE,OPTIONS'
DEFAULT_HEADERS = 'Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Razorpay-Signature'


def cors_headers(
    origin: Optional[str] = None,
    methods: str = DEFAULT_METHODS,
    extra_headers: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build CORS headers. If the request origin is in ALLOWED_ORIGINS,
    reflect it back; otherwise fall back to the primary domain.
    """
    allowed = origin if origin in ALLOWED_ORIGINS else ALLOWED_ORIGINS[0]
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': allowed,
        'Access-Control-Allow-Headers': extra_headers or DEFAULT_HEADERS,
        'Access-Control-Allow-Methods': methods,
    }
    return headers


def cors_response(
    status_code: int,
    body: Any,
    origin: Optional[str] = None,
    methods: str = DEFAULT_METHODS,
) -> Dict[str, Any]:
    """Return a properly formatted API Gateway / Function URL response."""
    return {
        'statusCode': status_code,
        'headers': cors_headers(origin, methods),
        'body': json.dumps(body, default=str),
    }


def options_response(origin: Optional[str] = None) -> Dict[str, Any]:
    """Shortcut for CORS preflight responses."""
    return cors_response(200, {}, origin)


def extract_origin(event: Dict[str, Any]) -> str:
    """Extract the Origin header from an API Gateway / Function URL event."""
    headers = event.get('headers', {})
    return headers.get('origin', headers.get('Origin', ''))


def error_response(
    status_code: int,
    message: str,
    origin: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Standardized error response format.
    All Lambda functions should use this for consistent error shapes.
    """
    body: Dict[str, Any] = {'error': message, 'statusCode': status_code}
    if details:
        body['details'] = details
    return cors_response(status_code, body, origin)
