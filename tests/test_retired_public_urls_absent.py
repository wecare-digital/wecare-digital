from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]

PARTS = [
    ("zi", "p"),
    ("ship", "ments/"),
    ("fa", "q"),
    ("per", "ks/"),
    ("refer-and-", "earn/"),
    ("shop/referral-", "partner/"),
    ("gift-", "card"),
    ("appoint", "ment"),
    ("enterprise-", "assist"),
    ("ll", "m"),
    ("dasta", "vez/"),
    ("clear-", "closure/"),
    ("ritual-", "guru/"),
    ("else", "where/"),
    ("hu", "nar/"),
    ("part", "ner/"),
    ("sto", "re/"),
    ("d", "m/"),
    ("enga", "ge/"),
    ("self", "service/"),
    ("product-", "page/"),
    ("product-page/partner-", "up/"),
    ("product-page/referral-", "partner/"),
]

TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".json", ".md", ".mdx",
    ".txt", ".csv", ".yml", ".yaml", ".toml", ".css", ".scss", ".html", ".xml",
}

SKIP_DIRS = {
    ".git", "node_modules", ".next", "out", "dist", "build", ".pytest_cache",
    "__pycache__", ".turbo",
}


def _retired_routes() -> list[str]:
    return ["/" + left + right for left, right in PARTS]


def _tracked_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _standalone_pattern(route: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9_/-]){re.escape(route)}(?![A-Za-z0-9_/?=&.-])"
    )


def test_retired_public_url_literals_are_absent_repo_wide():
    found: list[str] = []
    patterns = [(route, _standalone_pattern(route)) for route in _retired_routes()]

    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for route, pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{path.relative_to(ROOT)}:{line}: retired public route {route!r}")

    assert not found, (
        "Retired customer-facing URL literals must be completely absent from tracked text. "
        "Use current child/workspace/API destinations instead.\n" + "\n".join(found)
    )
