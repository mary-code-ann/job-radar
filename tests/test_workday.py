import unittest

from job_radar.ats.workday import parse_list, parse_workday_url, posting_to_job, search_body


class WorkdayTests(unittest.TestCase):
    def test_parse_url_skips_locale(self) -> None:
        board = parse_workday_url(
            "https://accenture.wd103.myworkdayjobs.com/en-US/AccentureCareers"
        )
        self.assertEqual(board["tenant"], "accenture")
        self.assertEqual(board["shard"], "wd103")
        self.assertEqual(board["site"], "AccentureCareers")
        self.assertEqual(board["board_slug"], "accenture/AccentureCareers")

    def test_posting_uses_bullets_and_path_for_location(self) -> None:
        board = parse_workday_url(
            "https://accenture.wd103.myworkdayjobs.com/AccentureCareers"
        )
        job = posting_to_job(
            {
                "title": "India GCC - Sales Capture Practitioner",
                "externalPath": "/job/Bengaluru/India-GCC---Sales_R00336744",
                "bulletFields": ["R00336744", "Bengaluru"],
                "locationsText": None,
            },
            board,
        )
        self.assertEqual(job.source_job_id, "R00336744")
        self.assertIn("Bengaluru", " ".join(job.locations))
        self.assertTrue(job.apply_url.endswith("/job/Bengaluru/India-GCC---Sales_R00336744"))

    def test_parse_list_and_search_body(self) -> None:
        board = parse_workday_url("https://accenture.wd103.myworkdayjobs.com/AccentureCareers")
        jobs, total = parse_list(
            {
                "total": 1,
                "jobPostings": [
                    {
                        "title": "Python Engineer",
                        "externalPath": "/job/Chennai/Python_R1",
                        "bulletFields": ["R1", "Chennai"],
                    }
                ],
            },
            board,
        )
        self.assertEqual(total, 1)
        self.assertEqual(jobs[0].title, "Python Engineer")
        self.assertEqual(search_body(20, "India")["offset"], 20)


if __name__ == "__main__":
    unittest.main()
