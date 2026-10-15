#!/usr/bin/env python3
"""The source-to-article ledger: which blog post came from which PDF or URL.

WHY A LEDGER AND NOT A LOG.

Running thousands of sources through a conversion pipeline has exactly one failure mode
that cannot be tidied up afterwards: the same PDF converted twice, publishing two
articles that say the same thing under two slugs. Section 28 of the quality standard
calls that out, and no amount of post-hoc dedupe fixes it once both are live and
indexed.

So the join key is the SHA-256 of the source bytes, and registration is
resolve-before-generate: a source already in the ledger returns its existing row rather
than minting a second one. That is deliberately the same discipline the payments path
uses for `reference_id` - a replayed event must land on the order that already exists.
Re-running the whole ingestion over the same directory is therefore a no-op, which is
what makes a 2,000-source run resumable after an interruption.

A URL has no stable bytes, so its identity is the SHA-256 of its normalized URL, and the
fetched body gets its own `contentSha256`. That split matters: a page that changed since
ingestion is visible as a content-hash mismatch against a stable source identity, rather
than silently becoming a second source.

The ledger is the answer to "list what blog was created from which link/PDF". It is
plain JSON, committed, and diffable.

Usage:
    python scripts/blog_ledger.py show     --ledger content/conversations/ledger.json
    python scripts/blog_ledger.py rollup   --ledger <file>
    python scripts/blog_ledger.py pending  --ledger <file>
    python scripts/blog_ledger.py verify   --ledger <file> --batches 'content/conversations/batches/*.json'
"""
from __future__ import annotations

import argparse
import glob as globlib
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LEDGER_VERSION = 1
SOURCE_TYPES = ("pdf", "url", "text")

#: The statuses a ledger row can hold are the quality standard's own, plus the two that
#: describe a source before an article exists for it at all.
PRE_ARTICLE_STATUSES = ("INGESTED", "EXTRACTION_FAILED")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def normalize_url(url: str) -> str:
    """Canonical form for URL identity.

    Lowercased scheme and host, no fragment, no trailing slash, and the tracking
    parameters stripped - otherwise the same article arriving with a `utm_source` reads
    as a different source and converts twice.
    """
    value = str(url or "").strip()
    if not value:
        return ""
    match = re.match(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://(?P<rest>.*)$", value)
    if not match:
        value = "https://" + value
        match = re.match(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*)://(?P<rest>.*)$", value)
    scheme = match.group("scheme").lower()
    rest = match.group("rest").split("#", 1)[0]

    # THE TRAILING SLASH IS STRIPPED FROM THE PATH, NOT FROM THE WHOLE STRING. `/p/?id=7`
    # and `/p?id=7` are the same page, and rstrip on the assembled URL cannot reach a slash
    # sitting before the `?` - so they registered as two sources and would have converted
    # the same article twice. Kept identical to `blog_sources.normalize_url` in the Lambda,
    # because the two must agree on source identity or the same URL gets two rows.
    path, _, query = rest.partition("?")
    host, _, tail = path.partition("/")
    path = host.lower() + ("/" + tail if tail else "")
    path = path.rstrip("/") or host.lower()

    keep = [
        part for part in query.split("&")
        if part and not re.match(r"^(?:utm_[a-z_]+|gclid|fbclid|mc_cid|mc_eid|ref|"
                                 r"source|igshid)=", part, re.IGNORECASE)
    ]
    return scheme + "://" + path + ("?" + "&".join(keep) if keep else "")


def source_identity(source_type: str, ref: str, payload: Optional[bytes] = None) -> str:
    """The ledger's primary key.

    A PDF is identified by its bytes, so a renamed file is the same source and will not
    convert twice - which is the common case when a batch is re-exported from a drive
    with different filenames.
    """
    kind = str(source_type or "").strip().lower()
    if kind == "pdf":
        if payload is None:
            raise ValueError("a pdf source identity requires its bytes")
        return sha256_bytes(payload)
    if kind == "url":
        return sha256_text(normalize_url(ref))
    return sha256_text(f"{kind}:{ref}")


@dataclass
class LedgerRow:
    """One source, and the article it became (or has not yet become)."""

    sourceId: str
    sourceType: str
    sourceRef: str
    sourceSha256: str
    ingestedAt: str
    status: str = "INGESTED"
    #: Intake decisions, made per source at ingestion time.
    category: str = ""
    articleClass: str = ""
    #: What extraction found.
    sourceTitle: str = ""
    sourceDate: str = ""
    sourcePages: int = 0
    sourceBytes: int = 0
    extractedChars: int = 0
    extractedWords: int = 0
    extractPath: str = ""
    #: For a URL, the hash of the fetched body, so a changed page is detectable.
    contentSha256: str = ""
    fetchedAt: str = ""
    #: The article, once one exists.
    slug: str = ""
    title: str = ""
    batchFile: str = ""
    #: Post-publication, filled by the publish and verify steps.
    publishedAt: str = ""
    verifiedAt: str = ""
    error: str = ""
    notes: List[str] = field(default_factory=list)
    updatedAt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def has_article(self) -> bool:
        return bool(self.slug)


class Ledger:
    """Load, mutate and save the ledger. Writes are atomic."""

    def __init__(self, path: Path, rows: Optional[List[LedgerRow]] = None) -> None:
        self.path = Path(path)
        self.rows: List[LedgerRow] = list(rows or [])
        self._by_id: Dict[str, LedgerRow] = {row.sourceId: row for row in self.rows}

    # ── persistence ────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        target = Path(path)
        if not target.exists():
            return cls(target)
        raw = json.loads(target.read_text(encoding="utf-8"))
        entries = raw.get("sources") if isinstance(raw, dict) else raw
        rows: List[LedgerRow] = []
        known = {f for f in LedgerRow.__dataclass_fields__}
        for entry in entries or []:
            #: Unknown keys are dropped rather than crashing the load: the ledger is
            #: committed and long-lived, and a field added by a later version of this
            #: script must not make the file unreadable by an earlier checkout.
            rows.append(LedgerRow(**{k: v for k, v in entry.items() if k in known}))
        return cls(target, rows)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "version": LEDGER_VERSION,
            "updatedAt": now_iso(),
            "count": len(self.rows),
            "sources": [row.to_dict() for row in
                        sorted(self.rows, key=lambda r: (r.ingestedAt, r.sourceRef))],
        }
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(self.path.parent),
            prefix=self.path.name + ".", suffix=".tmp", delete=False)
        try:
            with handle:
                json.dump(document, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, self.path)
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
        return self.path

    # ── resolve before generate ────────────────────────────────────────────────

    def resolve(self, source_id: str) -> Optional[LedgerRow]:
        return self._by_id.get(str(source_id))

    def resolve_source(self, source_type: str, ref: str,
                       payload: Optional[bytes] = None) -> Optional[LedgerRow]:
        return self.resolve(source_identity(source_type, ref, payload))

    def by_slug(self, slug: str) -> Optional[LedgerRow]:
        wanted = str(slug or "").strip()
        return next((row for row in self.rows if row.slug == wanted), None) if wanted else None

    def register(self, source_type: str, ref: str, payload: Optional[bytes] = None,
                 **fields: Any) -> Tuple[LedgerRow, bool]:
        """Return `(row, created)`. An already-known source is returned, never duplicated.

        This is the function that makes a re-run safe. It returns `created=False` for a
        source it has seen, and the caller is expected to skip the expensive extraction
        and any article generation on that basis.
        """
        kind = str(source_type or "").strip().lower()
        if kind not in SOURCE_TYPES:
            raise ValueError(f"sourceType must be one of {list(SOURCE_TYPES)}, got {kind!r}")
        source_id = source_identity(kind, ref, payload)
        existing = self._by_id.get(source_id)
        if existing is not None:
            return existing, False
        row = LedgerRow(
            sourceId=source_id,
            sourceType=kind,
            sourceRef=normalize_url(ref) if kind == "url" else str(ref),
            sourceSha256=source_id,
            ingestedAt=now_iso(),
            updatedAt=now_iso(),
            sourceBytes=len(payload) if payload is not None else 0,
        )
        for key, value in fields.items():
            if key in LedgerRow.__dataclass_fields__ and value is not None:
                setattr(row, key, value)
        self.rows.append(row)
        self._by_id[source_id] = row
        return row, True

    def update(self, source_id: str, **fields: Any) -> LedgerRow:
        row = self._by_id.get(str(source_id))
        if row is None:
            raise KeyError(f"unknown sourceId {source_id!r}")
        for key, value in fields.items():
            if key not in LedgerRow.__dataclass_fields__:
                raise KeyError(f"unknown ledger field {key!r}")
            if value is not None:
                setattr(row, key, value)
        row.updatedAt = now_iso()
        return row

    def attach_article(self, source_id: str, slug: str, title: str, category: str,
                       batch_file: str = "", status: str = "EDITORIAL_QA") -> LedgerRow:
        """Record that a source became an article.

        Refuses to repoint a source that already carries a different slug. Silently
        overwriting is how a source's history is lost, and the whole value of this file
        is being able to answer "where did this article come from" a year later.
        """
        row = self._by_id.get(str(source_id))
        if row is None:
            raise KeyError(f"unknown sourceId {source_id!r}")
        wanted = str(slug or "").strip()
        if row.slug and wanted and row.slug != wanted:
            raise ValueError(
                f"source {row.sourceRef!r} is already attached to {row.slug!r}; "
                f"refusing to repoint it at {wanted!r}")
        collision = self.by_slug(wanted)
        if collision is not None and collision.sourceId != row.sourceId:
            raise ValueError(
                f"slug {wanted!r} is already produced by {collision.sourceRef!r}")
        row.slug = wanted
        row.title = str(title or "")
        row.category = str(category or row.category)
        row.batchFile = str(batch_file or row.batchFile)
        row.status = status
        row.updatedAt = now_iso()
        return row

    # ── reporting ──────────────────────────────────────────────────────────────

    def pending(self) -> List[LedgerRow]:
        """Sources with no article yet - the actual work queue."""
        return [row for row in self.rows if not row.has_article and row.status != "EXTRACTION_FAILED"]

    def failed(self) -> List[LedgerRow]:
        return [row for row in self.rows if row.status == "EXTRACTION_FAILED"]

    def rollup(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for row in self.rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1
            by_type[row.sourceType] = by_type.get(row.sourceType, 0) + 1
            if row.category:
                by_category[row.category] = by_category.get(row.category, 0) + 1
        return {
            "total": len(self.rows),
            "withArticle": sum(1 for row in self.rows if row.has_article),
            "pending": len(self.pending()),
            "extractionFailed": len(self.failed()),
            "published": sum(1 for row in self.rows if row.publishedAt),
            "verified": sum(1 for row in self.rows if row.verifiedAt),
            "byStatus": dict(sorted(by_status.items())),
            "byCategory": dict(sorted(by_category.items())),
            "bySourceType": dict(sorted(by_type.items())),
        }

    def verify_against_batches(self, patterns: Sequence[str]) -> List[str]:
        """Reconcile the ledger against the committed batch manifests, both ways.

        Two failures this catches, and neither is visible from either file alone: an
        article in a batch that no ledger row claims (its provenance is gone), and a
        ledger row pointing at a slug that no batch contains (the article was dropped
        but the source still reads as converted, so it will never be reprocessed).
        """
        problems: List[str] = []
        batch_slugs: Dict[str, str] = {}
        for pattern in patterns:
            for match in sorted(globlib.glob(pattern, recursive=True)):
                path = Path(match)
                if not path.is_file() or path.suffix != ".json":
                    continue
                raw = json.loads(path.read_text(encoding="utf-8"))
                posts = raw.get("posts") if isinstance(raw, dict) else raw
                for post in posts or []:
                    slug = str((post or {}).get("slug") or "").strip()
                    if not slug:
                        continue
                    if slug in batch_slugs:
                        problems.append(f"slug {slug!r} appears in both {batch_slugs[slug]} "
                                        f"and {path}")
                    batch_slugs[slug] = str(path)

        ledger_slugs = {row.slug: row for row in self.rows if row.slug}
        for slug, origin in sorted(batch_slugs.items()):
            if slug not in ledger_slugs:
                problems.append(f"{origin}: article {slug!r} has no ledger row, so its source "
                                "provenance is unrecorded")
        for slug, row in sorted(ledger_slugs.items()):
            if slug not in batch_slugs:
                problems.append(f"ledger: {row.sourceRef!r} claims article {slug!r}, which is "
                                "in no committed batch")
        return problems


# ── CLI ─────────────────────────────────────────────────────────────────────────

DEFAULT_LEDGER = Path("content/conversations/ledger.json")


def _print_table(rows: Iterable[LedgerRow]) -> None:
    rows = list(rows)
    if not rows:
        print("  (none)")
        return
    print(f"  {'source':<46} {'type':<5} {'category':<14} {'status':<26} article")
    for row in rows:
        ref = row.sourceRef
        if len(ref) > 45:
            ref = "..." + ref[-42:]
        print(f"  {ref:<46} {row.sourceType:<5} {row.category or '-':<14} "
              f"{row.status:<26} {row.slug or '-'}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Blog source-to-article ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "rollup", "pending", "failed"):
        node = sub.add_parser(name)
        node.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        node.add_argument("--json", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    verify.add_argument("--batches", nargs="*",
                        default=["content/conversations/batches/*.json"])
    verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    ledger = Ledger.load(args.ledger)

    if args.command == "rollup":
        report = ledger.rollup()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"{args.ledger}")
            for key, value in report.items():
                print(f"  {key:<18} {value}")
        return 0

    if args.command == "show":
        if args.json:
            print(json.dumps([row.to_dict() for row in ledger.rows], indent=2))
        else:
            print(f"{args.ledger}: {len(ledger.rows)} source(s)")
            _print_table(ledger.rows)
        return 0

    if args.command == "pending":
        rows = ledger.pending()
        if args.json:
            print(json.dumps([row.to_dict() for row in rows], indent=2))
        else:
            print(f"{len(rows)} source(s) awaiting an article")
            _print_table(rows)
        return 0

    if args.command == "failed":
        rows = ledger.failed()
        if args.json:
            print(json.dumps([row.to_dict() for row in rows], indent=2))
        else:
            print(f"{len(rows)} source(s) failed extraction")
            for row in rows:
                print(f"  {row.sourceRef}: {row.error}")
        return 1 if rows else 0

    problems = ledger.verify_against_batches(args.batches)
    if args.json:
        print(json.dumps({"problems": problems}, indent=2))
    else:
        if problems:
            print(f"{len(problems)} reconciliation problem(s):")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"ledger and batches reconcile: {len(ledger.rows)} source(s), "
                  f"{sum(1 for r in ledger.rows if r.slug)} article(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
