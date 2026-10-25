"""Prometheus metrics with bounded label values."""

from prometheus_client import Counter, Histogram

INGEST_REJECTED = Counter(
    "cxr_ingest_rejected_total",
    "Rejected study submissions by bounded reason code",
    labelnames=("reason",),
)
INGEST_SECONDS = Histogram("cxr_ingest_seconds", "API ingest processing duration")

_ALLOWED_REASONS = {
    "too_large",
    "unsupported_type",
    "invalid_image",
    "dicom_policy",
    "qc_failed",
    "conflict",
    "storage_error",
    "database_error",
}


def rejection(reason: str) -> None:
    INGEST_REJECTED.labels(reason if reason in _ALLOWED_REASONS else "invalid_image").inc()
