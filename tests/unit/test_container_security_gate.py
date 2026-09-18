import copy
import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "container_security_gate", ROOT / "scripts/container_security_gate.py"
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.fixture
def sample():
    policy = json.loads((ROOT / "configs/container-exceptions.json").read_text())
    report = {
        "SchemaVersion": 2,
        "ArtifactType": "container_image",
        "Metadata": {"OS": policy["os"].copy()},
        "Results": [
            {
                "Class": "os-pkgs",
                "Type": "debian",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": cve,
                        "PkgName": package,
                        "InstalledVersion": version,
                        "Severity": "HIGH",
                        "Status": "affected",
                    }
                    for cve, packages in policy["findings"].items()
                    for package, version in packages.items()
                ],
            },
            {"Class": "lang-pkgs", "Type": "python-pkg"},
        ],
    }
    return report, policy


def test_approved_exact_findings_and_expiry(sample):
    report, policy = sample
    result = gate.evaluate(report, policy, date(2026, 10, 2))
    assert result["status"] == "accepted_with_exceptions"
    assert len(result["accepted"]) == 44
    assert not result["blocked"]
    assert len(gate.evaluate(report, policy, date(2026, 10, 3))["blocked"]) == 44
    policy["approved"] = False
    assert len(gate.evaluate(report, policy, date(2026, 9, 18))["blocked"]) == 44


@pytest.mark.parametrize(
    "changes",
    [
        {"Severity": "CRITICAL"},
        {"FixedVersion": "patched"},
        {"InstalledVersion": "new-version"},
        {"VulnerabilityID": "CVE-new"},
        {"PkgName": "unapproved-package"},
        {"Status": "fixed"},
    ],
)
def test_changed_or_fixable_findings_block(sample, changes):
    report, policy = sample
    report["Results"][0]["Vulnerabilities"][0].update(changes)
    result = gate.evaluate(report, policy, date(2026, 9, 18))
    assert result["status"] == "blocked"
    assert len(result["blocked"]) == 1


def test_python_findings_and_changed_os_cannot_use_exception(sample):
    report, policy = sample
    report["Results"][1]["Vulnerabilities"] = [
        copy.deepcopy(report["Results"][0]["Vulnerabilities"][0])
    ]
    assert len(gate.evaluate(report, policy, date(2026, 9, 18))["blocked"]) == 1
    report["Metadata"]["OS"]["Name"] = "new-release"
    assert len(gate.evaluate(report, policy, date(2026, 9, 18))["blocked"]) == 45


@pytest.mark.parametrize("missing", ["SchemaVersion", "ArtifactType", "Results"])
def test_incomplete_report_fails(sample, missing):
    report, policy = sample
    del report[missing]
    with pytest.raises(ValueError):
        gate.evaluate(report, policy, date(2026, 9, 18))


def test_empty_scans_fail_but_clean_complete_scan_passes(sample):
    report, policy = sample
    report["Results"][0]["Vulnerabilities"] = []
    assert gate.evaluate(report, policy, date(2026, 10, 3))["status"] == "clean"
    report["Results"].pop()
    with pytest.raises(ValueError, match="Python"):
        gate.evaluate(report, policy, date(2026, 9, 18))
