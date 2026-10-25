"""Database helpers and transactional study/outbox insertion."""

import json
from typing import Optional

from fastapi import HTTPException

from app.config import settings
from app.idempotency import IdempotencyConflict, dedup_action, idempotency_action


async def create_pool():
    import asyncpg

    return await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10, command_timeout=30)


async def find_existing(pool, tenant_id: str, sha256_orig: str, idem_key: Optional[str]):
    async with pool.acquire() as conn:
        if idem_key:
            row = await conn.fetchrow(
                "SELECT study_id, sha256_orig, status FROM studies " "WHERE tenant_id=$1 AND idem_key=$2",
                tenant_id,
                idem_key,
            )
            if row:
                try:
                    idempotency_action(row["sha256_orig"], sha256_orig)
                except IdempotencyConflict as exc:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency-Key was already used with a different payload",
                    ) from exc
                return row
        row = await conn.fetchrow(
            "SELECT study_id, sha256_orig, status FROM studies " "WHERE tenant_id=$1 AND sha256_orig=$2",
            tenant_id,
            sha256_orig,
        )
        if row:
            dedup_action(row["sha256_orig"], sha256_orig)
        return row


async def insert_study_and_outbox(
    pool,
    *,
    study_id,
    tenant_id: str,
    sha256_orig: str,
    sha256_stored: str,
    idem_key: Optional[str],
    s3_key: str,
    fmt: str,
    meta: dict,
    patient_pseudo: str,
    routing_key: str,
    payload: dict,
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO studies (
                    study_id, tenant_id, sha256_orig, sha256_stored, idem_key,
                    s3_key, fmt, meta, patient_pseudo, status, attempts
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,'QUEUED',0)
                ON CONFLICT DO NOTHING RETURNING study_id
                """,
                study_id,
                tenant_id,
                sha256_orig,
                sha256_stored,
                idem_key,
                s3_key,
                fmt,
                json.dumps(meta, separators=(",", ":")),
                patient_pseudo,
            )
            if row is None:
                raise HTTPException(status_code=409, detail="concurrent_duplicate")
            await conn.execute(
                "INSERT INTO outbox(study_id,routing_key,payload) VALUES($1,$2,$3::jsonb)",
                study_id,
                routing_key,
                json.dumps(payload, separators=(",", ":")),
            )


async def study_status(pool, study_id, tenant_id: str):
    async with pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT study_id, status, result, meta, created_at, updated_at "
            "FROM studies WHERE study_id=$1 AND tenant_id=$2",
            study_id,
            tenant_id,
        )


def tenant_may_stat(tenant_id: str) -> bool:
    """Only permit stat-priority routing for explicitly allowlisted tenants."""
    return tenant_id in settings.stat_tenant_allowlist
