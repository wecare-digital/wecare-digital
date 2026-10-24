#!/usr/bin/env python3
"""PlivoControlPlaneService - manage Plivo through its API, not the console.

The Plivo API is the control-plane source of truth. The console is a secondary
human verification surface only.

WHY THE UPDATE PATH USES REST AND NOT THE SDK
---------------------------------------------
The official SDK is installed (plivo==4.62.0, dev-only) and is used here for
reads. The update path deliberately does not use it. Its signature is:

    applications.update(app_id, answer_url=None, answer_method='POST',
                        hangup_url=None, ..., default_number_app=False,
                        default_endpoint_app=False, subaccount=None,
                        log_incoming_messages=True, public_uri=None, ...)

`default_endpoint_app` DEFAULTS TO FALSE. So the natural call -

    client.applications.update(APP_ID, answer_url=new_url)

- transmits `default_endpoint_app=False` and silently clears the protected
production invariant. That is exactly the regression this module exists to
prevent: on 2026-09-19 a partial update reset `default_endpoint_app` from true to
false, and it had to be restored. `log_incoming_messages=True` has the same
shape of hazard.

Plivo's Application API is a full replace for the fields you send, so ANY partial
update is unsafe. This module therefore always performs read -> merge -> write
with every protected field restated explicitly, then reads the object back and
compares. An HTTP 202 is not evidence; the persisted object is.

The SDK also has no Zentrunk surface at all - no `trunks`, `outbound_trunks`,
`inbound_trunks`, `sip_credentials` or `ip_access_control_lists` attributes - so
trunk discovery uses REST, which the rules explicitly allow where SDK support is
incomplete.

CREDENTIALS
-----------
Read from Secrets Manager `wecare/plivo/api` (fields auth_id, auth_token), never
from argv and never printed. Snapshots and reports contain neither the auth token
nor any SIP password.
"""
from __future__ import annotations

import base64
import copy
import datetime
import hashlib
import json
import os
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

socket.setdefaulttimeout(30)

PLIVO_API = "https://api.plivo.com/v1/Account"
ZENTRUNK_API = "https://api.plivo.com/v1/Account"
SECRET_ID = os.environ.get("PLIVO_API_SECRET_ID", "wecare/plivo/api")

# ---------------------------------------------------------------------------
# Known resources. §2: DO NOT RECREATE these.
# ---------------------------------------------------------------------------
APP_ID = "12775976954213184"
APP_NAME = "WECARE-WHATSAPP-IVR"
ENDPOINT_USERNAME = "wecarewaivr203331794466262"
ENDPOINT_ALIAS = "WECARE-WhatsApp-IVR-SIP"
NUMBER = "918031830030"

# §14: two DIFFERENT SIP resources. Never substitute one for the other.
#   application SIP -> external SIP invoking the Voice Application
#   endpoint SIP    -> a registered/authenticated SIP user
APPLICATION_SIP_URI = f"sip:{APP_ID}@app.plivo.com"
ENDPOINT_SIP_URI = f"sip:{ENDPOINT_USERNAME}@phone.plivo.com"

# ---------------------------------------------------------------------------
# §5 protected invariants. Never changed by a reconcile.
# ---------------------------------------------------------------------------
PROTECTED_FIELDS = (
    "app_id",
    "app_name",
    "default_endpoint_app",
    "default_number_app",
    "enabled",
    "public_uri",
    "sip_uri",
    "sip_auth_type",
    "credential_uuid",
    "ip_acl_uuid",
    "sub_account",
)

# The one invariant with a known regression history.
CRITICAL_INVARIANTS = {"default_endpoint_app": True}

# §4 fields captured in every snapshot.
CAPTURED_FIELDS = (
    "app_id", "app_name",
    "answer_url", "answer_method",
    "fallback_answer_url", "fallback_method",
    "hangup_url", "hangup_method",
    "message_url", "message_method",
    "default_number_app", "default_endpoint_app",
    "enabled", "public_uri", "sip_uri", "sip_auth_type",
    "credential_uuid", "ip_acl_uuid",
    "sub_account", "log_incoming_messages",
)

# §6 target webhook state.
# Moved off the `wecare.digital/api` custom domain on 2026-09-26. The apex path is
# served by an Amplify rewrite straight to the API Gateway execute-api endpoint, so
# it no longer depends on that custom domain existing — which is the whole point,
# since the domain is being retired.
#
# Verified equivalent before the switch: all five /plivo/* endpoints returned the
# identical status through both, and the `?token=` gate is preserved by
# apply_application_update rather than silently dropped.
#
# This constant is what verify_post_update_state and check_drift compare against, so
# it has to move at the same time as the live application. Leaving it behind would
# make the drift check report a permanent false positive and fail plivo-drift.yml on
# a correctly configured account.
API_BASE = os.environ.get("WECARE_API_BASE", "https://wecare.digital/api")
TARGET_URLS = {
    "answer_url": f"{API_BASE}/plivo/answer",
    "fallback_answer_url": f"{API_BASE}/plivo/fallback",
    "hangup_url": f"{API_BASE}/plivo/hangup",
}
TARGET_METHODS = {
    "answer_method": "POST",
    "fallback_method": "POST",
    "hangup_method": "POST",
}

SNAPSHOT_DIR = os.path.expanduser(
    os.environ.get("PLIVO_SNAPSHOT_DIR",
                   "~/.local/share/kiro-maintenance-reports/plivo-snapshots"))


class PlivoError(RuntimeError):
    pass


def _same(a: Any, b: Any) -> bool:
    """Compare two Plivo field values, treating unset forms as equivalent.

    Plivo reports an unset field as `None` on one read and `''` on another - the
    GET and the POST response do not agree. A naive `a == b` therefore reports
    `ip_acl_uuid: '' -> None` as a protected-field change.

    That is not hypothetical: it fired on the first real --apply. Every URL and
    the critical invariant had already PASSED, and this single false positive
    triggered a rollback of a correct, successful change. An over-strict
    verifier that reverts good work is worse than a slightly loose one, because
    the operator learns to bypass it.
    """
    empties = (None, "", [], {})
    if a in empties and b in empties:
        return True
    return a == b


def _strip_query(url: Optional[str]) -> str:
    """Compare URLs by path, ignoring the ?token= shared secret.

    The answer URLs legitimately carry `?token=<secret>`. Comparing full URLs
    would both leak the token into reports and report a spurious difference every
    time the token is rotated. Path comparison is the meaningful test; the token
    is verified separately by its own fingerprint.
    """
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _token_fingerprint(url: Optional[str]) -> str:
    """sha256 prefix of the ?token= value, so two systems can be compared
    without either displaying the secret."""
    if not url:
        return ""
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    token = (qs.get("token") or [""])[0]
    if not token:
        return ""
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()[:12]


class PlivoControlPlaneService:
    """Read, plan, apply and verify Plivo configuration through the API."""

    def __init__(self, auth_id: str = "", auth_token: str = "") -> None:
        if not auth_id or not auth_token:
            auth_id, auth_token = self._load_credentials()
        self._auth_id = auth_id
        self._auth = base64.b64encode(f"{auth_id}:{auth_token}".encode()).decode()

    # -- credentials ------------------------------------------------------
    @staticmethod
    def _load_credentials() -> Tuple[str, str]:
        """Secrets Manager only. Never argv, never an environment literal."""
        import boto3
        raw = boto3.client(
            "secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")
        ).get_secret_value(SecretId=SECRET_ID)["SecretString"]
        data = json.loads(raw)
        aid = (data.get("auth_id") or "").strip()
        tok = (data.get("auth_token") or "").strip()
        if not aid or not tok:
            raise PlivoError(f"{SECRET_ID} is missing auth_id/auth_token")
        return aid, tok

    @property
    def auth_id(self) -> str:
        return self._auth_id

    # -- transport --------------------------------------------------------
    def _call(self, method: str, path: str, body: Optional[dict] = None,
              host: str = PLIVO_API) -> Tuple[int, Any]:
        url = f"{host}/{self._auth_id}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Authorization": f"Basic {self._auth}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:400] if exc.fp else ""
            return exc.code, {"_error": detail}
        except Exception as exc:  # noqa: BLE001
            return 0, {"_error": f"{type(exc).__name__}: {exc}"}

    # -- §3 read surface --------------------------------------------------
    def get_application(self, app_id: str = APP_ID) -> Dict[str, Any]:
        status, body = self._call("GET", f"/Application/{app_id}/")
        if status != 200:
            raise PlivoError(f"GET Application/{app_id} -> {status} {body}")
        return body

    def list_applications(self) -> List[Dict[str, Any]]:
        status, body = self._call("GET", "/Application/")
        if status != 200:
            raise PlivoError(f"GET Application/ -> {status} {body}")
        return body.get("objects") or []

    def get_endpoint(self, username: str = ENDPOINT_USERNAME) -> Optional[Dict[str, Any]]:
        """Located by username or alias per §12. Never by position in a list."""
        for ep in self.list_endpoints():
            if ep.get("username") == username or ep.get("alias") == ENDPOINT_ALIAS:
                return ep
        return None

    def list_endpoints(self) -> List[Dict[str, Any]]:
        status, body = self._call("GET", "/Endpoint/")
        if status != 200:
            raise PlivoError(f"GET Endpoint/ -> {status} {body}")
        return body.get("objects") or []

    def get_number(self, number: str = NUMBER) -> Dict[str, Any]:
        status, body = self._call("GET", f"/Number/{number}/")
        if status != 200:
            raise PlivoError(f"GET Number/{number} -> {status} {body}")
        return body

    # Zentrunk lives under a /Zentrunk/ path prefix on api.plivo.com, NOT at
    # top-level /Trunk/ and NOT on zentrunk.plivo.com. Both of those were tried:
    # the former 404s and the latter resets the TLS connection. Verified against
    # the live account - /Zentrunk/Trunk/ and /Zentrunk/Credential/ return 200,
    # /Zentrunk/CredentialsList/ returns 503, and the plural
    # /Zentrunk/IpAccessControlList/ spelling 503s while the all-caps
    # /Zentrunk/IPAccessControlList/ works.
    ZENTRUNK_PATHS = (
        ("trunks", "/Zentrunk/Trunk/"),
        ("credentials", "/Zentrunk/Credential/"),
        ("ip_access_control_lists", "/Zentrunk/IPAccessControlList/"),
    )

    # Trunk field names as the API actually returns them. The obvious guesses
    # (direction, status, primary_uri) are all wrong.
    TRUNK_FIELDS = ("name", "trunk_id", "trunk_direction", "trunk_status",
                    "trunk_domain", "secure", "credential_uuid", "ipacl_uuid",
                    "primary_uri_uuid", "fallback_uri_uuid",
                    "created_at", "updated_at")

    def list_trunks(self) -> Dict[str, Any]:
        """§15 Zentrunk discovery. The SDK has no trunk surface at all - no
        `trunks`, `outbound_trunks`, `inbound_trunks`, `sip_credentials` or
        `ip_access_control_lists` attributes - so this is REST, which §1 allows
        where SDK support is incomplete.

        Read only. §15 forbids creating or mutating production trunks outside an
        approved migration.

        Reports per-path status rather than raising: Zentrunk provisioning varies
        by account and a 503 on one collection is information, not a failure of
        the whole discovery.
        """
        out: Dict[str, Any] = {}
        for label, path in self.ZENTRUNK_PATHS:
            status, body = self._call("GET", path, host=ZENTRUNK_API)
            if status != 200:
                out[label] = {"status": status,
                              "detail": str(body.get("_error", body))[:160]}
                continue
            objects = body.get("objects") if isinstance(body, dict) else None
            if label == "trunks" and isinstance(objects, list):
                objects = [{k: t.get(k) for k in self.TRUNK_FIELDS if k in t}
                           for t in objects]
            elif isinstance(objects, list):
                # Credentials carry a username; never echo a secret alongside it.
                objects = [{k: v for k, v in o.items()
                            if "password" not in k.lower() and "secret" not in k.lower()}
                           for o in objects]
            out[label] = {"status": status,
                          "count": len(objects) if isinstance(objects, list) else None,
                          "objects": objects if objects is not None else {}}
        return out

    def verify_application_sip(self, app: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """§13/§14: confirm the Application SIP URI from the API.

        Does NOT assume it is enabled just because the URI format is predictable.
        Returns the observed value alongside the expected one so a mismatch is
        visible rather than asserted away.
        """
        app = app or self.get_application()
        observed_sip = app.get("sip_uri") or ""
        observed_public = app.get("public_uri") or ""
        return {
            "expected_application_sip": APPLICATION_SIP_URI,
            "observed_sip_uri": observed_sip,
            "observed_public_uri": observed_public,
            "matches_expected": _strip_query(observed_sip) == APPLICATION_SIP_URI
                                or APP_ID in str(observed_sip),
            "sip_auth_type": app.get("sip_auth_type"),
            "credential_uuid_set": bool(app.get("credential_uuid")),
            "ip_acl_uuid_set": bool(app.get("ip_acl_uuid")),
            # §14: stated explicitly so the two are never conflated in a report.
            "endpoint_sip_uri_is_a_different_resource": ENDPOINT_SIP_URI,
        }

    # -- §26 snapshot -----------------------------------------------------
    def snapshot_current_state(self, *, write: bool = True,
                              note: str = "") -> Dict[str, Any]:
        """Sanitized before-state artifact. No auth token, no SIP password."""
        app = self.get_application()
        endpoint = self.get_endpoint()
        number = self.get_number()

        app_capture = {k: app.get(k) for k in CAPTURED_FIELDS}
        # The answer URLs carry ?token=. Store the path plus a fingerprint.
        for field in ("answer_url", "fallback_answer_url", "hangup_url"):
            raw = app.get(field)
            app_capture[field] = _strip_query(raw)
            fp = _token_fingerprint(raw)
            if fp:
                app_capture[f"{field}_token"] = fp

        snapshot = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "resource_type": "plivo",
            "account_auth_id": self._auth_id,   # an identifier, not a secret
            "git_commit": _git_commit(),
            "environment": os.environ.get("WECARE_ENV", "production"),
            "note": note,
            "application": app_capture,
            "endpoint": ({
                "endpoint_id": (endpoint or {}).get("endpoint_id"),
                "username": (endpoint or {}).get("username"),
                "alias": (endpoint or {}).get("alias"),
                "sip_uri": (endpoint or {}).get("sip_uri"),
                "application": (endpoint or {}).get("application"),
                "sub_account": (endpoint or {}).get("sub_account"),
                # password deliberately absent - §12 says do not rotate or expose
            } if endpoint else None),
            "number": {
                "number": number.get("number"),
                "alias": number.get("alias"),
                "application": number.get("application"),
                "number_type": number.get("number_type"),
                "voice_enabled": number.get("voice_enabled"),
                "sms_enabled": number.get("sms_enabled"),
                "sub_account": number.get("sub_account"),
            },
            "application_sip": self.verify_application_sip(app),
        }

        _assert_sanitized(snapshot)

        if write:
            os.makedirs(SNAPSHOT_DIR, exist_ok=True)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y%m%dT%H%M%SZ")
            path = os.path.join(SNAPSHOT_DIR, f"plivo-{stamp}.json")
            with open(path, "w") as fh:
                json.dump(snapshot, fh, indent=2, sort_keys=True)
            os.chmod(path, 0o600)
            snapshot["_snapshot_path"] = path
        return snapshot

    # -- drift detection --------------------------------------------------
    def check_drift(self) -> Dict[str, Any]:
        """Compare live provider state against the declared desired state.

        Read-only. Never mutates, never converges - a drift check that silently
        fixed things would destroy the evidence of what moved and when, and would
        make an unreviewed change to a production routing surface.

        Drift is separated into two severities, because they demand different
        responses:

          CRITICAL  a protected invariant or the number->application binding moved.
                    Someone changed live call routing outside this tool. Page.
          WARN      a callback URL or method drifted from target. Recoverable with
                    a reviewed `--apply`.

        The URL comparison deliberately ignores `?token=`, comparing a SHA-256
        fingerprint instead, so a token rotation is visible as a fingerprint change
        without the value ever entering a report or a log.
        """
        app = self.get_application()
        number = self.get_number()
        endpoint = self.get_endpoint()

        critical: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        # 1. Protected invariants with a known regression history.
        for field, required in CRITICAL_INVARIANTS.items():
            actual = app.get(field)
            if actual != required:
                critical.append({
                    "kind": "critical_invariant",
                    "field": field,
                    "expected": required,
                    "actual": actual,
                })

        # 2. Identity. If these moved, the tool is pointed at a different resource
        #    than the one it believes it manages.
        for field, expected in (("app_id", APP_ID), ("app_name", APP_NAME)):
            actual = str(app.get(field) or "")
            if actual != expected:
                critical.append({
                    "kind": "identity",
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                })

        # 3. The number -> application binding. This IS production call routing.
        number_app = str(number.get("application") or "")
        if APP_ID not in number_app:
            critical.append({
                "kind": "number_routing",
                "field": "number.application",
                "expected_contains": APP_ID,
                "actual": number_app,
                "detail": (f"number {NUMBER} is no longer routed to application "
                           f"{APP_ID}. Inbound calls are not reaching this "
                           "application."),
            })

        # 4. Plivo SMS must remain impossible on this number.
        if number.get("sms_enabled"):
            critical.append({
                "kind": "prohibited_capability",
                "field": "number.sms_enabled",
                "expected": False,
                "actual": True,
                "detail": ("Plivo SMS is prohibited by the provider policy. SMS "
                           "has been enabled on this number at the provider."),
            })

        # 5. The browser endpoint must still belong to this application.
        if endpoint is None:
            warnings.append({
                "kind": "endpoint_missing",
                "field": "endpoint",
                "expected": ENDPOINT_USERNAME,
                "actual": None,
            })
        else:
            if str(endpoint.get("username") or "") != ENDPOINT_USERNAME:
                critical.append({
                    "kind": "identity",
                    "field": "endpoint.username",
                    "expected": ENDPOINT_USERNAME,
                    "actual": endpoint.get("username"),
                })
            if APP_ID not in str(endpoint.get("application") or ""):
                critical.append({
                    "kind": "endpoint_routing",
                    "field": "endpoint.application",
                    "expected_contains": APP_ID,
                    "actual": endpoint.get("application"),
                })

        # 6. Callback URLs and methods. Recoverable, so WARN.
        for field, expected_url in TARGET_URLS.items():
            observed = _strip_query(app.get(field))
            if observed != expected_url:
                warnings.append({
                    "kind": "callback_url",
                    "field": field,
                    "expected": expected_url,
                    "actual": observed,
                    "token_fingerprint": _token_fingerprint(app.get(field)),
                })

        for field in ("answer_method", "fallback_method", "hangup_method"):
            actual = str(app.get(field) or "").upper()
            if actual != "POST":
                warnings.append({
                    "kind": "callback_method",
                    "field": field,
                    "expected": "POST",
                    "actual": actual,
                })

        # 7. Application SIP URI.
        sip = self.verify_application_sip(app)
        if not sip.get("matches_expected"):
            warnings.append({
                "kind": "application_sip",
                "field": "sip_uri",
                "expected": APPLICATION_SIP_URI,
                "actual": sip.get("observed_sip_uri"),
            })

        report = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "resource_type": "plivo",
            "account_auth_id": self._auth_id,
            "git_commit": _git_commit(),
            "drifted": bool(critical or warnings),
            "critical_count": len(critical),
            "warning_count": len(warnings),
            "critical": critical,
            "warnings": warnings,
            "checked": {
                "app_id": APP_ID,
                "app_name": APP_NAME,
                "number": NUMBER,
                "endpoint_username": ENDPOINT_USERNAME,
                "protected_fields": list(PROTECTED_FIELDS),
                "critical_invariants": dict(CRITICAL_INVARIANTS),
            },
            # Stated so a consumer cannot mistake this for a converge.
            "read_only": True,
        }
        _assert_sanitized(report)
        return report


    # -- §7 planning ------------------------------------------------------
    def plan_application_update(self, app: Optional[Dict[str, Any]] = None,
                                targets: Optional[Dict[str, str]] = None
                                ) -> List[Dict[str, Any]]:
        """Return a CURRENT / TARGET / CHANGE? / PROTECTED? row per field."""
        app = app or self.get_application()
        desired = dict(TARGET_URLS if targets is None else targets)
        desired.update(TARGET_METHODS)

        rows: List[Dict[str, Any]] = []
        for field, target in desired.items():
            current_raw = app.get(field)
            current = _strip_query(current_raw) if field.endswith("_url") else current_raw
            rows.append({
                "field": field,
                "current": current,
                "current_token": _token_fingerprint(current_raw) or None,
                "target": target,
                "change": current != target,
                "protected": field in PROTECTED_FIELDS,
            })

        # Protected fields are reported even though they are never targets, so a
        # reviewer sees their state in the same table rather than having to trust
        # that they were left alone.
        for field in PROTECTED_FIELDS:
            rows.append({
                "field": field,
                "current": app.get(field),
                "target": app.get(field),      # target IS current, by definition
                "change": False,
                "protected": True,
                "critical": field in CRITICAL_INVARIANTS,
            })
        return rows

    # -- §7/§8 apply + read-back -----------------------------------------
    def apply_application_update(self, rows: List[Dict[str, Any]],
                                 app: Optional[Dict[str, Any]] = None
                                 ) -> Dict[str, Any]:
        """Apply the plan as a FULL field set, then verify by reading back.

        Every mutable field is restated, including the ones not changing. Plivo's
        Application API replaces what it receives, and the SDK defaults
        `default_endpoint_app` and `default_number_app` to False, so a partial
        update silently clears them. This is the failure that already happened
        once.
        """
        app = app or self.get_application()
        before = copy.deepcopy(app)

        changes = {r["field"]: r["target"] for r in rows if r.get("change")}
        if not changes:
            return {"applied": False, "reason": "no changes planned",
                    "verification": self.verify_post_update_state(before, before)}

        # Preserve the ?token= on any URL that carries one and is not itself
        # changing host/path. A reconcile must not silently disarm the gate.
        payload: Dict[str, Any] = {}
        for field in ("answer_url", "fallback_answer_url", "hangup_url"):
            target = changes.get(field, _strip_query(app.get(field)))
            qs = urllib.parse.urlsplit(app.get(field) or "").query
            payload[field] = f"{target}?{qs}" if qs else target
        payload.update({
            "answer_method": changes.get("answer_method", app.get("answer_method") or "POST"),
            "fallback_method": changes.get("fallback_method", app.get("fallback_method") or "POST"),
            "hangup_method": changes.get("hangup_method", app.get("hangup_method") or "POST"),
        })
        # Protected fields restated verbatim. This is the whole point.
        for field in ("default_number_app", "default_endpoint_app",
                      "log_incoming_messages"):
            if app.get(field) is not None:
                payload[field] = app.get(field)

        status, body = self._call("POST", f"/Application/{APP_ID}/", payload)
        if status not in (200, 201, 202):
            raise PlivoError(f"POST Application/{APP_ID} -> {status} {body}")

        after = self._read_back(APP_ID)
        verification = self.verify_post_update_state(before, after)
        return {"applied": True, "http_status": status,
                "changed_fields": sorted(changes),
                "verification": verification,
                "before": before, "after": after}

    # Seconds between read-back polls. Plivo returns 202 and applies
    # asynchronously, so a real reconcile must wait. Tests set this to 0 - with
    # the default the clobber cases poll to exhaustion and add ~20s to the suite,
    # which is how a fast test file quietly becomes one people skip.
    read_back_delay = float(os.environ.get("PLIVO_READ_BACK_DELAY", "4"))

    def _read_back(self, app_id: str, attempts: int = 5) -> Dict[str, Any]:
        """Re-read until the change lands, because 202 is not confirmation."""
        import time
        app = self.get_application(app_id)
        for _ in range(attempts - 1):
            if _strip_query(app.get("hangup_url")) == TARGET_URLS["hangup_url"]:
                break
            if self.read_back_delay:
                time.sleep(self.read_back_delay)
            app = self.get_application(app_id)
        return app

    def verify_post_update_state(self, before: Dict[str, Any],
                                 after: Dict[str, Any]) -> Dict[str, Any]:
        """§8: assert the persisted object, not the HTTP status.

        Three classes of finding:
          urls        - did the intended change land
          protected   - did anything protected move (always a failure)
          unexpected  - did any other captured field move
        """
        failures: List[str] = []
        checks: List[Dict[str, Any]] = []

        for field, expected in TARGET_URLS.items():
            observed = _strip_query(after.get(field))
            ok = observed == expected
            checks.append({"check": field, "expected": expected,
                           "observed": observed, "pass": ok})
            if not ok:
                failures.append(f"{field} is {observed!r}, expected {expected!r}")

        for field, method in TARGET_METHODS.items():
            observed = (after.get(field) or "").upper()
            ok = observed == method
            checks.append({"check": field, "expected": method,
                           "observed": observed, "pass": ok})
            if not ok:
                failures.append(f"{field} is {observed!r}, expected {method!r}")

        for field, required in CRITICAL_INVARIANTS.items():
            observed = after.get(field)
            ok = observed == required
            checks.append({"check": f"{field} (CRITICAL)", "expected": required,
                           "observed": observed, "pass": ok})
            if not ok:
                failures.append(
                    f"CRITICAL INVARIANT {field} is {observed!r}, must be {required!r}")

        for field in PROTECTED_FIELDS:
            if field in CRITICAL_INVARIANTS:
                continue
            b, a = before.get(field), after.get(field)
            ok = _same(b, a)
            checks.append({"check": f"{field} unchanged", "expected": b,
                           "observed": a, "pass": ok})
            if not ok:
                failures.append(f"PROTECTED {field} changed: {b!r} -> {a!r}")

        # Anything else in the captured set that moved and was not an intended target.
        intended = set(TARGET_URLS) | set(TARGET_METHODS)
        for field in CAPTURED_FIELDS:
            if field in intended or field in PROTECTED_FIELDS:
                continue
            b = _strip_query(before.get(field)) if field.endswith("_url") else before.get(field)
            a = _strip_query(after.get(field)) if field.endswith("_url") else after.get(field)
            if not _same(b, a):
                failures.append(f"UNEXPECTED {field} changed: {b!r} -> {a!r}")
                checks.append({"check": f"{field} unexpected change",
                               "expected": b, "observed": a, "pass": False})

        return {"ok": not failures, "failures": failures, "checks": checks}

    def rollback_application_update(self, before: Dict[str, Any]) -> Dict[str, Any]:
        """Restore the captured before-state, full field set."""
        payload = {
            "answer_url": before.get("answer_url"),
            "answer_method": before.get("answer_method") or "POST",
            "fallback_answer_url": before.get("fallback_answer_url"),
            "fallback_method": before.get("fallback_method") or "POST",
            "hangup_url": before.get("hangup_url"),
            "hangup_method": before.get("hangup_method") or "POST",
        }
        for field in ("default_number_app", "default_endpoint_app",
                      "log_incoming_messages"):
            if before.get(field) is not None:
                payload[field] = before.get(field)
        status, body = self._call("POST", f"/Application/{APP_ID}/", payload)
        after = self._read_back(APP_ID, attempts=3)
        return {"http_status": status, "detail": body,
                "restored": _strip_query(after.get("hangup_url"))
                            == _strip_query(before.get("hangup_url"))}

    # -- §10 number routing, deliberately separate and guarded ------------
    def plan_number_routing_change(self, *, target_app_id: str = "",
                                   target_trunk_id: str = "") -> Dict[str, Any]:
        """§10: planning only. Never mutates.

        §11 requires +918031830030 to stay on the WECARE-WHATSAPP-IVR Voice
        Application while the Plivo IVR works and Meta remains on Lightsail.
        So the default plan is 'no change', and anything else must be asked for
        explicitly.
        """
        number = self.get_number()
        current_app = (number.get("application") or "").rstrip("/").split("/")[-1]
        if not target_app_id and not target_trunk_id:
            return {
                "change": False,
                "current_application": current_app,
                "required_state": APP_ID,
                "compliant": current_app == APP_ID,
                "reason": ("§11 keeps the live number on the Voice Application. "
                           "No routing change requested."),
            }
        return {
            "change": True,
            "current_application": current_app,
            "target_application": target_app_id or None,
            "target_trunk": target_trunk_id or None,
            "risk": "PRODUCTION ROUTING CUTOVER",
            "requires": "explicit production approval (§10)",
            "warning": ("§17: an operational provider webhook does NOT prove the "
                        "SIP route works. Verify India-resident SIP termination, "
                        "trunk hostname, signalling, media, TLS, SRTP, codecs, a "
                        "real test call, the post-call webhook and VoiceCDR "
                        "persistence first. Prefer a separate test number."),
        }

    def apply_number_routing_change(self, *, target_app_id: str,
                                    approved: bool = False) -> Dict[str, Any]:
        """§10: refuses without explicit approval."""
        if not approved:
            raise PlivoError(
                "number routing change requires approved=True. This is a "
                "production routing cutover (§10) and must not happen merely "
                "because a trunk exists.")
        before = self.get_number()
        status, body = self._call("POST", f"/Number/{NUMBER}/",
                                  {"app_id": target_app_id})
        after = self.get_number()
        return {"http_status": status, "detail": body,
                "before_application": before.get("application"),
                "after_application": after.get("application")}


# ---------------------------------------------------------------------------
def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.dirname(
                                  os.path.abspath(__file__)))).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _assert_sanitized(obj: Any) -> None:
    """Refuse to emit a snapshot containing credential material.

    Cheap belt-and-braces. The builder already omits the auth token and SIP
    password, but a future field addition could reintroduce one, and a snapshot
    is written to disk and kept for audit.
    """
    blob = json.dumps(obj).lower()
    for marker in ("auth_token", "password", "sip_user_password", "secret"):
        if marker in blob:
            raise PlivoError(
                f"snapshot contains a forbidden key matching {marker!r}; "
                "refusing to write credential material to disk")
