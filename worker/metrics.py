"""Prometheus inference-stage metrics with bounded cardinality."""

from prometheus_client import Counter, Gauge, Histogram

from app.config import settings

STAGE = Histogram("cxr_stage_seconds", "Stage latency in seconds", ("stage",))
QWAIT = Histogram("cxr_queue_wait_seconds", "Time from submit to worker start")
TASKS = Counter("cxr_tasks_total", "Inference tasks by bounded outcome", ("outcome",))
CXR_OOD = Counter("cxr_ood_total", "OOD decisions", ("decision",))
CONF = Histogram(
    "cxr_confidence",
    "Maximum calibrated class confidence",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
_SITE_ALLOWLIST = frozenset(sorted(settings.metric_site_allowlist)[:32])
SITE_CONF = Histogram(
    "cxr_site_confidence",
    "Maximum calibrated class confidence grouped by allowlisted site",
    ("site",),
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
SITE_OOD = Counter(
    "cxr_site_ood_total",
    "OOD decisions grouped by allowlisted site",
    ("site", "decision"),
)
WORKER_UP = Gauge("cxr_worker_up", "Worker process health")


def bounded_site(tenant_id: str) -> str:
    """Retain at most 32 configured site labels; aggregate every other tenant."""
    return tenant_id if tenant_id in _SITE_ALLOWLIST else "other"
