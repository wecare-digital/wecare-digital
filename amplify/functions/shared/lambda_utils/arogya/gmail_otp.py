"""Read only the OTP for a current Apollo login challenge through Gmail API v1.

The owning server supplies its OAuth-authenticated transport. This module neither
loads credentials nor polls on a schedule. A Gmail grant in a chat is not a runtime
grant. Call only while an authorized server-side Apollo sign-in is pending.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.utils import getaddresses, parseaddr
from typing import Callable, Mapping

MAX_AGE_MS = 5 * 60 * 1000
GMAIL_ROOT = "/gmail/v1/users/me"


class MailboxAccessRequired(ValueError):
    """The configured mailbox or approved sender is not valid for this operation."""


class GmailReadUnavailable(RuntimeError):
    """A bounded Gmail read failed; never includes upstream bodies or credentials."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise GmailReadUnavailable("Gmail redirect refused")


class GmailApi:
    """Fixed-origin read-only Gmail transport using an existing runtime token getter.

    The getter must preserve/refresh the owner's Google grant through the existing
    encrypted OAuth store. It must not receive a token supplied by the public form.
    """

    def __init__(self, access_token: Callable[[], str]):
        self._access_token = access_token
        self._opener = urllib.request.build_opener(_NoRedirect)

    def __call__(self, path: str, params: Mapping) -> dict:
        if not re.fullmatch(r"/gmail/v1/users/me/(?:profile|messages(?:/[A-Za-z0-9_-]{1,100})?)", path):
            raise GmailReadUnavailable("Gmail resource refused")
        allowed = {"q", "maxResults"} if path.endswith("/messages") else {"format"} if "/messages/" in path else set()
        if set(params) - allowed:
            raise GmailReadUnavailable("Gmail parameters refused")
        token = self._access_token()
        if not isinstance(token, str) or not token:
            raise MailboxAccessRequired("Gmail authorization required")
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            "https://gmail.googleapis.com" + path + ("?" + query if query else ""),
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, method="GET")
        try:
            with self._opener.open(request, timeout=5) as response:
                raw = response.read(262145)
                if len(raw) > 262144:
                    raise GmailReadUnavailable("Gmail response exceeded limit")
                document = json.loads(raw)
                if not isinstance(document, dict):
                    raise GmailReadUnavailable("Gmail response invalid")
                return document
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise MailboxAccessRequired("Gmail authorization requires attention") from None
            raise GmailReadUnavailable("Gmail read failed") from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise GmailReadUnavailable("Gmail read unavailable") from None


@dataclass(frozen=True)
class ChallengeCode:
    message_id: str
    code: str = field(repr=False)


def _text(part: Mapping) -> str:
    chunks = []
    mime = str(part.get("mimeType", ""))
    if mime in ("text/plain", "text/html"):
        encoded = str((part.get("body") or {}).get("data") or "")
        if len(encoded) <= 100000:
            try:
                chunks.append(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", "replace"))
            except (ValueError, UnicodeError):
                pass
    # Depth and part count are bounded independently of provider-controlled MIME.
    pending = [(child, 1) for child in list(part.get("parts") or [])[:30]]
    for _ in range(60):
        if not pending:
            break
        child, depth = pending.pop(0)
        if depth > 5 or not isinstance(child, Mapping):
            continue
        leaf = {key: value for key, value in child.items() if key != "parts"}
        chunks.append(_text(leaf))
        pending.extend((p, depth + 1) for p in list(child.get("parts") or [])[:30])
    return "\n".join(chunks)


def find_apollo_otp(gmail_get: Callable, *, expected_mailbox: str,
                    approved_sender: str, requested_at_ms: int, now_ms: int,
                    consumed_message_ids: frozenset[str] = frozenset()) -> ChallengeCode | None:
    """Return an unconsumed six-digit code, or None while the current mail is absent.

    gmail_get(path, params) is a fixed-origin, OAuth-authenticated GET transport.
    The code is intended only for Apollo VerifyOtp, never the website response.
    The caller owns the renewal lock and atomically consumes the message on success.
    """
    mailbox = expected_mailbox.strip().lower()
    sender = approved_sender.strip().lower()
    if (not re.fullmatch(r"[^\s@]+@gmail\.com", mailbox)
            or not re.fullmatch(r"[^\s@]+@(?:[a-z0-9-]+\.)*apollohospitals\.com", sender)):
        raise MailboxAccessRequired("Configure the intended Gmail mailbox and an approved Apollo sender")
    if not 0 <= now_ms - requested_at_ms <= MAX_AGE_MS:
        return None
    profile = gmail_get(GMAIL_ROOT + "/profile", {})
    if str(profile.get("emailAddress", "")).lower() != mailbox:
        raise MailboxAccessRequired("Gmail authorization belongs to a different mailbox")
    listed = gmail_get(GMAIL_ROOT + "/messages", {
        "q": f"from:{sender} to:{mailbox} after:{requested_at_ms // 1000}",
        "maxResults": 5,
    })
    if listed.get('nextPageToken'):
        return None  # cannot establish an unambiguous current challenge
    matches = []
    for candidate in list(listed.get("messages") or [])[:5]:
        message_id = str(candidate.get("id") or "")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", message_id) or message_id in consumed_message_ids:
            continue
        message = gmail_get(GMAIL_ROOT + "/messages/" + message_id, {"format": "full"})
        try:
            received = int(message.get("internalDate", 0))
        except (TypeError, ValueError):
            continue
        if not requested_at_ms <= received <= now_ms or now_ms - received > MAX_AGE_MS:
            continue
        payload = message.get("payload") or {}
        headers = {str(h.get("name", "")).lower(): str(h.get("value", ""))
                   for h in list(payload.get("headers") or [])[:100]}
        if parseaddr(headers.get("from", ""))[1].lower() != sender:
            continue
        recipients = {address.lower() for _, address in getaddresses([headers.get("to", "")])}
        if mailbox not in recipients:
            continue
        text = _text(payload)
        if not re.search(r"\b(?:otp|one.time.password|verification.code)\b", text, re.I):
            continue
        codes = set(re.findall(r"(?<!\d)\d{6}(?!\d)", text))
        if len(codes) == 1:
            matches.append(ChallengeCode(message_id, codes.pop()))
    return matches[0] if len(matches) == 1 else None
