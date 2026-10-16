#!/usr/bin/env python3
"""The supported-provider allow-list: the ONLY provider vocabulary the CI gates use.

What this is
------------
One declaration of every external party runtime code may depend on, and how it may be
referenced: hosts, Secrets Manager id prefixes, npm/pip packages, inbound webhook routes,
provider identifiers, environment-key namespaces and the names a screen may display.

Three gates read it:

    scripts/check_provider_allowlist.py   source  - runtime code references only what is here
    scripts/check_provider_policy_live.py live    - the AWS account uses only what is here
    scripts/check_ui_labels.py            UI      - a provider named on screen is named here

The gates are POSITIVE. They do not carry a list of providers that must not appear; they
fail on anything that is not declared below, whatever it is called. A provider that has
been retired is therefore not mentioned anywhere in CI - it is simply absent from this
file, and absence is what fails.

Adding a provider
-----------------
Adding an entry is a provider decision, not a lint fix. Give it a purpose, list only the
hosts, secret prefixes and packages it actually uses, and scope its transport to the
modules that hold it when the provider is approved for one capability only (see Sinch).
Removing a provider is the reverse: delete its entry, and the gates fail on every
reference that is left.

This module is data plus small pure helpers. It imports nothing outside the standard
library and performs no I/O, so every gate and test can import it.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    """One approved external party and every way runtime code may reference it."""

    key: str
    name: str
    purpose: str
    #: Registrable domains (or exact hosts) referenced anywhere in runtime scope. A host
    #: matches when it equals an entry or is a subdomain of it.
    domains: tuple = ()
    #: API hosts that must stay inside ``transport_scope``. Used for a provider approved
    #: for ONE capability, so its transport cannot be reached from any other module.
    transport_domains: tuple = ()
    #: Regex over the reference owner - a repo-relative path, or ``lambda:<name>`` for an
    #: entry in the Lambda environment manifest. Applies to transport hosts and secrets.
    transport_scope: str = ""
    #: Secrets Manager id prefixes. Confined to ``transport_scope`` when it is set.
    vault_prefixes: tuple = ()
    #: npm package names. ``@scope/*`` admits a whole scope.
    npm: tuple = ()
    #: pip distribution names (requirements files, Dockerfile installs).
    pip: tuple = ()
    #: Python top-level import names.
    imports: tuple = ()
    #: Values a ``provider`` field or selector may hold.
    provider_ids: tuple = ()
    #: Inbound webhook / callback routes, API-relative (no /api or stage prefix).
    webhook_routes: tuple = ()
    #: First token of a credential- or endpoint-shaped environment key.
    env_namespaces: tuple = ()
    #: Names a screen may display for this provider.
    ui_labels: tuple = ()


@dataclass(frozen=True)
class Reference:
    """A non-provider external reference: public content, standards and reserved names.

    None of these receives a credential or customer data. They are declared so that the
    host rule stays closed - an undeclared host fails whether or not it is a "provider".
    """

    key: str
    purpose: str
    domains: tuple = ()


@dataclass(frozen=True)
class Library:
    """A third-party package that is a library rather than a provider integration."""

    key: str
    purpose: str
    npm: tuple = ()
    pip: tuple = ()
    imports: tuple = ()


# --------------------------------------------------------------------------------------
# Where a single-capability provider's transport may live.
# --------------------------------------------------------------------------------------
#: Sinch is approved for India RCS only. Its API hosts and credential may appear only in
#: the RCS modules and in the environment of the RCS Lambdas.
RCS_TRANSPORT_SCOPE = (
    r"(lambda_utils/sinch_rcs\.py|lambda_utils/sinch_signature\.py|/rcs-send/|/rcs-dlr/"
    r"|providers/sinch/rcs/|services/rcs/sinch/|^lambda:wecare-rcs-(send|dlr)$)"
)


PROVIDERS: tuple = (
    Provider(
        key="wecare",
        name="WECARE.DIGITAL",
        purpose="First party: the public site, the API, short links, media and SIP hosts.",
        domains=("wecare.digital",),
        vault_prefixes=(
            "wecare/otp/",               # OTP pepper
            "wecare/prod/security/",     # gift-card code pepper
            "wecare/config/",            # non-credential configuration records
            "wecare/backup/",            # backup recovery passphrase
        ),
        webhook_routes=(
            "/pstn/session/events",           # browser softphone session events
            "/workspace/mcp/oauth/callback",  # workspace MCP OAuth return (PKCE, one-use state)
        ),
        env_namespaces=("APP", "STAFF", "CUSTOMER", "LINK", "SEO"),
        ui_labels=("WECARE.DIGITAL", "Grahak OS"),
    ),
    Provider(
        key="aws",
        name="Amazon Web Services",
        purpose=("Compute, data, delivery and messaging: Lambda, DynamoDB, S3, CloudFront, "
                 "End User Messaging SMS/voice, Polly, Transcribe, Translate, Bedrock, "
                 "Cognito, SES/SNS/SQS/EventBridge, Amplify hosting/builds, Secrets Manager."),
        domains=("amazonaws.com", "amazoncognito.com", "aws.amazon.com", "aws.com",
                 "community.aws", "awsstatic.com", "cloudfront.net", "amplifyapp.com"),
        vault_prefixes=("wecare/aws/",),
        npm=("aws-amplify", "@aws-amplify/*", "aws-cdk-lib", "@aws-cdk/*", "@aws-sdk/*",
             "constructs"),
        pip=("boto3", "botocore", "s3transfer", "jmespath", "awslambdaric",
             # the AWS SDK's own dependency closure, pinned beside it
             "python-dateutil", "six", "urllib3"),
        imports=("boto3", "botocore", "s3transfer", "jmespath", "dateutil", "six", "urllib3"),
        provider_ids=("aws", "aws-bedrock", "aws-end-user-messaging",
                      "aws-end-user-messaging-rcs"),
        env_namespaces=("AWS", "COGNITO"),
        ui_labels=("AWS", "Amazon Web Services", "AWS End User Messaging", "Amazon SES",
                   "Amazon S3", "Amazon Bedrock", "AWS Bedrock", "Amazon Polly",
                   "Amazon Transcribe", "Amazon Translate", "Amazon Cognito",
                   "Amazon CloudFront", "AWS Lambda", "Amazon DynamoDB", "AWS Amplify"),
    ),
    Provider(
        key="meta",
        name="Meta",
        purpose="WhatsApp Cloud API and calling, Graph API, Marketing and Conversions API.",
        domains=("facebook.com", "facebook.net", "fbcdn.net", "fb.com", "fb.me", "fbsbx.com",
                 "whatsapp.com", "whatsapp.net", "wa.me", "instagram.com", "cdninstagram.com",
                 "meta.com", "messenger.com"),
        vault_prefixes=(
            "wecare/meta-",              # system-user token, app secret
            "wecare/meta/",              # payments configuration
            "wecare/flow-private-key",   # WhatsApp Flows data-exchange key
            "wecare/partners/",          # per-tenant WABA tokens (tech partner)
            "wecare/agent-connector-token",  # token Meta's business agent presents to us
        ),
        provider_ids=("meta", "meta-direct", "meta-social", "meta-ads", "whatsapp"),
        webhook_routes=(
            "/whatsapp",                  # unified calling + messages webhook
            "/whatsapp/inbound",
            "/whatsapp/hangup",
            "/wa-business/webhooks",
            "/wa-business/flow-data",
            "/waba/events",
            "/waba/{wabaId}/events",
        ),
        env_namespaces=("META", "FB", "WA", "WABA", "WHATSAPP", "FLOW", "GRAPH"),
        ui_labels=("Meta", "Facebook", "Instagram", "Messenger", "WhatsApp",
                   "WhatsApp Business", "WhatsApp Business API", "WhatsApp Cloud API",
                   "WhatsApp Pay", "WhatsApp Flows", "WhatsApp Calling", "Meta Graph API",
                   "Graph API", "Embedded Signup", "Meta Embedded Signup",
                   "Meta Business Suite", "Conversions API", "Marketing API"),
    ),
    Provider(
        key="razorpay",
        name="Razorpay",
        purpose="Payments: orders, checkout, payment links, UPI collection and webhooks.",
        domains=("razorpay.com", "rzp.io"),
        vault_prefixes=("wecare/razorpay/", "wecare/razorpay-webhook"),
        provider_ids=("razorpay",),
        webhook_routes=("/razorpay-webhook", "/ecommerce/verify-callback"),
        env_namespaces=("RAZORPAY", "RZP", "UPI"),
        ui_labels=("Razorpay", "Razorpay Checkout", "Razorpay Payment Links"),
    ),
    Provider(
        key="plivo",
        name="Plivo",
        purpose="PSTN voice: IVR answer/hangup callbacks and the browser softphone.",
        domains=("plivo.com", "plivo.mintlify.app"),
        vault_prefixes=("wecare/plivo/", "wecare/plivo-answer"),
        webhook_routes=("/plivo/answer", "/plivo/hangup", "/plivo/events",
                        "/plivo/dial-events", "/plivo/fallback"),
        env_namespaces=("PLIVO", "PSTN"),
        ui_labels=("Plivo",),
    ),
    Provider(
        key="sinch",
        name="Sinch India",
        purpose="RCS for Indian destinations only. No SMS, voice or WhatsApp channel.",
        domains=("developers.sinch.com",),           # documentation, reachable from anywhere
        transport_domains=("aclwhatsapp.com", "sinch.com"),
        transport_scope=RCS_TRANSPORT_SCOPE,
        vault_prefixes=("wecare/sinch/rcs",),
        provider_ids=("sinch-rcs",),
        webhook_routes=("/webhook/sinch-rcs",),
        env_namespaces=("SINCH", "RCS"),
        ui_labels=("Sinch", "Sinch India", "Sinch RCS", "Sinch India Conversation API"),
    ),
    Provider(
        key="google",
        name="Google",
        purpose=("Maps, OAuth, Search Console, Ads, GA4/Tag Manager, Business Profile, "
                 "Play reporting, Translate/Weather/Air Quality/People APIs."),
        domains=("google.com", "googleapis.com", "gstatic.com", "googletagmanager.com",
                 "google-analytics.com", "googleusercontent.com", "googlehosted.com",
                 "goog", "youtube.com"),
        vault_prefixes=("wecare/google/", "wecare/google-", "wecare/seo/google-"),
        provider_ids=("google", "google-cloud", "google-ads"),
        env_namespaces=("GOOGLE", "GA4", "GTM", "GSC", "MAPS"),
        ui_labels=("Google", "Google Maps", "Google Analytics", "Google Ads",
                   "Google Search Console", "Google Business Profile", "Google Play",
                   "Google Cloud", "Google Tag Manager"),
    ),
    Provider(
        key="microsoft",
        name="Microsoft",
        purpose="Bing Webmaster Tools, and the container registry for the scraper image.",
        domains=("bing.com", "microsoft.com"),
        vault_prefixes=("wecare/bing/",),
        provider_ids=("bing", "microsoft"),
        env_namespaces=("BING", "MICROSOFT"),
        ui_labels=("Microsoft", "Bing", "Bing Webmaster Tools"),
    ),
    Provider(
        key="truecaller",
        name="Truecaller",
        purpose="Customer identity verification.",
        domains=("truecaller.com",),
        vault_prefixes=("wecare/truecaller",),
        provider_ids=("truecaller",),
        env_namespaces=("TRUECALLER",),
        ui_labels=("Truecaller",),
    ),
    Provider(
        key="openai",
        name="OpenAI",
        purpose="Model API for generative features.",
        domains=("openai.com",),
        vault_prefixes=("wecare/openai",),
        npm=("openai",),
        pip=("openai",),
        imports=("openai",),
        provider_ids=("openai",),
        env_namespaces=("OPENAI",),
        ui_labels=("OpenAI",),
    ),
    Provider(
        key="github",
        name="GitHub",
        purpose="Source hosting, Actions and the workspace code tools.",
        domains=("github.com", "githubusercontent.com"),
        vault_prefixes=("wecare/github-",),
        provider_ids=("github",),
        env_namespaces=("GITHUB",),
        ui_labels=("GitHub",),
    ),
)


REFERENCES: tuple = (
    Reference("standards", "Vocabulary namespaces in SVG, XML, JSON-LD and Open Graph.",
              domains=("w3.org", "schema.org", "ogp.me")),
    Reference("brand-profiles", "Organisation profile links (JSON-LD sameAs, footers).",
              domains=("linkedin.com", "twitter.com", "x.com")),
    Reference("public-assets", ("Keyless public content: country flag images for product "
                                "art, icon/CDN assets and open meteorological datasets."),
              domains=("flagcdn.com", "img.icons8.com", "api.open-meteo.com")),
    Reference("reference-rates", ("Keyless public daily currency reference rates. The browser "
                                  "sends only the selected currency pair, never the amount."),
              domains=("frankfurter.dev",)),
    Reference("developer-references", "Public API collections linked from operator screens.",
              domains=("postman.com",)),
    Reference("reserved", ("RFC 2606 / RFC 6761 documentation and local names. They never "
                           "resolve to a third party."),
              domains=("example.com", "example.org", "example.net", "example", "test",
                       "invalid", "localhost")),
)


LIBRARIES: tuple = (
    Library("react", "UI runtime.", npm=("react", "react-dom")),
    Library("next", "Web framework and static export.", npm=("next",)),
    Library("capacitor", "Native mobile shell for the web app.", npm=("@capacitor/*",)),
    Library("pillow", "Image rendering (Lambda layer).", pip=("pillow",), imports=("PIL",)),
    Library("cryptography", "Flows encryption and signatures (Lambda layer).",
            pip=("cryptography",), imports=("cryptography",)),
    Library("pypdf", "Blog source PDF extraction.", pip=("pypdf",), imports=("pypdf",)),
    Library("playwright", "Headless browser for the documentation scraper image.",
            pip=("playwright",), imports=("playwright",)),
    Library("beautifulsoup4", "HTML parsing in the documentation scraper.",
            pip=("beautifulsoup4", "lxml"), imports=("bs4", "lxml")),
)


# --------------------------------------------------------------------------------------
# Structural vocabulary: what the approved providers are used FOR.
# --------------------------------------------------------------------------------------
#: AWS SDK clients runtime code may create. SMS goes through End User Messaging
#: (`pinpoint-sms-voice-v2`) only, so the classic messaging client is not in this set.
AWS_SERVICES = frozenset({
    "amplify", "apigatewayv2", "bedrock-agent-runtime", "bedrock-runtime", "cloudfront", "cloudwatch",
    "cognito-idp", "dynamodb", "events", "health", "kms", "lambda", "logs",
    "pinpoint-sms-voice-v2", "polly", "s3", "scheduler", "secretsmanager", "ses", "sesv2",
    "sns", "sqs", "ssm", "sts", "support", "transcribe", "translate",
})

#: Plivo REST resources runtime code may call. Voice only: the messaging resource is not
#: one of them, which is what keeps Plivo off the SMS path.
PLIVO_VOICE_RESOURCES = frozenset({
    "Call", "Conference", "Endpoint", "Application", "Recording", "JWT",
})

#: The only channel the Sinch transport may address.
RCS_CHANNELS = frozenset({"RCS", "rcs"})

#: Lambda functions per channel. A function whose name carries a channel token must be
#: one of these, so a new transport for a channel is a provider decision made here.
CHANNEL_FUNCTIONS = {
    "voice": frozenset({
        "wecare-plivo-answer",       # Plivo PSTN answer/hangup/events, the CDR writer
        "wecare-pstn-softphone",     # Plivo browser softphone
        "wecare-voice-aws",          # AWS End User Messaging voice
        "wecare-voice-cdr-read",     # CDR reads
        "wecare-whatsapp-calling",   # Meta WhatsApp calling
        "wecare-whatsapp-voice",     # Meta WhatsApp voice notes
    }),
    "sms": frozenset({
        "wecare-sms-aws",            # AWS End User Messaging SMS transport
        "wecare-outbound-sms",       # SMS API, delegates to wecare-sms-aws
    }),
    "rcs": frozenset({
        "wecare-rcs-send",           # Sinch India RCS send
        "wecare-rcs-dlr",            # Sinch India RCS delivery reports
    }),
}

#: Name tokens that place a Lambda in a channel. Token matching rather than substring, so
#: `invoice` is not read as `voice`.
CHANNEL_TOKENS = {
    "voice": frozenset({"voice", "call", "calls", "calling", "cdr", "pstn", "plivo", "dial",
                        "dialer", "ivr", "softphone", "telephony"}),
    "sms": frozenset({"sms"}),
    "rcs": frozenset({"rcs"}),
}

#: Environment selectors that choose a backend, and the values each may hold.
SELECTOR_VALUES = {
    "CATALOG_SOURCE": frozenset({"aws"}),
    "BLOG_SOURCE": frozenset({"aws"}),
    "CHECKOUT_MODE": frozenset({"AWS_NATIVE"}),
}
#: Any selector ending in this suffix holds a provider id (or ``auto``).
PROVIDER_SELECTOR_SUFFIX = "_PROVIDER"
NEUTRAL_PROVIDER_IDS = frozenset({"auto"})

#: Suffixes that make an environment key an external account credential or endpoint.
#: Such a key must start with an approved namespace (see ``env_namespace_ok``).
CREDENTIAL_ENV_SUFFIXES = (
    "_API_KEY", "_API_SECRET", "_KEY_SECRET", "_CLIENT_ID", "_CLIENT_SECRET", "_SITE_ID",
    "_ACCOUNT_ID", "_AUTH_ID", "_AUTH_TOKEN", "_ACCESS_TOKEN", "_APP_ID", "_APP_SECRET",
    "_API_BASE", "_BASE_URL", "_API_URL", "_PROXY_URL", "_GRAPH_BASE",
)

#: A Razorpay-issued UPI VPA: `<merchant>.rzp@<bank handle>`. The handle belongs to the
#: PSP bank Razorpay settles through; it is not a provider of ours.
RAZORPAY_VPA = re.compile(r"^[a-z0-9][a-z0-9._-]*\.rzp@[a-z][a-z0-9]*$", re.I)

#: Product terms a screen may use in a provider position ("via SMS", "via RSS").
PRODUCT_TERMS = frozenset({
    "SMS", "RCS", "Email", "Push", "Voice", "Business Calling", "Common Inbox", "RSS",
    "OAuth", "UPI", "QR", "API",
})


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _domain_match(host: str, domain: str) -> bool:
    host = host.lower().rstrip(".")
    return host == domain or host.endswith("." + domain)


def host_owner(host: str, owner: str = "") -> tuple[str | None, str]:
    """Return (approving entry key or None, reason) for a host referenced by ``owner``.

    ``owner`` is the repo-relative path (or ``lambda:<name>``) that references the host,
    used to enforce a single-capability provider's transport scope.
    """
    host = host.lower().rstrip(".")
    if host.startswith("*."):
        host = host[2:]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified \
                or ip.is_reserved:
            return "local-network", ""
        return None, "a public IP address; reference a named, approved host instead"
    for provider in PROVIDERS:
        if any(_domain_match(host, d) for d in provider.domains):
            return provider.key, ""
    for provider in PROVIDERS:
        if any(_domain_match(host, d) for d in provider.transport_domains):
            if provider.transport_scope and not re.search(provider.transport_scope, owner):
                return None, (f"{provider.name} transport host outside its approved "
                              f"modules ({provider.purpose})")
            return provider.key, ""
    for ref in REFERENCES:
        if any(_domain_match(host, d) for d in ref.domains):
            return ref.key, ""
    return None, "not on the provider allow-list"


def vault_owner(secret_id: str, owner: str = "") -> tuple[str | None, str]:
    """Return (approving provider key or None, reason) for a Secrets Manager id."""
    for provider in PROVIDERS:
        if any(secret_id.startswith(p) for p in provider.vault_prefixes):
            if provider.transport_scope and owner and \
                    not re.search(provider.transport_scope, owner):
                return None, (f"{provider.name} credential outside its approved modules "
                              f"({provider.purpose})")
            return provider.key, ""
    return None, "secret id prefix not on the provider allow-list"


def _package_match(name: str, patterns) -> bool:
    for pattern in patterns:
        if pattern.endswith("/*"):
            if name.startswith(pattern[:-1]):
                return True
        elif name == pattern:
            return True
    return False


def npm_owner(name: str) -> str | None:
    for entry in (*PROVIDERS, *LIBRARIES):
        if _package_match(name, entry.npm):
            return entry.key
    return None


def pip_owner(name: str) -> str | None:
    norm = re.sub(r"[-_.]+", "-", name).lower()
    for entry in (*PROVIDERS, *LIBRARIES):
        if norm in {re.sub(r"[-_.]+", "-", p).lower() for p in entry.pip}:
            return entry.key
    return None


def import_owner(name: str) -> str | None:
    for entry in (*PROVIDERS, *LIBRARIES):
        if name in entry.imports:
            return entry.key
    return None


def provider_ids() -> frozenset:
    ids = set(NEUTRAL_PROVIDER_IDS)
    for provider in PROVIDERS:
        ids.update(provider.provider_ids)
    return frozenset(ids)


def webhook_routes() -> dict:
    """Approved webhook route -> provider key."""
    return {route: p.key for p in PROVIDERS for route in p.webhook_routes}


def ui_labels() -> frozenset:
    labels = set(PRODUCT_TERMS)
    for provider in PROVIDERS:
        labels.update(provider.ui_labels)
    return frozenset(labels)


def env_namespaces() -> frozenset:
    names = set()
    for provider in PROVIDERS:
        names.update(provider.env_namespaces)
    return frozenset(names)


def env_namespace_ok(key: str) -> bool:
    """A credential/endpoint-shaped env key must start with an approved namespace.

    ``NEXT_PUBLIC_`` is a build-time exposure prefix, not a namespace, so it is skipped.
    A key that is nothing but the suffix (``NEXT_PUBLIC_API_BASE``) names our own API.
    """
    bare = key[len("NEXT_PUBLIC_"):] if key.startswith("NEXT_PUBLIC_") else key
    for suffix in CREDENTIAL_ENV_SUFFIXES:
        if bare.endswith(suffix):
            head = bare[: -len(suffix)]
            if not head:
                return True
            return head.split("_", 1)[0] in env_namespaces()
    return True


def is_credential_env_key(key: str) -> bool:
    bare = key[len("NEXT_PUBLIC_"):] if key.startswith("NEXT_PUBLIC_") else key
    return bare.endswith(CREDENTIAL_ENV_SUFFIXES)


def channel_of(function_name: str) -> str | None:
    """The channel a Lambda name places it in, or None."""
    name = function_name
    if name.startswith("stack-"):
        name = name[len("stack-"):]
    if name.startswith("wecare-"):
        name = name[len("wecare-"):]
    tokens = set(re.split(r"[-/_]", name.lower()))
    for channel, words in CHANNEL_TOKENS.items():
        if tokens & words:
            return channel
    return None


def channel_function_ok(function_name: str) -> bool:
    channel = channel_of(function_name)
    if channel is None:
        return True
    name = function_name[len("stack-"):] if function_name.startswith("stack-") else function_name
    return name in CHANNEL_FUNCTIONS[channel]


# --- webhook routes ----------------------------------------------------------------------
_CALLBACK_VERBS = frozenset({"answer", "hangup", "fallback", "dial-events", "inbound", "dlr",
                             "delivery-report", "delivery-reports", "status-callback"})
_INBOUND_NAMESPACE = re.compile(r"^(sms|mms|voice|call|calls|rcs|email|whatsapp|wa)-in$")


def normalise_route(path: str) -> str:
    """API-relative path: no method, query, trailing slash, `/api` or stage prefix."""
    path = path.strip()
    if " " in path:
        path = path.split(None, 1)[1]
    path = path.split("?", 1)[0].split("#", 1)[0]
    for prefix in ("/api/", "/prod/", "/dev/", "/stage/"):
        if path.startswith(prefix):
            path = "/" + path[len(prefix):]
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def is_webhook_route(path: str) -> bool:
    """True when a path is in the inbound provider-callback namespace."""
    segments = [s for s in normalise_route(path).split("/") if s]
    for i, seg in enumerate(segments):
        low = seg.lower()
        if low in ("webhook", "webhooks") and i + 1 < len(segments):
            return True
        if low.endswith(("-webhook", "-webhooks")):
            return True
        if low == "dlr" or low.endswith("-dlr"):
            return True
        if low.endswith("callback") or low.endswith("-callbacks"):
            return True
        if _INBOUND_NAMESPACE.match(low) and i + 1 < len(segments):
            return True
        if i > 0 and low in _CALLBACK_VERBS:
            return True
    return False


def webhook_route_ok(path: str) -> bool:
    """An approved route, or a literal that is the tail of one (`/oauth/callback`).

    The tail must start at a segment boundary: the literal begins with `/`, so
    `/verify-callback` matches `/ecommerce/verify-callback` but `/callback` does not.
    """
    route = normalise_route(path)
    approved = webhook_routes()
    if route in approved:
        return True
    return route.startswith("/") and any(full.endswith(route) for full in approved)


__all__ = [
    "Provider", "Reference", "Library", "PROVIDERS", "REFERENCES", "LIBRARIES",
    "AWS_SERVICES", "PLIVO_VOICE_RESOURCES", "RCS_CHANNELS", "CHANNEL_FUNCTIONS",
    "CHANNEL_TOKENS", "SELECTOR_VALUES", "PROVIDER_SELECTOR_SUFFIX", "RAZORPAY_VPA",
    "PRODUCT_TERMS", "host_owner", "vault_owner", "npm_owner", "pip_owner", "import_owner",
    "provider_ids", "webhook_routes", "ui_labels", "env_namespaces", "env_namespace_ok",
    "is_credential_env_key", "channel_of", "channel_function_ok", "normalise_route",
    "is_webhook_route", "webhook_route_ok",
]
