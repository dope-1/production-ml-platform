"""Milestones 6–8 operations: reference, batch scoring, monitoring and retraining."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ml_platform.core.config import Settings
from ml_platform.core.io import read_json, write_json
from ml_platform.core.training_config import load_config
from ml_platform.data.splitting import load_dataset
from ml_platform.db.models import ApiEvent, MonitoringReport, Prediction
from ml_platform.db.session import create_db_engine
from ml_platform.inference.batch import score_csv
from ml_platform.inference.service import ModelService
from ml_platform.models.registry import Registry, RegistryReader
from ml_platform.monitoring.reference import publish_reference
from ml_platform.monitoring.report import build_report, save_report
from ml_platform.monitoring.simulation import simulate
from ml_platform.retraining.workflow import retrain


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracking-uri", default="http://127.0.0.1:5000")
    parser.add_argument("--control-dir", type=Path, default=Path(".state/registry"))
    parser.add_argument("--config", type=Path, default=Path("configs/training.yaml"))
    commands = parser.add_subparsers(dest="command", required=True)
    reference = commands.add_parser("reference")
    reference.add_argument("--dataset", type=Path)
    batch = commands.add_parser("batch")
    batch.add_argument("--input", type=Path, required=True)
    batch.add_argument("--output", type=Path, required=True)
    monitor = commands.add_parser("monitor")
    monitor.add_argument("--cohort", default="live")
    monitor.add_argument("--hours", type=int, default=24)
    monitor.add_argument("--output", type=Path, default=Path("reports/monitoring/latest.json"))
    demo = commands.add_parser("simulate")
    demo.add_argument("--dataset", type=Path)
    demo.add_argument("--output", type=Path, default=Path("reports/simulation"))
    fit = commands.add_parser("retrain")
    fit.add_argument("--dataset", type=Path)
    fit.add_argument("--labeled-data", type=Path, required=True)
    fit.add_argument("--trigger", choices=["manual", "drift", "performance"], default="manual")
    fit.add_argument("--output", type=Path, default=Path("reports/retraining"))
    purge = commands.add_parser("purge")
    purge.add_argument("--older-than-days", type=int, default=90)
    args = parser.parse_args()
    config = load_config(args.config)
    dataset = getattr(args, "dataset", None)
    if args.command in ("reference", "simulate", "retrain") and dataset is None:
        reader = RegistryReader(args.tracking_uri, config.model_name, args.control_dir)
        pointer = args.control_dir / "datasets" / f"{reader.alias()}.json"
        dataset = Path(
            read_json(pointer if pointer.exists() else Path("data/processed/latest.json"))[
                "directory"
            ]
        )
    if args.command == "reference":
        if dataset is None:
            raise ValueError("A verified dataset is required")
        registry = Registry(args.tracking_uri, config.model_name, args.control_dir)
        print(json.dumps({"reference_sha256": publish_reference(registry, dataset)}))
        return
    engine = create_db_engine(Settings())
    try:
        if args.command == "retrain":
            if dataset is None:
                raise ValueError("A verified dataset is required")
            registry = Registry(args.tracking_uri, config.model_name, args.control_dir)
            result = retrain(
                registry, dataset, args.labeled_data, config, args.output, args.trigger, engine
            )
            print(json.dumps(result, indent=2))
            return
        if args.command == "purge":
            if args.older_than_days < 1:
                raise ValueError("Retention must be at least one day")
            cutoff = datetime.now(UTC) - timedelta(days=args.older_than_days)
            with Session(engine) as session, session.begin():
                for table in (Prediction, ApiEvent, MonitoringReport):
                    session.execute(delete(table).where(table.created_at < cutoff))
            print(json.dumps({"purged_before": cutoff.isoformat()}))
            return
        service = ModelService(
            RegistryReader(args.tracking_uri, config.model_name, args.control_dir)
        )
        snapshot = service.reload()
        if args.command == "batch":
            print(
                json.dumps(score_csv(args.input, args.output, snapshot, engine, config.model_name))
            )
        elif args.command == "monitor":
            report = build_report(engine, snapshot, config.model_name, args.cohort, args.hours)
            save_report(engine, report)
            write_json(args.output, report)
            print(json.dumps(report, indent=2))
        elif args.command == "simulate":
            if dataset is None:
                raise ValueError("A verified dataset is required")
            parts, _ = load_dataset(dataset)
            results = simulate(parts["train"], args.output, snapshot, engine, config.model_name)
            write_json(args.output / "simulation.json", results)
            print(json.dumps({k: r["monitoring"]["drift"]["status"] for k, r in results.items()}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
