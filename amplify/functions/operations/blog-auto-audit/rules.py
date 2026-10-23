"""Pure rules for the protected WECARE.DIGITAL blog auto-audit worker."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

AUTHOR = "Anew by WECARE.DIGITAL"
PROTECTED_COUNTS = {"Conversations": 976, "Gastronomy": 454}
PROTECTED_TOTAL = 1430

# Exact replacements only. These are deliberately narrow: the worker may repair
# deterministic corruption/source-wrapper remnants, but it must never invent copy.
SAFE_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    ("The Dosha Questionnaire", "Traditional dosha self-observation"),
    ("Recipe symbols and modification notes", "Notes on contextual food adjustments"),
    ("Follow ’s distinction by treating food choice as contextual rather than fixed.",
     "Treat food choice as contextual rather than fixed."),
    ("They are varied, but menu plans keep dessert as the final part of a broader meal.",
     "They are varied, but dessert works best as the final part of a broader meal."),
    ("’s everyday-meal guidance is especially useful: dessert can simply be omitted when the meal is not an occasion.",
     "For everyday meals, dessert can simply be omitted when the meal is not an occasion."),
    ("using ’s general bean-and-lentil method", "using the general bean-and-lentil method"),
    ("Recipe symbols that connect dishes to the dosha framework",
     "Traditional dosha classifications used as culinary context"),
    ("The introduces Ayurveda through five elements: ether, air, fire, water, and earth.",
     "Traditional Ayurvedic cooking describes five elements: ether, air, fire, water, and earth."),
    ("recipes are marked according to how says they affect those patterns.",
     "recipes can be described according to how they are traditionally understood to relate to those patterns."),
    ("Read the elemental language as This article presents it: a traditional way of organizing culinary choices.",
     "Treat the elemental language as a traditional way of organizing culinary choices."),
    ("Rice appears throughout the as a calm base for stronger flavors.",
     "Rice can serve as a calm base for stronger flavors."),
    ("In menu plans, rice often sits beside dal, vegetables, curry, chutney, raita, and salad.",
     "At the table, rice often sits beside dal, vegetables, curry, chutney, raita, and salad."),
)

PUBLIC_TEXT_FIELDS = ("title", "seoTitle", "metaDescription", "excerpt", "content")

REVIEW_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("PUBLIC_EXTERNAL_URL", re.compile(r"https?://|www\.", re.I)),
    ("PUBLIC_SOURCE_LANGUAGE", re.compile(
        r"\b(?:source note|adapted from|quoted from|published by|cited by|quoted in|"
        r"the source|the author|the book|the cookbook)\b", re.I)),
    ("SOURCE_STRUCTURE", re.compile(
        r"\b(?:the|this|same|broader|later|breakfast|salad|soup|chutney|getting started)\s+"
        r"(?:chapter|section)\b|\b(?:the\s+)?menu[- ]plans?\b", re.I)),
    ("ORPHAN_POSSESSIVE", re.compile(
        r"(?:^|\s)[’']s\s+(?:general|traditional|dosha|core|structure|approach|guidance|"
        r"distinction|method|framework|notes|techniques)\b", re.I)),
    ("MALFORMED_COPY", re.compile(
        r"(?:^|[.!?]\s+)The\s+(?:compares|does|frames|places|brings|treats|distinguishes|"
        r"maps|cools|preserves|separates|introduces)\b|"
        r"^(?:How|Why|What changes when)\s+the\s+"
        r"(?:blooms|varies|balances|favors|structures|turns|bakes|gives|treats|frames|"
        r"places|brings|distinguishes|maps|cools|preserves)\b", re.I | re.M)),
)


def clone(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: clone(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clone(item) for item in value]
    return value


def _replace_string(value: str) -> Tuple[str, int]:
    changed = 0
    result = value
    for old, new in SAFE_REPLACEMENTS:
        if old in result:
            result = result.replace(old, new)
            changed += 1
    return result, changed


def replace_nested_strings(value: Any) -> Tuple[Any, int]:
    """Apply exact safe replacements recursively to strings in richContent."""
    if isinstance(value, str):
        return _replace_string(value)
    if isinstance(value, list):
        total = 0
        out = []
        for item in value:
            new_item, changed = replace_nested_strings(item)
            out.append(new_item)
            total += changed
        return out, total
    if isinstance(value, dict):
        total = 0
        out: Dict[str, Any] = {}
        for key, item in value.items():
            new_item, changed = replace_nested_strings(item)
            out[key] = new_item
            total += changed
        return out, total
    return value, 0


def safe_patch(post: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], int]:
    """Return exact field updates and never modify identity fields."""
    updates: Dict[str, Any] = {}
    fields: List[str] = []
    replacements = 0
    for field in PUBLIC_TEXT_FIELDS:
        value = post.get(field)
        if not isinstance(value, str) or not value:
            continue
        new_value, changed = _replace_string(value)
        if changed:
            updates[field] = new_value
            fields.append(field)
            replacements += changed

    if "richContent" in post:
        new_rich, changed = replace_nested_strings(post.get("richContent"))
        if changed:
            updates["richContent"] = new_rich
            fields.append("richContent")
            replacements += changed

    return updates, fields, replacements


def iter_public_strings(post: Dict[str, Any]) -> Iterable[Tuple[str, str]]:
    for field in PUBLIC_TEXT_FIELDS:
        value = post.get(field)
        if isinstance(value, str) and value:
            yield field, value

    def walk(value: Any, path: str) -> Iterable[Tuple[str, str]]:
        if isinstance(value, str):
            if value:
                yield path, value
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from walk(item, f"{path}/{index}")
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from walk(item, f"{path}/{key}")

    if "richContent" in post:
        yield from walk(post.get("richContent"), "richContent")


def review_findings(post: Dict[str, Any]) -> List[Dict[str, str]]:
    """Detect suspicious public text after safe replacements; detection never writes."""
    findings: List[Dict[str, str]] = []
    seen = set()
    for field, text in iter_public_strings(post):
        for code, pattern in REVIEW_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            key = (code, field, match.group(0).casefold())
            if key in seen:
                continue
            seen.add(key)
            start = max(0, match.start() - 120)
            end = min(len(text), match.end() + 180)
            findings.append({
                "code": code,
                "field": field,
                "match": match.group(0),
                "context": text[start:end].replace("\n", " "),
            })
    return findings
