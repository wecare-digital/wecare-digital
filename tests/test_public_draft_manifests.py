"""Published draft inventories retain metadata, never bearer preview links."""

import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).parents[1]
SENSITIVE_QUERY_KEYS = {
    "token", "access_token", "id_token", "signature", "sig",
    "x-amz-signature", "x-amz-security-token",
}


def credential_locations(value, location):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from credential_locations(child, f"{location}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from credential_locations(child, f"{location}/{index}")
    elif isinstance(value, str) and value.startswith(("https://", "http://")):
        for key, secret in parse_qsl(urlsplit(value).query, keep_blank_values=True):
            if key.lower() in SENSITIVE_QUERY_KEYS and secret:
                # Report only location and parameter name, never the credential or URL.
                yield f"{location}: {key}"


def test_public_draft_manifests_do_not_publish_token_bearing_urls():
    violations = []
    for path in sorted((ROOT / "docs/whatsapp/service-flow-drafts").glob("*.json")):
        violations.extend(credential_locations(json.loads(path.read_text()), path.relative_to(ROOT)))
    assert violations == [], "Token-bearing URLs in public draft metadata: " + "; ".join(violations)
