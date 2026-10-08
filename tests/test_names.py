import unittest

from job_radar.names import join_keys, normalize_name, slugs_related


class NormalizeNameTests(unittest.TestCase):
    def test_strips_legal_suffixes(self) -> None:
        self.assertEqual(normalize_name("Acme AI, Inc."), "acme ai")
        self.assertEqual(normalize_name("Razorpay Pvt Ltd"), "razorpay")
        self.assertEqual(normalize_name("Stripe"), "stripe")

    def test_ampersand_and_punctuation(self) -> None:
        self.assertEqual(normalize_name("Johnson & Johnson"), "johnson and johnson")
        self.assertEqual(normalize_name("0g Labs"), "0g labs")

    def test_join_keys_collapse_legal_wrappers(self) -> None:
        self.assertIn("razorpay", join_keys("Razorpay Software Private Limited"))
        self.assertTrue(slugs_related("razorpaysoftwareprivatelimited", "razorpay"))
        self.assertFalse(slugs_related("able", "ableton"))


if __name__ == "__main__":
    unittest.main()
