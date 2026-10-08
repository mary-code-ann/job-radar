import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from job_radar.jobs import Job
from job_radar.models import Candidate
from job_radar.store import Store, content_hash


def _cand() -> Candidate:
    return Candidate(name="Acme", normalized_name="acme", ats="greenhouse", board_slug="acme")


def _job(job_id: str, title: str = "Python Engineer") -> Job:
    return Job(
        ats="greenhouse",
        board_slug="acme",
        source_job_id=job_id,
        title=title,
        locations=["India"],
        family="python_backend",
    )


class StoreTests(unittest.TestCase):
    def test_hash_and_close_missing(self) -> None:
        self.assertEqual(content_hash([_job("b"), _job("a")]), content_hash([_job("a"), _job("b")]))
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "radar.sqlite")
            run_id = store.create_run()
            cand = _cand()
            store.apply_board(
                cand,
                run_id=run_id,
                all_jobs=[_job("1"), _job("2")],
                matches=[_job("1"), _job("2")],
                status="active",
                http_status=200,
                error=None,
            )
            store.commit()
            store.apply_board(
                cand,
                run_id=run_id,
                all_jobs=[_job("1")],
                matches=[_job("1")],
                status="active",
                http_status=200,
                error=None,
            )
            store.commit()
            rows = store.open_matches()
            self.assertEqual([row["source_job_id"] for row in rows], ["1"])
            closed = store.conn.execute(
                "SELECT source_job_id FROM jobs WHERE closed_at IS NOT NULL"
            ).fetchall()
            self.assertEqual([row["source_job_id"] for row in closed], ["2"])
            store.close()

    def test_error_does_not_close_jobs(self) -> None:
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "radar.sqlite")
            run_id = store.create_run()
            cand = _cand()
            store.apply_board(
                cand,
                run_id=run_id,
                all_jobs=[_job("1")],
                matches=[_job("1")],
                status="active",
                http_status=200,
                error=None,
            )
            store.apply_board(
                cand,
                run_id=run_id,
                all_jobs=[],
                matches=[],
                status="error",
                http_status=500,
                error="http_500",
            )
            store.commit()
            self.assertEqual(len(store.open_matches()), 1)
            row = store.get_company(cand.candidate_id)
            self.assertEqual(row["status"], "active")
            self.assertEqual(row["last_error"], "http_500")
            store.close()


if __name__ == "__main__":
    unittest.main()
