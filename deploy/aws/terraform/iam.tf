resource "aws_secretsmanager_secret" "api_key" {
  name                    = "${local.name}/api-key"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret" "admin_key" {
  name                    = "${local.name}/admin-key"
  recovery_window_in_days = 7
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    sid     = "ReadRuntimeSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.api_key.arn,
      aws_secretsmanager_secret.admin_key.arn,
      aws_db_instance.app.master_user_secret[0].secret_arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "runtime-secrets"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "ListModelBootstrap"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.bootstrap.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.bootstrap_prefix}/*"]
    }
  }

  statement {
    sid       = "ReadModelBootstrap"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.bootstrap.arn}/${var.bootstrap_prefix}/*"]
  }

  statement {
    sid       = "MountMlflowEfs"
    actions   = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
    resources = [aws_efs_file_system.mlflow.arn]

    condition {
      test     = "StringEquals"
      variable = "elasticfilesystem:AccessPointArn"
      values   = [aws_efs_access_point.mlflow.arn]
    }
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "bootstrap-and-efs"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}
