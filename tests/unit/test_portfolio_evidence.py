"""Checks publication privacy and prevents misleading successful evidence."""

import importlib.util
import json
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "portfolio_evidence",
    Path(__file__).resolve().parents[2] / "scripts/collect_portfolio_evidence.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Response:
    def __init__(self, status, value):
        self.status_code = status
        self.value = value

    def json(self):
        return self.value


class Client:
    def __init__(self, anonymous_status=401, change_version=False):
        self.anonymous_status = anonymous_status
        self.change_version = change_version
        self.model_reads = 0

    def get(self, path, headers=None):
        if path == "/health":
            return Response(200, {"status": "ok"})
        if path == "/ready":
            return Response(200, {"status": "ready"})
        if path == "/api/v1/model":
            if not headers:
                return Response(self.anonymous_status, {})
            self.model_reads += 1
            version = "2" if self.change_version and self.model_reads > 1 else "1"
            return Response(
                200,
                {"model_version": version, "run_id": "reference-run", "password": "NEVER-PUBLISH"},
            )
        cohort = path.split("cohort=", 1)[1].split("&", 1)[0]
        return Response(
            200,
            {
                "model_version": "1",
                "cohort": cohort,
                "prediction_count": 0,
                "raw_inputs": {"secret": "NEVER-PUBLISH"},
                "window": {"hours": 24, "token": "NEVER-PUBLISH"},
                "operational": {"requests": 0, "latency_ms": {"p95": None}},
                "drift": {"status": "insufficient_samples", "drift_trigger": False},
                "performance": {
                    "status": "insufficient_labels",
                    "labeled": 0,
                    "coverage": 0.0,
                    "api_key": "NEVER-PUBLISH",
                },
            },
        )


class PortfolioEvidenceTests(unittest.TestCase):
    def test_private_fields_are_excluded_and_insufficient_evidence_remains_visible(self):
        evidence = MODULE.collect(Client(), "NEVER-PUBLISH")
        rendered = json.dumps(evidence) + "".join(MODULE.documents(evidence).values())
        self.assertNotIn("NEVER-PUBLISH", rendered)
        self.assertNotIn("raw_inputs", rendered)
        self.assertIn("insufficient_labels", rendered)
        self.assertIn("Benchmark not run", rendered)
        self.assertIsNone(evidence["benchmark"])

    def test_unprotected_api_is_not_published_as_a_pass(self):
        with self.assertRaisesRegex(ValueError, "Anonymous access"):
            MODULE.collect(Client(anonymous_status=200), "key")

    def test_model_change_during_collection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity changed"):
            MODULE.collect(Client(change_version=True), "key")

    def test_unexpected_model_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected serving"):
            MODULE.collect(Client(), "key", expected_version="2")

    def test_failed_or_incomplete_benchmarks_cannot_be_reported_as_success(self):
        for errors, successes in ((1, 199), (0, 199), (0, 0)):
            with self.subTest(errors=errors, successes=successes):
                with self.assertRaisesRegex(ValueError, "failed or incomplete"):
                    MODULE.benchmark_summary(
                        {"errors": errors, "successes": successes, "requests": 200}, "1"
                    )

    def test_mixed_model_benchmark_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly the expected"):
            MODULE.benchmark_summary(
                {"errors": 0, "successes": 200, "requests": 200, "model_versions": ["1", "2"]},
                "1",
            )

    def test_real_numbers_are_rendered_and_benchmark_private_fields_are_dropped(self):
        raw = {
            "errors": 0,
            "successes": 200,
            "requests": 200,
            "warmup_requests": 10,
            "concurrency": 4,
            "model_versions": ["1"],
            "throughput_rps": 40.5,
            "latency_ms": {"p50": 50.0, "p95": 70.0, "p99": 90.0, "token": "NEVER-PUBLISH"},
            "client_environment": {"python": "3.12.11", "token": "NEVER-PUBLISH"},
            "token": "NEVER-PUBLISH",
        }
        evidence = MODULE.collect(Client(), "key", measurement=raw)
        text = MODULE.documents(evidence)["benchmark.md"]
        self.assertIn("70.00 ms", text)
        self.assertIn("40.50 requests/s", text)
        self.assertNotIn("NEVER-PUBLISH", text + json.dumps(evidence))


if __name__ == "__main__":
    unittest.main()
