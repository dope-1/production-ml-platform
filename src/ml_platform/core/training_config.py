from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class GateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_roc_auc: float = Field(default=0.65, ge=0, le=1)
    minimum_pr_auc: float = Field(default=0.30, ge=0, le=1)
    minimum_recall: float = Field(default=0.60, ge=0, le=1)
    maximum_brier: float = Field(default=0.23, ge=0, le=1)
    max_latency_ms: float = Field(default=100, gt=0)
    max_model_bytes: int = Field(default=50_000_000, gt=0)
    regression_tolerance: float = Field(default=0.01, ge=0, le=0.1)
    minimum_improvement: float = Field(default=0.001, ge=0, le=0.1)
    max_cv_std: float = Field(default=0.10, ge=0, le=1)
    # A diagnostic guardrail, not a claim of fairness.
    max_sex_recall_gap: float = Field(default=0.20, ge=0, le=1)
    min_group_positives: int = Field(default=20, ge=1)


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = Field(default=42, ge=0)
    cv_folds: int = Field(default=3, ge=2, le=5)
    threshold_minimum_recall: float = Field(default=0.65, gt=0, le=1)
    threshold_grid_size: int = Field(default=99, ge=10, le=999)
    shap_samples: int = Field(default=80, ge=1, le=500)
    latency_repeats: int = Field(default=30, ge=5, le=1000)
    selection_ap_tolerance: float = Field(default=0.005, ge=0, le=0.05)
    experiment: str = "credit-default-v1"
    model_name: str = Field(default="credit-default", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    gate: GateConfig = GateConfig()


def load_config(path: Path) -> TrainingConfig:
    return TrainingConfig.model_validate(yaml.safe_load(path.read_text()))
