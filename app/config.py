"""Small environment-backed settings object; avoids import-time external connections."""

from dataclasses import dataclass
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql://rad:rad_dev_password@localhost:5432/rad")
    amqp_url: str = os.getenv("AMQP_URL", "amqp://rad:rad_dev_password@localhost:5672/")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    s3_endpoint_url: str = os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
    s3_access_key_id: str = os.getenv("S3_ACCESS_KEY_ID", "minioadmin")
    s3_secret_access_key: str = os.getenv("S3_SECRET_ACCESS_KEY", "minioadmin")
    s3_region: str = os.getenv("S3_REGION", "us-east-1")
    raw_bucket: str = os.getenv("S3_RAW_BUCKET", "cxr-raw")
    results_bucket: str = os.getenv("S3_RESULTS_BUCKET", "cxr-results")
    jwt_audience: str = os.getenv("JWT_AUDIENCE", "rad-api")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "cxr-edge-triage-dev")
    jwt_public_key_b64: str = os.getenv("JWT_PUBLIC_KEY_B64", "")
    hmac_secret: str = os.getenv("HMAC_SECRET", "dev-only-change-this-hmac-secret-before-any-shared-use")
    max_upload_bytes: int = _int("MAX_UPLOAD_BYTES", 50_331_648)
    max_image_bytes: int = _int("MAX_IMAGE_BYTES", 50_331_648)
    min_image_dimension: int = _int("MIN_IMAGE_DIMENSION", 512)
    max_image_dimension: int = _int("MAX_IMAGE_DIMENSION", 4500)
    model_path: str = os.getenv("MODEL_PATH", "models/model.pt")
    model_id: str = os.getenv("MODEL_ID", "dummy-pipeline-smoke")
    model_version: str = os.getenv("MODEL_VERSION", "0.0.0-smoke")
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "0.25"))
    max_attempts: int = _int("MAX_ATTEMPTS", 4)
    stat_tenant_allowlist: frozenset = frozenset(
        item.strip() for item in os.getenv("STAT_TENANT_ALLOWLIST", "dev-clinic").split(",") if item.strip()
    )
    metric_site_allowlist: frozenset = frozenset(
        sorted(item.strip() for item in os.getenv("METRIC_SITE_ALLOWLIST", "dev-clinic").split(",") if item.strip())[
            :32
        ]
    )

    @property
    def s3_force_path_style(self) -> bool:
        return os.getenv("S3_FORCE_PATH_STYLE", "true").lower() in {"1", "true", "yes"}


settings = Settings()
