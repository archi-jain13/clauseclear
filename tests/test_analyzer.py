import unittest
from unittest.mock import patch
from backend.ingestion.chunker import ExtractedClause
from backend.analyzer import evidence as ev
from backend.analyzer.comparator import analyze_clause, analyze_clause_local, _build_llm_prompt
from backend.analyzer.validator import run_validation_pass


class TestAnalyzer(unittest.TestCase):

    @staticmethod
    def make_clause(text, title="Clause"):
        return ExtractedClause(
            clause_id="t", clause_number="1", clause_title=title, clause_text=text,
            raw_text="", start_char=0, end_char=len(text), word_count=len(text.split())
        )

    @staticmethod
    def neighbours(*labels, similarity=0.8):
        return {"labeled": [
            {"id": f"n{i}", "text": f"example {i}", "category": "other", "risk_level": label,
             "source": "claudette", "similarity": similarity}
            for i, label in enumerate(labels)
        ], "reference": []}

    def test_unfair_neighbours_raise_unflagged_clause_to_medium(self):
        clause = self.make_clause("We may change these terms whenever we like and you must accept them.")
        self.assertEqual(analyze_clause_local(clause, None).risk_level, "low")

        raised = analyze_clause_local(clause, None, self.neighbours("high", "medium", "high", "low"))
        self.assertEqual(raised.risk_level, "medium")
        self.assertTrue(raised.is_unusual)
        self.assertTrue(any("CLAUDETTE" in d for d in raised.deviation_points))

    def test_fair_or_distant_neighbours_do_not_flag(self):
        clause = self.make_clause("Tenant shall keep the premises clean.")
        fair = analyze_clause_local(clause, None, self.neighbours("low", "low", "low", "medium"))
        distant = analyze_clause_local(clause, None, self.neighbours("high", "high", "high", similarity=0.4))
        too_few = analyze_clause_local(clause, None, self.neighbours("high"))
        self.assertEqual((fair.risk_level, distant.risk_level, too_few.risk_level), ("low", "low", "low"))

    def test_neighbours_never_downgrade_a_rule_hit(self):
        clause = self.make_clause("The security deposit is non-refundable and forfeited in full.")
        result = analyze_clause_local(clause, None, self.neighbours("low", "low", "low", "low"))
        self.assertEqual(result.risk_level, "high")

    def test_prompt_includes_only_close_examples(self):
        clause = self.make_clause("Some clause text.")
        close = self.neighbours("high", "low")
        close["reference"] = [{"id": "c", "text": "real contract wording", "category": "governing_law",
                               "risk_level": "unlabeled", "source": "cuad", "similarity": 0.7}]
        prompt = _build_llm_prompt(clause, None, close)
        self.assertIn("Similar example clauses", prompt)
        self.assertIn("clearly unfair", prompt)
        self.assertIn("real contract wording", prompt)
        self.assertNotIn("Similar example clauses", _build_llm_prompt(clause, None, self.neighbours("high", similarity=0.2)))
        self.assertNotIn("Similar example clauses", _build_llm_prompt(clause, None))

    def test_vote_parameters_are_sane(self):
        self.assertGreaterEqual(ev.VOTE_MIN_NEIGHBOURS, 2)
        self.assertTrue(0.5 <= ev.VOTE_MIN_SIMILARITY < 1)

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
