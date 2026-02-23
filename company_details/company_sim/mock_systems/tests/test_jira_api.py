import unittest

from fastapi.testclient import TestClient

from company_sim.mock_systems.jira_api import app


class JiraApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_search_seed_tickets(self) -> None:
        response = self.client.get("/tickets/search", params={"project_key": "OPS", "severity": "P2"})
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertGreaterEqual(payload["total"], 1)
        self.assertEqual(payload["tickets"][0]["key"], "OPS-101")

    def test_create_update_and_search_ticket(self) -> None:
        create_response = self.client.post(
            "/tickets",
            json={
                "project_key": "OPS",
                "issue_type": "Incident",
                "summary": "Synthetic P1 auth outage",
                "description": "Login endpoint fails for enterprise tenants",
                "severity": "P1",
                "labels": ["auth", "customer-impact"],
            },
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertTrue(created["key"].startswith("OPS-"))
        self.assertEqual(created["status"], "New")

        update_response = self.client.patch(
            f"/tickets/{created['key']}",
            json={"status": "Investigating", "assignee": "Morgan Lee"},
        )
        self.assertEqual(update_response.status_code, 200)
        updated = update_response.json()
        self.assertEqual(updated["status"], "Investigating")
        self.assertEqual(updated["assignee"], "Morgan Lee")

        search_response = self.client.get("/tickets/search", params={"text": "Synthetic P1 auth outage"})
        self.assertEqual(search_response.status_code, 200)
        search_payload = search_response.json()
        self.assertEqual(search_payload["total"], 1)
        self.assertEqual(search_payload["tickets"][0]["key"], created["key"])

    def test_openapi_contains_ticket_paths(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/tickets", paths)
        self.assertIn("/tickets/search", paths)


if __name__ == "__main__":
    unittest.main()
