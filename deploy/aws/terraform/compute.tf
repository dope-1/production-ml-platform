locals {
  image_uri = "${aws_ecr_repository.api.repository_url}@${var.image_digest}"
  common_environment = [
    { name = "MLFLOW_DISABLE_TELEMETRY", value = "true" },
    { name = "ML_ENVIRONMENT", value = "production" },
    { name = "ML_DB_HOST", value = aws_db_instance.app.address },
    { name = "ML_DB_PORT", value = tostring(aws_db_instance.app.port) },
    { name = "ML_DB_NAME", value = var.db_name },
    { name = "ML_DB_USER", value = var.db_username },
    { name = "ML_DB_SSLMODE", value = "verify-full" },
    { name = "ML_DB_SSLROOTCERT", value = "/etc/ssl/certs/aws-rds-global-bundle.pem" },
  ]
  database_secret = [{
    name      = "ML_DB_PASSWORD"
    valueFrom = "${aws_db_instance.app.master_user_secret[0].secret_arn}:password::"
  }]
  awslogs = {
    logDriver = "awslogs"
    options = {
      awslogs-region        = var.aws_region
      awslogs-stream-prefix = "ecs"
    }
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "mlflow" {
  name              = "/ecs/${local.name}/mlflow"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "init" {
  name              = "/ecs/${local.name}/init"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_lb" "api" {
  name                       = substr(local.name, 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.load_balancer.id]
  subnets                    = aws_subnet.public[*].id
  drop_invalid_header_fields = true
  enable_deletion_protection = var.deletion_protection
}

resource "aws_lb_target_group" "api" {
  name        = substr("${local.name}-api", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 30

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200-499"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_route53_record" "api" {
  count = var.route53_zone_id == null ? 0 : 1

  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.api.dns_name
    zone_id                = aws_lb.api.zone_id
    evaluate_target_health = true
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.task_cpu)
  memory                   = tostring(var.task_memory)
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  volume {
    name = "mlflow"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.mlflow.id
      transit_encryption = "ENABLED"
      root_directory     = "/"
      authorization_config {
        access_point_id = aws_efs_access_point.mlflow.id
        iam             = "ENABLED"
      }
    }
  }

  volume { name = "api-tmp" }
  volume { name = "bootstrap-tmp" }
  volume { name = "mlflow-tmp" }
  volume { name = "migrate-tmp" }

  container_definitions = jsonencode([
    {
      name       = "volume-permissions"
      image      = local.image_uri
      essential  = false
      entryPoint = ["/bin/sh", "-c"]
      command = [
        "chown 10001:10001 /volumes/api /volumes/bootstrap /volumes/mlflow /volumes/migrate && chmod 0700 /volumes/api /volumes/bootstrap /volumes/mlflow /volumes/migrate"
      ]
      mountPoints = [
        { sourceVolume = "api-tmp", containerPath = "/volumes/api", readOnly = false },
        { sourceVolume = "bootstrap-tmp", containerPath = "/volumes/bootstrap", readOnly = false },
        { sourceVolume = "mlflow-tmp", containerPath = "/volumes/mlflow", readOnly = false },
        { sourceVolume = "migrate-tmp", containerPath = "/volumes/migrate", readOnly = false },
      ]
      readonlyRootFilesystem = true
      user                   = "0"
      logConfiguration = merge(local.awslogs, {
        options = merge(local.awslogs.options, { awslogs-group = aws_cloudwatch_log_group.init.name })
      })
    },
    {
      name       = "bootstrap"
      image      = var.aws_cli_image
      essential  = false
      entryPoint = ["/bin/sh", "-c"]
      command = [
        "if [ ! -s /mlflow/mlflow.db ]; then aws s3 sync s3://${aws_s3_bucket.bootstrap.id}/${var.bootstrap_prefix}/ /mlflow/ --only-show-errors; fi; test -s /mlflow/mlflow.db"
      ]
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "HOME", value = "/tmp" },
      ]
      mountPoints = [
        { sourceVolume = "mlflow", containerPath = "/mlflow", readOnly = false },
        { sourceVolume = "bootstrap-tmp", containerPath = "/tmp", readOnly = false },
      ]
      user        = "10001"
      dependsOn   = [{ containerName = "volume-permissions", condition = "SUCCESS" }]
      logConfiguration = merge(local.awslogs, {
        options = merge(local.awslogs.options, { awslogs-group = aws_cloudwatch_log_group.init.name })
      })
    },
    {
      name      = "migrate"
      image     = local.image_uri
      essential = false
      command   = ["alembic", "upgrade", "head"]
      environment = local.common_environment
      secrets     = local.database_secret
      dependsOn   = [{ containerName = "bootstrap", condition = "SUCCESS" }]
      readonlyRootFilesystem = true
      mountPoints = [{ sourceVolume = "migrate-tmp", containerPath = "/tmp", readOnly = false }]
      user        = "10001"
      logConfiguration = merge(local.awslogs, {
        options = merge(local.awslogs.options, { awslogs-group = aws_cloudwatch_log_group.init.name })
      })
    },
    {
      name      = "mlflow"
      image     = local.image_uri
      essential = true
      command = [
        "mlflow", "server", "--host", "0.0.0.0", "--port", "5000", "--workers", "1",
        "--backend-store-uri", "sqlite:////mlflow/mlflow.db", "--serve-artifacts",
        "--artifacts-destination", "/mlflow/artifacts"
      ]
      environment = [
        { name = "MLFLOW_DISABLE_TELEMETRY", value = "true" },
        { name = "MLFLOW_SERVER_ALLOWED_HOSTS", value = "127.0.0.1:5000,localhost:5000" },
        { name = "HOME", value = "/tmp" },
      ]
      dependsOn   = [{ containerName = "bootstrap", condition = "SUCCESS" }]
      mountPoints = [
        { sourceVolume = "mlflow", containerPath = "/mlflow", readOnly = false },
        { sourceVolume = "mlflow-tmp", containerPath = "/tmp", readOnly = false },
      ]
      readonlyRootFilesystem = true
      user                   = "10001"
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3)\""]
        interval    = 15
        timeout     = 5
        retries     = 10
        startPeriod = 30
      }
      logConfiguration = merge(local.awslogs, {
        options = merge(local.awslogs.options, { awslogs-group = aws_cloudwatch_log_group.mlflow.name })
      })
    },
    {
      name      = "api"
      image     = local.image_uri
      essential = true
      portMappings = [{
        containerPort = 8000
        hostPort      = 8000
        protocol      = "tcp"
        name          = "http"
      }]
      environment = concat(local.common_environment, [
        { name = "ML_INFERENCE_ENABLED", value = "true" },
        { name = "ML_AUTH_ENABLED", value = "true" },
        { name = "ML_ALLOWED_HOSTS", value = jsonencode([var.domain_name, "127.0.0.1", "localhost"]) },
        { name = "ML_CORS_ORIGINS", value = jsonencode(["https://${var.domain_name}"]) },
        { name = "ML_TRACKING_URI", value = "http://127.0.0.1:5000" },
        { name = "ML_CONTROL_DIR", value = "/registry-control" },
        { name = "HOME", value = "/tmp" },
      ])
      secrets = concat(local.database_secret, [
        { name = "ML_API_KEY", valueFrom = aws_secretsmanager_secret.api_key.arn },
        { name = "ML_ADMIN_KEY", valueFrom = aws_secretsmanager_secret.admin_key.arn },
      ])
      dependsOn = [
        { containerName = "bootstrap", condition = "SUCCESS" },
        { containerName = "migrate", condition = "SUCCESS" },
        { containerName = "mlflow", condition = "HEALTHY" },
      ]
      mountPoints = [{ sourceVolume = "api-tmp", containerPath = "/tmp", readOnly = false }]
      readonlyRootFilesystem = true
      user                   = "10001"
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)\""]
        interval    = 15
        timeout     = 5
        retries     = 5
        startPeriod = 120
      }
      logConfiguration = merge(local.awslogs, {
        options = merge(local.awslogs.options, { awslogs-group = aws_cloudwatch_log_group.api.name })
      })
    },
  ])
}

resource "aws_ecs_service" "api" {
  name            = local.name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.deploy_service ? 1 : 0
  launch_type     = "FARGATE"
  platform_version = "1.4.0"

  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"
  wait_for_steady_state   = true

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https, aws_efs_mount_target.mlflow]
}
