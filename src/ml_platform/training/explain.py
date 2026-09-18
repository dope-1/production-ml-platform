from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap

from ml_platform.core.io import write_json
from ml_platform.features.pipeline import ENGINEERED


def explain_model(
    model: Any, background: pd.DataFrame, sample: pd.DataFrame, destination: Path
) -> None:
    transformed = model[:-1].transform(sample)
    estimator = model.named_steps["model"]
    if hasattr(estimator, "coef_"):
        explainer = shap.LinearExplainer(estimator, model[:-1].transform(background))
    else:
        explainer = shap.TreeExplainer(estimator)
    values = np.asarray(explainer.shap_values(transformed))
    if values.ndim == 3:
        values = values[:, :, 1]
    if values.shape != transformed.shape or not np.isfinite(values).all():
        raise ValueError("Invalid SHAP output")
    contributions = np.abs(values).mean(axis=0)
    write_json(
        destination / "shap_summary.json",
        {
            "feature_names": ENGINEERED,
            "mean_absolute_contribution": contributions.tolist(),
            "sample_count": len(sample),
            "note": "Associations, not causality; units depend on model output space.",
        },
    )
    order = np.argsort(contributions)[-12:]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(np.asarray(ENGINEERED)[order], contributions[order])
    ax.set(xlabel="Mean absolute SHAP contribution", title="Validation sample explanation")
    fig.tight_layout()
    fig.savefig(destination / "shap_summary.png", dpi=150)
    plt.close(fig)
