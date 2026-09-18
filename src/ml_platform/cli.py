"""CLI for the local training and controlled registry workflow."""

import argparse
import json
import os
from pathlib import Path

from ml_platform.core.io import read_json, write_json
from ml_platform.core.training_config import load_config
from ml_platform.data.ingestion import download
from ml_platform.data.splitting import prepare_dataset
from ml_platform.models.registry import Registry
from ml_platform.training.train import train


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracking-uri", default=os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    )
    parser.add_argument("--config", type=Path, default=Path("configs/training.yaml"))
    parser.add_argument("--control-dir", type=Path, default=Path(".state/registry"))
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, default=Path("data/raw/uci-default.zip"))
    fit = commands.add_parser("train")
    fit.add_argument("--dataset", type=Path)
    register = commands.add_parser("register")
    register.add_argument("--run-id")
    promote = commands.add_parser("promote")
    promote.add_argument("--version", required=True)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--version", required=True)
    rollback.add_argument("--reason", required=True)
    commands.add_parser("status")
    commands.add_parser("reconcile")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == "prepare":
        source = args.source
        if source == Path("data/raw/uci-default.zip"):
            checksum = read_json(Path("configs/dataset.json"))["sha256"]
            source = download(source, checksum)
        dataset = prepare_dataset(source, Path("data/processed"), config.seed)
        write_json(Path("data/processed/latest.json"), {"directory": str(dataset)})
        print(json.dumps({"dataset": str(dataset)}))
        return
    if args.command == "train":
        dataset = args.dataset or Path(read_json(Path("data/processed/latest.json"))["directory"])
        report = train(dataset, config, args.tracking_uri, Path("reports/model"))
        print(
            json.dumps(
                {
                    "run_id": report["run_id"],
                    "algorithm": report["algorithm"],
                    "test": report["test"],
                },
                indent=2,
            )
        )
        return
    registry = Registry(args.tracking_uri, config.model_name, args.control_dir)
    if args.command == "register":
        run_id = args.run_id or read_json(Path("reports/model/latest.json"))["run_id"]
        print(json.dumps({"version": registry.register(run_id)}))
    elif args.command == "promote":
        print(json.dumps(registry.promote(args.version, config.gate), indent=2))
    elif args.command == "rollback":
        print(json.dumps(registry.rollback(args.version, config.gate, args.reason), indent=2))
    elif args.command == "reconcile":
        print(json.dumps(registry.reconcile(), indent=2))
    else:
        print(
            json.dumps(
                {"candidate": registry.alias("candidate"), "production": registry.alias()}, indent=2
            )
        )


if __name__ == "__main__":
    main()
