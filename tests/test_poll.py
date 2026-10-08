import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from job_radar.fetch_async import FetchResult
from job_radar.filters import load_profile
from job_radar.models import Candidate
from job_radar.poll import poll_async, select_candidates, write_candidate_statuses
from job_radar.store import Store

PROFILE = {"hard_floor_lpa": 8, "min_lpa": 12}

GH_OK = {
    "jobs": [
        {
            "id": 9,
            "title": "Python Engineer",
            "absolute_url": "https://boards.greenhouse.io/keep/jobs/9",
            "location": {"name": "Chennai, India"},
        },
        {
            "id": 8,
            "title": "Account Executive",
            "absolute_url": "https://boards.greenhouse.io/keep/jobs/8",
            "location": {"name": "Chennai, India"},
        },
    ]
}


def _cand(name: str, slug: str, ats: str = "greenhouse") -> Candidate:
    return Candidate(name=name, normalized_name=name.lower(), ats=ats, board_slug=slug)


class PollTests(unittest.TestCase):
    def test_select_skips_yc_only_and_resume_ids(self) -> None:
        rows = [
            _cand("Keep", "keep"),
            Candidate(name="YC", normalized_name="yc", ats=None, board_slug=None, yc_slug="yc"),
            _cand("Done", "done"),
        ]
        todo, skipped = select_candidates(rows, skip_ids={"greenhouse:done"})
        self.assertEqual([row.board_slug for row in todo], ["keep"])
        self.assertEqual(skipped, 1)

    def test_poll_gates_and_writes_outputs(self) -> None:
        async def fake(url, _proxy, _sem, method="GET", json_body=None, extra_headers=None):
            if "/keep/jobs" in url:
                return FetchResult(200, json.dumps(GH_OK).encode())
            if "/gone/jobs" in url:
                return FetchResult(404, b"")
            if "/empty/jobs" in url:
                return FetchResult(200, b'{"jobs":[]}')
            return FetchResult(500, b"", error="http_500")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            cand_path = root / "candidates.jsonl"
            rows = [_cand("Keep", "keep"), _cand("Gone", "gone"), _cand("Empty", "empty")]
            cand_path.write_text(
                "\n".join(json.dumps(row.to_json()) for row in rows) + "\n",
                encoding="utf-8",
            )
            store = Store(root / "radar.sqlite")
            summary = asyncio.run(
                poll_async(
                    candidates=rows,
                    store=store,
                    proxy="http://user:pass@proxy.test:80",
                    concurrency=4,
                    profile=PROFILE,
                    fetcher=fake,
                    seeds=[],
                    matches_path=root / "matches.jsonl",
                    summary_path=root / "poll_summary.json",
                    candidates_path=cand_path,
                )
            )
            self.assertEqual(summary["counts"]["active"], 1)
            self.assertEqual(summary["counts"]["dead"], 1)
            self.assertEqual(summary["counts"]["empty"], 1)
            self.assertEqual(summary["counts"]["matches"], 1)
            matches = (root / "matches.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(matches), 1)
            self.assertIn("Python Engineer", matches[0])
            updated = json.loads(cand_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(updated["status"], "active")
            store.close()

    def test_write_candidate_statuses(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.jsonl"
            path.write_text(
                json.dumps({"id": "greenhouse:keep", "status": "unproven", "name": "Keep"}) + "\n",
                encoding="utf-8",
            )
            n = write_candidate_statuses(path, {"greenhouse:keep": "active"})
            self.assertEqual(n, 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "active")

    def test_profile_loads(self) -> None:
        from job_radar.filters import PROFILE_PATH

        if not PROFILE_PATH.exists():
            self.skipTest("local profile is not part of the repo")
        profile = load_profile()
        self.assertIn("target_families", profile)
        self.assertIn("min_lpa", profile)


if __name__ == "__main__":
    unittest.main()
