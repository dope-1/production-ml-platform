from pathlib import Path
from time import perf_counter
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

from ml_platform.core.io import write_json


def evaluate(y: Any, probabilities: Any, threshold: float) -> dict[str, float]:
    probabilities = np.asarray(probabilities, dtype=float)
    if not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
        raise ValueError("Invalid probabilities")
    if set(np.asarray(y)) != {0, 1}:
        raise ValueError("Both classes required for evaluation")
    predicted = probabilities >= threshold
    return {
        "accuracy": float(accuracy_score(y, predicted)),
        "precision": float(precision_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted)),
        "f1": float(f1_score(y, predicted)),
        "roc_auc": float(roc_auc_score(y, probabilities)),
        # PR-AUC is average precision throughout this repository.
        "pr_auc": float(average_precision_score(y, probabilities)),
        "brier": float(brier_score_loss(y, probabilities)),
    }


def select_threshold(
    y: Any, probabilities: Any, minimum_recall: float, grid_size: int
) -> tuple[float, list[dict[str, float]]]:
    rows = [
        {"threshold": float(t), **evaluate(y, probabilities, float(t))}
        for t in np.linspace(0, 1, grid_size + 2)
    ]
    feasible = [row for row in rows if row["recall"] >= minimum_recall]
    best = max(feasible, key=lambda row: (row["precision"], row["f1"], row["threshold"]))
    return best["threshold"], rows


def subgroups(
    frame: pd.DataFrame, probabilities: Any, threshold: float, min_positives: int
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in ("sex", "age"):
        labels = (
            frame[column]
            if column == "sex"
            else pd.cut(
                frame["age"], [17, 29, 44, 59, 100], labels=["18-29", "30-44", "45-59", "60+"]
            )
        )
        groups: dict[str, Any] = {}
        for value in sorted(labels.dropna().unique(), key=str):
            mask = np.asarray(labels == value)
            y = frame.loc[mask, "default"].to_numpy()
            p = np.asarray(probabilities)[mask]
            positives, negatives = int(y.sum()), int((y == 0).sum())
            sufficient = positives >= min_positives and negatives >= min_positives
            groups[str(value)] = {"rows": len(y), "positives": positives, "sufficient": sufficient}
            if sufficient:
                metrics = evaluate(y, p, threshold)
                tn, fp, fn, tp = confusion_matrix(y, p >= threshold, labels=[0, 1]).ravel()
                groups[str(value)].update(
                    metrics,
                    false_positive_rate=float(fp / (fp + tn)),
                    false_negative_rate=float(fn / (fn + tp)),
                )
        result[column] = groups
    eligible = [g["recall"] for g in result["sex"].values() if g["sufficient"]]
    result["sex_recall_gap"] = max(eligible) - min(eligible) if len(eligible) == 2 else None
    return result


def latency(model: Any, X: pd.DataFrame, repeats: int) -> dict[str, float]:
    row = X.iloc[:1]
    for _ in range(3):
        model.predict_proba(row)
    timings = []
    for _ in range(repeats):
        start = perf_counter()
        model.predict_proba(row)
        timings.append((perf_counter() - start) * 1000)
    return {f"latency_p{q}_ms": float(np.percentile(timings, q)) for q in (50, 95, 99)}


def plot_report(y: Any, p: Any, threshold: float, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    fpr, tpr, _ = roc_curve(y, p)
    axes[0, 0].plot(fpr, tpr)
    axes[0, 0].plot([0, 1], [0, 1], "--", color="gray")
    axes[0, 0].set(xlabel="False-positive rate", ylabel="Recall", title="ROC")
    precision, recall, _ = precision_recall_curve(y, p)
    axes[0, 1].plot(recall, precision)
    axes[0, 1].axhline(float(np.mean(y)), linestyle="--", color="gray")
    axes[0, 1].set(xlabel="Recall", ylabel="Precision", title="Precision–recall")
    observed, predicted = calibration_curve(y, p, n_bins=10, strategy="quantile")
    axes[1, 0].plot(predicted, observed, "o-")
    axes[1, 0].plot([0, 1], [0, 1], "--")
    axes[1, 0].set(xlabel="Predicted risk", ylabel="Observed default rate", title="Calibration")
    matrix = confusion_matrix(y, np.asarray(p) >= threshold, labels=[0, 1])
    axes[1, 1].imshow(matrix, cmap="Blues")
    for i in range(2):
        for j in range(2):
            axes[1, 1].text(j, i, str(matrix[i, j]), ha="center", va="center", color="black")
    axes[1, 1].set(
        xticks=[0, 1],
        yticks=[0, 1],
        xlabel="Predicted",
        ylabel="Actual",
        title=f"Confusion matrix (threshold {threshold:.2f})",
    )
    fig.tight_layout()
    fig.savefig(destination / "evaluation.png", dpi=150)
    plt.close(fig)
    write_json(
        destination / "calibration.json",
        {"predicted": predicted.tolist(), "observed": observed.tolist()},
    )
