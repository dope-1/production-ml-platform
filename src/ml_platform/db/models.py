from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Metadata shared by PostgreSQL migrations and isolated SQLite tests."""


class Prediction(Base):
    __tablename__ = "predictions"
    prediction_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_name: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    cohort: Mapped[str] = mapped_column(String(32), default="live")
    feature_buckets: Mapped[dict[str, int]] = mapped_column(JSON)
    risk_score: Mapped[float] = mapped_column(Float)
    prediction: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    actual_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    __table_args__ = (
        Index("ix_prediction_window", "model_name", "model_version", "cohort", "created_at"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 1"),
        CheckConstraint("prediction IN (0, 1)"),
        CheckConstraint("actual_label IS NULL OR actual_label IN (0, 1)"),
    )


class ApiEvent(Base):
    __tablename__ = "api_events"
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    endpoint: Mapped[str] = mapped_column(String(64))
    status: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    cohort: Mapped[str] = mapped_column(String(32))
    missing_features: Mapped[list[str]] = mapped_column(JSON)


class MonitoringReport(Base):
    __tablename__ = "monitoring_reports"
    report_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    model_name: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    cohort: Mapped[str] = mapped_column(String(32))
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
