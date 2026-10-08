import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from job_radar.harvest import apply_mcp, apply_yc, is_priority, parse_lastround, write_outputs
from job_radar.models import Candidate
from job_radar.names import normalize_name


def _lastround_csv(path: Path) -> Path:
    path.write_text(
        "ats_vendor,company_name,board_slug,last_crawled\n"
        "greenhouse,Stripe,stripe,2026-08-01\n"
        "ashby,Razorpay,razorpay,2026-08-01\n"
        "lever,Infosys,infosys,2026-08-01\n",
        encoding="utf-8",
    )
    return path


class HarvestTests(unittest.TestCase):
    def test_lastround_keeps_service_companies(self) -> None:
        with TemporaryDirectory() as tmp:
            rows = parse_lastround(_lastround_csv(Path(tmp) / "lr.csv"))
        names = {row.normalized_name for row in rows}
        self.assertEqual(names, {"stripe", "razorpay", "infosys"})

    def test_mcp_merges_job_counts_and_adds_active_unknowns(self) -> None:
        rows = [
            Candidate(
                name="Stripe",
                normalized_name="stripe",
                ats="greenhouse",
                board_slug="stripe",
                sources=["lastround"],
            )
        ]
        apply_mcp(
            rows,
            [
                {"ats": "greenhouse", "board": "stripe", "jobs": 12, "checked": "2026-08-24"},
                {"ats": "ashby", "board": "newco", "jobs": 3, "company": "NewCo"},
                {"ats": "ashby", "board": "dead", "jobs": 0, "company": "Dead"},
            ],
        )
        by_slug = {row.board_slug: row for row in rows}
        self.assertEqual(by_slug["stripe"].recent_job_count, 12)
        self.assertIn("ats_mcp", by_slug["stripe"].sources)
        self.assertEqual(by_slug["newco"].name, "NewCo")
        self.assertNotIn("dead", by_slug)

    def test_yc_joins_and_adds_india_only(self) -> None:
        rows = [
            Candidate(
                name="Razorpay Software Private Limited",
                normalized_name="razorpay software",
                ats="greenhouse",
                board_slug="razorpaysoftwareprivatelimited",
                sources=["lastround"],
            )
        ]
        apply_yc(
            rows,
            [
                {
                    "name": "Razorpay",
                    "slug": "razorpay",
                    "isHiring": True,
                    "all_locations": "Bengaluru, KA, India",
                    "regions": ["India", "Remote"],
                    "website": "https://razorpay.com",
                    "one_liner": "payments",
                    "industry": "Fintech",
                },
                {
                    "name": "US Only Co",
                    "slug": "us-only-co",
                    "isHiring": True,
                    "all_locations": "New York, NY, USA",
                    "regions": ["United States", "Remote"],
                },
                {
                    "name": "Chennai Fresh",
                    "slug": "chennai-fresh",
                    "isHiring": True,
                    "all_locations": "Chennai, TN, India",
                    "regions": ["India"],
                    "website": "https://example.com",
                },
            ],
            source="yc_india",
            add_unmatched_if_india=True,
        )
        razor = next(row for row in rows if row.board_slug == "razorpaysoftwareprivatelimited")
        self.assertTrue(razor.india_hint)
        self.assertTrue(razor.remote_hint)
        self.assertTrue(razor.yc_hiring)
        self.assertTrue(is_priority(razor))
        names = {row.normalized_name for row in rows}
        self.assertIn("chennai fresh", names)
        self.assertNotIn(normalize_name("US Only Co"), names)
        chennai = next(row for row in rows if row.chennai_hint)
        self.assertEqual(chennai.yc_slug, "chennai-fresh")
        self.assertIsNone(chennai.ats)

    def test_write_outputs_splits_priority(self) -> None:
        rows = [
            Candidate(
                name="Razorpay",
                normalized_name="razorpay",
                ats="ashby",
                board_slug="razorpay",
                india_hint=True,
                sources=["lastround", "yc_india"],
            ),
            Candidate(
                name="Stripe",
                normalized_name="stripe",
                ats="greenhouse",
                board_slug="stripe",
                sources=["lastround"],
            ),
        ]
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = write_outputs(rows, out)
            self.assertEqual(summary["counts"]["candidates"], 2)
            self.assertEqual(summary["counts"]["priority_india_hint"], 1)
            lines = (out / "priority.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)


if __name__ == "__main__":
    unittest.main()
