"""Company-name normalization for joining directories."""

from __future__ import annotations

import re

_LEGAL_SUFFIX = re.compile(
    r"\b(incorporated|corporation|private limited|pvt ltd|limited|"
    r"ltd|llc|llp|inc|corp|co)\b\.?$",
    re.IGNORECASE,
)
_JOIN_SUFFIX = re.compile(
    r"\b(software|technologies|technology|labs|lab|private|pvt)\b\.?$",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    while True:
        stripped = _LEGAL_SUFFIX.sub("", text).strip()
        if stripped == text:
            return text
        text = stripped


def join_keys(name: str) -> set[str]:
    """Extra keys so 'Razorpay' matches 'Razorpay Software Private Limited'."""
    keys = {normalize_name(name)}
    text = normalize_name(name)
    while True:
        stripped = _JOIN_SUFFIX.sub("", text).strip()
        if stripped == text or len(stripped) < 4:
            break
        text = stripped
        keys.add(text)
    return keys


def slugs_related(board_slug: str, yc_slug: str) -> bool:
    left, right = board_slug.lower(), yc_slug.lower()
    if left == right:
        return True
    if min(len(left), len(right)) < 5:
        return False
    return left.startswith(right) or right.startswith(left)
