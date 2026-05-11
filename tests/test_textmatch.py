import unittest

from paperdownloader.textmatch import normalize_title, title_similarity


class TitleMatchTests(unittest.TestCase):
    def test_normalize_title_removes_punctuation_and_case(self) -> None:
        self.assertEqual(
            normalize_title("Customer-Oriented Approaches: Product-Markets!"),
            "customer oriented approaches product markets",
        )

    def test_matching_titles_score_high(self) -> None:
        score = title_similarity(
            "Customer-Oriented Approaches to Identifying Product-Markets",
            "Customer-Oriented Approaches to Identifying Product Markets",
        )
        self.assertGreaterEqual(score, 0.95)

    def test_different_titles_score_low(self) -> None:
        score = title_similarity(
            "Customer-Oriented Approaches to Identifying Product-Markets",
            "A Study of Neural Network Training",
        )
        self.assertLess(score, 0.5)


if __name__ == "__main__":
    unittest.main()

