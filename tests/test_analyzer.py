import unittest
from unittest.mock import patch
from backend.ingestion.chunker import ExtractedClause
from backend.analyzer.comparator import analyze_clause
from backend.analyzer.validator import run_validation_pass


class TestAnalyzer(unittest.TestCase):

    def test_local_provider_never_calls_cloud(self):
        clause = ExtractedClause(
            clause_id="test-local",
            clause_number="1",
            clause_title="Security Deposit",
            clause_text="The security deposit is non-refundable and forfeited in full.",
            raw_text="",
            start_char=0,
            end_char=60,
            word_count=10
        )
        env = {"GROQ_API_KEY": "gsk_test_key_for_local_check", "GEMINI_API_KEY": "AIzaSyTestKeyForLocalCheck"}
        with patch.dict("os.environ", env), patch("requests.post") as mock_post:
            analyzed = analyze_clause(clause, provider="local")
            run_validation_pass(analyzed, provider="local")

        mock_post.assert_not_called()

    def test_predatory_clause_detection(self):
        clause = ExtractedClause(
            clause_id="test-1",
            clause_number="4",
            clause_title="Security Deposit",
            clause_text="Tenant agrees that the entire security deposit of $3,500 shall be non-refundable and forfeited in full if tenant moves out early.",
            raw_text="",
            start_char=0,
            end_char=100,
            word_count=20
        )
        analyzed = analyze_clause(clause, provider="local")
        validated = run_validation_pass(analyzed, provider="local")

        self.assertTrue(validated.is_unusual)
        self.assertEqual(validated.risk_level, "high")
        self.assertGreaterEqual(validated.risk_score, 70)
        self.assertTrue(validated.validation_audit.is_validated)

    def test_standard_fair_clause(self):
        clause = ExtractedClause(
            clause_id="test-2",
            clause_number="5",
            clause_title="Right of Entry",
            clause_text="Landlord shall provide at least twenty-four (24) hours advance written notice prior to entering the premises during normal business hours.",
            raw_text="",
            start_char=0,
            end_char=100,
            word_count=18
        )
        analyzed = analyze_clause(clause, provider="local")
        validated = run_validation_pass(analyzed, provider="local")

        self.assertFalse(validated.is_unusual)
        self.assertEqual(validated.risk_level, "low")
        self.assertLess(validated.risk_score, 40)


if __name__ == "__main__":
    unittest.main()
