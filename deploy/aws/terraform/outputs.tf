output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "bootstrap_bucket" {
  value = aws_s3_bucket.bootstrap.id
}

output "bootstrap_prefix" {
  value = var.bootstrap_prefix
}

output "api_key_secret_arn" {
  value = aws_secretsmanager_secret.api_key.arn
}

output "admin_key_secret_arn" {
  value = aws_secretsmanager_secret.admin_key.arn
}

output "load_balancer_dns_name" {
  value = aws_lb.api.dns_name
}

output "api_url" {
  value = "https://${var.domain_name}"
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "rds_endpoint" {
  value     = aws_db_instance.app.endpoint
  sensitive = true
}

output "next_step" {
  value = var.deploy_service ? "Run scripts/verify_aws_deployment.py against the api_url output." : "Populate ECR, S3 and both Secrets Manager secrets, then set deploy_service=true."
}
