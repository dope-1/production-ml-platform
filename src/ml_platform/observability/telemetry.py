from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "http_requests_total",
            "Completed HTTP requests",
            ["endpoint", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration",
            ["endpoint"],
            registry=self.registry,
        )

        self.predictions = Counter(
            "model_predictions_total",
            "Persisted predictions",
            ["version", "prediction"],
            registry=self.registry,
        )
        self.scores = Histogram(
            "model_risk_score",
            "Risk score distribution",
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1],
            registry=self.registry,
        )
        self.model = Gauge(
            "serving_model_info", "Currently loaded model", ["version"], registry=self.registry
        )

    def set_model(self, version: str) -> None:
        self.model.clear()
        self.model.labels(version).set(1)
