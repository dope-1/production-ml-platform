import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from ml_platform.data.splitting import load_dataset, prepare_dataset, split_frame
from ml_platform.data.validation import FEATURES, model_features, profile_groups, validate_frame
from ml_platform.features.pipeline import FinancialFeatures, make_pipeline


@pytest.fixture
def frame():
    from tests_data import synthetic_frame

    return synthetic_frame()


@pytest.mark.parametrize(
    "damage",
    [
        "missing_column",
        "extra_column",
        "null",
        "infinity",
        "bad_dtype",
        "duplicate_id",
        "invalid_category",
        "bad_age",
        "fraction",
    ],
)
def test_validation_rejects_corruption(frame, damage):
    if damage == "missing_column":
        frame = frame.drop(columns="pay_amt1")
    elif damage == "extra_column":
        frame["future_default"] = 0
    elif damage == "null":
        frame.loc[0, "bill_amt1"] = np.nan
    elif damage == "infinity":
        frame["bill_amt1"] = frame["bill_amt1"].astype(float)
        frame.loc[0, "bill_amt1"] = np.inf
    elif damage == "bad_dtype":
        frame["bill_amt1"] = frame["bill_amt1"].astype(str)
    elif damage == "duplicate_id":
        frame.loc[0, "customer_id"] = frame.loc[1, "customer_id"]
    elif damage == "invalid_category":
        frame.loc[0, "education"] = 99
    elif damage == "bad_age":
        frame.loc[0, "age"] = -1
    else:
        frame["limit_bal"] = frame["limit_bal"].astype(float)
        frame.loc[0, "limit_bal"] = 5.5
    with pytest.raises(ValueError):
        validate_frame(frame)


def test_duplicate_predictors_cannot_cross_splits(frame):
    duplicate = frame.iloc[[0]].copy()
    duplicate["customer_id"] = 999999
    duplicate["default"] = 1 - duplicate["default"]
    duplicate["sex"] = 3 - duplicate["sex"]
    frame = pd.concat([frame, duplicate], ignore_index=True)
    parts = split_frame(frame, 42)
    groups = [set(profile_groups(part)) for part in parts.values()]
    assert not groups[0] & groups[1]
    assert not groups[0] & groups[2]
    assert not groups[1] & groups[2]
    assert sum(len(part) for part in parts.values()) == len(frame)
    reordered = split_frame(frame.sample(frac=1, random_state=7), 42)
    for name in parts:
        pd.testing.assert_frame_equal(parts[name], reordered[name])


def test_checksum_tampering_detected(frame, tmp_path):
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    directory = prepare_dataset(source, tmp_path / "datasets", 42)
    parts, manifest = load_dataset(directory)
    assert sum(len(part) for part in parts.values()) == len(frame)
    assert manifest["raw_sha256"]
    assert prepare_dataset(source, tmp_path / "datasets", 42) == directory
    with (directory / "test.csv").open("a") as stream:
        stream.write("corruption")
    with pytest.raises(ValueError, match="checksum"):
        load_dataset(directory)


def test_feature_contract_excludes_target_and_audit(frame):
    X = model_features(frame)
    assert list(X.columns) == FEATURES
    transformer = FinancialFeatures()
    transformed = transformer.fit_transform(X)
    assert transformed.shape == (len(frame), len(FEATURES) + 3)
    assert np.isfinite(transformed).all()
    with pytest.raises(ValueError, match="schema"):
        transformer.transform(frame)
    with pytest.raises(ValueError, match="schema"):
        transformer.transform(X[X.columns[::-1]])


def test_preprocessing_fit_only_on_training(frame):
    parts = split_frame(frame, 42)
    X = model_features(parts["train"])
    model = make_pipeline(LogisticRegression(max_iter=500), scale=True)
    model.fit(X, parts["train"]["default"])
    train_features = model.named_steps["features"].transform(X)
    np.testing.assert_allclose(model.named_steps["scale"].mean_, train_features.mean(axis=0))
    assert model.named_steps["scale"].n_samples_seen_ == len(X)
    probabilities = model.predict_proba(model_features(parts["test"]))[:, 1]
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
