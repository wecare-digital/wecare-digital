"""The AWS-native blog contract that the Conversations and Gastronomy runners check.

Three native seams define it. This module mirrors each one rather than inventing a fourth
definition, and names the seam beside every rule so a change there has an obvious twin here.

  STORE   `amplify/functions/operations/seo-tools/storage.py` `create_blog_post` writes a
          `blogPost` item into SeoToolsTable. Title and content are required, the slug goes
          through `_slugify` (lowercase ASCII words joined by single hyphens, cut at 120
          characters) and the body is kept verbatim as Markdown. A slug the store would
          rewrite is rejected here, because the article would then go live under a URL other
          than the one its canonical names.
  READ    `/seo-tools/blog-public` and `/seo-tools/blog-public/<slug>` on the
          `wecare-seo-tools` Lambda: the unauthenticated, published-only view the site build
          reads. The audits invoke it directly, so they need permission to invoke that one
          function and nothing else - no admin identity, no write path.
  RENDER  `src/pages/post/[slug].tsx` renders `content` one line at a time. `# `, `## ` and
          `### ` become headings, every other non-blank line becomes a paragraph, and inside
          a line only `**bold**` and `*italic*` are interpreted. Any other Markdown reaches
          the reader as literal characters, which is what `format_errors` exists to catch.

Validation needs no AWS SDK: boto3 is imported only inside `invoke_public`, so a CI job that
holds no AWS role can import this module and run every check except the live read.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

SITE = "https://wecare.digital"

#: STORE: what `storage._slugify` leaves unchanged.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG_MAX_CHARS = 120

#: STORE: DynamoDB refuses an item over 400 KB, and the body shares its `blogPost` item with
#: the title, SEO fields, tags and JSON-LD. The headroom keeps a body that passes here from
#: failing in the store.
MAX_BODY_BYTES = 380_000

#: READ: the function and route the site build reads published posts from.
PUBLIC_FUNCTION = "wecare-seo-tools"
PUBLIC_REGION = "us-east-1"
PUBLIC_ROUTE = "/seo-tools/blog-public"


# ── URLs ────────────────────────────────────────────────────────────────────────

def canonical_url(slug: str) -> str:
    """The canonical the post page emits (`next.config.js` sets `trailingSlash: true`)."""
    return f"{SITE}/post/{slug}/"


def same_url(left: Any, right: Any) -> bool:
    """A trailing slash is not a canonical difference.

    The store writes `<site>/post/<slug>` for a new post while migrated posts carry the
    trailing slash the page uses; both address the same page.
    """
    return str(left or "").strip().rstrip("/") == str(right or "").strip().rstrip("/")


def slug_errors(slug: Any) -> List[str]:
    value = str(slug or "").strip()
    if not value:
        return ["slug is required"]
    errors: List[str] = []
    if not SLUG_PATTERN.match(value):
        errors.append("slug must be lowercase words joined by single hyphens")
    if len(value) > SLUG_MAX_CHARS:
        errors.append(f"slug is {len(value)} characters; the native store cuts slugs at "
                      f"{SLUG_MAX_CHARS}")
    return errors


# ── RENDER: the body as the reader receives it ──────────────────────────────────

#: The renderer splits on `\r?\n` and trims each line; nothing else separates blocks.
_LINE_BREAK = re.compile(r"\r?\n")
#: Exactly the split `inlineFormat` uses in the post page.
_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


class Block(NamedTuple):
    """One rendered line. `kind` is heading, item or paragraph.

    An `item` is a `- ` line. The renderer shows it as a paragraph that keeps its dash, so it
    reads as a list without being list markup; it is its own kind here because the editorial
    rules count list items and prose paragraphs separately.
    """
    kind: str
    level: int
    text: str
    line: int


def inline_text(text: str) -> str:
    """A line's visible text: `**x**` and `*x*` resolved, everything else left as written."""
    def resolve(match: "re.Match[str]") -> str:
        token = match.group(0)
        return token[2:-2] if token.startswith("**") else token[1:-1]
    return _INLINE.sub(resolve, str(text or ""))


def _classify(line: str) -> Tuple[str, int, str]:
    if line.startswith("### "):
        return "heading", 3, inline_text(line[4:].strip())
    if line.startswith("## "):
        return "heading", 2, inline_text(line[3:].strip())
    if line.startswith("# "):
        #: The page title is the h1, so the renderer turns `# ` into an h2.
        return "heading", 2, inline_text(line[2:].strip())
    if line.startswith("- "):
        return "item", 0, inline_text(line[2:].strip())
    return "paragraph", 0, inline_text(line)


def parse_blocks(markdown: Any) -> List[Block]:
    blocks: List[Block] = []
    for number, raw in enumerate(_LINE_BREAK.split(str(markdown or "")), start=1):
        line = raw.strip()
        if line:
            kind, level, text = _classify(line)
            blocks.append(Block(kind, level, text, number))
    return blocks


def headings(markdown: Any) -> List[str]:
    return [block.text for block in parse_blocks(markdown) if block.kind == "heading"]


def rendered_text(markdown: Any) -> str:
    """What a reader sees, one line per block, with no Markdown markers left in it."""
    return "\n".join(block.text for block in parse_blocks(markdown))


#: Line-start Markdown the renderer does not interpret, so each shows up as typed.
_UNRENDERED_LINES: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"^#{4,}\s"), "heading deeper than ### shows its hashes; use ## or ###"),
    #: Two or more hashes: a single `#1` or `#tag` opening a line is ordinary text.
    (re.compile(r"^#{2,6}[^#\s]"), "heading marker needs a space after the hashes"),
    (re.compile(r"^\*\s"), "'* ' list marker collides with the italic marker; use '- '"),
    (re.compile(r"^\+\s"), "'+ ' list marker shows literally; use '- '"),
    (re.compile(r"^>"), "blockquote marker shows as a literal '>'"),
    (re.compile(r"^(?:-{3,}|\*{3,}|_{3,}|={3,})$"),
     "horizontal rule or underline shows as literal characters"),
    (re.compile(r"^\|.*\|$"), "Markdown table shows as literal pipes"),
    (re.compile(r"^(?:```|~~~)"), "code fence shows literally"),
)

#: Inline Markdown and markup with no rendering on the native blog.
_UNRENDERED_SPANS: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), "Markdown image; the blog is image-free"),
    (re.compile(r"(?<!!)\[[^\]\n]+\]\([^)\s]+\)"),
     "Markdown link shows literally; the native renderer has no links"),
    (re.compile(r"`"), "backtick code markup shows literally"),
    (re.compile(r"~~"), "strikethrough markup shows literally"),
    (re.compile(r"(?<![\w*])(__?)(?=\S)[^_\n]+?(?<=\S)\1(?![\w*])"),
     "underscore emphasis shows literally; use * or **"),
    (re.compile(r"</?(?:p|div|span|br|strong|em|b|i|u|a|img|h[1-6]|ul|ol|li|table|tr|td|th"
                r"|font|center|blockquote|figure|iframe|script|style)\b[^>]*>", re.IGNORECASE),
     "raw HTML markup"),
    (re.compile(r"&(?:nbsp|amp|lt|gt|quot|apos|mdash|ndash|hellip|[lr]squo|[lr]dquo"
                r"|#\d+|#x[0-9a-fA-F]+);"),
     "unresolved HTML entity"),
)

#: Seen on a line AFTER rendering: an emphasis marker without a partner, or a heading marker
#: in the middle of a line, which is what a body whose line breaks were lost looks like.
_STRAY_EMPHASIS = re.compile(r"\*")
_INLINE_HEADING = re.compile(r"(?:^|\s|\\n)#{2,6}\s")

#: Damage a pipeline does to a body on its way somewhere: written JSON-escaped, an editor's
#: tree pasted in as text, or a template variable that resolved to nothing.
CORRUPTION_PATTERNS: Tuple[Tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"\\n"), "literal escaped newline"),
    (re.compile(r"\\t"), "literal escaped tab"),
    (re.compile(r"\{\s*[\"']?(?:type|nodes|richContent|textData)[\"']?\s*:"),
     "raw editor JSON"),
    (re.compile(r"\b(?:undefined|NaN)\b"), "unresolved template placeholder"),
    (re.compile(r"\{\{[^}]+\}\}|\$\{[^}]+\}"), "unsubstituted template variable"),
)


def _first_lines(body: str, checks: Sequence[Tuple["re.Pattern[str]", str]],
                 per_line) -> Dict[str, int]:
    """Each finding once, with the first line it occurs on.

    Once rather than per line: a long body repeats one defect on every line, and forty
    identical messages bury the one that differs.
    """
    found: Dict[str, int] = {}
    for number, raw in enumerate(_LINE_BREAK.split(body), start=1):
        line = raw.strip()
        if not line:
            continue
        for pattern, description in checks:
            if pattern.search(line):
                found.setdefault(description, number)
        for description in per_line(line):
            found.setdefault(description, number)
    return found


def _format_line(line: str) -> List[str]:
    for pattern, description in _UNRENDERED_LINES:
        if pattern.match(line):
            return [description]
    shown = _classify(line)[2]
    out: List[str] = []
    if _STRAY_EMPHASIS.search(shown):
        out.append("unpaired * emphasis marker shows literally")
    if _INLINE_HEADING.search(shown):
        out.append("heading marker inside a line shows literally")
    return out


def format_errors(markdown: Any) -> List[str]:
    """RENDER: Markdown the native post page would show as literal characters."""
    found = _first_lines(str(markdown or ""), _UNRENDERED_SPANS, _format_line)
    return [f"{description} (line {line})" for description, line in found.items()]


def corruption_errors(markdown: Any) -> List[str]:
    found = _first_lines(str(markdown or ""), CORRUPTION_PATTERNS, lambda line: ())
    return [f"{description} (line {line})" for description, line in found.items()]


def body_errors(markdown: Any) -> List[str]:
    """The whole native body contract: present, storable, renderable and uncorrupted."""
    body = str(markdown or "")
    if not body.strip():
        return ["body is empty"]
    errors: List[str] = []
    size = len(body.encode("utf-8"))
    if size > MAX_BODY_BYTES:
        errors.append(f"body is {size:,} bytes; the native blogPost item allows "
                      f"{MAX_BODY_BYTES:,}")
    return errors + format_errors(body) + corruption_errors(body)


# ── READ: the published view ────────────────────────────────────────────────────

def invoke_public(path: str, query: Optional[Dict[str, str]] = None, *,
                  function: str = PUBLIC_FUNCTION, region: str = PUBLIC_REGION,
                  client: Any = None) -> Dict[str, Any]:
    """One GET against the public read route, as a direct Lambda invoke. Returns the body.

    Only GET, and only under `PUBLIC_ROUTE`: this is the route that needs no admin identity,
    which is what keeps an audit from ever being able to change a post.
    """
    if not str(path).startswith(PUBLIC_ROUTE):
        raise ValueError(f"{path!r} is not on the public read route")
    if client is None:
        import boto3
        client = boto3.client("lambda", region_name=region)
    event: Dict[str, Any] = {
        "version": "2.0",
        "requestContext": {"apiId": "content-pipeline-audit",
                           "http": {"method": "GET", "path": path,
                                    "sourceIp": "127.0.0.1"}},
        "rawPath": path,
    }
    if query:
        event["queryStringParameters"] = dict(query)
    response = client.invoke(FunctionName=function, InvocationType="RequestResponse",
                             Payload=json.dumps(event).encode("utf-8"))
    raw = response["Payload"].read().decode("utf-8")
    if response.get("FunctionError"):
        raise RuntimeError(f"{function} failed reading {path}: {raw[:400]}")
    outer = json.loads(raw)
    status = int(outer.get("statusCode") or 0)
    if status != 200:
        raise RuntimeError(f"public-blog HTTP {status} for {path}: "
                           f"{str(outer.get('body'))[:300]}")
    body = outer.get("body") or "{}"
    body = json.loads(body) if isinstance(body, str) else body
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise RuntimeError(f"public-blog reported not-ok for {path}")
    return body


def fetch_public_post(slug: str, **options: Any) -> Dict[str, Any]:
    return invoke_public(f"{PUBLIC_ROUTE}/{slug}", **options).get("post") or {}


def list_public_posts(fields: Sequence[str] = ("slug", "title"),
                      **options: Any) -> List[Dict[str, Any]]:
    """Every published post, projected to `fields`.

    Refuses a listing whose length disagrees with its own `total`: a truncated corpus would
    make a duplicate invisible and a published post look unpublished.
    """
    body = invoke_public(PUBLIC_ROUTE, {"fields": ",".join(fields)}, **options)
    posts = body.get("posts")
    if not isinstance(posts, list):
        raise RuntimeError("public-blog listing is not an array")
    total = body.get("total")
    if total is not None and int(total) != len(posts):
        raise RuntimeError(f"public-blog listing returned {len(posts)} of {total} posts")
    return [post for post in posts if isinstance(post, dict)]
