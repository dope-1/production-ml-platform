"""Strict UCI contract. Documented unknown codes are retained, never silently recoded."""

import numpy as np
import pandas as pd

from ml_platform.core.io import fingerprint

TARGET = "default"
ID = "customer_id"
SENSITIVE = ["sex", "education", "marriage", "age"]
PAY_STATUS = ["pay_0", "pay_2", "pay_3", "pay_4", "pay_5", "pay_6"]
BILLS = [f"bill_amt{i}" for i in range(1, 7)]
PAYMENTS = [f"pay_amt{i}" for i in range(1, 7)]
FEATURES = ["limit_bal", *PAY_STATUS, *BILLS, *PAYMENTS]
COLUMNS = [ID, "limit_bal", *SENSITIVE, *PAY_STATUS, *BILLS, *PAYMENTS, TARGET]
FEATURE_VERSION = "financial-only-v1"
SCHEMA_HASH = fingerprint({"features": FEATURES, "dtype": "float64", "version": FEATURE_VERSION})


def validate_frame(frame: pd.DataFrame) -> None:
    if set(frame.columns) != set(COLUMNS) or frame.columns.duplicated().any():
        raise ValueError("Schema mismatch: missing, unexpected, or duplicate columns")
    if len(frame) < 50:
        raise ValueError("At least 50 rows required")
    if frame.isna().any().any():
        raise ValueError("Missing values are forbidden by the source contract")
    if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in frame.dtypes):
        raise ValueError("Non-numeric source dtype")
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
        raise ValueError("Non-finite or non-integral source value")
    if frame[ID].duplicated().any() or frame.duplicated().any():
        raise ValueError("Duplicate records/customer IDs")
    bounds = {ID: (1, 2**53 - 1), "limit_bal": (1, 100_000_000), "age": (18, 100)}
    bounds.update({c: (-10_000_000, 100_000_000) for c in BILLS})
    bounds.update({c: (0, 100_000_000) for c in PAYMENTS})
    for column, (low, high) in bounds.items():
        if not frame[column].between(low, high).all():
            raise ValueError(f"Out-of-range values: {column}")
    categories = {
        "sex": {1, 2},
        "education": set(range(7)),
        "marriage": set(range(4)),
        TARGET: {0, 1},
        **{c: set(range(-2, 10)) for c in PAY_STATUS},
    }
    for column, allowed in categories.items():
        if not frame[column].isin(allowed).all():
            raise ValueError(f"Unknown category: {column}")
    if set(frame[TARGET]) != {0, 1} or frame[TARGET].value_counts().min() < 10:
        raise ValueError("Both target classes need at least 10 observations")


def model_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Explicit allowlist prevents target, identifier, and audit columns entering models."""
    return frame.loc[:, FEATURES].astype("float64")


def profile_groups(frame: pd.DataFrame) -> pd.Series:
    # Equal model-visible predictors always stay in the same partition, even if
    # protected attributes or labels differ. Hash values never become model inputs.
    return pd.util.hash_pandas_object(model_features(frame), index=False)
