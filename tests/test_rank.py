import unittest

from job_radar.jobs import Job
from job_radar.rank import score_job, score_text

PROFILE = {"yoe": 3, "yoe_max_apply": 5, "min_lpa": 12, "hard_floor_lpa": 8}


def _job(**kwargs) -> Job:
    defaults = {
        "ats": "greenhouse",
        "board_slug": "acme",
        "source_job_id": "1",
        "title": "Software Engineer",
        "locations": ["Bengaluru, India"],
        "family": "software_engineer",
    }
    defaults.update(kwargs)
    return Job(**defaults)


class RankTests(unittest.TestCase):
    def test_chennai_servicenow_beats_generic_sde(self) -> None:
        snow = score_job(
            _job(
                title="ServiceNow Developer",
                locations=["Chennai, India"],
                family="itom_servicenow",
            ),
            PROFILE,
        )
        sde = score_job(_job(title="Software Engineer"), PROFILE)
        self.assertGreater(snow.score, sde.score)
        self.assertEqual(snow.geo, "chennai")
        self.assertTrue(any("ServiceNow" in item for item in snow.why))

    def test_voice_india_beats_us_remote_ai(self) -> None:
        voice = score_job(
            _job(
                title="Lead Voice AI Engineer",
                locations=["Bengaluru, India"],
                family="voice_ai",
            ),
            PROFILE,
        )
        us_ai = score_job(
            _job(
                title="AI Engineer",
                locations=["San Francisco"],
                family="ai_automation",
                is_remote=True,
            ),
            PROFILE,
        )
        self.assertGreater(voice.score, us_ai.score)
        self.assertIn("title says Lead", voice.concerns)
        self.assertIn("US timezone", us_ai.concerns)

    def test_python_india_remote_beats_sde(self) -> None:
        backend = score_job(
            _job(
                title="Python Backend Engineer",
                locations=["India"],
                family="python_backend",
                is_remote=True,
            ),
            PROFILE,
        )
        sde = score_job(_job(title="Software Engineer", locations=["Remote"]), PROFILE)
        self.assertGreater(backend.score, sde.score)
        self.assertEqual(backend.geo, "india_remote")

    def test_yoe_and_salary(self) -> None:
        fit = score_text(
            title="Python Engineer (2-4 years)",
            locations=["Pune, India"],
            family="python_backend",
            salary_text="18 LPA",
            salary_bucket="confirmed",
            profile=PROFILE,
        )
        high = score_text(
            title="Python Engineer (5-6 years)",
            locations=["Pune, India"],
            family="python_backend",
            salary_text=None,
            salary_bucket="unknown",
            profile=PROFILE,
        )
        self.assertGreater(fit.score, high.score)
        self.assertTrue(any("YOE band" in item for item in fit.why))
        self.assertIn("asks 5–6 years", high.concerns)
        self.assertTrue(any("salary confirmed" in item for item in fit.why))

    def test_frontend_and_junk_sink(self) -> None:
        ui = score_job(
            _job(title="Front End AI Engineer", locations=["India"], family="ai_automation"),
            PROFILE,
        )
        python = score_job(
            _job(title="Python Backend Engineer", locations=["India"], family="python_backend"),
            PROFILE,
        )
        junk = score_job(
            _job(
                title="Customer Service Professionals: ServiceNow Workflow",
                locations=["United States"],
                family="itom_servicenow",
            ),
            PROFILE,
        )
        self.assertGreater(python.score, ui.score)
        self.assertIn("frontend / UI title", ui.concerns)
        self.assertIn("support / survey / clearance role", junk.concerns)
        self.assertLess(junk.score, python.score)
        support = score_job(
            _job(title="ServiceNow Platform Support", locations=["Bangalore, India"], family="itom_servicenow"),
            PROFILE,
        )
        self.assertIn("support / survey / clearance role", support.concerns)
        self.assertLess(support.score, python.score)


if __name__ == "__main__":
    unittest.main()
