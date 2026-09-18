from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ML_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    environment: Literal["development", "testing", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "ml_platform"
    db_user: str = "ml_platform"
    db_password: SecretStr = SecretStr("")
    db_password_file: Path | None = None
    db_connect_timeout: int = Field(default=3, ge=1, le=30)
    db_statement_timeout_ms: int = Field(default=3000, ge=100, le=30000)
    db_sslmode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = "prefer"
    cors_origins: list[str] = []
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    inference_enabled: bool = False
    tracking_uri: str = "http://127.0.0.1:5000"
    model_name: str = Field(default="credit-default", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    control_dir: Path = Path(".state/registry")
    # Compose and .env.example enable auth. The false default supports isolated legacy tests/CLIs.
    # Production can never disable it.
    auth_enabled: bool = False
    api_key: SecretStr | None = None
    api_key_file: Path | None = None
    admin_key: SecretStr | None = None
    admin_key_file: Path | None = None
    rate_limit_per_minute: int = Field(default=600, ge=1, le=100_000)
    anonymous_rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    max_request_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    request_body_timeout_seconds: float = Field(default=10, gt=0, le=60)

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        for name in ("db_password", "api_key", "admin_key"):
            secret_file = getattr(self, name + "_file")
            direct = getattr(self, name)
            if secret_file is not None:
                if direct is not None and direct.get_secret_value():
                    raise ValueError(f"Set either ML_{name.upper()} or its _FILE setting")
                try:
                    with secret_file.open(encoding="utf-8") as stream:
                        value = stream.read(4097)
                except (OSError, UnicodeError) as exc:
                    raise ValueError(f"Cannot read ML_{name.upper()}_FILE") from exc
                if len(value) > 4096:
                    raise ValueError("Secret file is too large")
                setattr(self, name, SecretStr(value.strip()))
        if len(self.db_password.get_secret_value()) < 16:
            raise ValueError("ML_DB_PASSWORD must contain at least 16 characters")
        for origin in self.cors_origins:
            parsed = urlsplit(origin)
            if (
                "*" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Specify explicit CORS origins without paths or credentials")
            if self.environment == "production" and parsed.scheme != "https":
                raise ValueError("Production CORS origins require HTTPS")
        if not self.allowed_hosts or any(
            not host or any(c in host for c in "*/:@ ") for host in self.allowed_hosts
        ):
            raise ValueError("ML_ALLOWED_HOSTS requires explicit hostnames without ports")
        if self.auth_enabled:
            for key in (self.api_key, self.admin_key):
                value = key.get_secret_value() if key else ""
                if (
                    not 32 <= len(value) <= 256
                    or not value.isascii()
                    or not value.isprintable()
                    or any(c.isspace() for c in value)
                ):
                    raise ValueError(
                        "Authentication requires two distinct ASCII keys of 32+ characters"
                    )
            if self.api_key == self.admin_key:
                raise ValueError("API and admin keys must differ")
        if self.environment == "production":
            if self.db_sslmode != "verify-full":
                raise ValueError("Production requires ML_DB_SSLMODE=verify-full")
            if not self.auth_enabled:
                raise ValueError("Production requires ML_AUTH_ENABLED=true")
        return self

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )
