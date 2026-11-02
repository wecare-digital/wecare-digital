#!/usr/bin/env python3
"""Verify the wecare.digital/get file-sharing path end to end.

Checks the whole chain, not just that the resources exist:

    browser -> wecare.digital (Amplify Hosting, app d22dm4b0jn71jw)
            -> customRules 200-rewrite  /get/<*>
            -> CloudFront E2GP22R4BIFGQ3 (no alias, default *.cloudfront.net cert)
            -> OAC -> private S3 bucket wecare-digital-get
            -> Lambda@Edge origin-response turns any 4xx into 302 -> wecare.digital

Three separate things have to stay true for a bad link to redirect rather than
error, and each one has broken at least once while this was being built:

1. The ``/get/<*>`` rule must sit ABOVE the SPA catch-all ``/<*>`` in customRules,
   or Amplify never reaches it.
2. The edge function must be attached at **origin-response**. A CloudFront
   Function on viewer-response silently never runs, because CloudFront skips
   viewer-response edge functions when the origin returns 400 or higher.
3. The edge function must mutate the origin response in place. Returning a fresh
   dict deletes the read-only ``Via`` header and CloudFront answers 502 with
   completely clean Lambda logs.

Usage
-----
    python scripts/verify_file_sharing.py
    python scripts/verify_file_sharing.py --json

Exit codes: 0 all checks passed, 1 at least one failed.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    import boto3
except ImportError:  # pragma: no cover
    sys.exit("boto3 is required: pip install boto3  (or use .venv/bin/python)")

REGION = "us-east-1"
APP_ID = "d22dm4b0jn71jw"
DIST_ID = "E2GP22R4BIFGQ3"
BUCKET = "wecare-digital-get"
EDGE_FN = "wecare-get-miss-redirect"
SITE = "https://wecare.digital"
# The open tier. Short on purpose so shared links stay tidy: /get/o/<file>.
PROBE_KEY = "o/healthcheck.txt"
# The gated tier. Must never be served over the public path, even when the object
# exists - it is delivered only as a presigned URL by wecare-secure-files.
GATED_PROBE_KEY = "secure/gated-probe.txt"
# A gated object that EXISTS (the zero-byte `secure/` prefix marker), requested with one
# percent-encoded character. S3 decodes the path once, so this proves the edge decodes too.
ENCODED_GATED_PROBE_KEY = "secure/"
ENCODED_GATED_PROBE_PATH = "secur%65/"
# Catalog deploy tree: an existing object that must not be served over /get. Catalog
# artwork is public only through the catalog-media API.
CATALOG_DEPLOY_PROBE_KEY = "secure/d/public/catalog-deploy/catalog/catalog-v3-final-manifest.json"
CATALOG_MEDIA_PROBE_URL = "https://wecare.digital/api/catalog-media/grahak-os-4096.png"
# The source the associated edge version must contain, byte for byte.
EDGE_SOURCE = Path(__file__).resolve().parents[1] / "amplify/functions/edge/get-miss-redirect/handler.py"


def _edge_source_matches(version_arn: str) -> tuple[bool, str]:
    """Compare the associated version's handler.py with the repo copy.

    Origin-response functions do not run on cache hits, so a cached 302 can make the live
    probes pass against any version. The deployed code cannot. The presigned code URL is a
    credential-bearing link and is never printed.
    """
    try:
        code = boto3.client("lambda", region_name=REGION).get_function(
            FunctionName=version_arn)["Code"]["Location"]
        with urllib.request.urlopen(code, timeout=30) as resp:
            deployed = zipfile.ZipFile(io.BytesIO(resp.read())).read("handler.py")
    except Exception as exc:  # noqa: BLE001 - reported as a failed check
        return False, f"could not read deployed code: {type(exc).__name__}"
    if deployed == EDGE_SOURCE.read_bytes():
        return True, "deployed handler.py is identical to the repo source"
    return False, "deployed handler.py differs from the repo source"


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append({"check": name, "ok": ok, "detail": detail})

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"]]


def _fetch(url: str, follow: bool = False) -> tuple[int, dict]:
    """Return (status, headers). Never follows redirects unless asked."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
            return None

    handlers = [] if follow else [NoRedirect]
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, method="GET")
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers)
    except (urllib.error.URLError, OSError) as exc:
        # Status 0 fails only the check that made this request; later checks still run
        # and report individually instead of being lost to one outer exception.
        return 0, {"X-Fetch-Error": type(exc).__name__}


def check_amplify_rules(r: Result) -> None:
    app = boto3.client("amplify", region_name=REGION).get_app(appId=APP_ID)["app"]
    rules = app.get("customRules", [])
    sources = [x.get("source") for x in rules]

    if "/get/<*>" not in sources:
        r.add("amplify rewrite present", False, "no /get/<*> rule in customRules")
        return

    get_idx = sources.index("/get/<*>")
    catchall_idx = sources.index("/<*>") if "/<*>" in sources else len(sources)
    r.add(
        "amplify rewrite present",
        True,
        f"/get/<*> at index {get_idx}",
    )
    r.add(
        "rewrite ordered above SPA catch-all",
        get_idx < catchall_idx,
        f"/get/<*> index {get_idx} vs /<*> index {catchall_idx}",
    )
    rule = rules[get_idx]
    r.add(
        "rewrite is a 200 proxy (not a redirect)",
        rule.get("status") == "200",
        f"status={rule.get('status')} target={rule.get('target')}",
    )
    for bare in ("/get", "/get/"):
        r.add(
            f"bare {bare} handled",
            bare in sources,
            "present" if bare in sources else "missing - would fall to the SPA",
        )


def check_distribution(r: Result) -> None:
    cf = boto3.client("cloudfront", region_name=REGION)
    dist = cf.get_distribution(Id=DIST_ID)["Distribution"]
    cfg = dist["DistributionConfig"]

    r.add("distribution deployed", dist["Status"] == "Deployed", dist["Status"])
    r.add(
        "no alternate domain name",
        cfg["Aliases"]["Quantity"] == 0,
        f"{cfg['Aliases']['Quantity']} alias(es) - a subdomain was not wanted",
    )
    r.add(
        "uses default CloudFront certificate",
        bool(cfg["ViewerCertificate"].get("CloudFrontDefaultCertificate")),
        "no ACM certificate consumed",
    )

    assoc = cfg["DefaultCacheBehavior"]["LambdaFunctionAssociations"].get("Items", [])
    origin_resp = [a for a in assoc if a["EventType"] == "origin-response"]
    r.add(
        "edge function on origin-response",
        len(origin_resp) == 1,
        origin_resp[0]["LambdaFunctionARN"] if origin_resp else "not attached",
    )
    r.add(
        "no CloudFront Function on viewer-response",
        cfg["DefaultCacheBehavior"]["FunctionAssociations"]["Quantity"] == 0,
        "a viewer-response function cannot fire on a 4xx origin response",
    )

    # The prefix deny lives in the edge function's source, so assert the deployed
    # version is recent enough to contain it rather than trusting the file on disk.
    if origin_resp:
        version = origin_resp[0]["LambdaFunctionARN"].rsplit(":", 1)[-1]
        r.add(
            "edge function is a published version, not $LATEST",
            version.isdigit(),
            f"version {version}",
        )
        r.add("edge function source matches the repo",
              *_edge_source_matches(origin_resp[0]["LambdaFunctionARN"]))
    r.add(
        "custom error responses cleared",
        cfg["CustomErrorResponses"]["Quantity"] == 0,
        "the edge redirect replaces any error page",
    )

    origin = cfg["Origins"]["Items"][0]
    r.add(
        "origin locked to the bucket via OAC",
        bool(origin.get("OriginAccessControlId")) and BUCKET in origin["DomainName"],
        f"{origin['DomainName']} oac={origin.get('OriginAccessControlId')}",
    )


def check_bucket(r: Result) -> None:
    s3 = boto3.client("s3", region_name=REGION)
    pab = s3.get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    r.add(
        "all public access blocked",
        all(pab.values()),
        json.dumps(pab),
    )
    r.add(
        "bucket policy is not public",
        not s3.get_bucket_policy_status(Bucket=BUCKET)["PolicyStatus"]["IsPublic"],
        "CloudFront service principal only",
    )
    enc = s3.get_bucket_encryption(Bucket=BUCKET)["ServerSideEncryptionConfiguration"]
    r.add(
        "default encryption on",
        True,
        enc["Rules"][0]["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"],
    )
    ver = s3.get_bucket_versioning(Bucket=BUCKET).get("Status")
    r.add("versioning enabled", ver == "Enabled", str(ver))


def check_live_behaviour(r: Result) -> None:
    # a real object must serve
    status, headers = _fetch(f"{SITE}/get/{PROBE_KEY}")
    r.add(
        "existing file serves through /get",
        status == 200,
        f"HTTP {status} content-type={headers.get('Content-Type')}",
    )

    # a miss must 302 to the main domain, not error and not serve the SPA
    miss = f"{SITE}/get/does-not-exist-{random.randint(10_000, 99_999)}.pdf"
    status, headers = _fetch(miss)
    loc = headers.get("Location", "")
    r.add(
        "missing file returns 302",
        status == 302,
        f"HTTP {status}" + ("" if status == 302 else " (502 => read-only header violation)"),
    )
    r.add(
        "302 points at the main domain",
        loc.rstrip("/") == SITE,
        f"Location={loc or 'absent'}",
    )

    # nested miss, to prove <*> captures multiple segments
    nested = f"{SITE}/get/a/b/c/nope-{random.randint(10_000, 99_999)}.zip"
    status, headers = _fetch(nested)
    r.add(
        "nested missing path also redirects",
        status == 302 and headers.get("Location", "").rstrip("/") == SITE,
        f"HTTP {status} Location={headers.get('Location', 'absent')}",
    )

    # the bucket must not be reachable without CloudFront
    status, _ = _fetch(f"https://{BUCKET}.s3.{REGION}.amazonaws.com/{PROBE_KEY}")
    r.add(
        "bucket unreachable directly",
        status == 403,
        f"HTTP {status} from the S3 endpoint",
    )

    # The gated tier. This object EXISTS, so a 302 here proves the edge function
    # checks the prefix before the status rather than only rewriting errors - which
    # is the distinction that would otherwise have served it.
    status, headers = _fetch(f"{SITE}/get/{GATED_PROBE_KEY}")
    r.add(
        "existing gated object is refused over the public path",
        status == 302 and headers.get("Location", "").rstrip("/") == SITE,
        f"HTTP {status} Location={headers.get('Location', 'absent')}",
    )

    # and refused at the distribution too, not just through the Amplify hop
    dist = boto3.client("cloudfront", region_name=REGION).get_distribution(Id=DIST_ID)
    status, headers = _fetch(
        f"https://{dist['Distribution']['DomainName']}/{GATED_PROBE_KEY}"
    )
    r.add(
        "gated object refused at the distribution directly",
        status == 302,
        f"HTTP {status}",
    )
    # A percent-encoded spelling of an EXISTING gated object, through both hops. Only
    # meaningful while the probe object exists, so its existence is checked first.
    s3 = boto3.client("s3", region_name=REGION)
    for name, key in (("encoded gated probe", ENCODED_GATED_PROBE_KEY),
                      ("catalog-deploy probe", CATALOG_DEPLOY_PROBE_KEY)):
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
            r.add(f"{name} object exists", True, key)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            r.add(f"{name} object exists", False, f"{key}: {type(exc).__name__}")
    for host in (f"{SITE}/get", f"https://{dist['Distribution']['DomainName']}"):
        status, _ = _fetch(f"{host}/{ENCODED_GATED_PROBE_PATH}")
        r.add(f"percent-encoded gated path refused: {host}",
              status == 302, f"HTTP {status}")
        status, _ = _fetch(f"{host}/{CATALOG_DEPLOY_PROBE_KEY}")
        r.add(f"catalog-deploy tree refused: {host}", status == 302, f"HTTP {status}")
    # ...while approved catalog artwork still serves through its own API route.
    status, headers = _fetch(CATALOG_MEDIA_PROBE_URL)
    r.add(
        "catalog artwork serves through /api/catalog-media/",
        status == 200 and headers.get("Content-Type", "").startswith("image/png"),
        f"HTTP {status} content-type={headers.get('Content-Type')}",
    )

    # the gated API must reject an unauthenticated caller
    for path, expect in (
        ("/secure-files", 401),
        ("/secure-files/mine", 401),
        ("/secure-files/nonexistent/download?grant=x", 401),
    ):
        status, _ = _fetch(f"https://wecare.digital/api{path}")
        r.add(f"gated API rejects anonymous: {path}", status == expect, f"HTTP {status}")

    # the rest of the site must be untouched
    for path in ("/", "/workspace/engage/inbox/", "/workspace/communications/"):
        status, _ = _fetch(f"{SITE}{path}")
        r.add(f"site unaffected: {path}", status == 200, f"HTTP {status}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    r = Result()
    for fn in (check_amplify_rules, check_distribution, check_bucket, check_live_behaviour):
        try:
            fn(r)
        except Exception as exc:  # noqa: BLE001 - report, do not abort the rest
            r.add(fn.__name__, False, f"{type(exc).__name__}: {exc}")

    if args.json:
        print(json.dumps({"checks": r.checks, "failed": len(r.failed)}, indent=2))
    else:
        for c in r.checks:
            print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['check']}: {c['detail']}")
        print()
        print(f"{len(r.checks) - len(r.failed)}/{len(r.checks)} passed")

    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
