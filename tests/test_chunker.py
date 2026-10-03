import unittest
from backend.ingestion.chunker import chunk_legal_document, ExtractedClause


class TestLegalChunker(unittest.TestCase):

    def test_numbered_section_chunking(self):
        sample_contract = """
SECTION 1. PARTIES
This agreement is between Landlord and Tenant.

SECTION 2. SECURITY DEPOSIT
Tenant shall deposit $1,500 refundable within 30 days.

SECTION 3. TERMINATION
Either party may terminate with 30 days notice.
        """
        clauses = chunk_legal_document(sample_contract)
        self.assertEqual(len(clauses), 3)
        self.assertEqual(clauses[0].clause_number, "1")
        self.assertEqual(clauses[1].clause_title, "SECURITY DEPOSIT")
        self.assertIn("refundable within 30 days", clauses[1].clause_text)

    def test_paragraph_chunking_fallback(self):
        unstructured_doc = """
The tenant must pay rent on the first day of each month. Late payments incur a fee.

The landlord reserves all rights to enter premises for regular inspections.

Any disputes will be resolved through local arbitration in county court.
        """
        clauses = chunk_legal_document(unstructured_doc)
        self.assertGreaterEqual(len(clauses), 2)
        self.assertIsInstance(clauses[0], ExtractedClause)


if __name__ == "__main__":
    unittest.main()
