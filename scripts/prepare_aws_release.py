"""Stage a verified local model release for the AWS Milestone 10 deployment.

This command is deliberately offline: it neither logs in to AWS nor creates resources.
The staged image context contains only the registry controller and RDS trust bundle;
the MLflow backup is extracted separately for an explicit S3 upload.
"""

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def copy_stream(source: BinaryIO, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)


def extract_mlflow_backup(archive_path: Path, destination: Path) -> None:
    found_database = False
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or not path.parts
                or path.parts[0] != "mlflow"
                or any(part in {"", ".", ".."} for part in path.parts)
            ):
                raise ValueError(f"Unsafe backup member: {member.name}")
            relative = Path(*path.parts[1:])
            if not relative.parts:
                if not member.isdir():
                    raise ValueError("The mlflow archive root must be a directory")
                continue
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"Backup links and special files are forbidden: {member.name}")
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Unreadable backup member: {member.name}")
            with source:
                copy_stream(source, target)
            if relative.as_posix() == "mlflow.db" and member.size > 0:
                found_database = True
    if not found_database:
        raise ValueError("Backup is missing a non-empty mlflow/mlflow.db")


def validate_registry(registry: Path, expected_model_name: str) -> None:
    identity_path = registry / "identity.json"
    audit_path = registry / "audit.jsonl"
    if not identity_path.is_file() or not audit_path.is_file():
        raise ValueError("Backup registry is missing identity.json or audit.jsonl")
    if (registry / "pending.json").exists():
        raise ValueError("Registry contains an unresolved pending operation")
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if identity.get("model_name") != expected_model_name:
        raise ValueError("Backup registry belongs to a different model")
    if not audit_path.read_text(encoding="utf-8").strip():
        raise ValueError("Backup registry audit log is empty")


def validate_ca_bundle(path: Path, expected_sha256: str) -> None:
    if sha256(path) != expected_sha256.lower():
        raise ValueError("RDS CA bundle SHA-256 does not match --ca-sha256")
    text = path.read_text(encoding="ascii")
    if "-----BEGIN CERTIFICATE-----" not in text or "-----END CERTIFICATE-----" not in text:
        raise ValueError("RDS CA bundle does not contain a PEM certificate")


def hashes_under(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "release-manifest.json"
    }


def stage_release(
    backup: Path,
    ca_bundle: Path,
    ca_sha256: str,
    output: Path,
    base_image: str,
    expected_model_version: str,
    expected_model_name: str,
) -> dict[str, object]:
    metadata_path = backup / "metadata.json"
    archive_path = backup / "mlflow.tar.gz"
    registry = backup / "registry"
    if output.exists():
        raise ValueError(f"Output already exists; choose a new path: {output}")
    if not metadata_path.is_file() or not archive_path.is_file() or not registry.is_dir():
        raise ValueError("Backup must contain metadata.json, mlflow.tar.gz and registry/")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    actual_version = str(metadata.get("before", {}).get("model_version", ""))
    if actual_version != expected_model_version:
        observed = actual_version or "missing"
        raise ValueError(f"Backup model version is {observed}, expected {expected_model_version}")
    validate_registry(registry, expected_model_name)
    validate_ca_bundle(ca_bundle, ca_sha256)

    image = output / "image"
    image.mkdir(parents=True)
    shutil.copytree(registry, image / "registry-control")
    shutil.copy2(ca_bundle, image / "aws-rds-global-bundle.pem")
    template = Path(__file__).resolve().parents[1] / "deploy/aws/release.Dockerfile"
    shutil.copy2(template, image / "Dockerfile")
    extract_mlflow_backup(archive_path, output / "mlflow")

    manifest: dict[str, object] = {
        "schema_version": 1,
        "model_name": expected_model_name,
        "model_version": expected_model_version,
        "base_image": base_image,
        "source_backup": backup.name,
        "source_archive_sha256": sha256(archive_path),
        "rds_ca_bundle_sha256": ca_sha256.lower(),
        "files": hashes_under(output),
    }
    (output / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--backup", type=Path, required=True)
    result.add_argument("--ca-bundle", type=Path, required=True)
    result.add_argument("--ca-sha256", required=True)
    result.add_argument("--output", type=Path, default=Path(".state/aws-release"))
    result.add_argument("--base-image", default="production-ml-platform-ml-api:latest")
    result.add_argument("--model-version", default="1")
    result.add_argument("--model-name", default="credit-default")
    return result


def main() -> None:
    args = parser().parse_args()
    manifest = stage_release(
        args.backup.resolve(),
        args.ca_bundle.resolve(),
        args.ca_sha256,
        args.output.resolve(),
        args.base_image,
        args.model_version,
        args.model_name,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"AWS release staged at {args.output.resolve()}")


if __name__ == "__main__":
    main()
