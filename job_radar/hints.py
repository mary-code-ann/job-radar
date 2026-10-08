"""Cheap geo/remote hints from directory text. Not job-board proof."""

from __future__ import annotations

import re

INDIA_MARKERS = (
    "india",
    "indian",
    "bharat",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "chennai",
    "madras",
    "pune",
    "mumbai",
    "delhi",
    "new delhi",
    "noida",
    "gurgaon",
    "gurugram",
    "kolkata",
    "ahmedabad",
    "kochi",
    "trivandrum",
    "thiruvananthapuram",
    "jaipur",
    "indore",
    "coimbatore",
    "chandigarh",
)

_REMOTE = re.compile(
    r"\b(remote|work from anywhere|distributed|worldwide|anywhere)\b",
    re.IGNORECASE,
)


def blob(*parts: object) -> str:
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple)):
            chunks.extend(str(item) for item in part if item)
        else:
            chunks.append(str(part))
    return " ".join(chunks)


def _has_marker(text: str, marker: str) -> bool:
    return re.search(rf"\b{re.escape(marker)}\b", text, re.IGNORECASE) is not None


def india_hint(text: str) -> bool:
    lowered = text.lower()
    return any(_has_marker(lowered, marker) for marker in INDIA_MARKERS)


def chennai_hint(text: str) -> bool:
    return bool(re.search(r"\b(chennai|madras)\b", text, re.IGNORECASE))


def remote_hint(text: str) -> bool:
    return _REMOTE.search(text) is not None
