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

# These files DOCUMENT the retirements themselves, so they necessarily NAME retired routes in
# prose (the change-authority history, the route-retirement note, and the generated mcp catalogue
# entry that explains a retired page now answers 404). Naming a route to say it is gone is the
# opposite of routing to it, so these are excluded from the literal scan. The catalogue is
# generated, so excluding it here keeps the generator's explanatory prose intact.
RETIREMENT_DOC_FILES = {
    pathlib.Path("config/public-pages.json"),
    pathlib.Path("docs/frontend-route-retirement.md"),
    pathlib.Path("docs/execution/change-authority-matrix.md"),
}

# These files declare live INTERNAL service API contracts whose path tokens overlap names
# that were retired only as public website routes. Removing or renaming these APIs would
# break Service Ops and is outside the public-URL retirement.
INTERNAL_API_CONTRACT_FILES = {
    pathlib.Path("amplify/functions/core/service-api/handler.py"),
    pathlib.Path("amplify/functions/messaging/whatsapp-business-api/service_api.py"),
    pathlib.Path("amplify/functions/messaging/whatsapp-business-api/handler.py"),
    pathlib.Path("src/api/client.ts"),
    pathlib.Path("src/components/workspace/platform/LambdaFunctions.tsx"),
    pathlib.Path("src/components/workspace/platform/SystemArchitecture.tsx"),
    pathlib.Path("_routes.json"),
    pathlib.Path("docs/service-implementation-matrix.md"),
    pathlib.Path("docs/execution/aws-inventory.json"),
    pathlib.Path("docs/execution/runtime-inventory.json"),
    pathlib.Path("docs/execution/infra-snapshot/apis.json"),
    pathlib.Path("docs/execution/infra-snapshot/snapshot.json"),
    pathlib.Path("docs/execution/workspace-retirement-candidates-20261007.json"),
    pathlib.Path("docs/execution/workspace-report-reconciliation-20261007.md"),
    pathlib.Path("docs/research/whatsapp-platform-coverage-audit.md"),
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
        rel = path.relative_to(ROOT)
        if rel in RETIREMENT_DOC_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for route, pattern in patterns:
            if rel in INTERNAL_API_CONTRACT_FILES and route in {
                "/" + "fa" + "q",
                "/" + "enterprise-" + "assist",
            }:
                continue
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                found.append(f"{path.relative_to(ROOT)}:{line}: retired public route {route!r}")

    assert not found, (
        "Retired customer-facing URL literals must be completely absent from tracked text. "
        "Use current child/workspace/API destinations instead.\n" + "\n".join(found)
    )
