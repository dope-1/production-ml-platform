# Contributing
Use Python 3.12. Create a virtual environment and install requirements-dev.lock,
then `pip install --no-deps -e .`. Run Ruff lint/format, mypy and pytest before
opening a pull request. PostgreSQL integration tests require TEST_DATABASE=1
and ML_DB_* settings pointing to a disposable PostgreSQL instance.
Do not commit data, credentials, models, or invented metrics.
Run scripts/verify_batch2.py against the verified Compose stack for inference,
monitoring and retraining checks. Keep simulation/test registries separate from
live aliases. Never use test metrics to tune candidates or relax deployment gates
merely to make a verification run pass.
