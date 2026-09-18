"""Fail closed except for explicitly approved, exact, unexpired Debian findings."""

import json
from datetime import UTC, datetime
from pathlib import Path


def evaluate(report, policy, today):
    if report.get("SchemaVersion") != 2 or report.get("ArtifactType") != "container_image":
        raise ValueError("Unexpected or incomplete Trivy image report")
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise ValueError("Missing image scan results")
    if not any(r.get("Class") == "os-pkgs" for r in results):
        raise ValueError("Missing operating-system scan results")
    if not any(r.get("Type") == "python-pkg" for r in results):
        raise ValueError("Missing Python scan results")
    expires = datetime.strptime(policy["expires_on"], "%Y-%m-%d").date()
    active = policy.get("approved") is True and today <= expires
    expected_os = report.get("Metadata", {}).get("OS") == policy["os"]
    accepted, blocked = [], []
    for result in results:
        for finding in result.get("Vulnerabilities", []):
            severity = finding["Severity"]
            if severity not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("Invalid vulnerability severity")
            if severity not in {"HIGH", "CRITICAL"}:
                continue
            item = {
                "id": finding["VulnerabilityID"],
                "package": finding["PkgName"],
                "version": finding["InstalledVersion"],
            }
            known = policy["findings"].get(item["id"], {})
            allowed = (
                active
                and expected_os
                and result.get("Class") == "os-pkgs"
                and result.get("Type") == "debian"
                and severity == "HIGH"
                and not finding.get("FixedVersion")
                and finding.get("Status") in {"affected", "fix_deferred"}
                and known.get(item["package"]) == item["version"]
            )
            (accepted if allowed else blocked).append(item)
    return {
        "status": "blocked" if blocked else "accepted_with_exceptions" if accepted else "clean",
        "expires_on": policy["expires_on"],
        "accepted": accepted,
        "blocked": blocked,
    }


def main():
    report = json.loads(Path("reports/security/image.json").read_text())
    policy = json.loads(Path("configs/container-exceptions.json").read_text())
    result = evaluate(report, policy, datetime.now(UTC).date())
    Path("reports/security/container-gate.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["blocked"]:
        raise SystemExit("Unapproved, changed, fixable, or expired findings block this image.")
    if result["accepted"]:
        print(
            "::warning::Known HIGH findings remain under temporary risk acceptance; "
            "not production clearance."
        )


if __name__ == "__main__":
    main()
