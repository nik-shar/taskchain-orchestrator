import unittest

from fastapi.testclient import TestClient

from company_sim.mock_systems.logs_api import app


class LogsApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_log_search_filters_by_service_time_and_pattern(self) -> None:
        response = self.client.get(
            "/logs/search",
            params={
                "service": "saas-api",
                "start_time": "2026-02-14T10:00:00Z",
                "end_time": "2026-02-14T10:20:00Z",
                "pattern": "timeout",
            },
        )
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["events"][0]["trace_id"], "trc-001")
        self.assertEqual(payload["events"][1]["trace_id"], "trc-003")

    def test_log_search_without_pattern_returns_service_events(self) -> None:
        response = self.client.get(
            "/logs/search",
            params={
                "service": "saas-web",
                "start_time": "2026-02-14T10:00:00Z",
                "end_time": "2026-02-14T10:20:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)

    def test_openapi_contains_logs_path(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/logs/search", paths)


if __name__ == "__main__":
    unittest.main()
