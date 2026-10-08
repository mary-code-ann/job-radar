"""Shared HTTP for public career-site APIs."""

from __future__ import annotations

import json
import urllib.request
from http.cookiejar import CookieJar
from typing import Any

USER_AGENT = "job-radar/0.1 (personal; public career-site reads)"
TIMEOUT_SECONDS = 25


class HttpClient:
    def __init__(self) -> None:
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if extra:
            headers.update(extra)
        return headers

    def get(self, url: str, extra_headers: dict[str, str] | None = None) -> tuple[int, str, str]:
        request = urllib.request.Request(url, headers=self._headers(extra_headers))
        with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, body, response.headers.get_content_type()

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, Any, str]:
        data = json.dumps(payload).encode("utf-8")
        headers = self._headers({"Content-Type": "application/json", **(extra_headers or {})})
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", "replace")
            ctype = response.headers.get_content_type()
            parsed: Any = json.loads(text) if "json" in ctype or text[:1] in "{[" else text
            return response.status, parsed, ctype
