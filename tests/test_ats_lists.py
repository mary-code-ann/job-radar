import unittest

from job_radar.ats.ashby import parse_list as parse_ashby
from job_radar.ats.greenhouse import parse_list as parse_gh
from job_radar.ats.lever import parse_list as parse_lever

GH = {
    "jobs": [
        {
            "id": 123,
            "title": "Python Engineer",
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
            "location": {"name": "Bengaluru, India"},
            "offices": [{"name": "India"}],
            "first_published": "2026-09-01T00:00:00Z",
        }
    ]
}

LEVER = [
    {
        "id": "abc",
        "text": "Backend Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "categories": {"location": "Remote"},
        "workplaceType": "remote",
        "createdAt": 1710000000000,
        "salaryRange": {"currency": "INR", "min": 1200000, "max": 1800000, "interval": "year"},
    }
]

ASHBY = {
    "jobs": [
        {
            "id": "job_1",
            "title": "AI Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/acme/job_1",
            "location": "Chennai, India",
            "isRemote": True,
            "publishedAt": "2026-09-01",
            "compensation": {"summary": "12-18 LPA", "currencyCode": "INR"},
        }
    ]
}


class AtsListTests(unittest.TestCase):
    def test_greenhouse(self) -> None:
        jobs = parse_gh(GH, "acme")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source_job_id, "123")
        self.assertIn("Bengaluru, India", jobs[0].locations)
        self.assertTrue(jobs[0].apply_url.endswith("/123"))

    def test_lever_remote_and_salary(self) -> None:
        jobs = parse_lever(LEVER, "acme")
        self.assertEqual(jobs[0].title, "Backend Engineer")
        self.assertTrue(jobs[0].is_remote)
        self.assertIn("INR", jobs[0].salary_text or "")

    def test_ashby_comp_and_remote(self) -> None:
        jobs = parse_ashby(ASHBY, "acme")
        self.assertEqual(jobs[0].family if False else jobs[0].title, "AI Engineer")
        self.assertTrue(jobs[0].is_remote)
        self.assertIn("12-18 LPA", jobs[0].salary_text or "")
        self.assertEqual(jobs[0].locations, ["Chennai, India"])

    def test_empty_payloads(self) -> None:
        self.assertEqual(parse_gh({"jobs": []}, "x"), [])
        self.assertEqual(parse_lever([], "x"), [])
        self.assertEqual(parse_ashby({"jobs": None}, "x"), [])


if __name__ == "__main__":
    unittest.main()
