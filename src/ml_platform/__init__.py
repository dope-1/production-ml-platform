import os

# Keep local model operations local; this must run before importing MLflow.
os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")

__version__ = "0.4.0"
