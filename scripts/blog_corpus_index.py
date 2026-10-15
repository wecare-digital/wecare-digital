#!/usr/bin/env python3
"""Index the whole published corpus, so the duplication gate means something.

THE DEFECT THIS CLOSES.

`blog_quality_v2.CorpusIndex` loaded from committed manifests. Measured 2026-09-29:

    committed manifest records                        383
    live published corpus                           1,140
    published posts with NO local record               757

So section 28's duplication gate compared every new article against a THIRD of the corpus
and returned a confident `PASS`. That is worse than having no gate, because a gate that
reports success is trusted. Section 29 of the standard says exactly this: "If this corpus
has not yet been indexed: report the required indexing work. Do not pretend the dedupe check
is complete."

## Why a sketch and not the text

Body similarity needs the body. Storing 1,140 bodies as exact 8-word shingle sets is roughly
4.5 MB of committed JSON that grows with every publish, and nobody will review a diff of it.

So each post is reduced to a **bottom-k sketch**: every 8-word shingle is hashed to 64 bits
and the k smallest hashes are kept. That is a uniform random sample of the shingle set,
because a good hash makes "smallest" independent of content - which is what lets a fixed 128
values estimate Jaccard over a set of any size. 1,140 posts at k=128 is about 600 kB, small
enough to commit and read in CI with no network.

The estimator below is the standard unbiased one, not the naive ratio of the two sketches.
See `jaccard` for why that distinction matters.

## What this does NOT do

It cannot index `centralDistinction`, because the 1,140 published posts predate the standard
that introduced the field. Distinction-level comparison therefore only works within a wave,
and the gate already treats it that way. Stated here rather than discovered later.

Usage:
    python scripts/blog_corpus_index.py build      # fetch and write the index
    python scripts/blog_corpus_index.py stats
    python scripts/blog_corpus_index.py verify     # is the index complete and current?
    python scripts/blog_corpus_index.py check --body-file draft.md --title "..." --slug x
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blog_quality_v2 as q  # noqa: E402

DEFAULT_INDEX = Path("content/conversations/corpus-index.json")
API_BASE = os.environ.get("NEXT_PUBLIC_API_BASE", "https://wecare.digital/api")
PUBLIC_BLOG = f"{API_BASE}/seo-tools/blog-public"

INDEX_VERSION = 1
#: Sketch size. 128 gives a Jaccard standard error around 1/sqrt(128) ~ 9%, which is ample
#: against thresholds of 0.35 and 0.60 - the decision is "clearly similar" vs "clearly not",
#: not a precise score. Raising it costs linear space for sqrt accuracy.
SKETCH_K = 128
SHINGLE = 8

USER_AGENT = "WECARE.DIGITAL-corpus-index/1.0 (+https://wecare.digital)"
TIMEOUT = 25
MAX_ATTEMPTS = 4
BASE_BACKOFF = 0.4
RETRYABLE = {408, 425, 429, 500, 502, 503, 504}


# ── Bottom-k sketching ──────────────────────────────────────────────────────────

#: 32 bits, not 64, and the width is a size decision with a measured justification.
#:
#: A JSON array of 128 64-bit integers renders as ~2.5 kB of decimal digits, which made the
#: first real index 3.7 MB - too large to review and too large to want in a diff. 32-bit
#: values pack into a single 1,024-character hex string, and the whole index lands near
#: 1.2 MB.
#:
#: The collision cost is negligible at this scale. The corpus is ~1,165 posts averaging
#: ~500 shingles, so ~600,000 distinct shingles; by the birthday bound that is roughly 42
#: expected collisions across the entire corpus. Similarity is estimated from a 128-value
#: sample, so a handful of spurious equalities among 600,000 shingles cannot move an
#: estimate across the 0.35 or 0.60 thresholds.
HASH_BITS = 32
HASH_MASK = (1 << HASH_BITS) - 1
HEX_WIDTH = HASH_BITS // 4


def _hash32(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(),
                          "big") & HASH_MASK


def shingle_hashes(text: str, size: int = SHINGLE) -> Set[int]:
    tokens = re.findall(r"[a-z0-9']+", q.strip_markdown(text).lower())
    if len(tokens) < size:
        return {_hash32(" ".join(tokens))} if tokens else set()
    return {_hash32(" ".join(tokens[i:i + size])) for i in range(len(tokens) - size + 1)}


def sketch(text: str, k: int = SKETCH_K) -> List[int]:
    """The k smallest shingle hashes, ascending.

    Sorted so a rebuilt index produces a byte-identical line for an unchanged post. That is
    what keeps the committed diff readable: publishing 25 posts changes 25 lines rather than
    churning all 1,165.
    """
    return sorted(shingle_hashes(text))[:k]


def encode_sketch(values: Sequence[int]) -> str:
    """Fixed-width hex, concatenated. One short string per post instead of a 128-item array."""
    return "".join(f"{value:0{HEX_WIDTH}x}" for value in values)


def decode_sketch(encoded: Any) -> List[int]:
    """Accepts the packed string, and a legacy integer array, so an older index still loads."""
    if isinstance(encoded, list):
        return [int(value) for value in encoded]
    text = str(encoded or "")
    return [int(text[i:i + HEX_WIDTH], 16) for i in range(0, len(text), HEX_WIDTH)]


def jaccard(left: Sequence[int], right: Sequence[int], k: int = SKETCH_K) -> float:
    """Unbiased Jaccard estimate from two bottom-k sketches.

    NOT `|A n B| / |A u B|` over the sketches, which is the obvious formula and is biased
    downward: each sketch only holds its OWN k smallest values, so a hash that is in both
    full sets can be present in one sketch and cut from the other purely because that
    document has more shingles. The bias grows with the size difference, which is exactly
    the case that matters here - a 300-word distinction against a 1,400-word deep article.

    The correct estimator takes the k smallest values of the UNION of the two sketches, and
    asks what fraction of those appear in both. Every value in that window is below both
    sketches' thresholds, so membership is known for both documents and the sample is fair.
    """
    if not left or not right:
        return 0.0
    left_set, right_set = set(left), set(right)
    window = sorted(left_set | right_set)[:k]
    if not window:
        return 0.0
    both = sum(1 for value in window if value in left_set and value in right_set)
    return both / len(window)


# ── Fetching ────────────────────────────────────────────────────────────────────

def _get(url: str) -> Optional[Dict[str, Any]]:
    """JSON, retried on transient failure. `None` for a genuine 404. Raises when exhausted.

    Same posture as `src/lib/public-blog.ts`: a 404 and a failed request are different
    facts, and conflating them is what put 219 dead links on the live site.
    """
    reason = "unknown"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code not in RETRYABLE:
                raise RuntimeError(f"{url}: HTTP {error.code} (not retryable)") from error
            reason = f"HTTP {error.code}"
        except Exception as error:  # noqa: BLE001
            reason = type(error).__name__
        if attempt < MAX_ATTEMPTS:
            time.sleep(BASE_BACKOFF * 2 ** (attempt - 1))
    raise RuntimeError(f"{url}: gave up after {MAX_ATTEMPTS} attempts ({reason})")


def fetch_listing() -> List[Dict[str, Any]]:
    body = _get(PUBLIC_BLOG)
    if not body or not body.get("ok") or not isinstance(body.get("posts"), list):
        raise RuntimeError("blog listing did not return a post array")
    return body["posts"]


def fetch_post(slug: str) -> Optional[Dict[str, Any]]:
    body = _get(f"{PUBLIC_BLOG}/{urllib.parse.quote(slug, safe='')}")
    if body is None:
        return None
    return body.get("post") if body.get("ok") else None


# ── The index ───────────────────────────────────────────────────────────────────

@dataclass
class IndexEntry:
    slug: str
    title: str
    normalizedTitle: str
    category: str
    publishedDate: str
    words: int
    sketch: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug, "title": self.title,
            "normalizedTitle": self.normalizedTitle, "category": self.category,
            "publishedDate": self.publishedDate, "words": self.words,
            "sketch": encode_sketch(self.sketch),
        }


def _entry(post: Dict[str, Any]) -> IndexEntry:
    body = str(post.get("content") or post.get("contentText") or "")
    title = str(post.get("title") or "")
    return IndexEntry(
        slug=str(post.get("slug") or ""),
        title=title,
        normalizedTitle=q._normalize_title(title),
        category=str(post.get("category") or ""),
        publishedDate=str(post.get("publishedDate") or ""),
        words=q.word_count(body),
        sketch=sketch(body),
    )


def build(out: Path, workers: int = 6, limit: int = 0,
          progress: bool = True) -> Dict[str, Any]:
    """Fetch the listing, then every body, and write the sketch index.

    Bodies are fetched concurrently but bounded. The list endpoint omits `content`, so each
    body is its own request - 1,140 of them - and the API access logs already record what an
    unbounded burst does here: 117 of 185,576 requests came back 429 in a 24-hour window.
    """
    listing = fetch_listing()
    slugs = [str(post.get("slug") or "") for post in listing if post.get("slug")]
    if limit:
        slugs = slugs[:limit]
    if progress:
        print(f"listing: {len(listing)} posts, indexing {len(slugs)}", file=sys.stderr)

    entries: List[IndexEntry] = []
    missing: List[str] = []
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for slug, post in zip(slugs, pool.map(fetch_post, slugs)):
            done += 1
            if progress and (done % 100 == 0 or done == len(slugs)):
                print(f"  {done}/{len(slugs)}", file=sys.stderr)
            if not post:
                missing.append(slug)
                continue
            entries.append(_entry(post))

    document = {
        "version": INDEX_VERSION,
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": PUBLIC_BLOG,
        "sketchK": SKETCH_K,
        "shingleSize": SHINGLE,
        "hashBits": HASH_BITS,
        "listingCount": len(listing),
        "indexedCount": len(entries),
        "missing": missing,
        "posts": [entry.to_dict() for entry in sorted(entries, key=lambda e: e.slug)],
    }
    _write_atomic(out, document)
    if progress:
        print(f"wrote {out}: {len(entries)} indexed, {len(missing)} missing",
              file=sys.stderr)
    return document


def _write_atomic(path: Path, document: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=path.name + ".",
        suffix=".tmp", delete=False)
    try:
        with handle:
            json.dump(document, handle, indent=1, ensure_ascii=False, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def load(path: Path = DEFAULT_INDEX) -> Dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {"version": INDEX_VERSION, "posts": [], "indexedCount": 0,
                "listingCount": 0, "missing": [], "builtAt": "", "sketchK": SKETCH_K}
    return json.loads(target.read_text(encoding="utf-8"))


def entries(path: Path = DEFAULT_INDEX) -> List[Dict[str, Any]]:
    return load(path).get("posts") or []


# ── Comparing a candidate against the index ─────────────────────────────────────

@dataclass
class Match:
    slug: str
    title: str
    kind: str
    score: float

    def __str__(self) -> str:
        return f"{self.kind} {self.score:.0%} vs {self.slug!r} ({self.title!r})"


def compare(title: str, slug: str, body: str,
            index: Optional[Sequence[Dict[str, Any]]] = None) -> List[Match]:
    """Every corpus match for a candidate, strongest first."""
    rows = list(index if index is not None else entries())
    candidate_sketch = sketch(body)
    normalized = q._normalize_title(title)
    wanted_slug = str(slug or "").strip()
    out: List[Match] = []

    for row in rows:
        row_slug = str(row.get("slug") or "")
        if wanted_slug and row_slug == wanted_slug:
            out.append(Match(row_slug, str(row.get("title") or ""), "SLUG_COLLISION", 1.0))
            continue
        row_normalized = str(row.get("normalizedTitle") or "")
        if normalized and row_normalized:
            if normalized == row_normalized:
                out.append(Match(row_slug, str(row.get("title") or ""),
                                 "TITLE_SAME_INQUIRY", 1.0))
            else:
                overlap = _token_jaccard(normalized, row_normalized)
                if overlap >= 0.80:
                    out.append(Match(row_slug, str(row.get("title") or ""),
                                     "NEAR_TITLE", overlap))
        row_sketch = decode_sketch(row.get("sketch"))
        if candidate_sketch and row_sketch:
            similarity = jaccard(candidate_sketch, row_sketch)
            if similarity >= 0.35:
                out.append(Match(row_slug, str(row.get("title") or ""),
                                 "BODY_OVERLAP", similarity))

    out.sort(key=lambda match: match.score, reverse=True)
    return out


def _token_jaccard(left: str, right: str) -> float:
    a, b = set(left.split()), set(right.split())
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Verification ────────────────────────────────────────────────────────────────

def verify(path: Path = DEFAULT_INDEX, live_count: Optional[int] = None) -> List[str]:
    """Problems with the index. Empty list means usable.

    Checks completeness against the LIVE listing when reachable, because an index that was
    complete last month is exactly as misleading as no index - it still reports `PASS`.
    """
    document = load(path)
    problems: List[str] = []

    if not document.get("posts"):
        problems.append(
            f"{path} holds no posts. Section 28's duplication gate cannot work; run "
            "`python scripts/blog_corpus_index.py build`.")
        return problems

    if int(document.get("version") or 0) != INDEX_VERSION:
        problems.append(f"index version {document.get('version')} != {INDEX_VERSION}")
    if int(document.get("sketchK") or 0) != SKETCH_K:
        problems.append(f"sketchK {document.get('sketchK')} != {SKETCH_K}; rebuild")
    if document.get("missing"):
        problems.append(f"{len(document['missing'])} post(s) could not be fetched: "
                        f"{document['missing'][:5]}")

    slugs = [str(post.get("slug") or "") for post in document["posts"]]
    if len(slugs) != len(set(slugs)):
        problems.append("the index contains a duplicate slug")
    for post in document["posts"]:
        if not post.get("slug"):
            problems.append("an index entry has no slug")
            break
        if not post.get("sketch"):
            problems.append(f"{post.get('slug')}: no sketch, so body comparison is blind")
            break

    if live_count is None:
        try:
            live_count = len(fetch_listing())
        except Exception:  # noqa: BLE001 - offline verification is still worth something
            live_count = None
    if live_count is not None:
        indexed = int(document.get("indexedCount") or 0)
        if indexed < live_count:
            problems.append(
                f"index covers {indexed} of {live_count} live posts "
                f"({live_count - indexed} unindexed). Dedupe would report PASS having "
                "checked only part of the corpus.")
    return problems


# ── CLI ─────────────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Published-corpus index for dedupe")
    sub = parser.add_subparsers(dest="command", required=True)

    build_cmd = sub.add_parser("build")
    build_cmd.add_argument("--out", type=Path, default=DEFAULT_INDEX)
    build_cmd.add_argument("--workers", type=int, default=6)
    build_cmd.add_argument("--limit", type=int, default=0)

    for name in ("stats", "verify"):
        node = sub.add_parser(name)
        node.add_argument("--index", type=Path, default=DEFAULT_INDEX)
        node.add_argument("--json", action="store_true")
        if name == "verify":
            node.add_argument("--offline", action="store_true",
                              help="skip the live completeness check")

    check = sub.add_parser("check")
    check.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    check.add_argument("--title", required=True)
    check.add_argument("--slug", default="")
    check.add_argument("--body-file", required=True, type=Path)
    check.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "build":
        document = build(args.out, workers=args.workers, limit=args.limit)
        print(f"indexed {document['indexedCount']} of {document['listingCount']}")
        return 1 if document["missing"] else 0

    if args.command == "stats":
        document = load(args.index)
        by_category: Dict[str, int] = {}
        for post in document.get("posts") or []:
            key = str(post.get("category") or "")
            by_category[key] = by_category.get(key, 0) + 1
        report = {
            "builtAt": document.get("builtAt", ""),
            "listingCount": document.get("listingCount", 0),
            "indexedCount": document.get("indexedCount", 0),
            "missing": len(document.get("missing") or []),
            "sketchK": document.get("sketchK"),
            "byCategory": dict(sorted(by_category.items())),
        }
        print(json.dumps(report, indent=2) if args.json else
              "\n".join(f"{k:<16} {v}" for k, v in report.items()))
        return 0

    if args.command == "verify":
        problems = verify(args.index, live_count=-1 if args.offline else None)
        problems = [p for p in problems if "live posts" not in p] if args.offline else problems
        if args.json:
            print(json.dumps({"problems": problems}, indent=2))
        elif problems:
            print(f"{len(problems)} problem(s):")
            for problem in problems:
                print(f"  - {problem}")
        else:
            document = load(args.index)
            print(f"index OK: {document.get('indexedCount')} posts, "
                  f"built {document.get('builtAt')}")
        return 1 if problems else 0

    matches = compare(args.title, args.slug,
                      args.body_file.read_text(encoding="utf-8"), entries(args.index))
    if args.json:
        print(json.dumps([{"slug": m.slug, "kind": m.kind, "score": m.score}
                          for m in matches], indent=2))
    else:
        if not matches:
            print("no corpus match")
        for match in matches[:10]:
            print(f"  {match}")
    return 1 if any(m.kind == "SLUG_COLLISION" or m.score >= 0.60 for m in matches) else 0


if __name__ == "__main__":
    raise SystemExit(main())
