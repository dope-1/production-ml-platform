"""Apply the CI security update locally, with an offline MLflow volume backup first.

Run with the project's existing Python 3.12 virtual environment. Stop other local
training/registry commands before running this script. A migration failure leaves
MLflow and the API stopped; it never deletes volumes or silently resets a model.
"""

import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path


def run(*args: str) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def capture(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def verify_archive(path: Path) -> None:
    found_database = False
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if member.name == "mlflow/mlflow.db":
                found_database = member.isfile() and member.size > 0
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError("Backup contains an unreadable file")
                with stream:
                    while stream.read(1024 * 1024):
                        pass
    if not found_database:
        raise ValueError("Backup is missing the existing MLflow database")


def container_image_details(container: str) -> tuple[str, str]:
    old_image_id = capture("docker", "inspect", "--format", "{{.Image}}", container)
    image_reference = capture("docker", "inspect", "--format", "{{.Config.Image}}", container)
    if not old_image_id or not image_reference:
        raise ValueError("Could not identify the existing MLflow container image")
    return old_image_id, image_reference


def main() -> None:
    if sys.version_info[:2] != (3, 12) or sys.prefix == sys.base_prefix:
        raise SystemExit("Use .venv/Scripts/python.exe (Python 3.12).")
    os.chdir(Path(__file__).resolve().parents[1])
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
    compose = ("docker", "compose")
    run(*compose, "config", "--quiet")
    run(sys.executable, "scripts/verify_milestone9.py")
    before = json.loads(Path("reports/milestone-9-verification.json").read_text())
    if before.get("model_version") is None:
        raise SystemExit("This upgrade expects the existing verified Milestone 9 model.")
    container = capture(*compose, "ps", "--quiet", "mlflow")
    if not container or "\n" in container:
        raise SystemExit("Expected one running local MLflow container.")
    old_image, backup_image = container_image_details(container)
    mounts = json.loads(capture("docker", "inspect", "--format", "{{json .Mounts}}", container))
    volumes = [m["Name"] for m in mounts if m["Type"] == "volume" and m["Destination"] == "/mlflow"]
    if len(volumes) != 1:
        raise SystemExit("Expected the existing named MLflow volume mounted at /mlflow.")

    # Build and validate the new software before stopping healthy services.
    run(sys.executable, "-m", "pip", "install", "-r", "requirements-dev.lock")
    run(sys.executable, "-m", "pip", "install", "--no-deps", "-e", ".")
    run(sys.executable, "-m", "pip", "check")
    run(sys.executable, "-m", "ruff", "check", ".")
    run(sys.executable, "-m", "ruff", "format", "--check", ".")
    run(sys.executable, "-m", "mypy")
    run(sys.executable, "-m", "pytest", "-q")
    run(*compose, "build", "--pull")
    # Config.Image is the stable Compose tag. The rebuild moves that tag to the
    # new image, whereas the old immutable image ID may be removed immediately.
    backup_image_id = capture("docker", "image", "inspect", "--format", "{{.Id}}", backup_image)
    if not backup_image_id:
        raise SystemExit("The rebuilt MLflow image is unavailable; services were not stopped.")

    backup = Path(".state/backups") / datetime.now(UTC).strftime("security-%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True, exist_ok=False)
    run(*compose, "stop", "ml-api", "mlflow")
    shutil.copytree(".state/registry", backup / "registry")
    (backup / "metadata.json").write_text(
        json.dumps(
            {
                "old_mlflow_image": old_image,
                "backup_image": backup_image,
                "backup_image_id": backup_image_id,
                "volume": volumes[0],
                "before": before,
            },
            indent=2,
        )
        + "\n"
    )
    archive = backup / "mlflow.tar.gz"
    print(f"Backing up the stopped MLflow volume to {archive}", flush=True)
    backup_code = (
        "import sys,tarfile; "
        "t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); "
        "t.add('/mlflow',arcname='mlflow'); t.close()"
    )
    with archive.open("xb") as output:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--mount",
                f"type=volume,source={volumes[0]},target=/mlflow,readonly",
                backup_image,
                "python",
                "-c",
                backup_code,
            ],
            stdout=output,
            check=True,
        )
        output.flush()
        os.fsync(output.fileno())
    verify_archive(archive)
    print(f"Verified backup: {backup.resolve()}", flush=True)
    run(
        *compose,
        "run",
        "--rm",
        "--no-deps",
        "mlflow",
        "mlflow",
        "db",
        "upgrade",
        "sqlite:////mlflow/mlflow.db",
    )
    run(*compose, "up", "--detach", "--no-deps", "--wait", "--wait-timeout", "300", "mlflow")
    run(*compose, "up", "--detach", "--no-deps", "--wait", "--wait-timeout", "300", "ml-api")
    run(sys.executable, "scripts/verify_milestone9.py")
    after = json.loads(Path("reports/milestone-9-verification.json").read_text())
    if after["model_version"] != before["model_version"]:
        raise SystemExit("Serving model changed unexpectedly; review the saved backup metadata.")
    print(f"Local upgrade verified; serving model remains v{after['model_version']}.")
    print("GitHub security scans are still required; this is not an all-clear from Trivy.")


if __name__ == "__main__":
    main()
