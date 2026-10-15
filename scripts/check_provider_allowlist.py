#!/usr/bin/env python3
"""Provider allow-list gate: runtime code references only approved providers.

Why it is positive
------------------
The earlier gates named the providers that had been retired and searched for them. A gate
built that way protects against the names it already knows and nothing else, and it keeps
every retired provider alive as a first-class word in CI. This gate inverts it: everything
external that runtime code references must be declared in scripts/provider_allowlist.py,
and anything that is not declared fails, whatever it is called.

What it checks
--------------
    hosts            every external host (URLs, CSP sources, bare host literals, email
                     domains, container registries) is an approved domain; a
                     single-capability provider's API hosts stay in its own modules
    secrets          every Secrets Manager id starts with an approved prefix
    packages         every third-party import and runtime dependency is approved
    webhook-routes   every inbound webhook/callback route is an approved one
    provider-ids     every `provider` value and backend selector is approved vocabulary
    env-namespaces   credential/endpoint-shaped env keys carry an approved namespace
    sms-transport    SMS goes through AWS End User Messaging only: AWS clients are from
                     the approved set, SNS publishes address a topic or endpoint, and
                     Plivo REST calls are voice resources only
    rcs-transport    the Sinch transport addresses the RCS channel only
    channel-lambdas  voice, SMS and RCS Lambdas are exactly the supported functions
    upi-vpa          UPI collection addresses are Razorpay-issued

Scope
-----
    scanned   amplify/**  src/**  config/**  public/**  customHttp.yml  amplify.yml
              next.config.js, and the `dependencies` of package.json (the runtime
              dependency manifest of src/)
    skipped   tests (tests/, __tests__/, src/test/, *.test.*, *.spec.*, test_*.py),
              documentation (*.md, licence text), lockfiles, binaries
    stripped  comments and docstrings: prose that mentions a host is not a dependency

Usage
-----
    python scripts/check_provider_allowlist.py              # gate
    python scripts/check_provider_allowlist.py --verbose    # every finding
    python scripts/check_provider_allowlist.py --json
    python scripts/check_provider_allowlist.py --allowlist  # print the allow-list
    python scripts/check_provider_allowlist.py FILE ...     # scan only these files

Exit codes: 0 compliant, 1 findings, 2 bad invocation.
"""
from __future__ import annotations

import argparse
import ast
import bisect
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import provider_allowlist as allow  # noqa: E402

SCOPE = ("amplify", "src", "config", "public", "customHttp.yml", "amplify.yml",
         "next.config.js")
ROOT_MANIFEST = "package.json"
BACKEND_PREFIXES = ("amplify/", "config/")
SKIP_DIRS = {"node_modules", ".next", "out", "__pycache__", ".venv", ".amplify", "cdk.out"}
TEST_PATH = re.compile(
    r"(^|/)(test|tests|__tests__|__mocks__)/|\.(test|spec)\.[cm]?[jt]sx?$"
    r"|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml",
             "poetry.lock", "Pipfile.lock"}
CODE_PY = (".py",)
CODE_JS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
TEXT_EXT = CODE_PY + CODE_JS + (".json", ".yml", ".yaml", ".html", ".htm", ".css", ".xml",
                                ".svg", ".txt", ".webmanifest")
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "crypto", "dns", "events", "fs", "http", "https",
    "module", "net", "os", "path", "perf_hooks", "process", "querystring", "readline",
    "stream", "string_decoder", "timers", "tls", "url", "util", "vm", "worker_threads",
    "zlib",
}
#: Top-level domains a bare (scheme-less) host literal may end in. Kept to real public
#: suffixes so that `handler.py`, `index.ts` or `README.md` are never read as hosts.
BARE_HOST_TLDS = {
    "com", "net", "org", "in", "io", "digital", "dev", "app", "ai", "co", "goog", "aws",
    "cloud", "info", "biz", "xyz", "us", "uk", "eu", "me", "tv",
}


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    value: str
    why: str


RULES = {
    "hosts": "external hosts are on the provider allow-list",
    "secrets": "Secrets Manager ids use an approved prefix",
    "packages": "third-party imports and dependencies are approved",
    "webhook-routes": "inbound webhook routes are approved routes",
    "provider-ids": "provider values and backend selectors are approved",
    "env-namespaces": "credential/endpoint env keys carry an approved namespace",
    "sms-transport": "SMS only via AWS End User Messaging; Plivo voice only",
    "rcs-transport": "Sinch transport addresses the RCS channel only",
    "channel-lambdas": "voice, SMS and RCS Lambdas are the supported set",
    "upi-vpa": "UPI collection addresses are Razorpay-issued",
}


# --------------------------------------------------------------------------------------
# File discovery
# --------------------------------------------------------------------------------------
def _skippable(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts):
        return True
    name = parts[-1]
    if TEST_PATH.search(rel) or name in LOCKFILES:
        return True
    if name.endswith(".md") or name.upper().startswith(("LICENSE", "LICENCE", "NOTICE")):
        return True
    if name.endswith(".txt") and not rel.startswith("public/") \
            and not name.startswith("requirements"):
        return True          # licence and font text bundled with a function
    if name == "Dockerfile" or name.startswith("requirements"):
        return False
    return not name.endswith(TEXT_EXT) and "." in name


def discover() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
             *SCOPE], cwd=ROOT, capture_output=True, check=True).stdout
        files = sorted({f for f in out.decode("utf-8", "replace").split("\0") if f})
    except (OSError, subprocess.CalledProcessError):
        files = []
        for base in SCOPE:
            path = ROOT / base
            if path.is_file():
                files.append(base)
                continue
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                for filename in filenames:
                    files.append(Path(dirpath, filename).relative_to(ROOT).as_posix())
        files.sort()
    return [f for f in files if (ROOT / f).is_file() and not _skippable(f)]


# --------------------------------------------------------------------------------------
# Comment stripping. Spans are BLANKED, never removed, so line numbers stay true.
# --------------------------------------------------------------------------------------
def _blank(chars: list, start: int, end: int) -> None:
    for i in range(start, min(end, len(chars))):
        if chars[i] != "\n":
            chars[i] = " "


def strip_python(text: str) -> str:
    """Blank comments and statement-level strings (docstrings) using the tokenizer."""
    line_starts = [0]
    for m in re.finditer("\n", text):
        line_starts.append(m.end())

    def offset(pos):
        row, col = pos
        return line_starts[row - 1] + col if row - 1 < len(line_starts) else len(text)

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text
    chars = list(text)
    skip = {tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT}
    for i, tok in enumerate(tokens):
        if tok.type == tokenize.COMMENT:
            _blank(chars, offset(tok.start), offset(tok.end))
        elif tok.type == tokenize.STRING:
            j = i - 1
            while j >= 0 and tokens[j].type in (tokenize.NL, tokenize.COMMENT):
                j -= 1
            starts = j < 0 or tokens[j].type in (tokenize.NEWLINE, tokenize.INDENT,
                                                  tokenize.DEDENT, tokenize.ENCODING)
            k = i + 1
            while k < len(tokens) and tokens[k].type in skip:
                k += 1
            ends = k >= len(tokens) or tokens[k].type in (tokenize.NEWLINE,
                                                          tokenize.ENDMARKER)
            if starts and ends:
                _blank(chars, offset(tok.start), offset(tok.end))
    return "".join(chars)


def strip_js(text: str) -> str:
    """Blank // and /* */ comments in JS/TS/JSX, respecting strings and templates.

    A `//` straight after `:` is a URL scheme separator, not a comment, so a URL written
    as JSX text survives. Quote strings end at a newline, which bounds the damage an
    apostrophe in JSX text can do to the line it is on.
    """
    chars = list(text)
    n = len(text)
    i = 0
    mode = "code"
    depth = 0
    stack: list = []
    while i < n:
        c = text[i]
        if mode == "code":
            nxt = text[i + 1] if i + 1 < n else ""
            if c == "/" and nxt == "/" and not (i > 0 and text[i - 1] == ":"):
                j = text.find("\n", i)
                j = n if j == -1 else j
                _blank(chars, i, j)
                i = j
                continue
            if c == "/" and nxt == "*":
                j = text.find("*/", i + 2)
                j = n if j == -1 else j + 2
                _blank(chars, i, j)
                i = j
                continue
            if c in "'\"":
                j = i + 1
                while j < n and text[j] not in (c, "\n"):
                    j += 2 if text[j] == "\\" else 1
                i = j + 1
                continue
            if c == "`":
                stack.append(("code", depth))
                mode = "tmpl"
                i += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0 and stack and stack[-1][0] == "expr":
                    _, depth = stack.pop()
                    mode = "tmpl"
                    i += 1
                    continue
                depth -= 1
            i += 1
        else:  # template literal body
            if c == "\\":
                i += 2
                continue
            if c == "`":
                _, depth = stack.pop() if stack else ("code", 0)
                mode = "code"
                i += 1
                continue
            if c == "$" and i + 1 < n and text[i + 1] == "{":
                stack.append(("expr", depth))
                depth = 0
                mode = "code"
                i += 2
                continue
            i += 1
    return "".join(chars)


def strip_hash_comments(text: str) -> str:
    """YAML, requirements and Dockerfile comments: `#` at line start or after a space."""
    out = []
    for line in text.split("\n"):
        quote = None
        for idx, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#" and (idx == 0 or line[idx - 1] in " \t"):
                line = line[:idx] + " " * (len(line) - idx)
                break
        out.append(line)
    return "\n".join(out)


def strip_markup(text: str) -> str:
    chars = list(text)
    for m in re.finditer(r"<!--.*?-->", text, re.S):
        _blank(chars, m.start(), m.end())
    return strip_js("".join(chars))


def strip_css(text: str) -> str:
    chars = list(text)
    for m in re.finditer(r"/\*.*?\*/", text, re.S):
        _blank(chars, m.start(), m.end())
    return "".join(chars)


PLACEHOLDER = re.compile(r"""\bplaceholder\s*[=:]\s*\{?\s*(['"`])((?:(?!\1).)*)\1""")


def strip_placeholders(code: str) -> str:
    """Blank input placeholder text. A placeholder is a hint shown to a person and is
    never fetched, so `placeholder="https://your-server.com/webhook"` is not a host."""
    chars = list(code)
    for m in PLACEHOLDER.finditer(code):
        _blank(chars, m.start(2), m.end(2))
    return "".join(chars)


def code_view(rel: str, text: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if rel.endswith(CODE_PY):
        return strip_python(text)
    if rel.endswith(CODE_JS):
        return strip_placeholders(strip_js(text))
    if rel.endswith((".yml", ".yaml")) or name == "Dockerfile" or name.startswith("requirements"):
        return strip_hash_comments(text)
    if rel.endswith((".html", ".htm", ".svg", ".xml")):
        return strip_markup(text)
    if rel.endswith(".css"):
        return strip_css(text)
    return text


# --------------------------------------------------------------------------------------
# Extractors
# --------------------------------------------------------------------------------------
#: A URL authority. Labels may be template placeholders (`{REGION}`, `${region}`) and dots
#: may be regex-escaped (`graph\\.facebook\\.com`); both are normalised before matching.
_LABEL = r"(?:[A-Za-z0-9-]+|\$?\{[^{}\s]{1,40}\})"
URL = re.compile(r"\b(?:https?|wss?)://(\*\.)?(" + _LABEL + r"(?:\\?\." + _LABEL + r")*)")
PROTOCOL_RELATIVE = re.compile(r"""['"`]//([a-z0-9-]+(?:\.[a-z0-9-]+)+)""")
BARE_HOST = re.compile(
    r"""(['"`])(\*\.)?([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)"""
    r"""(?::\d{2,5})?(?:/[^'"`\s]*)?\1""")
YAML_HOST = re.compile(r"(?<![\w./@-])(\*\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})(?![\w-])")
DOCKER_FROM = re.compile(r"^\s*FROM\s+([a-z0-9-]+(?:\.[a-z0-9-]+)+)/", re.M | re.I)
SECRET_LITERAL = re.compile(r"""['"`](wecare/[A-Za-z0-9._/{}+-]*)""")
SECRET_REFERENCE = re.compile(r"(?:resolve:secretsmanager:|:secret:)(wecare/[A-Za-z0-9._/+-]*)")
JS_IMPORTS = (
    re.compile(r"""\bimport\s+(?:type\s+)?[^'";]{0,2000}?\bfrom\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""\bimport\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""\bexport\s+[^'";]{0,2000}?\bfrom\s*['"]([^'"\n]+)['"]"""),
    re.compile(r"""\brequire\(\s*['"]([^'"\n]+)['"]\s*\)"""),
    re.compile(r"""\bimport\(\s*['"]([^'"\n]+)['"]\s*\)"""),
)
FIRST_PARTY_API = re.compile(
    r"https?://(?:(?:www\.)?wecare\.digital/api|api\.wecare\.digital"
    r"|[a-z0-9]{10}\.execute-api\.[a-z0-9-]+\.amazonaws\.com(?:/(?:prod|dev|\$default))?)"
    r"(/[A-Za-z0-9/_{}.+-]*)")
PATH_LITERAL = re.compile(
    r"""['"`]((?:(?:GET|POST|PUT|PATCH|DELETE|ANY|OPTIONS|HEAD)\s+)?/[A-Za-z0-9/_{}.+-]+)['"`]""")
PROVIDER_VALUE = re.compile(
    r"""(?<![\w.])['"]?([A-Za-z_]*provider)['"]?\s*(?:===|!==|==|!=|=|:)\s*['"]([^'"\n]{1,80})['"]""",
    re.I)
ENV_DEFAULT = re.compile(
    r"""\b(?:environ\.get|getenv|environ\.setdefault)\(\s*['"]([A-Z][A-Z0-9_]+)['"]\s*,\s*['"]([^'"\n]*)['"]""")
ENV_READ = re.compile(
    r"""(?:\benviron(?:\.get)?\s*[\[(]\s*|\bgetenv\(\s*|\b_?env[a-z_]*\(\s*)['"]([A-Z][A-Z0-9_]{2,})['"]"""
    r"""|\bprocess\.env\.([A-Z][A-Z0-9_]{2,})|\bprocess\.env\[\s*['"]([A-Z][A-Z0-9_]{2,})['"]\s*\]""")
AWS_CLIENT = re.compile(
    r"""\.(?:client|resource)\(\s*(?:service_name\s*=\s*)?['"]([a-z0-9-]+)['"]""")
AWS_SDK_JS = re.compile(r"""['"]@aws-sdk/client-([a-z0-9-]+)['"]""")
PLIVO_RESOURCE = re.compile(r"/v1/Account/[^/'\"\s]+/([A-Za-z]+)")
SNS_PHONE_JS = re.compile(r"PublishCommand\(\s*\{[^}]*\bPhoneNumber\s*:", re.S)
CHANNEL_VALUE = re.compile(
    r"""(?:['"]channel['"]\s*:|\bchannel\s*=)\s*['"]([A-Za-z_]+)['"]""")
CHANNEL_PRIORITY = re.compile(r"""channel_priority_order['"]?\s*[:=]\s*\[([^\]]*)\]""")
LAMBDA_NAME = re.compile(r"(?<![A-Za-z0-9_-])(?:stack-)?wecare-[a-z0-9]+(?:-[a-z0-9]+)*")
VPA_LITERAL = re.compile(r"""['"`]([A-Za-z0-9._-]+@[A-Za-z][A-Za-z0-9]*)['"`]""")
UPI_PA = re.compile(r"upi://pay\?[^'\"`\s]*?\bpa=([^&'\"`\s]+)")


def normalise_host(raw: str) -> str:
    """Lower-case, unescape `\\.`, and resolve template labels.

    A placeholder label becomes `x`, so `cognito-idp.{REGION}.amazonaws.com` is judged by
    its literal registrable suffix. A host that is wholly a placeholder, or whose last
    label is one, cannot be judged from source and is skipped (empty result).
    """
    host = re.sub(r"\$?\{[^{}]*\}", "\0", raw.replace("\\.", ".")).lower().rstrip(".")
    labels = host.split(".")
    if not labels or "\0" in labels[-1]:
        return ""
    return ".".join("x" if "\0" in label else label for label in labels)


def is_reverse_dns_identifier(host: str, owner: str) -> bool:
    """`digital.wecare.app` is our app bundle id - an approved domain written backwards."""
    reverse = ".".join(reversed(host.split(".")))
    return allow.host_owner(reverse, owner)[0] is not None


class Scan:
    def __init__(self):
        self.findings: list[Finding] = []
        self.files = 0
        self._local_py: set[str] | None = None

    def add(self, rule, rel, text, pos, value, why):
        line = text.count("\n", 0, pos) + 1 if pos is not None else 0
        self.findings.append(Finding(rule, rel, line, value[:120], why))

    # -- helpers -------------------------------------------------------------------
    def local_python_modules(self) -> set:
        if self._local_py is None:
            names = set()
            for base in (ROOT / "amplify" / "functions", ROOT / "scripts"):
                if not base.is_dir():
                    continue
                for dirpath, dirnames, filenames in os.walk(base):
                    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                    names.update(dirnames)
                    names.update(f[:-3] for f in filenames if f.endswith(".py"))
            self._local_py = names
        return self._local_py

    # -- rules -----------------------------------------------------------------------
    def hosts(self, rel, code):
        seen = set()

        def check(host, pos, how):
            host = normalise_host(host)
            if not host or (host, how) in seen:
                return
            seen.add((host, how))
            key, why = allow.host_owner(host, rel)
            if key is None and how == "bare" and is_reverse_dns_identifier(host, rel):
                return
            if key is None:
                self.add("hosts", rel, code, pos, host, why)

        for m in URL.finditer(code):
            check(m.group(2), m.start(), "url")
        for m in PROTOCOL_RELATIVE.finditer(code):
            check(m.group(1), m.start(), "url")
        for m in BARE_HOST.finditer(code):
            host = m.group(3)
            if host.rsplit(".", 1)[-1] in BARE_HOST_TLDS:
                check(host, m.start(), "bare")
        name = rel.rsplit("/", 1)[-1]
        if rel.endswith((".yml", ".yaml")):
            for m in YAML_HOST.finditer(code):
                host = m.group(2)
                if host.rsplit(".", 1)[-1] in BARE_HOST_TLDS:
                    check(host, m.start(), "yaml")
        if name == "Dockerfile":
            for m in DOCKER_FROM.finditer(code):
                check(m.group(1), m.start(), "image")

    def secrets(self, rel, code, owner=None):
        for rx in (SECRET_LITERAL, SECRET_REFERENCE):
            for m in rx.finditer(code):
                secret = m.group(1)
                if secret.rstrip("/.") in ("wecare", ""):
                    continue
                key, why = allow.secret_owner(secret, owner or rel)
                if key is None:
                    self.add("secrets", rel, code, m.start(), secret, why)

    def python_imports(self, rel, text):
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            self.add("packages", rel, text, None, f"unparseable: {exc.msg}",
                     "the file does not parse, so its imports cannot be checked")
            return
        local = self.local_python_modules()
        stdlib = set(getattr(sys, "stdlib_module_names", ()))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in stdlib or name in local or allow.import_owner(name):
                    continue
                self.findings.append(Finding(
                    "packages", rel, node.lineno, name,
                    "Python import of a package not on the allow-list"))

    def python_sns_phone(self, rel, text):
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "publish":
                kwargs = {k.arg for k in node.keywords if k.arg}
                if "PhoneNumber" in kwargs and not kwargs & {"TopicArn", "TargetArn"}:
                    self.findings.append(Finding(
                        "sms-transport", rel, node.lineno, "publish(PhoneNumber=...)",
                        "SNS publish must address a topic or endpoint ARN; SMS is sent "
                        "through AWS End User Messaging"))

    def js_imports(self, rel, code):
        for rx in JS_IMPORTS:
            for m in rx.finditer(code):
                spec = m.group(1).strip()
                if spec.startswith((".", "/", "@/", "~/")) or "://" in spec:
                    continue
                if spec.startswith("node:") or spec.split("/")[0] in NODE_BUILTINS:
                    continue
                parts = spec.split("/")
                name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
                if not allow.npm_owner(name):
                    self.add("packages", rel, code, m.start(1), name,
                             "npm package not on the allow-list")

    def manifests(self, rel, text):
        name = rel.rsplit("/", 1)[-1]
        if name == "package.json":
            try:
                data = json.loads(text)
            except ValueError:
                return
            sections = ["dependencies"] if rel == ROOT_MANIFEST else \
                ["dependencies", "devDependencies", "optionalDependencies"]
            for section in sections:
                for pkg in sorted(data.get(section) or {}):
                    if not allow.npm_owner(pkg):
                        pos = text.find(f'"{pkg}"')
                        self.add("packages", rel, text, pos if pos >= 0 else None, pkg,
                                 f"{section} entry not on the allow-list")
        elif name.startswith("requirements") and name.endswith(".txt"):
            code = strip_hash_comments(text)
            for m in re.finditer(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", code, re.M):
                if not allow.pip_owner(m.group(1)):
                    self.add("packages", rel, code, m.start(1), m.group(1),
                             "pip requirement not on the allow-list")
        elif name == "Dockerfile":
            code = strip_hash_comments(text)
            for m in re.finditer(r"\bpip3?\s+install\b([^\n]*)", code):
                for token in m.group(1).split():
                    if token.startswith("-") or token.endswith(".txt") or "/" in token:
                        continue
                    pkg = re.split(r"[=<>!~\[;]", token, maxsplit=1)[0]
                    if pkg and not allow.pip_owner(pkg):
                        self.add("packages", rel, code, m.start(), pkg,
                                 "image pip install not on the allow-list")

    def routes(self, rel, code):
        for m in FIRST_PARTY_API.finditer(code):
            path = m.group(1)
            if allow.is_webhook_route(path) and not allow.webhook_route_ok(path):
                self.add("webhook-routes", rel, code, m.start(), allow.normalise_route(path),
                         "webhook route not on the allow-list")
        # Path literals are routes only in backend code. A file passed explicitly from
        # outside the repository (an absolute owner) is treated as backend code too.
        if rel.startswith(BACKEND_PREFIXES) or rel.startswith("/"):
            for m in PATH_LITERAL.finditer(code):
                path = m.group(1)
                if allow.is_webhook_route(path) and not allow.webhook_route_ok(path):
                    self.add("webhook-routes", rel, code, m.start(),
                             allow.normalise_route(path), "webhook route not on the allow-list")

    def provider_ids(self, rel, code):
        ids = allow.provider_ids()
        for m in PROVIDER_VALUE.finditer(code):
            value = m.group(2).strip()
            if value and value not in ids:
                self.add("provider-ids", rel, code, m.start(), f"{m.group(1)}={value!r}",
                         "provider value not in the approved vocabulary (Plivo voice "
                         "identity is passed as notifications.keys.PROVIDER_PLIVO)")
        selectors = allow.SELECTOR_VALUES
        for m in ENV_DEFAULT.finditer(code):
            self._selector(rel, code, m.start(), m.group(1), m.group(2), selectors, ids)
        keys = "|".join(map(re.escape, selectors))
        rx = re.compile(r"""(?<![\w.])['"]?(%s|[A-Z][A-Z0-9_]*%s)['"]?\s*[:=]\s*['"]([^'"\n]*)['"]"""
                        % (keys, re.escape(allow.PROVIDER_SELECTOR_SUFFIX)))
        for m in rx.finditer(code):
            self._selector(rel, code, m.start(), m.group(1), m.group(2), selectors, ids)

    def _selector(self, rel, code, pos, key, value, selectors, ids):
        if key in selectors:
            if value not in selectors[key]:
                self.add("provider-ids", rel, code, pos, f"{key}={value!r}",
                         f"selector value not approved (approved: {sorted(selectors[key])})")
        elif key.endswith(allow.PROVIDER_SELECTOR_SUFFIX) and value and value not in ids:
            self.add("provider-ids", rel, code, pos, f"{key}={value!r}",
                     "provider selector value not in the approved vocabulary")

    def env_keys(self, rel, code, keys=None):
        found = []
        if keys is not None:
            found = [(k, code.find(f'"{k}"')) for k in keys]
        else:
            for m in ENV_READ.finditer(code):
                found.append((m.group(1) or m.group(2) or m.group(3), m.start()))
        for key, pos in found:
            if allow.is_credential_env_key(key) and not allow.env_namespace_ok(key):
                self.add("env-namespaces", rel, code, pos if pos >= 0 else None, key,
                         "credential/endpoint env key outside the approved provider "
                         "namespaces")

    def transports(self, rel, code):
        for m in AWS_CLIENT.finditer(code):
            if m.group(1) not in allow.AWS_SERVICES:
                self.add("sms-transport", rel, code, m.start(), m.group(1),
                         "AWS client not in the approved service set")
        for m in AWS_SDK_JS.finditer(code):
            if m.group(1) not in allow.AWS_SERVICES:
                self.add("sms-transport", rel, code, m.start(), f"client-{m.group(1)}",
                         "AWS SDK client not in the approved service set")
        for m in PLIVO_RESOURCE.finditer(code):
            if m.group(1) not in allow.PLIVO_VOICE_RESOURCES:
                self.add("sms-transport", rel, code, m.start(), m.group(1),
                         "Plivo REST resource outside the approved voice resources")
        for m in SNS_PHONE_JS.finditer(code):
            self.add("sms-transport", rel, code, m.start(), "PublishCommand(PhoneNumber)",
                     "SNS publish must address a topic or endpoint ARN")
        if re.search(allow.RCS_TRANSPORT_SCOPE, rel):
            for m in CHANNEL_VALUE.finditer(code):
                if m.group(1) not in allow.RCS_CHANNELS:
                    self.add("rcs-transport", rel, code, m.start(), m.group(1),
                             "the Sinch transport may address the RCS channel only")
            for m in CHANNEL_PRIORITY.finditer(code):
                for item in re.findall(r"['\"]([A-Za-z_]+)['\"]", m.group(1)):
                    if item not in allow.RCS_CHANNELS:
                        self.add("rcs-transport", rel, code, m.start(), item,
                                 "the Sinch channel priority may contain RCS only")

    def lambdas(self, rel, code):
        for m in LAMBDA_NAME.finditer(code):
            if not allow.channel_function_ok(m.group(0)):
                self.add("channel-lambdas", rel, code, m.start(), m.group(0),
                         f"{allow.channel_of(m.group(0))} Lambda outside the supported set")

    def vpas(self, rel, code):
        for rx in (VPA_LITERAL, UPI_PA):
            for m in rx.finditer(code):
                vpa = m.group(1)
                if not allow.RAZORPAY_VPA.match(vpa):
                    self.add("upi-vpa", rel, code, m.start(), vpa,
                             "UPI address is not a Razorpay-issued VPA")

    def env_manifest(self, rel, text):
        try:
            data = json.loads(text)
        except ValueError:
            return
        functions = data.get("functions") if isinstance(data, dict) else None
        if not isinstance(functions, dict):
            return
        for fn, env in functions.items():
            owner = f"lambda:{fn}"
            if not allow.channel_function_ok(fn):
                self.add("channel-lambdas", rel, text, text.find(f'"{fn}"'), fn,
                         f"{allow.channel_of(fn)} Lambda outside the supported set")
            if not isinstance(env, dict):
                continue
            self.env_keys(rel, text, keys=list(env))
            for key, value in env.items():
                if not isinstance(value, str):
                    continue
                if value.startswith("wecare/"):
                    found, why = allow.secret_owner(value, owner)
                    if found is None:
                        self.add("secrets", rel, text, text.find(value), value, why)
                for m in URL.finditer(value):
                    found, why = allow.host_owner(m.group(2), owner)
                    if found is None:
                        self.add("hosts", rel, text, text.find(value), m.group(2), why)

    # -- driver ----------------------------------------------------------------------
    def scan_file(self, rel: str, path: Path):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self.files += 1
        code = code_view(rel, text)
        name = rel.rsplit("/", 1)[-1]
        manifest = name == "package.json" or name == "Dockerfile" or \
            (name.startswith("requirements") and name.endswith(".txt"))
        if manifest:
            self.manifests(rel, text)
            if name == "Dockerfile":
                self.hosts(rel, code)
            return
        if rel.endswith("lambda-env-manifest.json"):
            self.env_manifest(rel, text)
            self.vpas(rel, code)
            self.provider_ids(rel, code)
            return
        self.hosts(rel, code)
        self.secrets(rel, code)
        self.routes(rel, code)
        self.provider_ids(rel, code)
        self.env_keys(rel, code)
        self.transports(rel, code)
        self.lambdas(rel, code)
        self.vpas(rel, code)
        if rel.endswith(CODE_PY):
            self.python_imports(rel, text)
            self.python_sns_phone(rel, text)
        elif rel.endswith(CODE_JS):
            self.js_imports(rel, code)

    def scan_function_dirs(self):
        """Every function entry point, at any depth, is named into its channel.

        `messaging/plivo-answer` becomes `wecare-plivo-answer`; a nested directory joins its
        segments, so `messaging/<channel>-in/<x>` becomes `wecare-<channel>-in-<x>`.
        """
        base = ROOT / "amplify" / "functions"
        if not base.is_dir():
            return
        entries = set()
        for pattern in ("handler.py", "index.ts", "index.js"):
            entries.update(base.rglob(pattern))
        for entry in sorted(entries):
            parts = entry.parent.relative_to(base).parts
            if len(parts) < 2 or parts[0] == "shared" or any(
                    p in SKIP_DIRS or p in ("tests", "test", "__tests__") for p in parts):
                continue
            slug = "-".join(parts[1:])
            if slug.endswith("-handler"):
                slug = slug[: -len("-handler")]
            name = "wecare-" + slug
            if not allow.channel_function_ok(name):
                rel = entry.parent.relative_to(ROOT).as_posix()
                self.findings.append(Finding(
                    "channel-lambdas", rel + "/", 0, name,
                    f"{allow.channel_of(name)} function directory outside the supported set"))


def run(paths: list[str] | None = None) -> Scan:
    scan = Scan()
    if paths:
        for raw in paths:
            path = Path(raw).resolve()
            try:
                rel = path.relative_to(ROOT).as_posix()
            except ValueError:
                rel = path.as_posix()
            scan.scan_file(rel, path)
        return scan
    for rel in discover():
        scan.scan_file(rel, ROOT / rel)
    if (ROOT / ROOT_MANIFEST).is_file():
        scan.scan_file(ROOT_MANIFEST, ROOT / ROOT_MANIFEST)
    scan.scan_function_dirs()
    return scan


def print_allowlist() -> None:
    print("SUPPORTED PROVIDERS (scripts/provider_allowlist.py)")
    for p in allow.PROVIDERS:
        print(f"\n  {p.name}  [{p.key}]  {p.purpose}")
        for label, values in (("domains", p.domains), ("transport", p.transport_domains),
                              ("secrets", p.secret_prefixes), ("npm", p.npm),
                              ("pip", p.pip), ("webhooks", p.webhook_routes),
                              ("provider ids", p.provider_ids)):
            if values:
                print(f"      {label:13s} {', '.join(values)}")
        if p.transport_scope:
            print(f"      {'scope':13s} {p.transport_scope}")
    print("\nNON-PROVIDER REFERENCES")
    for r in allow.REFERENCES:
        print(f"  {r.key:22s} {', '.join(r.domains)}")
    print("\nLIBRARIES")
    for lib in allow.LIBRARIES:
        print(f"  {lib.key:22s} {', '.join(lib.npm + lib.pip)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="scan only these files")
    ap.add_argument("--verbose", action="store_true", help="print every finding")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--allowlist", action="store_true", help="print the allow-list and exit")
    args = ap.parse_args(argv)

    if args.allowlist:
        print_allowlist()
        return 0
    missing = [p for p in args.paths if not Path(p).is_file()]
    if missing:
        print(f"not a file: {', '.join(missing)}", file=sys.stderr)
        return 2

    scan = run(args.paths or None)
    if scan.files == 0:
        print("nothing to scan", file=sys.stderr)
        return 2
    by_rule: dict[str, list[Finding]] = {}
    for f in scan.findings:
        by_rule.setdefault(f.rule, []).append(f)

    if args.json:
        print(json.dumps({"files": scan.files,
                          "rules": {r: len(by_rule.get(r, [])) for r in RULES},
                          "findings": [asdict(f) for f in scan.findings]}, indent=2))
        return 1 if scan.findings else 0

    print("\nPROVIDER ALLOW-LIST GATE")
    print(f"  scanned : {scan.files} runtime file(s)"
          + ("" if args.paths else f" in {', '.join(SCOPE)}, {ROOT_MANIFEST}"))
    print(f"  approved: {', '.join(p.name for p in allow.PROVIDERS)}\n")
    for rule, desc in RULES.items():
        items = by_rule.get(rule, [])
        if not items:
            print(f"  ok    {rule:16s} {desc}")
            continue
        print(f"  FAIL  {rule:16s} {desc}")
        print(f"        {len(items)} finding(s) in:")
        for f in sorted({f.file for f in items}):
            print(f"          {f}")
        if args.verbose:
            for f in items:
                print(f"          | {f.file}:{f.line}  {f.value}  - {f.why}")
    print()
    if scan.findings:
        print(f"PROVIDER ALLOW-LIST VIOLATED: {len(scan.findings)} finding(s) across "
              f"{len(by_rule)} rule(s).")
        print("  Runtime code may reference only what scripts/provider_allowlist.py approves.")
        print("  Either remove the reference, or add the provider there as a deliberate")
        print("  decision - with its purpose, and scoped to the modules that use it.")
        return 1
    print("PROVIDER ALLOW-LIST OK - every external reference is approved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
