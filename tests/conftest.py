"""Shared test fixtures use deterministic data and never download models or datasets."""

from datetime import datetime, timezone
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def valid_task():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "InferenceTask.v1",
        "message_id": str(uuid.uuid4()),
        "study_id": str(uuid.uuid4()),
        "tenant_id": "unit-test-tenant",
        "submitted_at": now,
        "priority": "routine",
        "image": {
            "bucket": "cxr-raw",
            "key": "deidentified/unit-test/image.dcm",
            "sha256": "a" * 64,
            "format": "dicom",
            "size_bytes": 4096,
        },
        "meta": {
            "modality": "CR",
            "manufacturer": "Test Vendor",
            "rows": 1024,
            "columns": 1024,
            "photometric_interpretation": "MONOCHROME1",
            "patient_age_years": 45,
            "vendor_label": "unknown",
        },
        "inference": {
            "model_id": "test-model",
            "model_version": "0.0-test",
            "tasks": ["finding_a", "finding_b", "finding_c"],
            "explain": True,
        },
        "output": {"bucket": "cxr-results", "prefix": "results/test-study"},
    }
