from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = ROOT / "deploy/aws/terraform"


def source(name):
    return (TERRAFORM / name).read_text(encoding="utf-8")


def test_cloud_database_and_model_storage_are_private_and_encrypted():
    storage = source("storage.tf")
    network = source("network.tf")
    assert "publicly_accessible    = false" in storage
    assert "storage_encrypted           = true" in storage
    assert "encrypted        = true" in storage
    assert 'status = "Enabled"' in storage
    assert "block_public_policy     = true" in storage
    assert "security_groups = [aws_security_group.task.id]" in network


def test_service_is_single_instance_and_cannot_start_by_default():
    compute = source("compute.tf")
    variables = source("variables.tf")
    compact_compute = " ".join(compute.split())
    assert "desired_count = var.deploy_service ? 1 : 0" in compact_compute
    assert "default     = false" in variables
    assert 'image_uri = "${aws_ecr_repository.api.repository_url}@${var.image_digest}"' in compute
    assert "assign_public_ip = true" in compute
    assert "security_groups  = [aws_security_group.task.id]" in compute


def test_runtime_uses_tls_auth_secrets_and_read_only_roots():
    compute = source("compute.tf")
    compact_compute = " ".join(compute.split())
    assert '{ name = "ML_ENVIRONMENT", value = "production" }' in compute
    assert '{ name = "ML_DB_SSLMODE", value = "verify-full" }' in compute
    assert "aws_secretsmanager_secret.api_key.arn" in compute
    assert "aws_secretsmanager_secret.admin_key.arn" in compute
    assert compute.count("readonlyRootFilesystem = true") == 4
    assert 'name       = "volume-permissions"' in compute
    assert (
        'dependsOn = [{ containerName = "volume-permissions", condition = "SUCCESS" }]'
        in compact_compute
    )
    assert 'transit_encryption = "ENABLED"' in compute


def test_https_and_rollback_safety_controls_exist():
    compute = source("compute.tf")
    edge = source("edge.tf")
    network = source("network.tf")
    storage = source("storage.tf")
    compact_compute = " ".join(compute.split())
    compact_edge = " ".join(edge.split())
    compact_network = " ".join(network.split())
    assert "cloudfront_default_certificate = true" in compact_edge
    assert 'viewer_protocol_policy = "redirect-to-https"' in compact_edge
    assert 'origin_protocol_policy = "http-only"' in compact_edge
    assert 'name = "X-Origin-Verify"' in compact_edge
    assert 'http_header_name = "X-Origin-Verify"' in compact_compute
    assert "prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]" in compact_network
    assert 'status_code = "403"' in compact_compute
    assert "rollback = true" in compute
    assert 'image_tag_mutability = "IMMUTABLE"' in storage
    assert "scan_on_push = true" in storage


def test_domainless_endpoint_has_no_domain_or_certificate_inputs():
    variables = source("variables.tf")
    outputs = source("outputs.tf")
    assert 'variable "domain_name"' not in variables
    assert 'variable "certificate_arn"' not in variables
    assert 'variable "route53_zone_id"' not in variables
    assert 'value = "https://${aws_cloudfront_distribution.api.domain_name}"' in outputs
