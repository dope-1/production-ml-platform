"""One command to verify Milestones 1–5 against running Docker services.

Runs real software checks first, then the full UCI training/registry lifecycle.
No synthetic data fallback; rejection is a valid outcome and preserves champion.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(*arguments: str) -> None:
    print("+", " ".join(arguments), flush=True)
    subprocess.run(arguments, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri", default="http://127.0.0.1:5000")
    parser.add_argument(
        "--resume-registry",
        action="store_true",
        help="Resume an existing completed training run; skip software checks and retraining.",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    os.environ["TEST_DATABASE"] = "1"
    if not args.resume_registry:
        run(sys.executable, "-m", "ruff", "check", ".")
        run(sys.executable, "-m", "ruff", "format", "--check", ".")
        run(sys.executable, "-m", "mypy")
        run(sys.executable, "-m", "pytest", "--cov=ml_platform", "--cov-report=term-missing")
        run(sys.executable, "scripts/verify_compose.py")
        command = (sys.executable, "-m", "ml_platform.cli", "--tracking-uri", args.tracking_uri)
        run(*command, "prepare")
        run(*command, "train")
    from ml_platform.core.io import read_json, write_json
    from ml_platform.core.training_config import load_config
    from ml_platform.models.registry import Registry

    config = load_config(Path("configs/training.yaml"))
    registry = Registry(args.tracking_uri, config.model_name, Path(".state/registry"))
    run_id = read_json(Path("reports/model/latest.json"))["run_id"]
    version = registry.register(run_id)
    result = registry.promote(version, config.gate)
    if result["decision"] in ("PROMOTE", "UNCHANGED"):
        from ml_platform.data.splitting import load_dataset
        from ml_platform.data.validation import model_features

        dataset = Path(read_json(Path("data/processed/latest.json"))["directory"])
        parts, _ = load_dataset(dataset)
        model, evidence = registry.load_production()
        probabilities = model.predict_proba(model_features(parts["validation"]).iloc[:3])[:, 1]
        assert all(0 <= value <= 1 for value in probabilities)
        result["artifact_load_verified"] = True
        result["production_version"] = evidence["model_version"]
    write_json(Path("reports/batch-verification.json"), result)
    print(json.dumps(result, indent=2))
    if args.resume_registry:
        print("Registry resume complete; prior software checks were not rerun.")
    else:
        print("Software verification complete. Review the promotion decision above.")
    print("MLflow UI: " + args.tracking_uri)


if __name__ == "__main__":
    main()
