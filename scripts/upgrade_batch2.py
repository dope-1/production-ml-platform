"""Windows/VS Code one-command upgrade for the already verified Batch 1 checkout."""

import os
import secrets
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use the project's Python 3.12 virtual environment")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    env = root / ".env"
    if not env.exists():
        raise SystemExit("Keep your existing Batch 1 .env and Docker volumes before upgrading")
    lines = env.read_text(encoding="utf-8-sig").splitlines()
    existing = next(
        (
            line.split("=", 1)[1].strip()
            for line in lines
            if line.strip().startswith("ML_ADMIN_KEY=")
        ),
        "",
    )
    if len(existing.strip("\"'")) < 32:
        lines = [line for line in lines if not line.strip().startswith("ML_ADMIN_KEY=")]
        lines.append("ML_ADMIN_KEY=" + secrets.token_urlsafe(32))
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("Created a local admin key in .env; it is not printed or included in reports.")
    commands = [
        [sys.executable, "-m", "pip", "install", "-r", "requirements-dev.lock"],
        [sys.executable, "-m", "pip", "install", "--no-deps", "-e", "."],
        ["docker", "compose", "config", "--quiet"],
        ["docker", "compose", "build"],
        [
            "docker",
            "compose",
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "300",
            "postgres",
            "mlflow",
        ],
        ["docker", "compose", "run", "--rm", "migrate"],
        [sys.executable, "-m", "ml_platform.ops", "reference"],
        [
            "docker",
            "compose",
            "up",
            "--detach",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "300",
            "ml-api",
        ],
        [sys.executable, "scripts/verify_batch2.py"],
    ]
    for command in commands:
        print("+", " ".join(command), flush=True)
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
