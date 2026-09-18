from typing import Any

from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from ml_platform.features.pipeline import make_pipeline


def candidates(seed: int) -> list[tuple[str, dict[str, Any], Any]]:
    result = []
    params: dict[str, Any]
    for c in (0.1, 1.0):
        params = {"C": c, "max_iter": 1500, "random_state": seed}
        result.append(("logistic", params, make_pipeline(LogisticRegression(**params), scale=True)))
    for depth in (6, 12):
        params = {
            "n_estimators": 80,
            "max_depth": depth,
            "min_samples_leaf": 15,
            "n_jobs": 2,
            "random_state": seed,
        }
        result.append(("random_forest", params, make_pipeline(RandomForestClassifier(**params))))
    for leaves in (15, 31):
        params = {
            "n_estimators": 120,
            "num_leaves": leaves,
            "learning_rate": 0.05,
            "min_child_samples": 30,
            "n_jobs": 2,
            "random_state": seed,
            "verbosity": -1,
            "deterministic": True,
            "force_col_wise": True,
        }
        result.append(("lightgbm", params, make_pipeline(LGBMClassifier(**params))))
    return result
