import asyncio
import os
import unittest
from unittest.mock import patch

from job_radar.fetch_async import FetchResult, fetch_url, load_geonode, parse_proxy, scrub


class FetchAsyncTests(unittest.TestCase):
    def test_parse_proxy_host_port_user_pass(self) -> None:
        self.assertEqual(
            parse_proxy("proxy.example:9000:geonode_user:s3cret"),
            "http://geonode_user:s3cret@proxy.example:9000",
        )

    def test_scrub_hides_credentials(self) -> None:
        text = scrub("http://geonode_user:s3cret@proxy.example:9000 timeout")
        self.assertNotIn("s3cret", text)
        self.assertNotIn("geonode_user", text)

    def test_missing_proxy_aborts(self) -> None:
        env = {key: value for key, value in os.environ.items() if key not in {"GEONODE_PROXY", "SCRAPE_PROXY"}}
        with patch.dict(os.environ, env, clear=True):
            with patch("job_radar.fetch_async._ENV_FILES", ()):
                with self.assertRaises(SystemExit):
                    load_geonode()

    def test_retries_then_succeeds(self) -> None:
        calls = {"n": 0}

        async def fake(_method, _url, _proxy, _body, _headers=None):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("timeout")
            return FetchResult(200, b'{"ok":true}')

        async def go() -> FetchResult:
            with patch("job_radar.fetch_async._call_fetcher", fake):
                return await fetch_url("https://example.test", "http://x", asyncio.Semaphore(1))

        result = asyncio.run(go())
        self.assertEqual(result.status, 200)
        self.assertEqual(calls["n"], 3)

    def test_404_is_final(self) -> None:
        calls = {"n": 0}

        async def fake(_method, _url, _proxy, _body, _headers=None):
            calls["n"] += 1
            return FetchResult(404, b"gone")

        async def go() -> FetchResult:
            with patch("job_radar.fetch_async._call_fetcher", fake):
                return await fetch_url("https://example.test/missing", "http://x", asyncio.Semaphore(1))

        result = asyncio.run(go())
        self.assertEqual(result.status, 404)
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
