import unittest

from fastapi.testclient import TestClient

from company_sim.mock_systems.metrics_api import app


class MetricsApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_metrics_query_returns_expected_aggregates(self) -> None:
        response = self.client.get(
            "/metrics/query",
            params={
                "service": "saas-api",
                "start_time": "2026-02-14T10:00:00Z",
                "end_time": "2026-02-14T10:20:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload["points_count"], 5)
        self.assertEqual(payload["latency_p95_ms_avg"], 227.0)
        self.assertEqual(payload["latency_p95_ms_max"], 260.0)
        self.assertEqual(payload["error_rate_avg"], 1.92)
        self.assertEqual(payload["error_rate_max"], 3.1)

    def test_metrics_query_handles_no_points(self) -> None:
        response = self.client.get(
            "/metrics/query",
            params={
                "service": "unknown-service",
                "start_time": "2026-02-14T10:00:00Z",
                "end_time": "2026-02-14T10:20:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["points_count"], 0)
        self.assertEqual(payload["points"], [])

    def test_openapi_contains_metrics_schema(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        components = response.json()["components"]["schemas"]
        self.assertIn("MetricsQueryResponse", components)


if __name__ == "__main__":
    unittest.main()
