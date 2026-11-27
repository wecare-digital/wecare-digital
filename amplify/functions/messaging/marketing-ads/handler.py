"""
Marketing Ads — WECARE.DIGITAL  (Ads that Click to WhatsApp / CTWA)

Backend for creating and managing "Ads that Click to WhatsApp" via the Meta
Marketing API. A click on the ad opens a WhatsApp chat with our business number,
optionally pre-filling a greeting/autofill message.

Marketing API flow (docs: developers.facebook.com/documentation/ads-commerce/
marketing-api/ad-creative/messaging-ads/click-to-whatsapp):
  1. POST /act_{ad_account}/campaigns        -> campaign_id   (objective OUTCOME_*)
  2. POST /act_{ad_account}/adsets           -> adset_id      (destination_type WHATSAPP)
  3. POST /act_{ad_account}/adcreatives      -> creative_id   (object_story_spec)
  4. POST /act_{ad_account}/ads              -> ad_id         (creative + adset)
  5. POST /{ad_id} status=ACTIVE             -> publish (review -> PENDING_REVIEW)

SAFETY: everything is created PAUSED by default. Nothing spends money until the
ad is explicitly published (action=ad_publish) AND approved by Meta review.

Auth: Cognito (require_auth) for the console. Meta token from Secrets Manager
(wecare/meta-system-user-token) with appsecret_proof — never from env.

Permissions this exercises (App Review, advanced access):
  ads_management, ads_read, pages_manage_ads, pages_read_engagement, pages_show_list
"""

import os
import json
import hmac
import hashlib
import logging
import urllib.request
import urllib.parse
import urllib.error

import boto3

from lambda_utils.middleware import require_auth
from lambda_utils.response import cors_headers
from lambda_utils.meta_version import GRAPH_BASE  # one source; validated at import
from lambda_utils import media_paths  # one bucket, two roots: o/ public, secure/ gated

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-east-1")
secrets_client = boto3.client("secretsmanager", region_name=REGION)
META_TOKEN_SECRET = os.environ.get("META_TOKEN_SECRET", "wecare/meta-system-user-token")
GRAPH = os.environ.get("META_GRAPH_BASE", GRAPH_BASE)

# Business assets (discovered live 2026-07). Frontend may override per request.
BUSINESS_PORTFOLIO_ID = os.environ.get("META_BUSINESS_ID", "382642103987922")
DEFAULT_AD_ACCOUNT = os.environ.get("META_AD_ACCOUNT", "506155527842845")  # WECARE.DIGITAL ADS ACCOUNT
DEFAULT_PAGE_ID = os.environ.get("META_PAGE_ID", "820748321125906")         # Wecare.Digital

# WABA display phone numbers (E.164, digits only) for promoted_object.whatsapp_phone_number
WABA_PHONE = {
    "WABA1": os.environ.get("WABA1_DISPLAY", "919330994400"),   # +91 93309 94400
    "WABA2": os.environ.get("WABA2_DISPLAY", "919903300044"),   # +91 99033 00044
}

_OBJECTIVES = {"OUTCOME_ENGAGEMENT", "OUTCOME_LEADS", "OUTCOME_SALES", "OUTCOME_TRAFFIC"}
_OPT_GOALS = {"CONVERSATIONS", "LINK_CLICKS", "IMPRESSIONS", "REACH",
              "LANDING_PAGE_VIEWS", "POST_ENGAGEMENT", "OFFSITE_CONVERSIONS"}
_STATUSES = {"ACTIVE", "PAUSED", "DELETED", "ARCHIVED"}

_token_cache = {}
# Authenticated admin API: answer only the canonical origin, never "*".
CORS = {
    **cors_headers(None, "GET,POST,OPTIONS", "Content-Type,Authorization"),
    "Vary": "Origin",
}


def _creds():
    if "t" in _token_cache:
        return _token_cache["t"], _token_cache["s"]
    resp = secrets_client.get_secret_value(SecretId=META_TOKEN_SECRET)
    data = json.loads(resp["SecretString"])
    _token_cache["t"] = (data.get("access_token") or "").strip()
    _token_cache["s"] = (data.get("app_secret") or "").strip()
    return _token_cache["t"], _token_cache["s"]


def _proof(token, secret):
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest() if secret else ""


def _resp(status, body):
    return {"statusCode": status, "headers": CORS, "body": json.dumps(body)}


def _pass_status(status, ok=(200, 201)):
    if status in ok:
        return status
    if 400 <= status < 500:
        return status
    return 502


def _graph(method, path, params=None, form=None, raw_body=None, headers=None):
    """Call the Graph/Marketing API. `params` -> querystring, `form` -> urlencoded
    body, `raw_body` -> bytes with custom headers (multipart). Auth is added
    automatically (access_token + appsecret_proof)."""
    token, secret = _creds()
    q = dict(params or {})
    q["access_token"] = token
    if secret:
        q["appsecret_proof"] = _proof(token, secret)
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(q)}"
    data = None
    hdrs = dict(headers or {})
    if raw_body is not None:
        data = raw_body
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in hdrs.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail)
        except Exception:
            pass
        return e.code, {"error": detail}
    except Exception as e:  # noqa: BLE001
        return 502, {"error": str(e)}


def _act(body):
    """Resolve the ad account id (without the act_ prefix)."""
    acc = str(body.get("adAccountId") or DEFAULT_AD_ACCOUNT).replace("act_", "")
    return acc


def _page(body):
    return str(body.get("pageId") or DEFAULT_PAGE_ID)


# ─────────────────────────────────────────────────────────────────────────
# Discovery
# ─────────────────────────────────────────────────────────────────────────
def _ad_accounts(_body):
    st, d = _graph("GET", "me/adaccounts",
                   {"fields": "id,account_id,name,account_status,currency"})
    return _resp(_pass_status(st), {"adAccounts": d})


def _pages(_body):
    st, d = _graph("GET", f"{BUSINESS_PORTFOLIO_ID}/owned_pages",
                   {"fields": "id,name,connected_whatsapp_business_account"})
    return _resp(_pass_status(st), {"pages": d})


def _upload_image(body):
    """POST /act_{acc}/adimages — multipart upload of an image. Returns image_hash.
    Accepts base64 `imageData` (+ optional contentType) or an S3 `s3Key`."""
    import base64
    import uuid
    acc = _act(body)
    b64 = body.get("imageData")
    s3_key = body.get("s3Key")
    if s3_key:
        s3 = boto3.client("s3", region_name=REGION)
        bucket = body.get("bucket") or os.environ.get("MEDIA_BUCKET", media_paths.BUCKET)
        # The caller hands us a key it read off a message or media row, so root it.
        img = s3.get_object(Bucket=bucket, Key=media_paths.canonical(s3_key))["Body"].read()
        ctype = body.get("contentType", "image/jpeg")
    elif b64:
        img = base64.b64decode(b64)
        ctype = body.get("contentType", "image/jpeg")
    else:
        return _resp(400, {"error": "imageData (base64) or s3Key required"})
    filename = body.get("filename", "adimage.jpg")
    boundary = uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="filename"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {ctype}\r\n\r\n".encode(),
        img, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    st, d = _graph("POST", f"act_{acc}/adimages", raw_body=b"".join(parts),
                   headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    # Response: {"images": {"<filename>": {"hash": "...", "url": "..."}}}
    image_hash = None
    if isinstance(d, dict) and isinstance(d.get("images"), dict):
        for _k, v in d["images"].items():
            image_hash = (v or {}).get("hash")
            break
    return _resp(_pass_status(st), {"imageHash": image_hash, "raw": d})


# ─────────────────────────────────────────────────────────────────────────
# Campaign / Ad set / Creative / Ad
# ─────────────────────────────────────────────────────────────────────────
def _campaigns_list(body):
    acc = _act(body)
    st, d = _graph("GET", f"act_{acc}/campaigns",
                   {"fields": "id,name,objective,status,effective_status,created_time", "limit": "50"})
    return _resp(_pass_status(st), {"campaigns": d})


def _campaign_create(body):
    acc = _act(body)
    name = (body.get("name") or "").strip()
    objective = (body.get("objective") or "OUTCOME_ENGAGEMENT").upper()
    if not name:
        return _resp(400, {"error": "name required"})
    if objective not in _OBJECTIVES:
        return _resp(400, {"error": f"objective must be one of {sorted(_OBJECTIVES)}"})
    form = {
        "name": name,
        "objective": objective,
        "status": (body.get("status") or "PAUSED").upper(),
        "special_ad_categories": json.dumps(body.get("specialAdCategories") or []),
        # Required by Marketing API when campaign budget is not set: each ad set
        # keeps its own budget (no cross-ad-set budget sharing) unless overridden.
        "is_adset_budget_sharing_enabled": "true" if body.get("adsetBudgetSharing") else "false",
    }
    st, d = _graph("POST", f"act_{acc}/campaigns", form=form)
    logger.info(json.dumps({"event": "campaign_create", "status": st, "name": name}))
    return _resp(_pass_status(st), {"campaign": d})


def _adset_create(body):
    """Create a WhatsApp-destination ad set. Money-safe: PAUSED by default."""
    acc = _act(body)
    name = (body.get("name") or "").strip()
    campaign_id = str(body.get("campaignId") or "")
    if not name or not campaign_id:
        return _resp(400, {"error": "name and campaignId required"})
    opt = (body.get("optimizationGoal") or "CONVERSATIONS").upper()
    if opt not in _OPT_GOALS:
        return _resp(400, {"error": f"optimizationGoal must be one of {sorted(_OPT_GOALS)}"})
    daily = int(body.get("dailyBudget") or 0)  # in minor units (paise for INR)
    if daily <= 0:
        return _resp(400, {"error": "dailyBudget (minor units, e.g. paise) required and > 0"})

    waba = (body.get("waba") or "WABA1").upper()
    promoted = {"page_id": _page(body)}
    wa_phone = body.get("whatsappPhoneNumber") or WABA_PHONE.get(waba)
    if wa_phone:
        promoted["whatsapp_phone_number"] = str(wa_phone)

    targeting = body.get("targeting") or {
        "geo_locations": {"countries": ["IN"]},
        "device_platforms": ["mobile", "desktop"],
    }
    form = {
        "name": name,
        "campaign_id": campaign_id,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": opt,
        "destination_type": "WHATSAPP",
        "daily_budget": str(daily),
        "promoted_object": json.dumps(promoted),
        "targeting": json.dumps(targeting),
        "status": (body.get("status") or "PAUSED").upper(),
    }
    if body.get("bidAmount"):
        form["bid_amount"] = str(int(body["bidAmount"]))
        form["bid_strategy"] = body.get("bidStrategy") or "LOWEST_COST_WITH_BID_CAP"
    else:
        # No bid cap -> automatic bidding (no bid_amount required).
        form["bid_strategy"] = body.get("bidStrategy") or "LOWEST_COST_WITHOUT_CAP"
    if body.get("startTime"):
        form["start_time"] = body["startTime"]
    st, d = _graph("POST", f"act_{acc}/adsets", form=form)
    logger.info(json.dumps({"event": "adset_create", "status": st, "waba": waba}))
    return _resp(_pass_status(st), {"adset": d})


def _welcome_message(body):
    """Build page_welcome_message from a simple {greeting, autofill} pair, or pass
    through a full object in `pageWelcomeMessage`."""
    if isinstance(body.get("pageWelcomeMessage"), dict):
        return body["pageWelcomeMessage"]
    greeting = body.get("greeting")
    autofill = body.get("autofill")
    if not greeting and not autofill:
        return None
    return {
        "type": "VISUAL_EDITOR", "version": 2,
        "landing_screen_type": "welcome_message", "media_type": "text",
        "text_format": {
            "customer_action_type": "autofill_message",
            "message": {
                "text": greeting or "Hello! How can we help you?",
                "autofill_message": {"content": autofill or "Hi, I'd like more info."},
            },
        },
    }


def _creative_create(body):
    acc = _act(body)
    name = (body.get("name") or "").strip()
    if not name:
        return _resp(400, {"error": "name required"})
    link_data = {
        "name": body.get("headline") or "",
        "message": body.get("primaryText") or "",
        "description": body.get("description") or "",
        "link": "https://api.whatsapp.com/send",
        "call_to_action": {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}},
    }
    if body.get("imageHash"):
        link_data["image_hash"] = body["imageHash"]
    wm = _welcome_message(body)
    if wm:
        link_data["page_welcome_message"] = json.dumps(wm) if isinstance(wm, dict) else wm
    story = {"page_id": _page(body), "link_data": link_data}
    form = {"name": name, "object_story_spec": json.dumps(story)}
    if body.get("standardEnhancements", True):
        form["degrees_of_freedom_spec"] = json.dumps(
            {"creative_features_spec": {"standard_enhancements": {"enroll_status": "OPT_IN"}}})
    st, d = _graph("POST", f"act_{acc}/adcreatives", form=form)
    logger.info(json.dumps({"event": "creative_create", "status": st}))
    return _resp(_pass_status(st), {"creative": d})


def _ad_create(body):
    acc = _act(body)
    name = (body.get("name") or "").strip()
    adset_id = str(body.get("adsetId") or "")
    creative_id = str(body.get("creativeId") or "")
    if not name or not adset_id or not creative_id:
        return _resp(400, {"error": "name, adsetId and creativeId required"})
    form = {
        "name": name,
        "adset_id": adset_id,
        "creative": json.dumps({"creative_id": creative_id}),
        "status": (body.get("status") or "PAUSED").upper(),
    }
    st, d = _graph("POST", f"act_{acc}/ads", form=form)
    logger.info(json.dumps({"event": "ad_create", "status": st}))
    return _resp(_pass_status(st), {"ad": d})


def _ads_list(body):
    acc = _act(body)
    st, d = _graph("GET", f"act_{acc}/ads",
                   {"fields": "id,name,status,effective_status,adset_id,campaign_id,created_time",
                    "limit": "50"})
    return _resp(_pass_status(st), {"ads": d})


def _ad_set_status(body):
    ad_id = str(body.get("adId") or "")
    status = (body.get("status") or "").upper()
    if not ad_id or status not in _STATUSES:
        return _resp(400, {"error": f"adId and status ({sorted(_STATUSES)}) required"})
    st, d = _graph("POST", ad_id, form={"status": status})
    logger.info(json.dumps({"event": "ad_status", "adId": ad_id, "status": status, "http": st}))
    return _resp(_pass_status(st, (200,)), {"updated": d, "status": status})


def _ad_status_read(body):
    ad_id = str(body.get("adId") or "")
    if not ad_id:
        return _resp(400, {"error": "adId required"})
    st, d = _graph("GET", ad_id, {"fields": "id,name,status,effective_status,adset_id,campaign_id"})
    return _resp(_pass_status(st, (200,)), {"ad": d})


def _full_create(body):
    """Convenience: create campaign -> adset -> creative -> ad in one call.
    Everything PAUSED. Returns all ids. Caller publishes explicitly afterwards."""
    steps = {}
    # campaign
    r = json.loads(_campaign_create(body)["body"])
    steps["campaign"] = r.get("campaign")
    cid = (r.get("campaign") or {}).get("id")
    if not cid:
        return _resp(400, {"error": "campaign create failed", "steps": steps})
    # adset
    r = json.loads(_adset_create({**body, "campaignId": cid,
                                  "name": body.get("adsetName") or (body.get("name") + " - adset")})["body"])
    steps["adset"] = r.get("adset")
    asid = (r.get("adset") or {}).get("id")
    if not asid:
        return _resp(400, {"error": "adset create failed", "steps": steps})
    # creative
    r = json.loads(_creative_create({**body,
                                     "name": body.get("creativeName") or (body.get("name") + " - creative")})["body"])
    steps["creative"] = r.get("creative")
    crid = (r.get("creative") or {}).get("id")
    if not crid:
        return _resp(400, {"error": "creative create failed", "steps": steps})
    # ad
    r = json.loads(_ad_create({**body, "adsetId": asid, "creativeId": crid,
                               "name": body.get("adName") or (body.get("name") + " - ad")})["body"])
    steps["ad"] = r.get("ad")
    return _resp(200, {"created": steps, "note": "All PAUSED. Publish with action=ad_publish."})


def lambda_handler(event, context):
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except Exception:
            event = {}
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "")
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    auth = require_auth(event)
    if auth is not None:
        return auth

    body = {}
    if isinstance(event.get("body"), str):
        try:
            body = json.loads(event["body"])
        except Exception:
            body = {}
    elif isinstance(event.get("body"), dict):
        body = event["body"]
    body = {**event, **body}
    action = body.get("action") or ""

    routes = {
        "ad_accounts": _ad_accounts,
        "pages": _pages,
        "upload_image": _upload_image,
        "campaigns": _campaigns_list, "campaigns_list": _campaigns_list,
        "campaign_create": _campaign_create,
        "adset_create": _adset_create,
        "creative_create": _creative_create,
        "ad_create": _ad_create,
        "ads": _ads_list, "ads_list": _ads_list,
        "ad_status": _ad_status_read,
        "ad_publish": lambda b: _ad_set_status({**b, "status": "ACTIVE"}),
        "ad_pause": lambda b: _ad_set_status({**b, "status": "PAUSED"}),
        "ad_set_status": _ad_set_status,
        "full_create": _full_create,
    }
    fn = routes.get(action)
    if not fn:
        return _resp(400, {"error": "unknown action", "supported": sorted(routes.keys())})
    return fn(body)


# API Gateway entrypoint alias
handler = lambda_handler
