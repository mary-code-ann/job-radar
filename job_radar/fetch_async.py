"""Geonode + Scrapling AsyncFetcher. No direct egress if proxy is missing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 20
ATTEMPTS = 4
MAX_BYTES = 3_000_000
CONCURRENCY = 5000

os.environ.setdefault("SCRAPLING_DISABLE_BANNER", "1")

CRED_AT = re.compile(r"://[^/\s]+@")
CRED_HOST = re.compile(r"geonode_[^\s:/]+", re.I)

_ENV_FILES = (ROOT / ".env",)


def scrub(msg: object) -> str:
    text = CRED_AT.sub("://***@", str(msg))
    text = CRED_HOST.sub("geonode_***", text)
    return text[:200]


def parse_proxy(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty proxy")
    if "@" in raw:
        return raw if "://" in raw else f"http://{raw}"
    s = raw.split("://", 1)[-1]
    parts = s.split(":")
    if len(parts) == 4:
        host, port, user, pw = parts
        return f"http://{user}:{pw}@{host}:{port}"
    raise ValueError("unrecognised proxy format")


def _env_file_value(path: Path) -> str:
    if not path.exists():
        return ""
    vals: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals.get("GEONODE_PROXY") or vals.get("SCRAPE_PROXY") or ""


def load_geonode() -> str:
    raw = (os.environ.get("GEONODE_PROXY") or os.environ.get("SCRAPE_PROXY") or "").strip()
    if not raw:
        for path in _ENV_FILES:
            raw = _env_file_value(path)
            if raw:
                break
    if not raw:
        raise SystemExit("geonode proxy missing — abort, no direct fetch")
    return parse_proxy(raw)


@dataclass
class FetchResult:
    status: int
    body: bytes
    error: str | None = None
    attempts: int = 1

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8", "replace"))


def _silence_scrapling() -> None:
    log = logging.getLogger("scrapling")
    log.setLevel(logging.CRITICAL)
    log.propagate = False
    log.handlers.clear()
    log.addHandler(logging.NullHandler())


async def _call_fetcher(
    method: str,
    url: str,
    proxy: str,
    json_body: dict[str, Any] | None,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    _silence_scrapling()
    from scrapling.fetchers import AsyncFetcher

    headers = {"Accept-Language": "en-US"}
    if extra_headers:
        headers.update(extra_headers)
    kwargs: dict[str, Any] = {
        "proxy": proxy,
        "timeout": TIMEOUT,
        "stealthy_headers": True,
        "follow_redirects": True,
        "retries": 1,
        "impersonate": "chrome131",
        "verify": False,
        "headers": headers,
    }
    if method == "POST":
        headers.setdefault("Content-Type", "application/json")
        kwargs["json"] = json_body or {}
        response = await AsyncFetcher.post(url, **kwargs)
    else:
        response = await AsyncFetcher.get(url, **kwargs)
    raw = response.body or b""
    if not isinstance(raw, bytes):
        raw = str(raw).encode("utf-8", "replace")
    return FetchResult(status=int(response.status or 0), body=raw[:MAX_BYTES])


async def fetch_url(
    url: str,
    proxy: str,
    sem: asyncio.Semaphore,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    last = "unreachable"
    tries = 0
    async with sem:
        for attempt in range(ATTEMPTS):
            tries += 1
            try:
                result = await _call_fetcher(method, url, proxy, json_body, extra_headers)
                result.attempts = tries
                if result.status == 404:
                    return result
                if result.status >= 500 or result.status in {0, 429} or not result.body:
                    last = f"http_{result.status}"
                    if attempt < ATTEMPTS - 1:
                        await asyncio.sleep(0.4 * (attempt + 1))
                        continue
                    result.error = last
                    return result
                return result
            except Exception as exc:
                last = scrub(f"{type(exc).__name__}:{exc}")
                if attempt < ATTEMPTS - 1:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
    return FetchResult(status=0, body=b"", error=last, attempts=tries)
