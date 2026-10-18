#!/usr/bin/env python3
"""Live test of the four public machine-readable surfaces. Read-only throughout.

    /sitemap.xml     what crawlers are invited to
    /llms.txt        curated map of the public pages
    /llms-full.txt   the same plus every article title and summary
    /mcp             read-only MCP server, Streamable HTTP

WHY /mcp NEEDS ITS OWN TREATMENT. It is not a page and a browser cannot test it. A GET
answers

    {"jsonrpc":"2.0","error":{"code":-32600,
     "message":"This endpoint does not offer an SSE stream. POST a JSON-RPC message instead."}}

which is CORRECT rather than broken: Streamable HTTP allows a server to decline the optional
GET/SSE channel, and this one does, so every exchange is a POST. `-32600` is JSON-RPC's
"Invalid Request". Asserted here as expected behaviour so the error stops looking like an
outage - and so a future change that turns the GET into a 500 or an HTML error page fails.

Nothing here writes. The MCP server exposes a frozen read-only tool allowlist, and this
calls only tools that return descriptions of the public site.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SITE = "https://wecare.digital"
UA = "wecare-live-surface-test/1"

results: list[tuple[bool, str, str]] = []


def record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))


def fetch(path: str, *, method: str = "GET", body: bytes | None = None,
          headers: dict[str, str] | None = None, timeout: int = 45):
    url = path if path.startswith("http") else SITE + path
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except Exception as e:  # noqa: BLE001
        return 0, {}, f"{type(e).__name__}".encode()


# ── sitemap.xml ────────────────────────────────────────────────────────────────

def test_sitemap() -> None:
    print("\n=== /sitemap.xml ===")
    st, h, raw = fetch("/sitemap.xml")
    record(st == 200, "responds 200", f"http {st}, {len(raw):,} bytes")
    ctype = (h.get("Content-Type") or "").split(";")[0]
    record(ctype in ("application/xml", "text/xml"), "served as XML", ctype or "none")
    if st != 200:
        return
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        record(False, "parses as well-formed XML", str(e))
        return
    record(True, "parses as well-formed XML")
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    urls = root.findall(f"{ns}url")
    record(len(urls) > 1000, "carries the full corpus", f"{len(urls)} <url> entries")
    locs = [u.findtext(f"{ns}loc") or "" for u in urls]
    record(all(l.startswith(f"{SITE}/") for l in locs),
           "every <loc> is an absolute apex URL",
           f"{sum(1 for l in locs if not l.startswith(SITE))} bad")
    record(len(set(locs)) == len(locs), "no duplicate <loc>",
           f"{len(locs) - len(set(locs))} duplicates")
    mods = [u.findtext(f"{ns}lastmod") or "" for u in urls]
    days = {m[:10] for m in mods if m}
    record(len(days) > 1, "lastmod is not one fabricated date",
           f"{len(days)} distinct day(s) across {sum(1 for m in mods if m)} dated URLs")
    record(not any("/workspace/" in l for l in locs),
           "no authenticated /workspace/ URL leaked")
    # Spot-check that advertised URLs actually resolve.
    sample = [locs[0], locs[len(locs) // 2], locs[-1]]
    bad = []
    for loc in sample:
        s, _, _ = fetch(loc)
        if s != 200:
            bad.append(f"{loc} -> {s}")
    record(not bad, "sampled advertised URLs return 200",
           "; ".join(bad) or f"{len(sample)} sampled")


# ── llms.txt / llms-full.txt ──────────────────────────────────────────────────

def test_llms(path: str, *, min_bytes: int, expect_articles: bool) -> None:
    print(f"\n=== {path} ===")
    st, h, raw = fetch(path)
    record(st == 200, "responds 200", f"http {st}, {len(raw):,} bytes")
    if st != 200:
        return
    ctype = (h.get("Content-Type") or "").split(";")[0]
    record(ctype == "text/plain", "served as text/plain", ctype or "none")
    text = raw.decode("utf-8", errors="replace")
    record(len(raw) >= min_bytes, "is not truncated or empty",
           f"{len(raw):,} bytes (floor {min_bytes:,})")
    record(text.lstrip().startswith("# "),
           "opens with an H1, per the llms.txt convention",
           text.strip().splitlines()[0][:60] if text.strip() else "empty")
    record("> " in text, "carries the blockquote summary")
    # It must advertise real, resolvable URLs and not the retired page.
    import re
    # EXTRACTING LINKS FROM PROSE NEEDS TWO EXCLUSIONS, and both were learned by this check
    # reporting a healthy surface as broken.
    #
    # 1. Quotes and commas must end a match. Stopping only at whitespace and brackets captured
    #    `https://wecare.digital/mcp"` with the quote attached, which 404s.
    # 2. A URL TEMPLATE IS NOT A LINK. llms.txt documents the article pattern as
    #    `https://wecare.digital/post/<slug>/`, and cutting the match at `<` yields
    #    `https://wecare.digital/post/` - a path that correctly 404s because there is no
    #    /post/ index; posts live only at /post/<slug>/ and the index is /blog/. So the
    #    placeholder is matched deliberately and then discarded, rather than truncated into a
    #    URL nobody advertised.
    raw_links = re.findall(r"https://wecare\.digital/[^\s)\]\"',]*", text)
    links = [l.rstrip(".,;:") for l in raw_links if "<" not in l and ">" not in l]
    templates = [l for l in raw_links if "<" in l or ">" in l]
    if templates:
        print(f"         ({len(templates)} URL template(s) skipped, e.g. {templates[0][:52]})")
    record(bool(links), "advertises apex URLs", f"{len(links)} link(s)")
    if expect_articles:
        record(text.count("\n- ") > 500 or text.count("\n## ") > 100,
               "includes the article corpus",
               f"{text.count(chr(10) + '- ')} list items, {text.count(chr(10) + '## ')} sections")
    # Sample advertised links for reachability.
    #
    # /mcp IS EXCLUDED FROM THE 200 EXPECTATION, and the exclusion is the correct answer rather
    # than a loosened assertion. llms.txt legitimately advertises the MCP endpoint, and a GET on
    # it answers 405 by design - it offers no SSE stream, so every exchange is a POST. Demanding
    # 200 there marked a healthy endpoint as broken on the first run of this file. It is checked
    # properly in test_mcp() below; here it only has to be REACHABLE, which a 405 proves (a DNS
    # or routing failure would give 0, and a dead route would give 404).
    uniq = sorted(set(links))
    post_only = {f"{SITE}/mcp", f"{SITE}/mcp/"}
    sample = [uniq[0], uniq[len(uniq) // 2], uniq[-1]] if len(uniq) >= 3 else uniq
    bad = []
    for link in sample:
        s, _, _ = fetch(link)
        expected_ok = s == 405 if link.rstrip("/") in {u.rstrip("/") for u in post_only} else s == 200
        if not expected_ok:
            bad.append(f"{link} -> {s}")
    record(not bad, "sampled advertised links resolve (200, or 405 for the POST-only /mcp)",
           "; ".join(bad) or f"{len(sample)} sampled")
    # And nothing advertised may be a dead address.
    dead_links = []
    for link in uniq:
        s, _, _ = fetch(link)
        if s in (404, 410) or s == 0:
            dead_links.append(f"{link} -> {s}")
    record(not dead_links, "no advertised link is dead",
           "; ".join(dead_links[:4]) or f"all {len(uniq)} checked")


# ── /mcp ───────────────────────────────────────────────────────────────────────

MCP_HEADERS = {
    "Content-Type": "application/json",
    # Streamable HTTP: a client must accept both, even when the server declines SSE.
    "Accept": "application/json, text/event-stream",
}


def rpc(method: str, params: dict | None = None, rpc_id: int | None = 1):
    payload: dict = {"jsonrpc": "2.0", "method": method}
    if rpc_id is not None:
        payload["id"] = rpc_id
    if params is not None:
        payload["params"] = params
    st, h, raw = fetch("/mcp", method="POST",
                       body=json.dumps(payload).encode(), headers=MCP_HEADERS)
    text = raw.decode("utf-8", errors="replace")
    # A Streamable HTTP server may answer JSON or an SSE frame. Handle both.
    if text.lstrip().startswith("event:") or text.lstrip().startswith("data:"):
        for line in text.splitlines():
            if line.startswith("data:"):
                text = line[5:].strip()
                break
    try:
        return st, h, json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        return st, h, {"_raw": text[:300]}


def test_mcp() -> None:
    print("\n=== /mcp ===")

    # 1. The GET that produced the reported error. Expected, not broken.
    st, _, raw = fetch("/mcp")
    text = raw.decode("utf-8", errors="replace")
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        body = {}
    code = (body.get("error") or {}).get("code")
    record(code == -32600 and st in (400, 405, 200),
           "GET is declined with JSON-RPC -32600, not an HTML error",
           f"http {st}, code {code}, "
           f"{(body.get('error') or {}).get('message', text[:80])!r}")

    # 2. initialize
    st, h, body = rpc("initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "wecare-live-surface-test", "version": "1"},
    })
    ok = st == 200 and "result" in body
    record(ok, "initialize succeeds", f"http {st}"
           + ("" if ok else f" {json.dumps(body)[:200]}"))
    if ok:
        res = body["result"]
        info = res.get("serverInfo") or {}
        record(bool(res.get("protocolVersion")), "declares a protocol version",
               str(res.get("protocolVersion")))
        record(bool(info.get("name")), "identifies itself",
               f"{info.get('name')} {info.get('version', '')}")
        record(bool(res.get("instructions")),
               "returns instructions so the endpoint is self-describing",
               f"{len(res.get('instructions') or '')} chars")

    # 3. tools/list
    st, _, body = rpc("tools/list", {}, rpc_id=2)
    tools = ((body.get("result") or {}).get("tools")) or []
    record(st == 200 and bool(tools), "tools/list returns the catalogue",
           f"http {st}, {len(tools)} tool(s)")
    names = [t.get("name") for t in tools if isinstance(t, dict)]
    if names:
        print(f"         tools: {', '.join(str(n) for n in names)}")
        record(all(t.get("inputSchema") for t in tools if isinstance(t, dict)),
               "every tool declares an inputSchema")
        # Nothing here should look like a mutation on an unauthenticated endpoint.
        mutating = [n for n in names if isinstance(n, str)
                    and any(v in n.lower() for v in
                            ("create", "update", "delete", "send", "pay", "write", "set_"))]
        record(not mutating, "no tool name implies a write on this public endpoint",
               ", ".join(mutating))

    # 4. call a read-only tool
    target = next((n for n in names if isinstance(n, str)
                   and "summary" in n.lower()), names[0] if names else None)
    if target:
        st, _, body = rpc("tools/call", {"name": target, "arguments": {}}, rpc_id=3)
        content = ((body.get("result") or {}).get("content")) or []
        text_out = " ".join(c.get("text", "") for c in content
                            if isinstance(c, dict))
        record(st == 200 and bool(content), f"tools/call {target} returns content",
               f"http {st}, {len(text_out):,} chars"
               + ("" if content else f" {json.dumps(body)[:200]}"))

    # 5. an unknown method must be refused cleanly, not 500
    st, _, body = rpc("this/method/does/not/exist", {}, rpc_id=4)
    err = body.get("error") or {}
    record(bool(err) and st < 500, "an unknown method is refused cleanly",
           f"http {st}, code {err.get('code')}")


def main() -> int:
    print(f"live AI-surface test against {SITE}")
    test_sitemap()
    test_llms("/llms.txt", min_bytes=4000, expect_articles=False)
    test_llms("/llms-full.txt", min_bytes=200_000, expect_articles=True)
    test_mcp()
    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} assertions passed")
    if failed:
        print("FAILED:")
        for _, name, detail in failed:
            print(f"  - {name}{f' ({detail})' if detail else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
