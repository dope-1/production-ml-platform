"""Upgrade only the API/security layer of an already verified Milestone 8 checkout."""

import argparse
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def configure_keys(path: Path) -> None:
    """Preserve DB credentials and existing strong keys; atomically update local auth."""
    if not path.is_file():
        raise SystemExit(
            "Keep your existing .env. For a fresh install, create it from .env.example."
        )
    original = path.read_text(encoding="utf-8-sig")
    updates = {"ML_AUTH_ENABLED": "true"}
    for key in ("ML_API_KEY", "ML_ADMIN_KEY"):

        def value(name: str) -> str:
            found = re.findall(rf"^\s*(?:export\s+)?{name}\s*=(.*)$", original, re.MULTILINE)
            if not found:
                return ""
            pieces = shlex.split(found[-1], comments=True)
            return pieces[0] if pieces else ""

        if value(key + "_FILE"):
            continue
        current = value(key)
        if len(current) < 32:
            updates[key] = secrets.token_urlsafe(32)
    names = "|".join(updates)
    lines = []
    written = set()
    for line in original.splitlines():
        match = re.match(rf"^\s*(?:export\s+)?({names})\s*=", line)
        if match:
            key = match.group(1)
            if key not in written:
                lines.append(f"{key}={updates[key]}")
                written.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in updates.items() if key not in written)
    updated = "\n".join(lines) + "\n"
    if updated == original:
        return
    # Same-directory atomic replace; mkstemp creates a private file on POSIX.
    descriptor, name = tempfile.mkstemp(prefix=".env-update-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--configure-only", action="store_true", help="Set local keys without Docker."
    )
    modes.add_argument(
        "--init-ci", action="store_true", help="Create NEW ephemeral CI configuration."
    )
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use the project's existing Python 3.12 virtual environment")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    env = root / ".env"
    if args.init_ci:
        # Exclusive creation prevents accidentally replacing an initialized DB's credentials.
        with env.open("x", encoding="utf-8") as stream:
            for key in ("ML_DB_PASSWORD", "ML_API_KEY", "ML_ADMIN_KEY"):
                stream.write(key + "=" + secrets.token_urlsafe(32) + "\n")
            stream.write("ML_AUTH_ENABLED=true\nML_ENVIRONMENT=testing\n")
        env.chmod(0o600)
        print("Created ephemeral CI configuration; credentials are not printed.")
        return
    configure_keys(env)
    print("Authentication enabled. Existing strong keys and database credentials retained.")
    if args.configure_only:
        return
    from ml_platform.core.config import Settings

    settings = Settings()
    if not settings.auth_enabled:
        raise SystemExit("Remove the ML_AUTH_ENABLED=false override from this terminal, then retry")
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    commands = [
        [sys.executable, "-m", "pip", "install", "--no-deps", "-e", "."],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "ruff", "check", "src", "--select", "S"],
        [sys.executable, "-m", "mypy"],
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/unit/test_security.py",
            "tests/unit/test_milestone9_scripts.py",
            "tests/unit/test_config.py",
            "tests/unit/test_api.py",
            "tests/unit/test_inference_monitoring.py",
            "-q",
        ],
        ["docker", "compose", "config", "--quiet"],
        ["docker", "compose", "build", "ml-api"],
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
        [sys.executable, "scripts/verify_milestone9.py"],
    ]
    for command in commands:
        print("+", " ".join(command), flush=True)
        subprocess.run(command, check=True)
    print("Milestone 9 local checks passed. Advisory and image scans run in GitHub Actions.")
    print("Open .env in VS Code, copy ML_API_KEY into the dashboard's API key field, then Connect.")
    print("Dashboard: http://127.0.0.1:8000/api/v1/dashboard (select verification or benchmark).")


if __name__ == "__main__":
    main()
