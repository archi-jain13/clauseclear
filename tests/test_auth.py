import unittest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app import app


class TestAuthenticationEndpoints(unittest.TestCase):

    def setUp(self):
        client_ip = f"198.51.{int(uuid.uuid4().hex[:2], 16)}.{int(uuid.uuid4().hex[2:4], 16)}"
        self.client = TestClient(app, client=(client_ip, 12345))
        self.test_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        self.test_password = "SecurePassword123!"
        self.test_name = "Legal Tester"

    def test_01_demo_login(self):
        """Test pre-seeded demo user instant login."""
        res = self.client.post("/api/auth/demo-login")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("token", data)
        self.assertEqual(data["user"]["email"], "demo@clauseclear.com")
        self.assertEqual(data["user"]["name"], "Demo User")

    def test_demo_login_disabled_in_production(self):
        with patch("backend.auth.router.DEMO_LOGIN_ENABLED", False):
            demo_route = self.client.post("/api/auth/demo-login")
            demo_credentials = self.client.post("/api/auth/login", json={
                "email": "demo@clauseclear.com",
                "password": "Password123!"
            })

        self.assertEqual(demo_route.status_code, 404)
        self.assertEqual(demo_credentials.status_code, 401)

    def test_login_rate_limit(self):
        from backend.request_limits import limiter

        limiter.reset()
        rate_client = TestClient(app, client=("198.51.100.77", 12345))
        statuses = [
            rate_client.post("/api/auth/login", json={"email": "missing@example.com", "password": "wrong"}).status_code
            for _ in range(6)
        ]
        limiter.reset()

        self.assertEqual(statuses, [401, 401, 401, 401, 401, 429])

    def test_02_register_user(self):
        """Test registration of a new user account."""
        payload = {
            "name": self.test_name,
            "email": self.test_email,
            "password": self.test_password
        }
        res = self.client.post("/api/auth/register", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("token", data)
        self.assertEqual(data["user"]["email"], self.test_email)
        self.assertEqual(data["user"]["name"], self.test_name)

    def test_03_register_duplicate_email(self):
        """Test registering the same email twice fails with 400."""
        payload = {
            "name": self.test_name,
            "email": self.test_email,
            "password": self.test_password
        }
        # First registration
        self.client.post("/api/auth/register", json=payload)
        # Second registration with same email
        res = self.client.post("/api/auth/register", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", res.json()["detail"])

    def test_04_register_validation_errors(self):
        """Test invalid email format and short passwords."""
        res = self.client.post("/api/auth/register", json={
            "name": "Bad User",
            "email": "not-an-email",
            "password": "validpassword"
        })
        self.assertIn(res.status_code, [400, 422])

        res2 = self.client.post("/api/auth/register", json={
            "name": "Bad User",
            "email": "valid@email.com",
            "password": "123"
        })
        self.assertIn(res2.status_code, [400, 422])

    def test_05_login_success_and_failure(self):
        """Test authentication with correct and incorrect credentials."""
        # Create user
        self.client.post("/api/auth/register", json={
            "name": "Login Tester",
            "email": self.test_email,
            "password": self.test_password
        })

        # Correct password
        res = self.client.post("/api/auth/login", json={
            "email": self.test_email,
            "password": self.test_password
        })
        self.assertEqual(res.status_code, 200)
        token = res.json()["token"]
        self.assertTrue(bool(token))

        # Incorrect password
        res_wrong = self.client.post("/api/auth/login", json={
            "email": self.test_email,
            "password": "WrongPassword999!"
        })
        self.assertEqual(res_wrong.status_code, 401)

        # Non-existent user
        res_unknown = self.client.post("/api/auth/login", json={
            "email": "ghost_user@example.com",
            "password": self.test_password
        })
        self.assertEqual(res_unknown.status_code, 401)

    def test_06_get_current_user_profile(self):
        """Test /api/auth/me with valid, invalid, and missing tokens."""
        # Register user and get token
        res_reg = self.client.post("/api/auth/register", json={
            "name": self.test_name,
            "email": self.test_email,
            "password": self.test_password
        })
        token = res_reg.json()["token"]

        # Valid Bearer token
        res_me = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res_me.status_code, 200)
        self.assertEqual(res_me.json()["email"], self.test_email)

        # Missing token
        res_no_auth = self.client.get("/api/auth/me")
        self.assertEqual(res_no_auth.status_code, 401)

        # Corrupted token
        res_bad_token = self.client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer totally_bogus_token_123"}
        )
        self.assertEqual(res_bad_token.status_code, 401)

    def test_07_user_analysis_history(self):
        """Test saving, retrieving, and deleting personal contract analysis history."""
        # Sign in as demo user
        res_login = self.client.post("/api/auth/demo-login")
        token = res_login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Save history item
        save_payload = {
            "document_title": "Commercial Lease Agreement Test",
            "overall_risk_score": 85,
            "total_clauses": 4,
            "high_risk_count": 2,
            "summary_verdict": "HIGH RISK: Non-standard indemnification and rent escalation provisions.",
            "analysis": {
                "document_title": "Commercial Lease Agreement Test",
                "summary": {"overall_risk_score": 85},
                "clauses": []
            }
        }
        res_save = self.client.post("/api/user/history", json=save_payload, headers=headers)
        self.assertEqual(res_save.status_code, 200)
        hist_id = res_save.json()["history_id"]
        self.assertIsInstance(hist_id, int)

        # List history
        res_list = self.client.get("/api/user/history", headers=headers)
        self.assertEqual(res_list.status_code, 200)
        history_list = res_list.json()["history"]
        self.assertGreaterEqual(len(history_list), 1)
        found = any(h["id"] == hist_id for h in history_list)
        self.assertTrue(found)

        # Get history detail
        res_detail = self.client.get(f"/api/user/history/{hist_id}", headers=headers)
        self.assertEqual(res_detail.status_code, 200)
        detail = res_detail.json()
        self.assertEqual(detail["document_title"], "Commercial Lease Agreement Test")
        self.assertEqual(detail["overall_risk_score"], 85)
        self.assertIn("analysis", detail)

        # Delete history item
        res_delete = self.client.delete(f"/api/user/history/{hist_id}", headers=headers)
        self.assertEqual(res_delete.status_code, 200)

        # Verify deletion
        res_detail_after = self.client.get(f"/api/user/history/{hist_id}", headers=headers)
        self.assertEqual(res_detail_after.status_code, 404)


if __name__ == "__main__":
    unittest.main()
