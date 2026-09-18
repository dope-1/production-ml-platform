import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ml_platform.data.validation import FEATURES

ENGINEERED = [*FEATURES, "utilisation", "payment_to_limit", "bill_trend_to_limit"]


class FinancialFeatures(TransformerMixin, BaseEstimator):  # type: ignore[misc]
    """Stateless, shared feature calculation packaged inside every model artifact."""

    def fit(self, X: pd.DataFrame, y: object = None) -> "FinancialFeatures":
        self.transform(X)
        self.n_features_in_ = len(FEATURES)
        return self

    def transform(self, X: pd.DataFrame) -> NDArray[np.float64]:
        if list(X.columns) != FEATURES:
            raise ValueError("Feature order/schema mismatch; target and audit columns forbidden")
        values = X.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (X["limit_bal"] <= 0).any():
            raise ValueError("Invalid numeric model input")
        return np.column_stack(
            [
                values,
                X["bill_amt1"] / X["limit_bal"],
                X["pay_amt1"] / X["limit_bal"],
                (X["bill_amt1"] - X["bill_amt6"]) / X["limit_bal"],
            ]
        )

    def get_feature_names_out(self, input_features: object = None) -> NDArray[np.object_]:
        return np.asarray(ENGINEERED, dtype=object)


def make_pipeline(estimator: BaseEstimator, scale: bool = False) -> Pipeline:
    steps = [("features", FinancialFeatures())]
    if scale:
        steps.append(("scale", StandardScaler()))
    steps.append(("model", estimator))
    return Pipeline(steps)
