import unittest

from job_radar.hints import chennai_hint, india_hint, remote_hint


class HintTests(unittest.TestCase):
    def test_india_cities(self) -> None:
        self.assertTrue(india_hint("Bengaluru, KA, India"))
        self.assertTrue(india_hint("Remote · Chennai"))
        self.assertFalse(india_hint("San Francisco, CA, United States"))

    def test_chennai(self) -> None:
        self.assertTrue(chennai_hint("Chennai, TN, India"))
        self.assertFalse(chennai_hint("Bengaluru, KA, India"))

    def test_remote(self) -> None:
        self.assertTrue(remote_hint("Fully Remote"))
        self.assertTrue(remote_hint("Work from anywhere"))
        self.assertFalse(remote_hint("Onsite New York"))

if __name__ == "__main__":
    unittest.main()
