"""
Meta Business Agent — WECARE.DIGITAL

Backend for onboarding/configuring Meta's Business AI Agent on WhatsApp.
Docs (scraped to s3://wecare-digital-get/o/stream/docs/meta-business-agent/):
  Onboarding: POST https://api.facebook.com/{entity_id}/agent_onboarding/?channel=whatsapp
    headers: Authorization: Bearer <token>, X-API-Version: 2.0.0
    entity_id = WhatsApp Business Phone Number ID (or FB Page ID)
    body: {} -> 201 (creates entities + schedules async data-prep jobs)

Auth token comes from Secrets Manager (wecare/meta-system-user-token), same as
the other WhatsApp handlers — never from env.

Actions (event.action or API route):
  - onboard        : trigger onboarding for an entity+channel
  - status         : (placeholder) read onboarding status
NOTE: configure/operate endpoints (skills, knowledge, connectors, eval, test)
will be added from the per-endpoint OpenAPI specs — see README.
"""

import os
import json
import logging
import urllib.request
import urllib.error

import time

import boto3

from lambda_utils.middleware import require_auth
from lambda_utils.meta_version import GRAPH_BASE  # one source; validated at import
from lambda_utils.privacy import mask_phone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
secrets_client = boto3.client("secretsmanager", region_name=REGION)
META_TOKEN_SECRET = os.environ.get("META_TOKEN_SECRET", "wecare/meta-system-user-token")
API_VERSION = os.environ.get("META_AGENT_API_VERSION", "2.0.0")
GRAPH_HOST = os.environ.get("META_AGENT_HOST", "https://api.facebook.com")

# Default WhatsApp Business phone-number IDs (entity_id candidates)
DEFAULT_ENTITIES = {
    "WABA2": "1055232054343117",   # +91 99033 00044 (alias for WABA-T; frontend sends WABA2)
    "WABA1": "1016149501586345",   # +91 93309 94400
    "WABA-T": "1055232054343117",  # +91 99033 00044
}

# agent_config/settings enum constraints (per Meta Business Agent spec)
_AI_AUDIENCES = {"ALLOWLISTED_ONLY", "EVERYONE"}
_FOLLOWUP_INTERVALS = {0, 300, 900, 1800, 3600, 7200, 28800, 86400}

_token_cache = {}
CORS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


import hmac
import hashlib


def _creds():
    if "t" in _token_cache:
        return _token_cache["t"], _token_cache["s"]
    resp = secrets_client.get_secret_value(SecretId=META_TOKEN_SECRET)
    data = json.loads(resp["SecretString"])
    _token_cache["t"] = (data.get("access_token") or "").strip()
    _token_cache["s"] = (data.get("app_secret") or "").strip()
    return _token_cache["t"], _token_cache["s"]


def _appsecret_proof(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


# ─────────────────────────────────────────────────────────────────────────
# Agent Tool endpoint — the target that Meta Business Agent connector tools call.
# Public route (POST /agent-tool) but GATED by a scoped static token in the
# X-Agent-Token header (secret wecare/agent-connector-token). Read-only.
# ─────────────────────────────────────────────────────────────────────────
AGENT_TOOL_SECRET = os.environ.get("AGENT_TOOL_SECRET", "wecare/agent-connector-token")
# WABA phone-number-id -> its Meta product catalog id
_CATALOG_BY_ENTITY = {
    "1016149501586345": "1607047307067517",   # WABA1 wecare_catalog
    "1055232054343117": "1424934879646296",   # WABA2 Catalogue_Products
}


def _agent_tool_token() -> str:
    if "agent_tool" in _token_cache:
        return _token_cache["agent_tool"]
    try:
        resp = secrets_client.get_secret_value(SecretId=AGENT_TOOL_SECRET)
        tok = (json.loads(resp["SecretString"]).get("token") or "").strip()
    except Exception:
        tok = ""
    _token_cache["agent_tool"] = tok
    return tok


def _tool_product_lookup(body: dict):
    """Return catalog products matching a query (name substring) or retailer_id.
    Read-only; used by the agent to answer product/price/availability questions."""
    query = (body.get("query") or body.get("product") or "").strip().lower()
    retailer_id = (body.get("retailer_id") or "").strip()
    entity_id = str(body.get("entity_id") or "1016149501586345")
    catalog_id = _CATALOG_BY_ENTITY.get(entity_id, "1607047307067517")
    token, secret = _creds()
    fields = "retailer_id,name,price,sale_price,availability,description,url"
    # GRAPH (defined below) rather than a second hardcoded version, so the
    # Graph version for this function lives in exactly one place. Resolved from
    # module globals at call time, so the later definition is fine.
    url = f"{GRAPH}/{catalog_id}/products?fields={fields}&limit=100&access_token={token}"
    if secret:
        url += "&appsecret_proof=" + _appsecret_proof(token, secret)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode())
        products = data.get("data", [])
    except Exception as e:
        return {"statusCode": 200, "headers": CORS,
                "body": json.dumps({"status": "error", "error": str(e)[:120], "products": []})}
    out = []
    for p in products:
        rid = p.get("retailer_id", "")
        name = (p.get("name") or "")
        if retailer_id and rid != retailer_id:
            continue
        if query and query not in name.lower():
            continue
        out.append({"retailer_id": rid, "name": name, "price": p.get("price"),
                    "sale_price": p.get("sale_price"), "availability": p.get("availability"),
                    "description": p.get("description"), "url": p.get("url")})
    if not out and not query and not retailer_id:
        out = [{"retailer_id": p.get("retailer_id"), "name": p.get("name"), "price": p.get("price"),
                "availability": p.get("availability")} for p in products]
    return {"statusCode": 200, "headers": CORS, "body": json.dumps({"status": "success", "products": out})}


def _agent_tool(event: dict):
    """Token-gated, read-only endpoint the Meta agent connector tools call."""
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    supplied = headers.get("x-agent-token", "")
    expected = _agent_tool_token()
    if not expected or supplied != expected:
        return {"statusCode": 401, "headers": CORS, "body": json.dumps({"error": "unauthorized"})}
    body = {}
    if isinstance(event.get("body"), str):
        try:
            body = json.loads(event["body"])
        except Exception:
            body = {}
    elif isinstance(event.get("body"), dict):
        body = event["body"]
    op = (body.get("op") or "product_lookup").lower()
    if op == "product_lookup":
        return _tool_product_lookup(body)
    return {"statusCode": 400, "headers": CORS, "body": json.dumps({"error": "unknown op", "supported": ["product_lookup"]})}


def _resp(status, body):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body)}


def _pass_status(status, ok=(200,), success_status=None):
    """Map an upstream Meta status to the HTTP status we return to the caller.

    A non-2xx from Meta is NOT a gateway failure. In particular Meta returns
    403 when the Business AI Terms of Service have not been accepted for the
    WABA. Surfacing that as 502 falsely trips the apigw-5xx CloudWatch alarm.

    - success (status in `ok`) -> success_status (or the upstream status)
    - upstream client error (4xx) -> surface the SAME 4xx (e.g. 403) so API
      Gateway records a 4xx, not a 5xx
    - genuine upstream 5xx / network error -> 502 Bad Gateway
    """
    if status in ok:
        return success_status or status
    if 400 <= status < 500:
        return status
    return 502


def _meta_request(method: str, url: str, payload: dict | None,
                  api_version: str | None = API_VERSION):
    """The one transport for every agent-API and Graph call in this module.

    `api_version` exists only so a GRAPH call can suppress `X-API-Version`, which is
    an agent-API header and has no business on a Graph request where the version
    already travels in the URL. It defaults to API_VERSION, and every pre-existing
    call site passes exactly three positional arguments, so none of them moves.

    The `appsecret_proof` appended below is an HMAC-SHA256 of the token under the app
    secret, NOT the token: api.facebook.com requires it and removing it breaks the
    call. The token itself travels in the Authorization header and never in the URL.
    """
    token, secret = _creds()
    if secret:  # api.facebook.com requires appsecret_proof
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}appsecret_proof={_appsecret_proof(token, secret)}"
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=body if method != "GET" else None, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    if api_version:
        req.add_header("X-API-Version", api_version)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode("utf-8")
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail)
        except Exception:
            pass
        return e.code, {"error": detail}
    except Exception as e:
        return 502, {"error": str(e)}


CHANNELS = {"email", "instagram", "line", "messenger", "sms", "tiktok", "unknown", "webchat", "whatsapp"}


def _onboard(body: dict):
    """POST /{entity_id}/agent_onboarding/?channel=<channel>"""
    entity_id = body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")
    channel = (body.get("channel") or "whatsapp").lower()
    if not entity_id:
        return _resp(400, {"error": "entityId (WhatsApp Business Phone Number ID) required"})
    if channel not in CHANNELS:
        return _resp(400, {"error": f"channel must be one of {sorted(CHANNELS)}"})
    url = f"{GRAPH_HOST}/{entity_id}/agent_onboarding/?channel={channel}"
    status, data = _meta_request("POST", url, {})
    logger.info(json.dumps({"event": "agent_onboard", "entity": entity_id, "channel": channel, "status": status}))
    return _resp(_pass_status(status, (200, 201)), {"onboarding": data, "entityId": entity_id, "channel": channel})


# Aligned with the rest of the fleet (lambda_utils/meta_client.py and
# whatsapp_types.py both default to v25.0). This was pinned to v22.0 while every
# other handler moved on, which put the two oldest Graph calls in the account
# here. Deliberately NOT v26.0: that release blocked a batch of commerce
# endpoints, and _tool_product_lookup below reads /{catalog_id}/products.
GRAPH = os.environ.get("META_GRAPH_BASE", GRAPH_BASE)
# WABA IDs (not phone-number IDs) — subscribed_apps is per WABA
WABA_IDS = {"WABA1": "2094615664435155", "WABA-T": "2513394156072604", "WABA2": "2513394156072604"}


def _readiness(body: dict):
    """Step 6/7 check: is the app subscribed to each WABA, and which webhook
    fields are set? (Uses Graph API, not the ToS-gated agent API.)"""
    out = {}
    for name, waba in WABA_IDS.items():
        status, data = _meta_request("GET", f"{GRAPH}/{waba}/subscribed_apps", None)
        out[name] = {"waba": waba, "httpStatus": status, "subscribed_apps": data}
    return _resp(200, {"readiness": out,
                       "need_fields": ["messages", "standby", "messaging_handovers"]})


def _eligibility(body: dict):
    """GET /{entity_id}/agent_eligibility/ -> {is_eligible: bool}"""
    entity_id = body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")
    if not entity_id:
        return _resp(400, {"error": "entityId required"})
    status, data = _meta_request("GET", f"{GRAPH_HOST}/{entity_id}/agent_eligibility/", None)
    return _resp(_pass_status(status, (200,)), {"eligibility": data, "entityId": entity_id})


def _settings_url(entity_id: str, agent_id: str | None) -> str:
    url = f"{GRAPH_HOST}/{entity_id}/agent_config/settings"
    return f"{url}?agent_id={agent_id}" if agent_id else url


def _settings_get(body: dict):
    """GET /{entity_id}/agent_config/settings  -> array of settings."""
    entity_id = body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")
    if not entity_id:
        return _resp(400, {"error": "entityId required"})
    status, data = _meta_request("GET", _settings_url(entity_id, body.get("agentId")), None)
    return _resp(_pass_status(status, (200,)), {"settings": data, "entityId": entity_id})


def _settings_update(body: dict):
    """PUT /{entity_id}/agent_config/settings — full replace, so we GET current
    settings and merge the requested changes to avoid clobbering other fields.
    Accepted inputs: enabled(bool), handoff{enabled,message}, followup{enabled,
    followup_interval_in_seconds,message}, aiAudience(ALLOWLISTED_ONLY|EVERYONE)."""
    entity_id = body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")
    if not entity_id:
        return _resp(400, {"error": "entityId required"})
    agent_id = body.get("agentId")

    # ── validate enum fields against the Meta spec (fail fast with a clear 400) ──
    if "aiAudience" in body and body["aiAudience"] not in _AI_AUDIENCES:
        return _resp(400, {"error": f"aiAudience must be one of {sorted(_AI_AUDIENCES)}"})
    if "followup" in body and isinstance(body["followup"], dict):
        _iv = body["followup"].get("followup_interval_in_seconds")
        if _iv is not None and _iv not in _FOLLOWUP_INTERVALS:
            return _resp(400, {"error": f"followup_interval_in_seconds must be one of {sorted(_FOLLOWUP_INTERVALS)}"})

    # merge base = current settings (if any)
    _, cur = _meta_request("GET", _settings_url(entity_id, agent_id), None)
    current = cur[0] if isinstance(cur, list) and cur else (cur if isinstance(cur, dict) else {})
    payload = {
        "rollout": current.get("rollout") or {"enabled": False},
        "handoff": current.get("handoff"),
        "followup": current.get("followup"),
        "ai_audience": current.get("ai_audience"),
    }
    if "enabled" in body:
        payload["rollout"] = {"enabled": bool(body["enabled"])}
    if "handoff" in body:
        payload["handoff"] = body["handoff"]
    if "followup" in body:
        payload["followup"] = body["followup"]
    if "aiAudience" in body:
        payload["ai_audience"] = body["aiAudience"]
    payload = {k: v for k, v in payload.items() if v is not None}

    status, data = _meta_request("PUT", _settings_url(entity_id, agent_id), payload)
    logger.info(json.dumps({"event": "agent_settings_update", "entity": entity_id,
                            "enabled": payload.get("rollout", {}).get("enabled"), "status": status}))
    return _resp(_pass_status(status, (200,)), {"settings": data, "entityId": entity_id})


def _allowlist_url(entity_id: str, entry_id: str | None = None) -> str:
    base = f"{GRAPH_HOST}/{entity_id}/agent_config/allowlist"
    return f"{base}/{entry_id}" if entry_id else base


def _allowlist_list(body: dict):
    """GET /{entity_id}/agent_config/allowlist -> [{id, consumer_phone_number}]"""
    entity_id = body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")
    if not entity_id:
        return _resp(400, {"error": "entityId required"})
    status, data = _meta_request("GET", _allowlist_url(entity_id), None)
    return _resp(_pass_status(status, (200,)), {"allowlist": data, "entityId": entity_id})


def _allowlist_add(body: dict):
    """POST /{entity_id}/agent_config/allowlist  {consumer_phone_number} (E.164)"""
    entity_id = body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")
    phone = (body.get("consumerPhoneNumber") or body.get("phone") or "").strip()
    if not entity_id or not phone:
        return _resp(400, {"error": "entityId and consumerPhoneNumber (E.164, e.g. +15551234567) required"})
    status, data = _meta_request("POST", _allowlist_url(entity_id), {"consumer_phone_number": phone})
    return _resp(_pass_status(status, (200, 201)), {"entry": data, "entityId": entity_id})


def _allowlist_remove(body: dict):
    """DELETE /{entity_id}/agent_config/allowlist/{entry_id} -> 204"""
    entity_id = body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")
    entry_id = (body.get("entryId") or "").strip()
    if not entity_id or not entry_id:
        return _resp(400, {"error": "entityId and entryId required"})
    status, data = _meta_request("DELETE", _allowlist_url(entity_id, entry_id), None)
    return _resp(_pass_status(status, (200, 204), success_status=200), {"deleted": status in (200, 204), "detail": data})


# ─────────────────────────────────────────────────────────────────────────
# Configure group — skills, knowledge, connectors.
# Paths follow the agent_config/ + agent_knowledge/ convention used by the
# settings/allowlist endpoints above. Request bodies mirror Meta's docs; verify
# exact shapes against the per-endpoint OpenAPI specs when refining.
# ─────────────────────────────────────────────────────────────────────────

_KNOWLEDGE = {"business_info", "faqs", "websites", "files"}


def _entity(body: dict) -> str:
    return body.get("entityId") or DEFAULT_ENTITIES.get(body.get("waba", ""), "")


def _with_agent(url: str, agent_id: str | None) -> str:
    return f"{url}?agent_id={agent_id}" if agent_id else url


def _skills_get(body: dict):
    """GET /{entity_id}/agent_config/skills — system instructions that shape replies."""
    eid = _entity(body)
    if not eid:
        return _resp(400, {"error": "entityId required"})
    st, d = _meta_request("GET", _with_agent(f"{GRAPH_HOST}/{eid}/agent_config/skills", body.get("agentId")), None)
    return _resp(_pass_status(st, (200,)), {"skills": d, "entityId": eid})


def _skill_payload(body: dict) -> dict:
    """Build a BizAIOmniChannelSkillsRequest: {title, description, skill}.
    `title` must be lowercase letters/numbers/hyphens; `skill` is the instruction body."""
    return {k: v for k, v in {
        "title": body.get("title"),
        "description": body.get("description"),
        "skill": body.get("skill") or body.get("instruction"),  # `skill` is the instruction text
    }.items() if v is not None}


def _skills_create(body: dict):
    """POST /{entity_id}/agent_config/skills — create a skill {title, description, skill}."""
    eid = _entity(body)
    payload = _skill_payload(body)
    if not eid or not payload.get("title") or not payload.get("skill"):
        return _resp(400, {"error": "entityId, title (lowercase-hyphen) and skill (instruction text) required"})
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_config/skills", payload)
    return _resp(_pass_status(st, (200, 201)), {"skill": d, "entityId": eid})


def _skills_update(body: dict):
    """PUT /{entity_id}/agent_config/skills/{skill_id} — replace one skill."""
    eid = _entity(body)
    sid = (body.get("skillId") or "").strip()
    payload = _skill_payload(body)
    if not eid or not sid or not payload.get("skill"):
        return _resp(400, {"error": "entityId, skillId and skill (instruction text) required"})
    st, d = _meta_request("PUT", f"{GRAPH_HOST}/{eid}/agent_config/skills/{sid}", payload)
    return _resp(_pass_status(st, (200,)), {"skill": d, "entityId": eid})


def _skills_delete(body: dict):
    """DELETE /{entity_id}/agent_config/skills/{skill_id} -> 204"""
    eid = _entity(body)
    sid = (body.get("skillId") or "").strip()
    if not eid or not sid:
        return _resp(400, {"error": "entityId and skillId required"})
    st, d = _meta_request("DELETE", f"{GRAPH_HOST}/{eid}/agent_config/skills/{sid}", None)
    return _resp(_pass_status(st, (200, 204), success_status=200), {"deleted": st in (200, 204), "detail": d})


# ── Business Info (agent_config/business_info) — VERIFIED paths ──
_BUSINESS_INFO_FIELDS = {"payment_method", "return_policy", "purchase_info",
                         "delivery_and_shipping", "business_description", "contact_info"}


def _business_info_get(body: dict):
    """GET /{entity_id}/agent_config/business_info"""
    eid = _entity(body)
    if not eid:
        return _resp(400, {"error": "entityId required"})
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_config/business_info", None)
    return _resp(_pass_status(st, (200,)), {"business_info": d, "entityId": eid})


def _business_info_update(body: dict):
    """PUT /{entity_id}/agent_config/business_info — full replace with provided fields."""
    eid = _entity(body)
    info = body.get("businessInfo") or body.get("business_info") or {}
    if not eid or not isinstance(info, dict) or not info:
        return _resp(400, {"error": "entityId and businessInfo{} required"})
    payload = {k: v for k, v in info.items() if k in _BUSINESS_INFO_FIELDS}
    st, d = _meta_request("PUT", f"{GRAPH_HOST}/{eid}/agent_config/business_info", payload)
    return _resp(_pass_status(st, (200,)), {"business_info": d, "entityId": eid})


def _business_info_reset(body: dict):
    """DELETE /{entity_id}/agent_config/business_info — reset to defaults."""
    eid = _entity(body)
    if not eid:
        return _resp(400, {"error": "entityId required"})
    st, d = _meta_request("DELETE", f"{GRAPH_HOST}/{eid}/agent_config/business_info", None)
    return _resp(_pass_status(st, (200,)), {"business_info": d, "entityId": eid})


# ── FAQs (agent_config/faq) — VERIFIED paths ──
def _faq_list(body: dict):
    """GET /{entity_id}/agent_config/faq -> [{id, question, answer, created_at}]"""
    eid = _entity(body)
    if not eid:
        return _resp(400, {"error": "entityId required"})
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_config/faq", None)
    return _resp(_pass_status(st, (200,)), {"faqs": d, "entityId": eid})


def _faq_create(body: dict):
    """POST /{entity_id}/agent_config/faq  {question, answer, metadata?}"""
    eid = _entity(body)
    q = (body.get("question") or "").strip()
    a = (body.get("answer") or "").strip()
    if not eid or not q or not a:
        return _resp(400, {"error": "entityId, question and answer required"})
    item = {"question": q, "answer": a}
    if isinstance(body.get("metadata"), dict):
        item["metadata"] = body["metadata"]
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_config/faq", item)
    return _resp(_pass_status(st, (200, 201)), {"faq": d, "entityId": eid})


def _faq_update(body: dict):
    """PUT /{entity_id}/agent_config/faq/{faq_id}  {question, answer}"""
    eid = _entity(body)
    fid = (body.get("faqId") or "").strip()
    q = (body.get("question") or "").strip()
    a = (body.get("answer") or "").strip()
    if not eid or not fid or not q or not a:
        return _resp(400, {"error": "entityId, faqId, question and answer required"})
    item = {"question": q, "answer": a}
    if isinstance(body.get("metadata"), dict):
        item["metadata"] = body["metadata"]
    st, d = _meta_request("PUT", f"{GRAPH_HOST}/{eid}/agent_config/faq/{fid}", item)
    return _resp(_pass_status(st, (200,)), {"faq": d, "entityId": eid})


def _faq_delete(body: dict):
    """DELETE /{entity_id}/agent_config/faq/{faq_id} -> 204"""
    eid = _entity(body)
    fid = (body.get("faqId") or "").strip()
    if not eid or not fid:
        return _resp(400, {"error": "entityId and faqId required"})
    st, d = _meta_request("DELETE", f"{GRAPH_HOST}/{eid}/agent_config/faq/{fid}", None)
    return _resp(_pass_status(st, (200, 204), success_status=200), {"deleted": st in (200, 204), "detail": d})


# ── Websites (agent_config/websites) — crawled knowledge sources ──
def _websites_list(body: dict):
    """GET /{entity_id}/agent_config/websites -> [{id, url, crawl_status}]"""
    eid = _entity(body)
    if not eid:
        return _resp(400, {"error": "entityId required"})
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_config/websites", None)
    return _resp(_pass_status(st, (200,)), {"websites": d, "entityId": eid})


def _websites_add(body: dict):
    """POST /{entity_id}/agent_config/websites  {url}"""
    eid = _entity(body)
    url = (body.get("url") or "").strip()
    if not eid or not url:
        return _resp(400, {"error": "entityId and url required"})
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_config/websites", {"url": url})
    return _resp(_pass_status(st, (200, 201)), {"website": d, "entityId": eid})


def _websites_remove(body: dict):
    """DELETE /{entity_id}/agent_config/websites/{website_id}"""
    eid = _entity(body)
    wid = (body.get("websiteId") or "").strip()
    if not eid or not wid:
        return _resp(400, {"error": "entityId and websiteId required"})
    st, d = _meta_request("DELETE", f"{GRAPH_HOST}/{eid}/agent_config/websites/{wid}", None)
    return _resp(_pass_status(st, (200, 204), success_status=200), {"deleted": st in (200, 204), "detail": d})


# ── Connectors + Tools (agent_connectors/{connector_id}/tools) — lets the AI call our APIs ──
def _connectors_list(body: dict):
    """GET /{entity_id}/agent_connectors — external APIs the agent can call."""
    eid = _entity(body)
    if not eid:
        return _resp(400, {"error": "entityId required"})
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_connectors", None)
    return _resp(_pass_status(st, (200,)), {"connectors": d, "entityId": eid})


def _list_connectors_raw(eid: str) -> list:
    """Return the raw connectors array for an entity (empty list on any error)."""
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_connectors", None)
    if st != 200:
        return []
    if isinstance(d, dict):
        return d.get("data") if isinstance(d.get("data"), list) else []
    return d if isinstance(d, list) else []


def _find_connector(connectors: list, *, name: str | None = None, cid: str | None = None):
    """Find a connector by name or id in a raw connectors array."""
    for c in connectors:
        if not isinstance(c, dict):
            continue
        if cid and str(c.get("id") or c.get("connector_id") or "") == str(cid):
            return c
        if name and str(c.get("name") or "") == str(name):
            return c
    return None


def _connectors_add(body: dict):
    """POST /{entity_id}/agent_connectors  {connector...}

    Meta's Membrane backend returns a cosmetic 500 ("Membrane: Authorization
    failed") on create even though the connector IS provisioned and becomes
    ACTIVE. So on any non-2xx we re-list and, if the named connector now exists,
    treat it as success. Verified live against WABA1 (2026-07)."""
    eid = _entity(body); spec = body.get("connector") or {}
    if not eid or not spec:
        return _resp(400, {"error": "entityId and connector{} required"})
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_connectors", spec)
    if st in (200, 201):
        return _resp(st, {"created": d, "entityId": eid})
    # cosmetic-500 tolerance: re-list and confirm the connector actually exists
    found = _find_connector(_list_connectors_raw(eid), name=spec.get("name"))
    if found:
        logger.info(json.dumps({"event": "connector_add_recovered", "entity": eid,
                                "name": spec.get("name"), "upstreamStatus": st}))
        return _resp(200, {"created": found, "entityId": eid, "recovered": True,
                           "note": "upstream returned %s but connector is provisioned" % st})
    return _resp(_pass_status(st, (200, 201)), {"created": d, "entityId": eid})


def _connectors_remove(body: dict):
    """DELETE /{entity_id}/agent_connectors/{connector_id}

    Same cosmetic-500 handling as create: DELETE can return 500 while actually
    archiving the connector. On non-2xx we re-list and, if the connector id is
    gone, report success."""
    eid = _entity(body); cid = body.get("connectorId", "")
    if not eid or not cid:
        return _resp(400, {"error": "entityId and connectorId required"})
    st, d = _meta_request("DELETE", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}", None)
    if st in (200, 204):
        return _resp(200, {"deleted": True, "detail": d})
    # cosmetic-500 tolerance: if the connector is no longer listed, it's gone
    still_there = _find_connector(_list_connectors_raw(eid), cid=cid)
    if not still_there:
        logger.info(json.dumps({"event": "connector_remove_recovered", "entity": eid,
                                "connectorId": cid, "upstreamStatus": st}))
        return _resp(200, {"deleted": True, "recovered": True,
                           "note": "upstream returned %s but connector is gone" % st})
    return _resp(_pass_status(st, (200, 204), success_status=200), {"deleted": False, "detail": d})


def _tools_list(body: dict):
    """GET /{entity_id}/agent_connectors/{connector_id}/tools"""
    eid = _entity(body); cid = body.get("connectorId", "")
    if not eid or not cid:
        return _resp(400, {"error": "entityId and connectorId required"})
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}/tools", None)
    return _resp(_pass_status(st, (200,)), {"tools": d, "entityId": eid})


def _tools_add(body: dict):
    """POST /{entity_id}/agent_connectors/{connector_id}/tools  {tool...}"""
    eid = _entity(body); cid = body.get("connectorId", ""); spec = body.get("tool") or {}
    if not eid or not cid or not spec:
        return _resp(400, {"error": "entityId, connectorId and tool{} required"})
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}/tools", spec)
    return _resp(_pass_status(st, (200, 201)), {"created": d, "entityId": eid})


def _tools_remove(body: dict):
    """DELETE /{entity_id}/agent_connectors/{connector_id}/tools/{tool_id}"""
    eid = _entity(body); cid = body.get("connectorId", ""); tid = body.get("toolId", "")
    if not eid or not cid or not tid:
        return _resp(400, {"error": "entityId, connectorId and toolId required"})
    st, d = _meta_request("DELETE", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}/tools/{tid}", None)
    return _resp(_pass_status(st, (200, 204), success_status=200), {"deleted": st in (200, 204), "detail": d})


def _tools_run(body: dict):
    """POST /{entity_id}/agent_connectors/{connector_id}/tools/{tool_id}/run  {input}"""
    eid = _entity(body); cid = body.get("connectorId", ""); tid = body.get("toolId", "")
    if not eid or not cid or not tid:
        return _resp(400, {"error": "entityId, connectorId and toolId required"})
    payload = {"input": body.get("input") or "{}"}
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}/tools/{tid}/run", payload)
    return _resp(_pass_status(st, (200,)), {"result": d, "entityId": eid})


def _connector_get(body: dict):
    """GET /{entity_id}/agent_connectors/{connector_id} — single connector detail."""
    eid = _entity(body); cid = body.get("connectorId", "")
    if not eid or not cid:
        return _resp(400, {"error": "entityId and connectorId required"})
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}", None)
    return _resp(_pass_status(st, (200,)), {"connector": d, "entityId": eid})


def _connector_logs(body: dict):
    """GET /{entity_id}/agent_connectors/{connector_id}/logs?include_stats=true
    Returns recent tool-call logs + success-rate stats for the connector."""
    eid = _entity(body); cid = body.get("connectorId", "")
    if not eid or not cid:
        return _resp(400, {"error": "entityId and connectorId required"})
    inc = "true" if body.get("includeStats", True) else "false"
    st, d = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}/logs?include_stats={inc}", None)
    return _resp(_pass_status(st, (200,)), {"logs": d, "entityId": eid})


def _connector_upsert_apikey(body: dict):
    """POST /{entity_id}/agent_connectors/{connector_id}/upsertApiKey
    Sets/updates the API_KEY auth for a connector.
    Expects auth{api_key:{headers:[{field_name,value,prefix?}]}} or a flat
    {headerName, headerValue, prefix?} shorthand."""
    eid = _entity(body); cid = body.get("connectorId", "")
    if not eid or not cid:
        return _resp(400, {"error": "entityId and connectorId required"})
    auth = body.get("auth")
    if not auth:
        hn = (body.get("headerName") or "").strip()
        hv = (body.get("headerValue") or "").strip()
        if not hn or not hv:
            return _resp(400, {"error": "auth{} or headerName+headerValue required"})
        header = {"field_name": hn, "value": hv}
        if body.get("prefix"):
            header["prefix"] = body["prefix"]
        auth = {"api_key": {"headers": [header]}}
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}/upsertApiKey", auth)
    return _resp(_pass_status(st, (200, 201)), {"result": d, "entityId": eid})


def _connector_upsert_oauth(body: dict):
    """POST /{entity_id}/agent_connectors/{connector_id}/upsertOAuth
    Sets/updates OAUTH2_CLIENT_CREDENTIALS auth for a connector."""
    eid = _entity(body); cid = body.get("connectorId", "")
    if not eid or not cid:
        return _resp(400, {"error": "entityId and connectorId required"})
    auth = body.get("auth") or {}
    if not auth:
        return _resp(400, {"error": "auth{oauth2_client_credentials:{...}} required"})
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_connectors/{cid}/upsertOAuth", auth)
    return _resp(_pass_status(st, (200, 201)), {"result": d, "entityId": eid})


def _provider_status(body: dict):
    """Consolidated Tech Provider overview for BOTH WABAs, so the console can
    render per-WABA workspace/connector state in one call. For each WABA we
    report: phone entity id, eligibility, connector count + names/statuses, and
    whether a connector workspace appears provisioned."""
    # Which WABAs to report — default both.
    targets = [
        {"waba": "WABA1", "entityId": DEFAULT_ENTITIES["WABA1"], "wabaId": WABA_IDS["WABA1"]},
        {"waba": "WABA2", "entityId": DEFAULT_ENTITIES["WABA2"], "wabaId": WABA_IDS["WABA2"]},
    ]
    only = (body.get("waba") or "").upper()
    if only in ("WABA1", "WABA2"):
        targets = [t for t in targets if t["waba"] == only]

    out = []
    for t in targets:
        eid = t["entityId"]
        # eligibility (200 => agent eligible)
        est, edata = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_eligibility/", None)
        connectors = _list_connectors_raw(eid)
        conn_summ = []
        for c in connectors:
            if not isinstance(c, dict):
                continue
            conn_summ.append({
                "id": str(c.get("id") or c.get("connector_id") or ""),
                "name": c.get("name"),
                "status": (c.get("connection_status") or {}).get("status") if isinstance(c.get("connection_status"), dict) else c.get("status"),
                "authType": c.get("auth_type"),
                "baseUrl": c.get("base_url"),
            })
        # Connector API readability: does the connectors endpoint respond 200?
        # NOTE: a 200 list does NOT guarantee create works — the per-WABA
        # connector *workspace* is provisioned separately by Meta and create can
        # still return 400 "No workspace found" (observed on WABA2, 2026-07).
        # We infer write-readiness from the presence of connectors: if any exist
        # the workspace clearly accepts writes; otherwise it's unconfirmed.
        lst_st, _ = _meta_request("GET", f"{GRAPH_HOST}/{eid}/agent_connectors", None)
        out.append({
            "waba": t["waba"],
            "entityId": eid,
            "wabaId": t["wabaId"],
            "eligible": est == 200 and bool((edata or {}).get("is_eligible", True)),
            "eligibilityStatus": est,
            "eligibility": edata,
            "connectorsReadable": lst_st == 200,
            # workspace confirmed writable only when it already holds connectors
            "workspaceProvisioned": lst_st == 200 and len(conn_summ) > 0,
            "connectorCount": len(conn_summ),
            "connectors": conn_summ,
        })
    return _resp(200, {"providers": out})


# ─────────────────────────────────────────────────────────────────────────
# Operate group — thread control, agent events, test, eval.
# ─────────────────────────────────────────────────────────────────────────

_THREAD_CONTROL_ACTIONS = ("release", "pass", "take")


def _thread_control_recipient(bsuid: str, to: str) -> dict:
    """The thread_control recipient shape, in one place.

    UNVERIFIED. This repository's only PROVEN BSUID-recipient form is FLAT:
    whatsapp-business-api._send_message:2096-2102 sets message['recipient'] = '<bsuid>'
    as a bare string, and the _thread_control this replaced sent a flat "to". The
    nested object below is what Conversation Routing is believed to want, and no live
    round trip can settle it here because a routing configuration is owner answer O1,
    which is unanswered.

    So this is the one correction point. The tests read this helper rather than
    asserting a literal nesting, which means a corrected shape costs one function body
    and zero test edits -- the same discipline the carousel action key and the MM edge
    name get.
    """
    return {"recipient": {"user_id": bsuid} if bsuid else {"to": to}}


def _thread_control(body: dict):
    """POST {GRAPH}/{phone_number_id}/thread_control -- Conversation Routing.

    `release` hands the thread back to the responder that passed it to us. `pass`
    hands it to a named role and requires control_pass.target_role. `take` is REFUSED
    in code: Meta answers 2494191 unless this account is the designated escalation
    partner, which is owner answer O3 and is unanswered -- a structured 409 naming O3
    is more useful to an operator than a Graph 400 they cannot interpret.

    The thread is identified by BSUID where one is known, because that is how a routing
    event identifies it (see lambda_utils.thread_ownership.parse_handover). `to` is the
    fallback.
    """
    phone_id = _entity(body)
    bsuid = (body.get("bsuid") or body.get("userId") or "").strip()
    to = (body.get("to") or body.get("recipient") or "").strip()
    action = (body.get("action") or "release").lower()
    target_role = (body.get("targetRole") or body.get("target_role") or "").strip()

    if not phone_id:
        return _resp(400, {"error": "entityId (phone_number_id) required"})
    if not bsuid and not to:
        return _resp(400, {"error": "one of bsuid (business-scoped user id) or to "
                                    "(consumer phone, E.164) required"})
    if action not in _THREAD_CONTROL_ACTIONS:
        return _resp(400, {"error": f"action must be one of {list(_THREAD_CONTROL_ACTIONS)}"})
    if action == "take":
        return _resp(409, {
            "error": "take is not available",
            "reason": ("Taking thread control requires this account to be the designated "
                       "escalation partner. That designation is owner answer O3 in "
                       ".agents/tasks/conversation-routing-20261006/findings.md and is "
                       "unanswered; Meta would answer 2494191."),
            "ownerAction": "O3",
            "action": action})
    if action == "pass" and not target_role:
        return _resp(400, {"error": "targetRole is required for action=pass"})

    payload = {"messaging_product": "whatsapp", "action": action}
    payload.update(_thread_control_recipient(bsuid, to))
    if action == "pass":
        payload["control_pass"] = {"target_role": target_role}

    status, data = _meta_request("POST", f"{GRAPH}/{phone_id}/thread_control",
                                 payload, api_version=None)
    logger.info(json.dumps({
        "event": "thread_control_requested", "action": action,
        "phoneNumberId": phone_id, "bsuid": bsuid,
        "to": mask_phone(to) if to else "",
        "targetRole": target_role, "httpStatus": status}))
    return _resp(_pass_status(status, (200,)),
                 {"thread_control": data, "action": action, "entityId": phone_id,
                  "bsuid": bsuid, "targetRole": target_role or None})


def _agent_event(body: dict):
    """POST /{entity_id}/agent_event — trigger an agent action on a business event
    (e.g. payment_received, document_verified). Body: {to, event:{type, description, payload}}."""
    eid = _entity(body)
    to = (body.get("to") or "").strip()
    event = body.get("event") or {}
    if not eid or not to or not isinstance(event, dict) or not event.get("type"):
        return _resp(400, {"error": "entityId, to (E.164) and event{type, description, payload} required"})
    # payload must be an opaque JSON string
    if isinstance(event.get("payload"), (dict, list)):
        event["payload"] = json.dumps(event["payload"])
    st, d = _meta_request("POST", f"{GRAPH_HOST}/{eid}/agent_event", {"to": to, "event": event})
    return _resp(_pass_status(st, (200, 201)), {"event": d, "entityId": eid})


def _agent_test(body: dict):
    """POST /{entity_id}/agent_test — send a test message to the agent."""
    eid = _entity(body); msg = body.get("message")
    if not eid or not msg:
        return _resp(400, {"error": "entityId and message required"})
    st, d = _meta_request("POST", _with_agent(f"{GRAPH_HOST}/{eid}/agent_test", body.get("agentId")), {"message": msg})
    return _resp(_pass_status(st, (200, 201)), {"result": d, "entityId": eid})


def _agent_eval(body: dict):
    """Agent eval (agent-eval, hyphen) — GET /cases|/summary|/details|/run, POST /run.
    Defaults to listing eval cases. sub = cases|summary|details|run ; extra query passthrough."""
    eid = _entity(body)
    if not eid:
        return _resp(400, {"error": "entityId required"})
    sub = (body.get("sub") or "cases").lower()
    method = (body.get("method") or ("POST" if body.get("evalCaseIds") else "GET")).upper()
    qs = []
    for k in ("job_id", "eval_ids", "summary_ids", "eval_case_ids"):
        camel = ''.join([k.split('_')[0]] + [p.capitalize() for p in k.split('_')[1:]])
        if body.get(camel):
            qs.append(f"{k}={body[camel]}")
    url = f"{GRAPH_HOST}/{eid}/agent-eval/{sub}"
    if qs:
        url += "?" + "&".join(qs)
    st, d = _meta_request(method, url, body.get("payload") if method == "POST" else None)
    return _resp(_pass_status(st, (200,)), {"eval": d, "sub": sub, "entityId": eid})


# ─────────────────────────────────────────────────────────────────────────
# Tech Partner readiness — live measurement of the 4 upgrade eligibility gates
#   1. quality   : phone quality rating >= GREEN on both WABAs
#   2. volume    : >= 2,500 avg daily messages (sent+delivered) over last 7 days
#   3. clients   : >= 10 onboarded partner tenants (active senders in 30d)
#   4. (provider): Tech Provider Get Started completed (already true)
# ─────────────────────────────────────────────────────────────────────────
PARTNER_WALLET_TABLE = os.environ.get("PARTNER_WALLET_TABLE", "stack-wecare-digital-PartnerWallet")
BUSINESS_PORTFOLIO_ID = os.environ.get("META_BUSINESS_ID", "382642103987922")
_QUALITY_OK = {"GREEN"}


def _tp_eligibility(_body):
    now = int(time.time())
    start = now - 7 * 86400

    # ── Gate 1: phone quality rating (per WABA) ──
    quality = {}
    q_pass = True
    for name, pid in (("WABA1", DEFAULT_ENTITIES["WABA1"]), ("WABA2", DEFAULT_ENTITIES["WABA2"])):
        st, d = _meta_request(
            "GET",
            f"{GRAPH}/{pid}?fields=display_phone_number,verified_name,quality_rating,status",
            None,
        )
        rating = (d or {}).get("quality_rating") if isinstance(d, dict) else None
        quality[name] = {
            "phone": (d or {}).get("display_phone_number") if isinstance(d, dict) else None,
            "rating": rating,
            "status": (d or {}).get("status") if isinstance(d, dict) else None,
            "ok": rating in _QUALITY_OK,
        }
        q_pass = q_pass and (rating in _QUALITY_OK)

    # ── Gate 2: message volume (7-day avg/day across both WABAs) ──
    per_waba = {}
    total_msgs = 0
    for name, waba in (("WABA1", WABA_IDS["WABA1"]), ("WABA2", WABA_IDS["WABA2"])):
        st, d = _meta_request(
            "GET",
            f"{GRAPH}/{waba}?fields=analytics.start({start}).end({now}).granularity(DAY)",
            None,
        )
        pts = (((d or {}).get("analytics") or {}).get("data_points")
               if isinstance(d, dict) else None) or []
        wtotal = sum((p.get("sent", 0) + p.get("delivered", 0)) for p in pts)
        per_waba[name] = {"total7d": wtotal, "points": len(pts)}
        total_msgs += wtotal
    avg_per_day = round(total_msgs / 7.0, 1)
    v_pass = avg_per_day >= 2500

    # ── Gate 3: active clients ──
    # Meta counts CLIENT WhatsApp Business Accounts shared to the app (separate
    # businesses), NOT the app owner's own owned WABAs. So we read the business
    # portfolio's client_whatsapp_business_accounts edge. Test/sandbox WABAs are
    # flagged so the operator sees exactly what counts.
    clients_err = ""
    client_list = []
    owned_count = 0
    try:
        st, cd = _meta_request(
            "GET", f"{GRAPH}/{BUSINESS_PORTFOLIO_ID}/client_whatsapp_business_accounts?fields=id,name",
            None)
        for w in ((cd or {}).get("data") or []):
            nm = w.get("name") or ""
            client_list.append({"id": w.get("id"), "name": nm,
                                 "isTest": "test" in nm.lower()})
        st2, od = _meta_request(
            "GET", f"{GRAPH}/{BUSINESS_PORTFOLIO_ID}/owned_whatsapp_business_accounts?fields=id",
            None)
        owned_count = len((od or {}).get("data") or [])
    except Exception as e:  # noqa: BLE001
        clients_err = str(e)[:160]
    # "real" clients exclude sandbox/test WABAs
    real_clients = [c for c in client_list if not c["isTest"]]
    active_clients = len(real_clients)
    c_pass = active_clients >= 10

    gates = {
        "provider": {"pass": True, "label": "Tech Provider Get Started",
                     "detail": "Completed — app has Tech Provider status."},
        "quality": {"pass": q_pass, "label": "Phone quality rating ≥ GREEN",
                    "byWaba": quality},
        "volume": {"pass": v_pass, "label": "≥ 2,500 avg daily messages (7d)",
                   "avgPerDay": avg_per_day, "threshold": 2500,
                   "total7d": total_msgs, "byWaba": per_waba},
        "clients": {"pass": c_pass, "label": "≥ 10 active client businesses",
                    "active": active_clients, "threshold": 10, "error": clients_err,
                    "ownedWabas": owned_count, "clientList": client_list,
                    "testCount": len(client_list) - len(real_clients)},
    }
    return _resp(200, {
        "eligible": all(g["pass"] for g in gates.values()),
        "gates": gates,
        "checkedAt": now,
    })


def lambda_handler(event, context):
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except Exception:
            event = {}
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    # Agent Tool endpoint (POST /agent-tool) — called by Meta's agent connector,
    # gated by the X-Agent-Token header (NOT Cognito). Must run before require_auth.
    _path = (event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "")
             or event.get("routeKey", ""))
    if "agent-tool" in _path:
        return _agent_tool(event)

    # Inbound auth: require a valid Cognito token (gateway routes are NONE, so
    # protection is enforced here — consistent with the platform middleware).
    auth = require_auth(event)
    if auth is not None:
        return auth

    body = {}
    if isinstance(event.get("body"), str):
        try:
            body = json.loads(event["body"])
        except Exception:
            body = {}
    body = {**event, **body}
    action = body.get("action") or ("onboard" if "onboard" in (event.get("routeKey", "") + event.get("rawPath", "")) else "")

    if action == "readiness":
        return _readiness(body)
    if action == "eligibility":
        return _eligibility(body)
    if action == "onboard":
        return _onboard(body)
    if action in ("settings", "settings_get"):
        return _settings_get(body)
    if action in ("settings_update", "enable", "disable"):
        if action == "enable":
            body["enabled"] = True
        elif action == "disable":
            body["enabled"] = False
        return _settings_update(body)
    if action in ("allowlist", "allowlist_list"):
        return _allowlist_list(body)
    if action == "allowlist_add":
        return _allowlist_add(body)
    if action == "allowlist_remove":
        return _allowlist_remove(body)
    # Configure group
    if action in ("skills", "skills_list"):
        return _skills_get(body)
    if action == "skills_create":
        return _skills_create(body)
    if action == "skills_update":
        return _skills_update(body)
    if action == "skills_delete":
        return _skills_delete(body)
    # Business info (knowledge)
    if action in ("business_info", "business_info_get"):
        return _business_info_get(body)
    if action == "business_info_update":
        return _business_info_update(body)
    if action == "business_info_reset":
        return _business_info_reset(body)
    # FAQs
    if action in ("faq", "faq_list", "faqs"):
        return _faq_list(body)
    if action == "faq_create":
        return _faq_create(body)
    if action == "faq_update":
        return _faq_update(body)
    if action == "faq_delete":
        return _faq_delete(body)
    # Websites
    if action in ("websites", "websites_list"):
        return _websites_list(body)
    if action == "websites_add":
        return _websites_add(body)
    if action == "websites_remove":
        return _websites_remove(body)
    # Connectors + tools
    if action in ("connectors", "connectors_list"):
        return _connectors_list(body)
    if action == "connectors_add":
        return _connectors_add(body)
    if action == "connectors_remove":
        return _connectors_remove(body)
    if action in ("tools", "tools_list"):
        return _tools_list(body)
    if action == "tools_add":
        return _tools_add(body)
    if action == "tools_remove":
        return _tools_remove(body)
    if action == "tools_run":
        return _tools_run(body)
    if action in ("connector_get", "connector"):
        return _connector_get(body)
    if action in ("connector_logs", "logs"):
        return _connector_logs(body)
    if action in ("connector_upsert_apikey", "upsert_apikey"):
        return _connector_upsert_apikey(body)
    if action in ("connector_upsert_oauth", "upsert_oauth"):
        return _connector_upsert_oauth(body)
    if action in ("provider_status", "tech_provider", "providers"):
        return _provider_status(body)
    if action in ("tp_eligibility", "tech_partner_readiness", "readiness_partner"):
        return _tp_eligibility(body)
    # Operate group
    if action == "thread_control":
        return _thread_control(body)
    if action == "agent_event":
        return _agent_event(body)
    if action == "agent_test":
        return _agent_test(body)
    if action == "agent_eval":
        return _agent_eval(body)
    if action == "entities":
        return _resp(200, {"entities": DEFAULT_ENTITIES, "channels": sorted(CHANNELS)})
    return _resp(400, {"error": "unknown action", "supported": [
        "eligibility", "onboard", "readiness", "settings", "settings_update", "enable", "disable",
        "allowlist", "allowlist_add", "allowlist_remove",
        "skills", "skills_create", "skills_update", "skills_delete",
        "business_info", "business_info_update", "business_info_reset",
        "faq", "faq_create", "faq_update", "faq_delete",
        "websites", "websites_add", "websites_remove",
        "connectors", "connectors_add", "connectors_remove",
        "connector_get", "connector_logs", "connector_upsert_apikey", "connector_upsert_oauth",
        "provider_status", "tp_eligibility",
        "tools", "tools_add", "tools_remove", "tools_run",
        "thread_control", "agent_event", "agent_test", "agent_eval", "entities"]})
