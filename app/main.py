"""FastAPI ingress: authenticate, cap bytes, de-identify, store, and enqueue atomically."""

import asyncio
import hashlib
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.auth import require_tenant
from app.config import settings
from app.db import create_pool, find_existing, insert_study_and_outbox, study_status, tenant_may_stat
from app.ingest import validate_and_deidentify
from app.metrics import INGEST_SECONDS, rejection
from app.storage import ObjectStore


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.pool = await create_pool()
    application.state.storage = ObjectStore()
    yield
    pool = getattr(application.state, "pool", None)
    if pool is not None:
        await pool.close()


app = FastAPI(
    title="CXR Edge Triage API",
    version="1.0.0",
    description="Research pipeline ingestion API; not for clinical decision-making.",
    lifespan=lifespan,
)


async def _read_capped(request: Request, limit: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            rejection("too_large")
            raise HTTPException(status_code=413, detail="upload exceeds configured limit")
        body.extend(chunk)
    if not body:
        rejection("invalid_image")
        raise HTTPException(status_code=400, detail="empty request body")
    return bytes(body)


def _existing_response(row) -> dict:
    return {"study_id": str(row["study_id"]), "status": row["status"], "duplicate": True}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request):
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="database pool is not initialized")
    try:
        async with pool.acquire() as connection:
            await connection.fetchval("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database is not ready") from exc
    return {"status": "ready"}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/v1/studies", status_code=202)
async def submit_study(
    request: Request,
    tenant_id: str = Depends(require_tenant),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    priority_header: str | None = Header(default=None, alias="X-Priority"),
):
    started = time.perf_counter()
    with INGEST_SECONDS.time():
        raw = await _read_capped(request, min(settings.max_upload_bytes, 48 * 1024 * 1024))
        sha256_orig = hashlib.sha256(raw).hexdigest()
        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()
            if not idempotency_key or len(idempotency_key) > 200:
                raise HTTPException(status_code=400, detail="invalid Idempotency-Key")
        pool = request.app.state.pool
        existing = await find_existing(pool, tenant_id, sha256_orig, idempotency_key)
        if existing:
            return _existing_response(existing)
        try:
            stored, meta, patient_pseudo, content_type, fmt = await asyncio.to_thread(
                validate_and_deidentify, raw, tenant_id
            )
        except HTTPException as exc:
            detail = str(exc.detail)
            reason = (
                "unsupported_type"
                if exc.status_code == 415
                else (
                    "dicom_policy"
                    if "dicom_policy" in detail
                    else "qc_failed" if "qc_failed" in detail else "invalid_image"
                )
            )
            rejection(reason)
            raise
        if len(stored) > settings.max_image_bytes:
            rejection("too_large")
            raise HTTPException(status_code=413, detail="normalized object exceeds size cap")
        study_id = uuid.uuid4()
        s3_key = f"deidentified/{study_id}/{fmt}.{('dcm' if fmt == 'dicom' else 'png')}"
        try:
            sha256_stored = await request.app.state.storage.put_bytes(settings.raw_bucket, s3_key, stored, content_type)
        except Exception as exc:
            rejection("storage_error")
            raise HTTPException(status_code=503, detail="object storage upload failed") from exc
        requested_stat = (priority_header or "").lower().strip() == "stat"
        priority = "stat" if requested_stat and tenant_may_stat(tenant_id) else "routine"
        submitted_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema_version": "InferenceTask.v1",
            "message_id": str(uuid.uuid4()),
            "study_id": str(study_id),
            "tenant_id": tenant_id,
            "submitted_at": submitted_at,
            "priority": priority,
            "image": {
                "bucket": settings.raw_bucket,
                "key": s3_key,
                "sha256": sha256_stored,
                "format": fmt,
                "size_bytes": len(stored),
            },
            "meta": {
                "modality": meta.get("modality", "DX"),
                "manufacturer": meta.get("manufacturer", "unknown"),
                "rows": int(meta["rows"]),
                "columns": int(meta["columns"]),
                "photometric_interpretation": meta.get("photometric_interpretation", "UNKNOWN"),
                "patient_age_years": (
                    min(120, int(str(meta["patient_age_years"])[:3])) if meta.get("patient_age_years") else None
                ),
                "vendor_label": "unknown",
            },
            "inference": {
                "model_id": settings.model_id,
                "model_version": settings.model_version,
                "tasks": ["finding_a", "finding_b", "finding_c"],
                "explain": True,
            },
            "output": {
                "bucket": settings.results_bucket,
                "prefix": f"results/{study_id}",
            },
        }
        try:
            await insert_study_and_outbox(
                pool,
                study_id=study_id,
                tenant_id=tenant_id,
                sha256_orig=sha256_orig,
                sha256_stored=sha256_stored,
                idem_key=idempotency_key,
                s3_key=s3_key,
                fmt=fmt,
                meta=meta,
                patient_pseudo=patient_pseudo,
                routing_key=priority,
                payload=payload,
            )
        except HTTPException:
            rejection("conflict")
            raise
        except Exception as exc:
            rejection("database_error")
            raise HTTPException(status_code=503, detail="database commit failed") from exc
        return {
            "study_id": str(study_id),
            "status": "QUEUED",
            "duplicate": False,
            "priority": priority,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }


@app.get("/v1/studies/{study_id}")
async def get_study(
    study_id: uuid.UUID,
    request: Request,
    tenant_id: str = Depends(require_tenant),
):
    row = await study_status(request.app.state.pool, study_id, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="study not found")
    result = row["result"]
    if isinstance(result, str):
        result = json.loads(result)
    meta = row["meta"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    created_at = row["created_at"].isoformat() if row["created_at"] else None
    updated_at = row["updated_at"].isoformat() if row["updated_at"] else None
    return {
        "study_id": str(row["study_id"]),
        "status": row["status"],
        "result": result,
        "meta": meta,
        "created_at": created_at,
        "updated_at": updated_at,
    }
