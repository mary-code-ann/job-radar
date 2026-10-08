import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from job_radar.enrich import (
    apply_payload,
    load_openrouter_key,
    messages_for,
    normalize_fit,
    normalize_india,
    parse_json_content,
    run,
    scrub,
)
from job_radar.jobs import Job
from job_radar.models import Candidate
from job_radar.store import Store

PROFILE = {
    "name": "Case Candidate",
    "yoe": 3,
    "location": "Example City",
    "proof_points": ["Example Voice IVP", "ServiceNow ticket to JSON"],
}


class EnrichTests(unittest.TestCase):
    def test_parse_json_and_fence(self) -> None:
        payload = parse_json_content('```json\n{"fit":"strong","brief":"x"}\n```')
        self.assertEqual(payload["fit"], "strong")
        self.assertEqual(parse_json_content('noise {"india_eligible":"yes"} tail')["india_eligible"], "yes")

    def test_scrub_hides_key(self) -> None:
        text = scrub("Authorization Bearer sk-or-v1-abc123def456")
        self.assertNotIn("abc123", text)
        self.assertIn("sk-or-***", text)

    def test_prompt_grounds_her_work(self) -> None:
        msgs = messages_for(
            {"title": "ServiceNow Developer", "company_name": "Ensono", "locations": ["Chennai"]},
            PROFILE,
        )
        blob = msgs[0]["content"] + msgs[1]["content"]
        self.assertIn("Example Voice IVP", blob)
        self.assertIn("ServiceNow", blob)
        self.assertIn("Ensono", blob)

    def test_normalize_labels(self) -> None:
        self.assertEqual(normalize_fit("Strong — extra prose"), "strong")
        self.assertEqual(normalize_fit("moderate"), "possible")
        self.assertEqual(normalize_india(True), "yes")
        self.assertEqual(normalize_india("unclear"), "unclear")

    def test_apply_payload(self) -> None:
        job = {"concerns": ["title says Senior"]}
        apply_payload(
            job,
            {
                "skills": ["ServiceNow", "CMDB"],
                "implied_yoe": "3-5",
                "india_eligible": "yes",
                "us_only_trap": False,
                "salary_guess_lpa": 18,
                "fit": "strong",
                "brief": "Map the CMDB work here.",
                "concerns": ["senior title"],
                "_model": "qwen/qwen3.8-27b:free",
            },
            "qwen/qwen3.8-27b:free",
        )
        self.assertEqual(job["fit"], "strong")
        self.assertIn("ServiceNow", job["skills"])
        self.assertIn("senior title", job["concerns"])
        self.assertTrue(job["enriched_at"])

    def test_missing_key_aborts(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with patch("job_radar.enrich.ENV_PATH", Path("/tmp/missing-job-radar-env")):
                with self.assertRaises(SystemExit):
                    load_openrouter_key()

    def test_run_with_mock_completer(self) -> None:
        def fake(_model, _messages):
            return {
                "skills": ["Python"],
                "implied_yoe": "3-5",
                "india_eligible": "yes",
                "us_only_trap": False,
                "salary_guess_lpa": 15,
                "salary_note": "",
                "fit": "strong",
                "brief": "Infinity/Dify workflows match this agentic role.",
                "concerns": [],
                "_model": "mock",
            }

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "radar.sqlite"
            store = Store(db)
            cand = Candidate(name="Weekday", normalized_name="weekday", ats="lever", board_slug="weekday")
            job = Job(
                ats="lever",
                board_slug="weekday",
                source_job_id="abc",
                title="Agentic AI Engineer",
                locations=["India"],
                family="ai_automation",
            )
            run_id = store.create_run()
            store.apply_board(
                cand,
                run_id=run_id,
                all_jobs=[job],
                matches=[job],
                status="active",
                http_status=200,
                error=None,
            )
            store.save_ranks(
                [
                    {
                        "ats": "lever",
                        "board_slug": "weekday",
                        "source_job_id": "abc",
                        "score": 69,
                        "why": ["AI automation"],
                        "concerns": [],
                    }
                ]
            )
            store.close()
            result = run(limit=5, db_path=db, completer=fake, key="test", workers=1)
            self.assertEqual(result["summary"]["ok"], 1)
            self.assertIn("Infinity", result["jobs"][0]["brief"])


if __name__ == "__main__":
    unittest.main()
