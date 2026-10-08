"""Download public directories into data/raw with a local cache."""

from __future__ import annotations

import urllib.request
from pathlib import Path

USER_AGENT = "job-radar/0.1 (personal Wave 1 harvest; https://github.com)"
TIMEOUT_SECONDS = 60

SOURCES: dict[str, tuple[str, str]] = {
    "lastround.csv": (
        "https://raw.githubusercontent.com/fyrosofttech/lastroundai-hiring-data/"
        "main/ats-directory/lastroundai-ats-company-directory-2026-08.csv",
        "LastRound ATS directory (CC BY 4.0)",
    ),
    "ats_mcp.json": (
        "https://raw.githubusercontent.com/groundtruthtools/ats-jobs-mcp/"
        "main/src/ats_jobs_mcp/directory.json",
        "ats-jobs-mcp confirmed boards",
    ),
    "yc_india.json": (
        "https://yc-oss.github.io/api/tags/india.json",
        "YC companies tagged India",
    ),
    "yc_hiring.json": (
        "https://yc-oss.github.io/api/companies/hiring.json",
        "YC companies currently hiring",
    ),
}


def cached_get(url: str, dest: Path, *, refresh: bool = False) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return dest
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        dest.write_bytes(response.read())
    return dest


def download_sources(raw_dir: Path, *, refresh: bool = False) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for filename, (url, _label) in SOURCES.items():
        paths[filename] = cached_get(url, raw_dir / filename, refresh=refresh)
    return paths
