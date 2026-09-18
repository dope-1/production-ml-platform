"""Immutable serving snapshots; registry access happens only at startup/explicit reload."""

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd

from ml_platform.features.pipeline import ENGINEERED
from ml_platform.models.registry import RegistryReader
from ml_platform.monitoring.reference import load_reference


@dataclass(frozen=True)
class Snapshot:
    model: Any
    evidence: dict[str, Any]
    reference: dict[str, Any]
    explain_lock: Any = field(default_factory=Lock)

    @property
    def version(self) -> str:
        return str(self.evidence["model_version"])

    def score(self, frame: pd.DataFrame) -> Any:
        p = np.asarray(self.model.predict_proba(frame)[:, 1], dtype=float)
        if p.shape != (len(frame),) or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
            raise ValueError("Model produced invalid probabilities")
        return p

    def explain(self, frame: pd.DataFrame) -> dict[str, Any]:
        # The linear model uses exact independent-feature SHAP in log-odds space.
        # TreeExplainer uses its training path counts; no raw background rows are stored.
        x = self.model[:-1].transform(frame)
        estimator = self.model.named_steps["model"]
        with self.explain_lock:
            if hasattr(estimator, "coef_"):
                mean = np.asarray(self.reference["transformed_mean"])
                values = (x[0] - mean) * estimator.coef_[0]
                base = float(estimator.intercept_[0] + mean @ estimator.coef_[0])
                space = "log_odds"
            else:
                import shap

                explainer = shap.TreeExplainer(estimator)
                result = np.asarray(explainer.shap_values(x))
                expected = np.asarray(explainer.expected_value).reshape(-1)
                values = result[0, :, 1] if result.ndim == 3 else result[0]
                base = float(expected[1] if len(expected) == 2 else expected[0])
                space = "probability" if hasattr(estimator, "estimators_") else "log_odds"
        raw = float(base + values.sum())
        reconstructed = raw if space == "probability" else float(1 / (1 + np.exp(-raw)))
        score = float(self.score(frame)[0])
        if not np.isfinite(values).all() or not np.isclose(reconstructed, score, atol=1e-5):
            raise ValueError("Explanation does not reconstruct the prediction")
        contributions = [
            {"feature": name, "contribution": float(value)}
            for name, value in zip(ENGINEERED, values, strict=True)
        ]
        return {
            "method": "SHAP",
            "output_space": space,
            "base_value": base,
            "reconstructed_risk_score": reconstructed,
            "contributions": sorted(
                contributions, key=lambda r: abs(r["contribution"]), reverse=True
            ),
            "note": "Feature associations, not causality or a credit decision.",
        }


class ModelService:
    def __init__(self, reader: RegistryReader) -> None:
        self.reader = reader
        self._snapshot: Snapshot | None = None
        self._reload_lock = Lock()

    def current(self) -> Snapshot:
        if self._snapshot is None:
            raise RuntimeError("No verified serving model loaded")
        return self._snapshot

    def reload(self) -> Snapshot:
        with self._reload_lock:
            model, evidence = self.reader.load_production()
            reference = load_reference(self.reader, evidence)
            snapshot = Snapshot(model, evidence, reference)
            self.reader._ensure_no_pending()
            if self.reader.alias() != snapshot.version:
                raise RuntimeError("Production alias changed during reload; retry")
            # Failed reloads leave the last verified snapshot available.
            self._snapshot = snapshot
            return snapshot
