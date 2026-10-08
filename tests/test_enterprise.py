import unittest

from job_radar.enterprise import apply_enterprise, board_slug, seed_candidates
from job_radar.models import Candidate


SEED = [
    {
        "name": "Accenture",
        "ats": "workday",
        "board_url": "https://accenture.wd103.myworkdayjobs.com/AccentureCareers",
        "india_hint": True,
    }
]


class EnterpriseTests(unittest.TestCase):
    def test_workday_slug(self) -> None:
        self.assertEqual(board_slug(SEED[0]), "accenture/AccentureCareers")

    def test_seed_and_merge(self) -> None:
        rows = seed_candidates(SEED)
        self.assertEqual(rows[0].ats, "workday")
        self.assertTrue(rows[0].india_hint)
        existing = [
            Candidate(
                name="Stripe",
                normalized_name="stripe",
                ats="greenhouse",
                board_slug="stripe",
            )
        ]
        apply_enterprise(existing, SEED)
        apply_enterprise(existing, SEED)
        workday = [row for row in existing if row.ats == "workday"]
        self.assertEqual(len(workday), 1)


if __name__ == "__main__":
    unittest.main()
