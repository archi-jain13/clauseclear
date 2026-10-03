import unittest
import uuid
from unittest.mock import patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from backend.app import app
from backend.request_limits import RequestSizeLimitMiddleware


class TestAPIEndpoints(unittest.TestCase):

    def setUp(self):
        client_ip = f"198.51.{int(uuid.uuid4().hex[:2], 16)}.{int(uuid.uuid4().hex[2:4], 16)}"
        self.client = TestClient(app, client=(client_ip, 12345))

    def test_samples_endpoint(self):
        res = self.client.get("/api/samples")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("samples", data)
        self.assertGreaterEqual(len(data["samples"]), 2)

    def test_kb_clauses_endpoint(self):
        res = self.client.get("/api/kb/clauses")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("clauses", data)
        self.assertGreaterEqual(data["count"], 5)

    def test_security_headers_present(self):
        res = self.client.get("/health")
        self.assertIn("default-src 'self'", res.headers["Content-Security-Policy"])
        self.assertEqual(res.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(res.headers["X-Frame-Options"], "DENY")

    def test_runtime_provider_key_updates_disabled(self):
        with patch("backend.config.RUNTIME_API_KEY_UPDATES_ENABLED", False):
            gemini = self.client.post("/api/config/key", json={"gemini_api_key": "AIzaSyExampleKey123"})
            groq = self.client.post("/api/config/groq-key", json={"groq_api_key": "gsk_example_key_123456789"})

        self.assertEqual(gemini.status_code, 404)
        self.assertEqual(groq.status_code, 404)

    def test_request_size_middleware_rejects_oversized_body(self):
        limited_app = FastAPI()
        limited_app.add_middleware(RequestSizeLimitMiddleware, max_bytes=8)

        @limited_app.post("/echo")
        async def echo(request: Request):
            return {"size": len(await request.body())}

        with TestClient(limited_app) as client:
            response = client.post("/echo", content=b"123456789")

        self.assertEqual(response.status_code, 413)

    def test_unsupported_upload_type_is_rejected(self):
        token = self.client.post("/api/auth/demo-login").json()["token"]
        response = self.client.post(
            "/api/analyze/file",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("contract.docx", b"contract text longer than thirty characters", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 415)

    def test_misnamed_pdf_is_rejected_by_signature(self):
        token = self.client.post("/api/auth/demo-login").json()["token"]
        response = self.client.post(
            "/api/analyze/file",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("contract.pdf", b"not a PDF document", "application/pdf")},
        )

        self.assertEqual(response.status_code, 415)

    def test_oversized_upload_is_rejected(self):
        token = self.client.post("/api/auth/demo-login").json()["token"]
        with patch("backend.config.MAX_REQUEST_BYTES", 16):
            response = self.client.post(
                "/api/analyze/file",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("contract.txt", b"x" * 17, "text/plain")},
            )

        self.assertEqual(response.status_code, 413)

    def test_text_analysis_hides_internal_errors(self):
        token = self.client.post("/api/auth/demo-login").json()["token"]
        payload = {"text": "A sufficiently long contract clause for analysis."}
        with patch("backend.app.process_document_pipeline", side_effect=RuntimeError("internal file path")):
            response = self.client.post(
                "/api/analyze/text",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Unable to analyze this text.")
        self.assertNotIn("internal file path", response.text)

    def test_analyze_text_endpoint(self):
        payload = {
            "text": """
SECTION 1. LATE PENALTIES
Late fee of $75 per day shall accumulate with no grace period.

SECTION 2. NOTICE OF ENTRY
Landlord may enter premises at any time 24/7 without notice.
            """,
            "document_title": "Trap Agreement",
            "provider": "local"
        }
        # Unauthenticated request should be rejected with 401
        res_unauth = self.client.post("/api/analyze/text", json=payload)
        self.assertEqual(res_unauth.status_code, 401)

        # Authenticate via demo login
        login_res = self.client.post("/api/auth/demo-login")
        self.assertEqual(login_res.status_code, 200)
        token = login_res.json()["token"]

        # Authenticated request should succeed
        res = self.client.post(
            "/api/analyze/text",
            json=payload,
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["summary"]["total_clauses"], 2)
        self.assertEqual(data["summary"]["high_risk_count"], 2)
        self.assertGreaterEqual(data["summary"]["overall_risk_score"], 70)


if __name__ == "__main__":
    unittest.main()
