"""Tests for scripts/verify_deployed_headers.py.

The bug these pin is not in the header logic - that was always right. It was the
TARGET: the script requested `app.wecare.digital`, a different CloudFront
distribution that Amplify's customHeaders never reach, so it reported RESULT: FAIL
against a host that was never meant to carry them. A gate that fails for a reason
unrelated to what it guards gets learned as noise, and then the real regression is
invisible. So the assertions here are mostly about *which host*.

No network access: the fetch is stubbed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = ROOT / "scripts" / "verify_deployed_headers.py"

_spec = importlib.util.spec_from_file_location("deployed_headers_under_test", _SCRIPT)
vdh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vdh)


# What a fully-correct live response looks like: every header customHttp.yml declares.
#
# DERIVED FROM THE REAL FILE, not hardcoded. The gate now requires declared == live, so
# a hardcoded subset here would stop describing a passing response the moment a header
# is added to customHttp.yml, and these tests would fail for a reason that has nothing
# to do with what they are pinning. This was three entries when the gate only checked
# three names.
GOOD_HEADERS = dict(vdh.declared_headers())

# The same, DERIVED THE SAME WAY, for the one non-sitewide pattern the file declares.
#
# WHY THIS HAD TO BE ADDED. `declared_headers()` is the sitewide `**/*` view, and
# `/_next/static/**/*` additionally carries `Cache-Control: public, max-age=31536000,
# immutable` - deliberately not on HTML. So a stub that served GOOD_HEADERS for a static
# asset reports a correctly-configured header as ABSENT, and the gate fails on correct
# configuration. That is exactly what happened to this file when the verifier became
# pattern-aware: the script grew `declared_headers_by_pattern()` and a second gate, and
# the fixtures here still described a one-pattern world.
STATIC_PATTERN = "/_next/static/**/*"
STATIC_GOOD_HEADERS = dict(vdh.declared_headers_by_pattern()[STATIC_PATTERN])

# A content-hashed asset path, shaped like the one `resolve_pattern_probe` discovers by
# reading the live page's markup. Fixed here so no test in this file needs the network.
PROBE_URL = "https://wecare.digital/_next/static/chunks/app-0000000000000000.js"


#: The real resolver, captured before the autouse fixture below replaces it, so the
#: function's own contract stays testable rather than hidden by its stub.
_REAL_RESOLVE_PROBE = vdh.resolve_pattern_probe


def live_headers(url: str) -> dict:
    """What a fully-correct origin serves for `url`: the declared set for its pattern.

    One helper rather than a per-test literal, because the point of deriving GOOD_HEADERS
    from the real file is lost the moment a second stub hardcodes a subset of it.
    """
    return dict(STATIC_GOOD_HEADERS) if "/_next/static/" in url else dict(GOOD_HEADERS)


@pytest.fixture(autouse=True)
def _probe_without_network(monkeypatch):
    """Keep `resolve_pattern_probe` offline, without skipping the block it resolves.

    That function reads the live page through its OWN `urllib.request.urlopen` rather
    than through `fetch_headers`, so stubbing the fetch - which is all these tests did -
    left every one of them making a real request to the apex, and the asset it found was
    then gated against whatever the fetch stub returned. Pinning a fixed path removes the
    network and still exercises the non-sitewide gate for real; returning None would make
    the block SKIP, which would pass the tests by checking less.
    """
    monkeypatch.setattr(
        vdh, "resolve_pattern_probe",
        lambda pattern, page_url: PROBE_URL if pattern == STATIC_PATTERN else None)


# ── the target ────────────────────────────────────────────────────────────────

def test_the_gate_targets_the_amplify_host_not_the_assets_distribution():
    """`amplify.yml` customHeaders are applied by Amplify Hosting. The Amplify app
    is served from the apex; `app.wecare.digital` is CloudFront ERCXSFDL0VM8X over
    S3 and can never carry them."""
    assert vdh.DEFAULT_URL == "https://wecare.digital/"
    assert "app.wecare.digital" not in vdh.DEFAULT_URL


def test_the_media_edge_is_still_reported_but_kept_out_of_the_gate():
    """Retargeted 2026-09-29, and the point of the test is unchanged.

    This used to assert `ASSETS_URL == "https://app.wecare.digital/"`. That host is
    gone - distribution ERCXSFDL0VM8X returns NoSuchDistribution, the name resolves
    to no address, and the bucket 404s - so the report it drove printed only
    `request failed`. That is the same learned-as-noise failure the module docstring
    is about, so pinning the dead name would have preserved the bug it warns of.

    Media now lives on the apex at /get/<key> via E2GP22R4BIFGQ3. The invariants that
    actually matter are asserted rather than just the literal: it targets a real
    object under the `o/` root, it is not the gated root, it is not the gate's own
    URL, and it does not name the retired host.
    """
    assert vdh.ASSETS_URL == (
        "https://wecare.digital/get/o/stream/media/m/wecare-digital.png"
    )
    assert vdh.ASSETS_URL != vdh.DEFAULT_URL
    assert "app.wecare.digital" not in vdh.ASSETS_URL
    # An object, not a bare prefix: a prefix has nothing to serve and would report a
    # 403/404 that says nothing about headers.
    assert "/get/o/" in vdh.ASSETS_URL and not vdh.ASSETS_URL.endswith("/")
    # Never probe the gated root - those keys are presigned-only by design.
    assert "/secure/" not in vdh.ASSETS_URL


def test_the_assets_report_cannot_change_the_verdict(monkeypatch, capsys):
    """Reported, never gated. Even if the media edge returns no headers at all, the
    Amplify origin still decides the exit code.

    That bare state was the media distribution's real posture when this test was
    written. It is not any more - all four headers measured present on 2026-09-29
    once media moved behind the apex. The stub keeps the bare case deliberately,
    because the invariant under test is "a headerless media response cannot fail the
    gate", and that must hold regardless of what the live edge happens to serve.
    """
    def fake(url):
        if url == vdh.ASSETS_URL:
            return 200, {"content-type": "text/html"}
        return 200, live_headers(url)

    monkeypatch.setattr(vdh, "fetch_headers", fake)
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py"])

    rc = vdh.main()
    out = capsys.readouterr().out

    assert rc == 0, "a bare assets distribution must not fail the gate"
    assert "reported, never gated" in out
    assert "RESULT: PASS" in out


def test_a_broken_assets_request_does_not_fail_the_gate(monkeypatch):
    def fake(url):
        if url == vdh.ASSETS_URL:
            raise OSError("boom")
        return 200, live_headers(url)

    monkeypatch.setattr(vdh, "fetch_headers", fake)
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py"])

    assert vdh.main() == 0


# ── the verdict still depends on the Amplify origin ───────────────────────────

def test_a_missing_permissions_policy_on_the_amplify_origin_fails(monkeypatch):
    monkeypatch.setattr(vdh, "fetch_headers",
                        lambda url: (200, {"x-content-type-options": "nosniff",
                                           "referrer-policy": "strict-origin-when-cross-origin"}))
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    assert vdh.main() == 1


def test_the_microphone_regression_this_script_was_written_for_still_fails(monkeypatch):
    """2026-09-19: config said microphone=(self), the deployed header said
    microphone=(). That is the exact case the script exists to catch."""
    bad = dict(GOOD_HEADERS)
    bad["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
    monkeypatch.setattr(vdh, "fetch_headers", lambda url: (200, bad))
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    assert vdh.main() == 1


def test_a_transport_failure_is_2_and_never_0(monkeypatch):
    """Exit 2, distinct from a header failure, and never a pass - an unreachable
    origin proves nothing about its headers."""
    def boom(url):
        raise OSError("dns")

    monkeypatch.setattr(vdh, "fetch_headers", boom)
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    assert vdh.main() == 2


# ── the parser, which was never the bug but is worth holding still ────────────

@pytest.mark.parametrize("value,expected", [
    ("camera=(), microphone=(self)", {"camera": "()", "microphone": "(self)"}),
    ("camera=()", {"camera": "()"}),
    ("", {}),
])
def test_permissions_policy_parsing(value, expected):
    assert vdh.parse_permissions_policy(value) == expected


def test_customhttp_yml_is_the_configured_source_and_still_parses():
    """Hand-parsed rather than handed to PyYAML, so the script keeps working in a
    bare CI shell with no third-party dependency.

    The source moved on 2026-09-29: this used to read `amplify.yml`, whose
    `customHeaders:` block turned out to be inert - Amplify was serving the app-level
    config instead, so a CSP declared in amplify.yml never shipped on any build.
    """
    declared = vdh.declared_headers()
    assert declared["permissions-policy"] == "camera=(), microphone=(self), geolocation=()"
    # The enforced CSP, which is the header that was declared-and-never-served.
    assert declared["content-security-policy"] == (
        "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
    )
    # HSTS was live WITHOUT being declared anywhere in the repo. It is declared now,
    # and it must stay declared, because customHttp.yml overrides the app-level config
    # wholesale - dropping the line would remove a live header.
    assert declared["strict-transport-security"] == "max-age=31536000"


def test_a_matched_quote_pair_is_stripped_but_an_inner_quote_survives():
    """Regression on the parser, which had exactly this bug when first written.

    The enforced CSP is double-quoted in YAML and ends in a single quote:

        value: "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"

    A blanket `.strip("\\"'")` removes the double quotes and then keeps going, eating
    the final `'` and silently producing a different policy than the file declares.
    """
    assert vdh.declared_headers()["content-security-policy"].endswith("'self'")


def test_no_declared_header_value_contains_a_newline():
    """The defect that kept the report-only CSP off the site for its entire life.

    `>-` is a FOLDED scalar, but YAML does not fold a line indented deeper than the
    first line of the value - it keeps a literal newline. An HTTP header value cannot
    contain one, so Amplify drops the whole header: no build error, no warning, six
    headers served and the seventh simply absent.

    Asserted against PyYAML rather than the script's own parser, because that parser
    joins continuation lines with spaces and would therefore hide exactly this bug.
    """
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load((ROOT / "customHttp.yml").read_text())
    for block in spec["customHeaders"]:
        for header in block["headers"]:
            assert "\n" not in header["value"], (
                f"{header['key']} spans multiple lines as YAML parses it. "
                "Indent every line of the folded scalar identically."
            )


def test_the_parser_agrees_with_pyyaml_exactly():
    """The hand-rolled parser exists so the gate needs no third-party dependency. It
    is only worth having if it reads the file the same way YAML does.

    COMPARED PER PATTERN, not flattened. This used to hold `declared_headers()` against a
    reference flattened across every block, which was right while the file had one block
    and became wrong the moment `/_next/static/**/*` appeared: `declared_headers()` is
    documented as the sitewide `**/*` view, so the flattened reference carried a
    Cache-Control the sitewide view is not supposed to contain. Both views are pinned
    here, which is strictly more than the flat comparison checked - it also catches a
    header landing in the wrong block.
    """
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load((ROOT / "customHttp.yml").read_text())
    reference: dict = {}
    for block in spec["customHeaders"]:
        pattern = reference.setdefault(block["pattern"], {})
        for header in block["headers"]:
            pattern[header["key"].lower()] = header["value"]

    assert vdh.declared_headers_by_pattern() == reference
    assert vdh.declared_headers() == reference[vdh.SITEWIDE_PATTERN]
    # The split is the whole reason the gate stopped reporting correct configuration as a
    # failure: Cache-Control is declared for the static prefix and for nothing else.
    assert "cache-control" in reference[STATIC_PATTERN]
    assert "cache-control" not in reference[vdh.SITEWIDE_PATTERN]


def test_a_more_indented_folded_line_is_reported_as_a_defect(tmp_path, monkeypatch):
    """The detector that makes this fail locally instead of after a deploy."""
    (tmp_path / "customHttp.yml").write_text(
        'customHeaders:\n'
        '  - pattern: "**/*"\n'
        '    headers:\n'
        '      - key: Content-Security-Policy-Report-Only\n'
        '        value: >-\n'
        "          default-src 'self';\n"
        "            img-src 'self' https://example.com;\n"   # deeper -> literal newline
    )
    monkeypatch.setattr(vdh, "ROOT", tmp_path)
    vdh.declared_headers()
    assert vdh.FOLD_DEFECTS, "a more-indented folded line must be reported"
    assert vdh.FOLD_DEFECTS[0][0] == "Content-Security-Policy-Report-Only"


def test_uniformly_indented_folded_lines_are_not_a_defect(tmp_path, monkeypatch):
    (tmp_path / "customHttp.yml").write_text(
        'customHeaders:\n'
        '  - pattern: "**/*"\n'
        '    headers:\n'
        '      - key: Content-Security-Policy-Report-Only\n'
        '        value: >-\n'
        "          default-src 'self';\n"
        "          img-src 'self' https://example.com;\n"
    )
    monkeypatch.setattr(vdh, "ROOT", tmp_path)
    parsed = vdh.declared_headers()
    assert not vdh.FOLD_DEFECTS
    assert parsed["content-security-policy-report-only"] == (
        "default-src 'self'; img-src 'self' https://example.com;"
    )


def test_a_header_declared_but_absent_from_the_response_fails(monkeypatch):
    """THE BUG THIS CHANGE FIXES, pinned.

    A CSP sat declared-but-never-served for weeks and every check passed, because the
    gate only compared an allowlist of three header names that happened to be live for
    an unrelated reason. Declared-vs-live is the check that catches it.
    """
    without_csp = {k: v for k, v in GOOD_HEADERS.items()
                   if k != "content-security-policy-report-only"}
    monkeypatch.setattr(vdh, "fetch_headers", lambda url: (200, without_csp))
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    assert vdh.main() == 1, "a declared header missing from the response must fail"


def test_a_declared_header_served_with_a_different_value_fails(monkeypatch):
    """Present is not enough. An enforced CSP that lost a directive in transit is a
    weaker policy than the file claims, and must not pass."""
    weakened = dict(GOOD_HEADERS)
    weakened["content-security-policy"] = "object-src 'none'"
    monkeypatch.setattr(vdh, "fetch_headers", lambda url: (200, weakened))
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    assert vdh.main() == 1


def test_a_static_asset_missing_its_cache_control_fails(monkeypatch):
    """The non-sitewide gate really gates.

    Cache-Control is declared for `/_next/static/**/*` and for nothing else, so it cannot
    be seen on the apex HTML response the sitewide gate reads. If the asset stops carrying
    it, every byte under that prefix is re-fetched on every navigation and nothing else in
    this file would notice.
    """
    def fake(url):
        headers = live_headers(url)
        headers.pop("cache-control", None)
        return 200, headers

    monkeypatch.setattr(vdh, "fetch_headers", fake)
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    assert vdh.main() == 1


def test_the_probe_refuses_to_guess_a_url_for_an_unhandled_pattern():
    """Asserted against the REAL resolver, which the autouse fixture replaces elsewhere.

    It returns before making any request for a pattern it does not handle, so this needs
    no network. Returning None is the honest answer: the caller prints the block as
    UNVERIFIED instead of assuming it passed.
    """
    assert _REAL_RESOLVE_PROBE("**/*.json", vdh.DEFAULT_URL) is None


def test_an_unresolvable_pattern_is_reported_unverified(monkeypatch, capsys):
    """And the report says so out loud, rather than the block vanishing from the output."""
    monkeypatch.setattr(vdh, "resolve_pattern_probe", lambda pattern, page_url: None)
    monkeypatch.setattr(vdh, "fetch_headers", lambda url: (200, live_headers(url)))
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    rc = vdh.main()
    out = capsys.readouterr().out

    assert "UNVERIFIED" in out
    assert f"SKIP  {STATIC_PATTERN}" in out
    # A skipped block is not a failure - it is unproven. Stated here so the distinction is
    # deliberate rather than incidental.
    assert rc == 0


def test_whitespace_folding_differences_are_not_failures(monkeypatch):
    """A folded YAML scalar and the header a CDN re-emits can differ in run-length
    without differing in meaning. That must not be a red gate."""
    key = "content-security-policy-report-only"

    def respaced(url):
        headers = live_headers(url)
        if key in headers:
            headers[key] = headers[key].replace("; ", ";   ")
        return 200, headers

    monkeypatch.setattr(vdh, "fetch_headers", respaced)
    monkeypatch.setattr("sys.argv", ["verify_deployed_headers.py", "--no-assets"])

    assert vdh.main() == 0
