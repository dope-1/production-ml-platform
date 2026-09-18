"""Prediction ledger, HTTP observations and versioned monitoring reports."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("prediction_id", sa.String(32), primary_key=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("cohort", sa.String(32), nullable=False),
        sa.Column("feature_buckets", sa.JSON(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("prediction", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("actual_label", sa.Integer(), nullable=True),
        sa.Column("label_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("risk_score >= 0 AND risk_score <= 1"),
        sa.CheckConstraint("prediction IN (0, 1)"),
        sa.CheckConstraint("actual_label IS NULL OR actual_label IN (0, 1)"),
    )
    op.create_index(
        "ix_prediction_window",
        "predictions",
        ["model_name", "model_version", "cohort", "created_at"],
    )
    op.create_table(
        "api_events",
        sa.Column("event_id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("cohort", sa.String(32), nullable=False),
        sa.Column("missing_features", sa.JSON(), nullable=False),
    )
    op.create_index("ix_api_events_created_at", "api_events", ["created_at"])
    op.create_table(
        "monitoring_reports",
        sa.Column("report_id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(32), nullable=False),
        sa.Column("cohort", sa.String(32), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
    )
    op.create_index("ix_monitoring_reports_created_at", "monitoring_reports", ["created_at"])


def downgrade() -> None:
    op.drop_table("monitoring_reports")
    op.drop_table("api_events")
    op.drop_table("predictions")
