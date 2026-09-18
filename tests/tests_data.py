"""Deterministic synthetic data strictly for automated tests, never demo metrics."""

import numpy as np
import pandas as pd

from ml_platform.data.validation import BILLS, COLUMNS, PAY_STATUS, PAYMENTS


def synthetic_frame(rows=800):
    rng = np.random.default_rng(731)
    frame = pd.DataFrame(
        {
            "customer_id": np.arange(1, rows + 1),
            "limit_bal": rng.integers(1, 50, rows) * 10000,
            "sex": rng.integers(1, 3, rows),
            "education": rng.integers(1, 5, rows),
            "marriage": rng.integers(1, 4, rows),
            "age": rng.integers(21, 75, rows),
        }
    )
    for column in PAY_STATUS:
        frame[column] = rng.integers(-2, 5, rows)
    for column in BILLS:
        frame[column] = rng.integers(-1000, 200000, rows)
    for column in PAYMENTS:
        frame[column] = rng.integers(0, 20000, rows)
    frame["default"] = (frame["pay_0"] >= 2).astype(int)
    return frame[COLUMNS]
