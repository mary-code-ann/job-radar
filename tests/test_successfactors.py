import unittest

from job_radar.ats.successfactors import (
    _csb_job,
    csrf_from_html,
    origin_from_url,
    parse_csb,
    parse_rmk_tiles,
)


CSB_ROW = {
    "response": {
        "id": "195451",
        "unifiedStandardTitle": "Senior Full Stack Engineer",
        "unifiedUrlTitle": "Senior-Full-Stack-Engineer",
        "supportedLocales": ["en_US"],
        "jobLocationShort": ["Bengaluru, IND-29, IND, 560035<br/>"],
        "jobLocationCountry": ["India"],
    }
}

RMK_HTML = """
<li class="job-tile job-id-1388812733 job-row-index-23" data-url="/job/Bangalore-SAP-Cutover-Manager/1388812733/">
  <a class="jobTitle-link" href="/job/Bangalore-SAP-Cutover-Manager/1388812733/">
    SAP Cutover Manager
  </a>
</li>
<li class="job-tile job-id-1388812733 job-row-index-23" data-url="/job/Bangalore-SAP-Cutover-Manager/1388812733/">
  <a class="jobTitle-link" href="/job/Bangalore-SAP-Cutover-Manager/1388812733/">
    SAP Cutover Manager
  </a>
</li>
"""


class SuccessFactorsTests(unittest.TestCase):
    def test_csb_job(self) -> None:
        job = _csb_job(CSB_ROW, "https://careers.wipro.com", "careers.wipro.com")
        self.assertEqual(job.source_job_id, "195451")
        self.assertEqual(job.title, "Senior Full Stack Engineer")
        self.assertTrue(any("Bengaluru" in loc for loc in job.locations))
        self.assertEqual(
            job.apply_url,
            "https://careers.wipro.com/job/Senior-Full-Stack-Engineer/195451-en_US",
        )

    def test_rmk_tiles_dedupe_and_city(self) -> None:
        jobs = parse_rmk_tiles(RMK_HTML, "https://careers.capgemini.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source_job_id, "1388812733")
        self.assertEqual(jobs[0].title, "SAP Cutover Manager")
        self.assertEqual(jobs[0].locations, ["Bangalore"])

    def test_origin(self) -> None:
        self.assertEqual(origin_from_url("https://careers.wipro.com/foo"), "https://careers.wipro.com")

    def test_parse_csb_and_csrf(self) -> None:
        jobs, total = parse_csb(
            {"totalJobs": 1, "jobSearchResult": [CSB_ROW]},
            "https://careers.wipro.com",
        )
        self.assertEqual(total, 1)
        self.assertEqual(jobs[0].source_job_id, "195451")
        self.assertEqual(csrf_from_html('X-CSRF-Token":"abc123"'), "abc123")
        self.assertEqual(parse_csb({"error": "nope"}, "https://careers.wipro.com"), ([], 0))


if __name__ == "__main__":
    unittest.main()
