"""The same 19 financial fields used by the fitted training pipeline."""

from typing import Annotated

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ml_platform.data.validation import BILLS, FEATURES, PAY_STATUS, PAYMENTS

Balance = Annotated[int, Field(strict=True, ge=-10_000_000, le=100_000_000)]
Payment = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
Status = Annotated[int, Field(strict=True, ge=-2, le=9)]


class PredictionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit_bal: Annotated[int, Field(strict=True, ge=1, le=100_000_000)]
    pay_0: Status
    pay_2: Status
    pay_3: Status
    pay_4: Status
    pay_5: Status
    pay_6: Status
    bill_amt1: Balance
    bill_amt2: Balance
    bill_amt3: Balance
    bill_amt4: Balance
    bill_amt5: Balance
    bill_amt6: Balance
    pay_amt1: Payment
    pay_amt2: Payment
    pay_amt3: Payment
    pay_amt4: Payment
    pay_amt5: Payment
    pay_amt6: Payment

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([self.model_dump()], columns=FEATURES).astype("float64")


def validate_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Vectorized validation for CSV scoring; no row-by-row HTTP or Pydantic loop."""
    import numpy as np

    if list(frame.columns) != FEATURES:
        raise ValueError("Feature columns must follow the published schema")
    if not len(frame) or not all(
        pd.api.types.is_numeric_dtype(t) and not pd.api.types.is_bool_dtype(t) for t in frame.dtypes
    ):
        raise ValueError("Empty batch or non-numeric features")
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all() or not np.equal(values, np.floor(values)).all():
        raise ValueError("Features must be finite integers; missing values are forbidden")
    bounds = {"limit_bal": (1, 100_000_000)}
    bounds.update({c: (-2, 9) for c in PAY_STATUS})
    bounds.update({c: (-10_000_000, 100_000_000) for c in BILLS})
    bounds.update({c: (0, 100_000_000) for c in PAYMENTS})
    for column, (low, high) in bounds.items():
        if not frame[column].between(low, high).all():
            raise ValueError(f"Feature out of range: {column}")
    return frame.astype("float64")
