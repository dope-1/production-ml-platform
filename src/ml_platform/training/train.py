import importlib.metadata
import platform
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import mlflow
import mlflow.sklearn
import numpy as np
from mlflow.models import infer_signature
from sklearn.model_selection import StratifiedGroupKFold, cross_val_score

from ml_platform.core.io import digest, fingerprint, write_json
from ml_platform.core.training_config import TrainingConfig
from ml_platform.data.splitting import load_dataset
from ml_platform.data.validation import (
    FEATURES,
    SCHEMA_HASH,
    TARGET,
    model_features,
    profile_groups,
)
from ml_platform.training.evaluate import (
    evaluate,
    latency,
    plot_report,
    select_threshold,
    subgroups,
)
from ml_platform.training.explain import explain_model
from ml_platform.training.tuning import candidates


def code_identity() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    code_hash = fingerprint(
        {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*.py"))}
    )
    try:
        git = shutil.which("git")
        if git is None:
            raise FileNotFoundError("git unavailable")
        # Resolved local git executable and constant arguments; no shell or user input.
        commit = subprocess.check_output(  # noqa: S603
            [git, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        status = subprocess.check_output([git, "status", "--porcelain"], text=True)  # noqa: S603
        dirty = bool(status.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "uncommitted", True
    return {"git_commit": commit, "git_dirty": str(dirty), "source_sha256": code_hash}


def train(
    dataset: Path,
    config: TrainingConfig,
    tracking_uri: str,
    output: Path,
    *,
    evaluate_test: bool = True,
) -> dict[str, Any]:
    partitions, manifest = load_dataset(dataset)
    X = model_features(partitions["train"])
    y = partitions["train"][TARGET]
    val = partitions["validation"]
    Xv, yv = model_features(val), val[TARGET]
    identity = code_identity()
    versions = {
        name: importlib.metadata.version(name)
        for name in (
            "scikit-learn",
            "lightgbm",
            "mlflow",
            "numpy",
            "pandas",
            "shap",
            "production-ml-platform",
        )
    }
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(config.experiment)
    cv = list(
        StratifiedGroupKFold(
            n_splits=config.cv_folds, shuffle=True, random_state=config.seed
        ).split(X, y, profile_groups(partitions["train"]))
    )
    trials: list[dict[str, Any]] = []
    with mlflow.start_run(run_name="training-pipeline") as parent:
        parent_id = parent.info.run_id
        mlflow.set_tags(
            {
                **identity,
                "dataset_version": manifest["dataset_version"],
                "kind": "training-pipeline",
            }
        )
        mlflow.log_dict(manifest, "dataset.json")
        mlflow.log_dict(config.model_dump(), "configuration.json")
        mlflow.log_dict(versions, "dependencies.json")
        for name, params, model in candidates(config.seed):
            with mlflow.start_run(run_name=name, nested=True) as run:
                start = perf_counter()
                scores = cross_val_score(
                    model, X, y, cv=cv, scoring="average_precision", n_jobs=1, error_score="raise"
                )
                model.fit(X, y)
                training_seconds = perf_counter() - start
                probabilities = model.predict_proba(Xv)[:, 1]
                threshold, thresholds = select_threshold(
                    yv, probabilities, config.threshold_minimum_recall, config.threshold_grid_size
                )
                metrics = evaluate(yv, probabilities, threshold)
                mlflow.log_metrics(latency(model, Xv, config.latency_repeats))
                mlflow.log_params(
                    {
                        "algorithm": name,
                        **params,
                        "split_seed": config.seed,
                        "schema_hash": SCHEMA_HASH,
                        "dataset_version": manifest["dataset_version"],
                    }
                )
                mlflow.log_metrics({f"validation_{key}": value for key, value in metrics.items()})
                mlflow.log_metrics(
                    {
                        "cv_pr_auc_mean": float(scores.mean()),
                        "cv_pr_auc_std": float(scores.std()),
                        "training_seconds": training_seconds,
                        "threshold": threshold,
                    }
                )
                mlflow.set_tags(identity)
                mlflow.log_dict({"thresholds": thresholds}, "threshold_tradeoffs.json")
                trial = {
                    "algorithm": name,
                    "parameters": params,
                    "run_id": run.info.run_id,
                    "cv_pr_auc_mean": float(scores.mean()),
                    "cv_pr_auc_std": float(scores.std()),
                    "validation": metrics,
                    "threshold": threshold,
                    "training_seconds": training_seconds,
                }
                trials.append({**trial, "model": model})
                with tempfile.TemporaryDirectory() as temporary:
                    folder = Path(temporary)
                    plot_report(yv, probabilities, threshold, folder)
                    explain_model(model, X.iloc[:100], Xv.iloc[: config.shap_samples], folder)
                    mlflow.log_artifacts(str(folder), "validation_report")
                mlflow.log_dict(manifest, "dataset.json")
                mlflow.log_dict(config.model_dump(), "configuration.json")
                mlflow.log_dict(versions, "dependencies.json")
                # Preserve the run/model artifact contract used by the verified registry.
                # MLflow 3 log_model stores models outside the run artifact directory.
                with tempfile.TemporaryDirectory() as temporary:
                    folder = Path(temporary) / "model"
                    mlflow.sklearn.save_model(
                        model,
                        str(folder),
                        serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
                        signature=infer_signature(X.iloc[:5], model.predict(X.iloc[:5])),
                        input_example=X.iloc[:2],
                        code_paths=[str(Path(__file__).resolve().parents[1])],
                        pip_requirements=[
                            f"{n}=={v}"
                            for n, v in versions.items()
                            if n != "production-ml-platform"
                        ],
                    )
                    mlflow.log_artifacts(str(folder), "model")
        # Selection uses train-only CV; <=0.005 AP difference prefers the earlier,
        # simpler algorithm. Test data have not been scored or used for selection.
        best_score = max(t["cv_pr_auc_mean"] for t in trials)
        selected = next(
            t for t in trials if t["cv_pr_auc_mean"] >= best_score - config.selection_ap_tolerance
        )
        model = selected.pop("model")
        clean_trials = [{k: v for k, v in trial.items() if k != "model"} for trial in trials]
        test = partitions["test"]
        test_metrics: dict[str, Any] = {"status": "not_evaluated_in_retraining"}
        if evaluate_test:
            test_probabilities = model.predict_proba(model_features(test))[:, 1]
            test_metrics = evaluate(test[TARGET], test_probabilities, selected["threshold"])
        validation_probabilities = model.predict_proba(Xv)[:, 1]
        fairness = subgroups(
            val, validation_probabilities, selected["threshold"], config.gate.min_group_positives
        )
        report = {
            "created_at": datetime.now(UTC).isoformat(),
            "parent_run_id": parent_id,
            "run_id": selected["run_id"],
            "algorithm": selected["algorithm"],
            "parameters": selected["parameters"],
            "threshold": selected["threshold"],
            "cv_pr_auc_mean": selected["cv_pr_auc_mean"],
            "cv_pr_auc_std": selected["cv_pr_auc_std"],
            "validation": selected["validation"],
            "test": test_metrics,
            "subgroups": fairness,
            "schema_hash": SCHEMA_HASH,
            "feature_implementation_sha256": digest(
                Path(__file__).resolve().parents[1] / "features/pipeline.py"
            ),
            "dataset_version": manifest["dataset_version"],
            "validation_sha256": manifest["splits"]["validation"]["sha256"],
            "test_sha256": manifest["splits"]["test"]["sha256"],
            "identity": identity,
            "dependencies": versions,
            "configuration": config.model_dump(),
            "latency_environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "processor": platform.processor(),
                "repeats": config.latency_repeats,
            },
            **latency(model, Xv, config.latency_repeats),
            "checks": {
                "finite_features": bool(np.isfinite(model[:-1].transform(Xv)).all()),
                "probability_bounds": bool(
                    ((validation_probabilities >= 0) & (validation_probabilities <= 1)).all()
                ),
                "schema": list(X.columns) == FEATURES,
                "reload_equivalence": False,
            },
        }
        output = output / parent_id
        output.mkdir(parents=True)
        write_json(
            output / "comparison.json",
            {"trials": clean_trials, "selected_run_id": report["run_id"]},
        )
        if evaluate_test:
            plot_report(test[TARGET], test_probabilities, selected["threshold"], output / "test")
        # Reload only the artifact this process just logged to the trusted registry.
        with tempfile.TemporaryDirectory() as temporary:
            local_model = Path(
                mlflow.artifacts.download_artifacts(
                    run_id=report["run_id"], artifact_path="model", dst_path=temporary
                )
            )
            hashes = {
                str(p.relative_to(local_model)).replace("\\", "/"): digest(p)
                for p in sorted(local_model.rglob("*"))
                if p.is_file()
            }
            report["artifact_hashes"] = hashes
            report["model_bytes"] = sum(
                p.stat().st_size for p in local_model.rglob("*") if p.is_file()
            )
            loaded = mlflow.sklearn.load_model(str(local_model))
            report["checks"]["reload_equivalence"] = bool(
                np.allclose(
                    loaded.predict_proba(Xv.iloc[:16]),
                    model.predict_proba(Xv.iloc[:16]),
                    atol=1e-12,
                )
            )
        if not all(report["checks"].values()):
            raise ValueError("Candidate artifact compatibility check failed")
        write_json(output / "candidate.json", report)
        mlflow.log_artifacts(str(output), "pipeline_report")
        mlflow.log_dict({"selected_run_id": report["run_id"]}, "selection.json")
    # Evidence belongs to the selected model run, not just its parent.
    client = mlflow.MlflowClient(tracking_uri=tracking_uri)
    client.log_artifact(report["run_id"], str(output / "candidate.json"), "evidence")
    client.set_tag(report["run_id"], "candidate_evidence_sha256", digest(output / "candidate.json"))
    client.set_tag(report["run_id"], "pipeline", "controlled-training-v1")
    client.set_tag(report["run_id"], "schema_hash", SCHEMA_HASH)
    write_json(
        output.parent / "latest.json",
        {
            "report": str(output / "candidate.json"),
            "run_id": report["run_id"],
            "parent_run_id": parent_id,
        },
    )
    return report
