"""A rendered invoice must not be fetchable by URL.

An invoice PNG/PDF carries the customer's name, address, the amount and the GST breakdown.
It used to be written under `media_paths.public('stack/invoices/')` — the `o/` root, which
CloudFront serves with **no authentication** — and the API handed back
`https://{CDN_DOMAIN}/{s3_key}`, a permanent link. The exposure was bounded rather than
absent (the key embeds a 70-bit reference and bucket listing is off, so it was
unlisted-but-public: safe from enumeration, unsafe the moment a URL leaks) which is why it
was a P1 rather than a P0.

It moved to the gated root while `o/stack/invoices/` held **0 objects** and `InvoicesTable`
held **0 rows** — measured at the time. That timing is the point: once an invoice URL has
been delivered it cannot be retracted, which is the same argument `media_paths` records for
the 61 approved WhatsApp template URLs.

Four writers/readers had to move together, and a disagreement between any two would be worse
than the original state, because it would be inconsistent rather than uniformly wrong:

    invoice-engine            writes PNG + PDF, hands back the link
    inbound-whatsapp-handler  ALSO writes an invoice PNG on the payment path
    system-cleanup            sweeps the prefix; pointed at the wrong root it reports 0
                              objects, and 0 reads as "nothing to clean" rather than an error
    dashboard (frontend)      mirrors the cleanup prefix list

These are source-level assertions because the live behaviour needs AWS and CI has no
credentials. The live half was verified separately at the time of the change: a presigned GET
returns the object bytes, and the same key over CloudFront returns the SPA shell rather than
the object.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FUNCTIONS = ROOT / "amplify" / "functions"

INVOICE_ENGINE = FUNCTIONS / "payments" / "invoice-engine" / "handler.py"
INBOUND = FUNCTIONS / "messaging" / "inbound-whatsapp-handler" / "handler.py"
CLEANUP = FUNCTIONS / "operations" / "system-cleanup" / "handler.py"
# The frontend dashboard mirror (src/pages/workspace/dashboard/index.tsx) that used to echo the
# cleanup prefix list was removed in the 2026-10 workspace redesign (the Dashboard section is
# gone and nothing in src names `s3_invoices` any more). Its guard test is retired below; the
# backend gating guards (PREFIX_SITES) are the load-bearing ones and are unchanged.

#: Every site that names the invoice prefix, and the file it lives in.
PREFIX_SITES = [INVOICE_ENGINE, INBOUND, CLEANUP]


@pytest.mark.parametrize("path", PREFIX_SITES, ids=lambda p: p.parent.name)
def test_no_backend_site_writes_invoices_to_the_public_root(path):
    """`media_paths.public('stack/invoices/...')` anywhere means a publicly fetchable invoice."""
    source = path.read_text(encoding="utf-8")
    offenders = [
        match.group(0)
        for match in re.finditer(r"media_paths\.public\(\s*f?['\"]stack/invoices/[^)]*\)", source)
    ]
    assert not offenders, (
        f"{path.parent.name} composes an invoice key under the PUBLIC root: {offenders}. "
        f"CloudFront serves `o/` without authentication, and an invoice carries the customer's "
        f"name, address, amount and GST breakdown."
    )


@pytest.mark.parametrize("path", PREFIX_SITES, ids=lambda p: p.parent.name)
def test_every_backend_site_uses_the_gated_root(path):
    """Present as well as absent: a site that stopped naming the prefix at all would pass the
    test above while quietly writing somewhere else."""
    source = path.read_text(encoding="utf-8")
    assert re.search(r"media_paths\.secure\(\s*f?['\"]stack/invoices/", source), (
        f"{path.parent.name} no longer composes an invoice key with media_paths.secure(...). "
        f"All writers and the cleanup sweeper must agree on the root."
    )


def test_the_api_never_returns_a_permanent_cdn_url_for_an_invoice():
    """The link handed to a caller must be signed and expiring.

    Checked on the AST so the comments explaining the old `https://{CDN_DOMAIN}/{s3_key}` form
    do not trip it — the same trap that caught two earlier source-level tests in this repo.
    """
    tree = ast.parse(INVOICE_ENGINE.read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):   # an f-string
            continue
        literal = "".join(part.value for part in node.values
                          if isinstance(part, ast.Constant) and isinstance(part.value, str))
        if "https://" not in literal:
            continue
        names = {p.value.id for p in node.values
                 if isinstance(p, ast.FormattedValue) and isinstance(p.value, ast.Name)}
        if "CDN_DOMAIN" in names and any(n.endswith("key") or n == "s3_key" for n in names):
            offenders.append(node.lineno)

    assert not offenders, (
        f"invoice-engine builds a permanent CDN URL from an S3 key at line(s) {offenders}. "
        f"Use _signed_invoice_url() - a presigned link expires, and the key is under the "
        f"gated root so a CDN URL is a dead link as well as a bad idea."
    )


def test_the_signing_helper_exists_and_never_falls_back_to_a_public_url():
    """A fallback to a CDN URL on signing failure would reintroduce the exposure precisely
    when something is already going wrong."""
    source = INVOICE_ENGINE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    helper = next((node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "_signed_invoice_url"),
                  None)
    assert helper is not None, "invoice-engine must define _signed_invoice_url"

    body = ast.get_source_segment(source, helper) or ""
    assert "receipt_links.signed_url" in body, "it must go through the shared signing primitive"
    assert "CDN_DOMAIN" not in body, (
        "the signing helper must not reference CDN_DOMAIN; returning a public URL when signing "
        "fails is worse than returning nothing")

    # Every `return` in the helper is either a signed URL or the empty string.
    returned_constants = {node.value.value for node in ast.walk(helper)
                          if isinstance(node, ast.Return)
                          and isinstance(node.value, ast.Constant)}
    assert returned_constants <= {""}, (
        f"the helper returns unexpected constants {returned_constants}; the failure value must "
        f"be '' so the caller degrades rather than leaking a link")


def test_no_asset_record_persists_a_url():
    """A presigned URL expires, so a stored one is correct when written and silently broken
    afterwards — and `send_invoice_whatsapp` reads that row on its second call, so it would
    have handed out an expired link. The key is permanent; the URL is minted per response."""
    source = INVOICE_ENGINE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Only dicts that are actually WRITTEN. An earlier version of this test matched any dict
    # carrying assetType + s3Key + url, which also caught `_normalize_asset` - a response
    # builder, where a `url` key is correct and is minted per call. The distinction is the
    # point of the test, so it is encoded rather than worked around: persisting is the problem,
    # returning is not.
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "put_item"):
            continue
        for keyword in node.keywords:
            if keyword.arg != "Item" or not isinstance(keyword.value, ast.Dict):
                continue
            keys = {k.value for k in keyword.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if {"assetType", "s3Key"} <= keys and "url" in keys:
                offenders.append(node.lineno)

    assert not offenders, (
        f"an invoice asset record still persists a `url` at line(s) {offenders}; a presigned "
        f"URL expires, and send_invoice_whatsapp reads that row on its second call")


def test_the_asset_response_mints_its_url_instead_of_reading_one():
    """The other half of the same change. Since the row no longer stores a `url`, a response
    builder that reads one answers `''` for every asset - an API that silently says "no link"
    rather than erroring."""
    source = INVOICE_ENGINE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    normalize = next((node for node in tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "_normalize_asset"),
                     None)
    assert normalize is not None, "invoice-engine must define _normalize_asset"
    body = ast.get_source_segment(source, normalize) or ""
    assert "_signed_invoice_url" in body, (
        "_normalize_asset must mint a signed URL from s3Key rather than read a stored one")


def test_whatsapp_delivery_is_guarded_on_the_key_it_actually_sends():
    """The guard used to test `image_url` and then send `mediaFile: s3_key` — one variable
    checked, a different one used. A row with a URL but no key passed and sent a message with
    no media; a row with a key but no URL was refused despite being deliverable."""
    source = INVOICE_ENGINE.read_text(encoding="utf-8")

    # Locate the guard by the response it produces, not by taking the first `if not s3_key:` in
    # the file - the signing helper opens with the same test, and an earlier version of this
    # test matched that one and reported a false failure.
    message = "No invoice image available"
    assert message in source, "the delivery guard's error response has gone"
    message_index = source.index(message)

    # The guard must be the `if not s3_key:` immediately preceding that response.
    preceding = source[:message_index]
    last_guard = preceding.rfind("if not ")
    assert last_guard != -1, "no guard found before the delivery error response"
    guard_line = preceding[last_guard:].split("\n", 1)[0]
    assert "s3_key" in guard_line, (
        f"the '{message}' guard tests {guard_line.strip()!r}, but delivery sends "
        f"`mediaFile: s3_key`. Checking one variable and using another is how a row with a "
        f"URL but no key sent a message with no media.")
    assert "image_url" not in guard_line


def test_delivery_does_not_need_a_public_url_at_all():
    """The reason the move is safe: Meta never fetches an invoice by URL. outbound-whatsapp
    receives the S3 key, reads the bytes and uploads them."""
    source = INVOICE_ENGINE.read_text(encoding="utf-8")
    assert "'mediaFile': s3_key" in source, (
        "delivery must pass the S3 key, not a URL; if this becomes a link, a gated prefix "
        "breaks WhatsApp invoice delivery")


def test_a_gated_key_answers_200_with_a_fallback_rather_than_403():
    """Records the measurement that nearly produced a false report, because it will mislead
    the next person the same way.

    Checking whether `secure/` is gated by STATUS CODE gives the wrong answer. The request
    never reaches the S3 origin, so it falls through to the Amplify origin and returns
    **HTTP 200 with the Next.js SPA shell** (measured: `text/html`, 64906 bytes) rather than
    403. Compare the returned BYTES against the object.

    This test asserts the documentation of that fact exists, not the behaviour itself, which
    needs AWS credentials CI does not have.
    """
    doc = (ROOT / "docs" / "execution" / "change-authority-matrix.md").read_text(encoding="utf-8")
    assert "SPA" in doc and "64906" in doc, (
        "the matrix must record that a gated key returns 200 with the SPA shell, not 403 - "
        "otherwise the next status-code check concludes the opposite of the truth")
