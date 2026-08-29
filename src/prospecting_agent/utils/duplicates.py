"""Soft duplicate detection by business name — catches the same business showing up
under a slightly different name (a rebrand, "LLC" vs no suffix, etc.) that the existing
exact place_id/phone dedup in storage/leads.py doesn't catch on its own.

Deliberately simple (exact match on a normalized form, no fuzzy-matching library) —
good enough to flag for human review without risking false positives that silently drop
a genuinely different business.
"""

import re

_SUFFIXES = re.compile(
    r"\b(llc|inc|incorporated|corp|corporation|co|company|ltd|limited)\.?\s*$",
    re.IGNORECASE,
)


def normalize_business_name(name: str) -> str:
    """Lowercase, strip a trailing legal-entity suffix, collapse whitespace/punctuation."""
    normalized = name.strip().lower()
    normalized = _SUFFIXES.sub("", normalized).strip()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def is_probable_duplicate(name: str, existing_names: set[str]) -> bool:
    """True if `name`'s normalized form matches any name already in `existing_names`
    (which should already be normalized — see normalize_business_name).
    """
    return normalize_business_name(name) in existing_names
