"""The client IP for per-IP throttles, behind an optional trusted reverse proxy.

`requestContext.http.sourceIp` is the connecting peer. Requests that come through the Amplify
`/api` rewrite arrive from a few AWS proxy addresses, so every customer behind that proxy
shares one per-IP bucket, while a caller of the execute-api endpoint gets its own.

`TRUSTED_PROXY_CIDRS` (comma- or space-separated, default empty) lists the proxy addresses.
When the peer is inside that list, the client is the right-most `X-Forwarded-For` entry that
is not itself a trusted proxy. Entries further left are written by the client and are never
used. A malformed entry at that point stops the walk and the peer is returned. With the
default empty list the peer is returned, as before.

List only the proxies' own addresses. A wide range (for example a whole cloud region) would
let a caller inside it choose its bucket with a spoofed header.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

TRUSTED_PROXY_ENV = "TRUSTED_PROXY_CIDRS"

_Network = Any  # ipaddress.IPv4Network | ipaddress.IPv6Network
_parsed: Dict[str, Tuple[_Network, ...]] = {}


def trusted_proxies(raw: Optional[str] = None) -> Tuple[_Network, ...]:
    """The trusted proxy networks from `raw`, or from the environment. Bad entries are dropped."""
    text = os.environ.get(TRUSTED_PROXY_ENV, "") if raw is None else raw
    if text not in _parsed:
        networks: List[_Network] = []
        invalid = 0
        for part in re.split(r"[\s,]+", text.strip()):
            if not part:
                continue
            try:
                networks.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                invalid += 1
        if invalid:
            logger.warning('{"event":"trusted_proxy_cidrs_invalid","count":%d}', invalid)
        _parsed[text] = tuple(networks)
    return _parsed[text]


def parse_ip(value: Any) -> Optional[Any]:
    """The address in one `X-Forwarded-For` entry, or None.

    Accepts `a.b.c.d`, `a.b.c.d:port`, a bare IPv6 address and `[v6]:port`. An IPv4-mapped IPv6
    address is returned as IPv4 so it matches IPv4 proxy ranges.
    """
    text = str(value or "").strip()
    if not text or len(text) > 64:
        return None
    port = ""
    if text.startswith("["):
        host, sep, rest = text[1:].partition("]")
        if not sep or (rest and not rest.startswith(":")):
            return None
        port = rest[1:] if rest else ""
        if rest and not port:
            return None
    elif text.count(":") == 1:
        host, port = text.split(":")
        if not port:
            return None
    else:
        host = text
    if port and not (len(port) <= 5 and all(ch in "0123456789" for ch in port)):
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return None
    if address.version == 6 and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _trusted(address: Any, networks: Sequence[_Network]) -> bool:
    return any(address.version == net.version and address in net for net in networks)


def _forwarded_for(event: Dict[str, Any]) -> List[str]:
    """Every `X-Forwarded-For` entry in order, from `headers` or REST `multiValueHeaders`."""
    values: List[str] = []
    for name, value in (event.get("headers") or {}).items():
        if str(name).lower() == "x-forwarded-for" and value is not None:
            values.append(str(value))
    if not values:
        for name, items in (event.get("multiValueHeaders") or {}).items():
            if str(name).lower() == "x-forwarded-for":
                values.extend(str(item) for item in (items or []) if item is not None)
    return [entry.strip() for value in values for entry in value.split(",")]


def peer_ip(event: Dict[str, Any]) -> str:
    """The connecting peer: `requestContext.http.sourceIp`, else REST `identity.sourceIp`."""
    rc = event.get("requestContext") or {}
    candidate = (
        ((rc.get("http") or {}).get("sourceIp"))
        or ((rc.get("identity") or {}).get("sourceIp"))
        or ""
    )
    return str(candidate).strip()


def client_ip(event: Dict[str, Any], trusted: Optional[Sequence[_Network]] = None) -> str:
    """The client address to throttle on. See the module docstring for the rules."""
    peer = peer_ip(event or {})
    networks = trusted_proxies() if trusted is None else tuple(trusted)
    if not networks or not peer:
        return peer
    address = parse_ip(peer)
    if address is None or not _trusted(address, networks):
        return peer
    for entry in reversed(_forwarded_for(event)):
        hop = parse_ip(entry)
        if hop is None:
            return peer
        if not _trusted(hop, networks):
            return str(hop)
    return peer


__all__ = [
    "TRUSTED_PROXY_ENV",
    "trusted_proxies",
    "parse_ip",
    "peer_ip",
    "client_ip",
]
