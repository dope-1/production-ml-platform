"""Upgrade this checkout and verify Batch 1 using its existing Python 3.12 venv."""

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Run this script with the project's Python 3.12 virtual environment.")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    commands = [
        [sys.executable, "-m", "pip", "install", "-r", "requirements-dev.lock"],
        [sys.executable, "-m", "pip", "install", "--no-deps", "-e", "."],
        ["docker", "compose", "config", "--quiet"],
        ["docker", "compose", "up", "--build", "--detach", "--wait", "--wait-timeout", "300"],
        [sys.executable, "scripts/verify_batch.py"],
    ]
    # Bootstrap health checks while no approved model/reference exists yet.
    environment = {**os.environ, "ML_COMPOSE_INFERENCE_ENABLED": "false"}
    for command in commands:
        print("+", " ".join(command), flush=True)
        subprocess.run(command, check=True, env=environment)


if __name__ == "__main__":
    main()
