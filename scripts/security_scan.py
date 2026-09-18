"""Fail closed on source-security findings, vulnerable dependencies or incomplete audits.

Install requirements-security.txt in a separate venv; runtime ML pins stay untouched.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    os.chdir(Path(__file__).resolve().parents[1])
    output = Path("reports/security")
    output.mkdir(parents=True, exist_ok=True)
    commands = [
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src",
            "--select",
            "S",
            "--output-format",
            "json",
            "--output-file",
            str(output / "source.json"),
        ],
        [
            sys.executable,
            "-m",
            "pip_audit",
            "--strict",
            "--no-deps",
            "--disable-pip",
            "-r",
            "requirements.lock",
            "-r",
            "requirements-dev.lock",
            "--format",
            "json",
            "--progress-spinner",
            "off",
            "--timeout",
            "30",
            "--output",
            str(output / "dependencies.json"),
        ],
    ]
    failed = False
    for command in commands:
        print("+", " ".join(command), flush=True)
        result = subprocess.run(command, check=False)
        failed |= result.returncode != 0
    report = output / "dependencies.json"
    if report.exists():
        audit = json.loads(report.read_text(encoding="utf-8"))
        for package in audit.get("dependencies", []):
            seen: set[str] = set()
            for finding in package.get("vulns", []):
                if finding["id"] in seen:
                    continue
                seen.add(finding["id"])
                fixes = ", ".join(finding.get("fix_versions", [])) or "no fix listed"
                print(f"{package['name']}=={package['version']}: {finding['id']}; fixes: {fixes}")
    if failed:
        raise SystemExit("Security checks failed. Review reports/security; do not bypass the gate.")
    print("Source and dependency security checks passed.")


if __name__ == "__main__":
    main()
