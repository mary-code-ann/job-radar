import unittest

from job_radar.filters import apply_gate, family_for, gate, geo_ok, salary_bucket
from job_radar.jobs import Job

PROFILE = {"hard_floor_lpa": 8, "min_lpa": 12}


def _job(**kwargs) -> Job:
    defaults = {
        "ats": "greenhouse",
        "board_slug": "acme",
        "source_job_id": "1",
        "title": "Software Engineer",
        "locations": ["Bengaluru, India"],
    }
    defaults.update(kwargs)
    return Job(**defaults)


class FilterTests(unittest.TestCase):
    def test_keep_ai_family_india(self) -> None:
        result = gate(_job(title="GenAI Engineer"), PROFILE)
        self.assertTrue(result.keep)
        self.assertEqual(result.family, "ai_automation")

    def test_keep_voice_and_python_and_servicenow(self) -> None:
        self.assertEqual(family_for("Voice AI Engineer"), "voice_ai")
        self.assertEqual(family_for("Python Backend Engineer"), "python_backend")
        self.assertEqual(family_for("ServiceNow Integration Engineer"), "itom_servicenow")
        self.assertTrue(gate(_job(title="FastAPI Backend Engineer"), PROFILE).keep)

    def test_sde_india_or_remote_only(self) -> None:
        self.assertTrue(gate(_job(title="Software Engineer"), PROFILE).keep)
        remote = gate(_job(title="SDE II", locations=["Remote"]), PROFILE)
        self.assertTrue(remote.keep)
        us = gate(_job(title="Software Engineer", locations=["San Francisco, CA"]), PROFILE)
        self.assertFalse(us.keep)
        self.assertEqual(us.reason, "geo")

    def test_reject_seniority_junk_intern_mobile_java(self) -> None:
        self.assertEqual(gate(_job(title="Staff Software Engineer"), PROFILE).reason, "seniority")
        self.assertEqual(gate(_job(title="Solutions Architect"), PROFILE).reason, "seniority")
        self.assertNotEqual(gate(_job(title="Junior Architect"), PROFILE).reason, "seniority")
        self.assertEqual(gate(_job(title="Account Executive"), PROFILE).reason, "junk_title")
        self.assertEqual(gate(_job(title="Software Engineer Intern"), PROFILE).reason, "intern")
        self.assertEqual(gate(_job(title="iOS Engineer"), PROFILE).reason, "mobile_only")
        self.assertEqual(gate(_job(title="Java Developer"), PROFILE).reason, "wrong_stack")
        self.assertEqual(gate(_job(title="Software Engineer, Frontend"), PROFILE).reason, "sde_wrong_stack")

    def test_yoe_and_us_only(self) -> None:
        self.assertEqual(gate(_job(title="Backend Engineer 6+ years"), PROFILE).reason, "yoe_too_high")
        blocked = gate(
            _job(title="Python Engineer", locations=["United States only"]),
            PROFILE,
        )
        self.assertEqual(blocked.reason, "us_only")

    def test_salary_buckets(self) -> None:
        low = _job(title="Python Engineer", salary_text="5 LPA")
        self.assertEqual(salary_bucket(low, hard_floor=8, min_lpa_want=12), "reject_low")
        self.assertEqual(gate(low, PROFILE).reason, "salary_below_hard_floor")
        mid = _job(title="Python Engineer", salary_text="10 LPA")
        self.assertTrue(gate(mid, PROFILE).keep)
        self.assertEqual(gate(mid, PROFILE).salary_bucket, "below_floor")
        high = _job(title="Python Engineer", salary_text="₹15 LPA")
        self.assertEqual(gate(high, PROFILE).salary_bucket, "confirmed")

    def test_hybrid_geo_and_apply_gate(self) -> None:
        job = _job(title="AI Engineer", locations=["Hybrid, APAC"])
        self.assertTrue(geo_ok(job))
        result = apply_gate(job, PROFILE)
        self.assertTrue(result.keep)
        self.assertEqual(job.family, "ai_automation")

    def test_lead_alone_is_kept(self) -> None:
        result = gate(_job(title="Lead Software Engineer"), PROFILE)
        self.assertTrue(result.keep)


if __name__ == "__main__":
    unittest.main()
