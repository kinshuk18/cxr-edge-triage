"""Idempotent worker handler with DB claim fencing and bounded retry semantics."""

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aio_pika
import jsonschema

from app.config import settings
from app.storage import ObjectStore
from worker.metrics import (
    CONF,
    CXR_OOD,
    QWAIT,
    SITE_CONF,
    SITE_OOD,
    STAGE,
    TASKS,
    bounded_site,
)

LOG = logging.getLogger("inference-worker")
MAX_MESSAGE_BYTES = 1_048_576
LOCK_TTL_SECONDS = 90


class PermanentTaskError(Exception):
    """Invalid payload or data that cannot succeed on retry."""


@dataclass
class WorkerContext:
    pool: object
    redis: object
    retry_exchange: object
    storage: ObjectStore
    runner: object
    worker_id: str
    schema: dict


def load_task_schema() -> dict:
    path = Path(__file__).resolve().parents[1] / "schemas" / "inference_task.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def norm_vendor(manufacturer: str | None) -> str:
    value = (manufacturer or "").strip().lower()
    if not value:
        return "unknown"
    # Bounded categories prevent arbitrary vendor strings from expanding metric cardinality.
    mapping = {
        "ge": "ge",
        "general electric": "ge",
        "siemens": "siemens",
        "philips": "philips",
        "canon": "canon",
        "toshiba": "canon",
        "fujifilm": "fujifilm",
        "fuji": "fujifilm",
        "carestream": "carestream",
        "agfa": "agfa",
        "hologic": "hologic",
    }
    for fragment, label in mapping.items():
        if fragment in value:
            return label
    return "other"


async def _publish_retry(context: WorkerContext, payload: dict) -> None:
    message = aio_pika.Message(
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        message_id=str(payload["message_id"]),
        content_type="application/json",
    )
    await context.retry_exchange.publish(message, routing_key=payload["priority"], mandatory=True)


async def _release_lock(context: WorkerContext, key: str, token: str) -> None:
    script = "if redis.call('get', KEYS[1]) == ARGV[1] then " "return redis.call('del', KEYS[1]) else return 0 end"
    try:
        await context.redis.eval(script, 1, key, token)
    except Exception:
        LOG.warning("best-effort Redis lock release failed")


async def _extend_lock(context: WorkerContext, key: str, token: str, stop: asyncio.Event):
    script = (
        "if redis.call('get', KEYS[1]) == ARGV[1] then "
        "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
    )
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=25)
        except asyncio.TimeoutError:
            try:
                ok = await context.redis.eval(script, 1, key, token, LOCK_TTL_SECONDS)
                if not ok:
                    return
            except Exception:
                LOG.warning("best-effort Redis lock extension failed")
                return


async def _claim(context: WorkerContext, payload: dict):
    async with context.pool.acquire() as connection:
        row = await connection.fetchrow(
            "UPDATE studies SET status='PROCESSING', attempts=attempts+1, worker=$3, "
            "updated_at=now() WHERE study_id=$1 AND tenant_id=$2 "
            "AND status IN ('QUEUED','PROCESSING') AND attempts < $4 "
            "RETURNING attempts, created_at, s3_key",
            uuid.UUID(payload["study_id"]),
            payload["tenant_id"],
            context.worker_id,
            settings.max_attempts,
        )
        if row:
            return row
        existing = await connection.fetchrow(
            "SELECT status, attempts FROM studies WHERE study_id=$1 AND tenant_id=$2",
            uuid.UUID(payload["study_id"]),
            payload["tenant_id"],
        )
        if existing and existing["status"] not in {"DONE", "FAILED"} and existing["attempts"] >= settings.max_attempts:
            await connection.execute(
                "UPDATE studies SET status='FAILED',updated_at=now(),"
                "result=jsonb_build_object('reason','max_attempts') "
                "WHERE study_id=$1 AND tenant_id=$2 AND status IN ('QUEUED','PROCESSING')",
                uuid.UUID(payload["study_id"]),
                payload["tenant_id"],
            )
        return None


async def _set_failed(context: WorkerContext, payload: dict, attempt: int, reason: str):
    async with context.pool.acquire() as connection:
        await connection.execute(
            "UPDATE studies SET status='FAILED',updated_at=now(),"
            "result=$4::jsonb WHERE study_id=$1 AND tenant_id=$2 "
            "AND attempts=$3 AND status='PROCESSING'",
            uuid.UUID(payload["study_id"]),
            payload["tenant_id"],
            attempt,
            json.dumps({"abstained": True, "reason": reason}),
        )


async def _retry_or_fail(context: WorkerContext, payload: dict, attempt: int, reason: str):
    if attempt >= settings.max_attempts:
        await _set_failed(context, payload, attempt, "max_attempts")
        TASKS.labels("failed").inc()
        return False
    async with context.pool.acquire() as connection:
        await connection.execute(
            "UPDATE studies SET status='QUEUED',worker=NULL,updated_at=now() "
            "WHERE study_id=$1 AND tenant_id=$2 AND attempts=$3 AND status='PROCESSING'",
            uuid.UUID(payload["study_id"]),
            payload["tenant_id"],
            attempt,
        )
    await _publish_retry(context, payload)
    LOG.warning("task rescheduled after %s; attempt=%d", reason, attempt)
    TASKS.labels("retry").inc()
    return True


async def handle(payload: dict, message, context: WorkerContext) -> None:
    """Handle one message; all DB mutations are tenant-scoped and attempt-fenced."""
    try:
        if len(message.body) > MAX_MESSAGE_BYTES:
            raise PermanentTaskError("message exceeds size cap")
        payload["meta"]["vendor_label"] = norm_vendor(payload["meta"].get("manufacturer"))
        jsonschema.validate(payload, context.schema)
        lock_key = f"cxr:lock:{payload['tenant_id']}:{payload['study_id']}"
        lock_token = f"{context.worker_id}:{uuid.uuid4()}"
        try:
            got_lock = await context.redis.set(lock_key, lock_token, nx=True, ex=LOCK_TTL_SECONDS)
        except Exception:
            # Redis is best-effort: continue with the DB claim if it is unavailable.
            got_lock = True
            lock_key = ""
        if not got_lock:
            await _publish_retry(context, payload)
            await message.ack()
            TASKS.labels("deferred_lock").inc()
            return
        stop_extend = asyncio.Event()
        extend_task = (
            asyncio.create_task(_extend_lock(context, lock_key, lock_token, stop_extend)) if lock_key else None
        )
        attempt = None
        try:
            with STAGE.labels("db_claim").time():
                claim = await _claim(context, payload)
            if claim is None:
                await message.ack()
                TASKS.labels("duplicate").inc()
                return
            attempt = int(claim["attempts"])
            created_at = claim["created_at"]
            if created_at:
                QWAIT.observe(max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds()))
            image = payload["image"]
            with STAGE.labels("download").time():
                try:
                    image_bytes = await context.storage.get_bytes(
                        image["bucket"], image["key"], settings.max_image_bytes
                    )
                except ValueError as exc:
                    raise PermanentTaskError(str(exc)) from exc
            if hashlib.sha256(image_bytes).hexdigest() != image["sha256"]:
                raise PermanentTaskError("stored image SHA-256 mismatch")
            with STAGE.labels("inference").time():
                result, overlay = await asyncio.to_thread(
                    context.runner.infer,
                    image_bytes,
                    image["format"],
                    payload["inference"].get("tasks"),
                )
            result_key = f"{payload['output']['prefix']}/result.json"
            overlay_key = f"{payload['output']['prefix']}/overlay.png"
            result["artifacts"] = {
                "result_key": result_key,
                "overlay_key": overlay_key,
                "overlay_sha256": hashlib.sha256(overlay).hexdigest(),
            }
            result_bytes = json.dumps(result, separators=(",", ":")).encode("utf-8")
            with STAGE.labels("upload").time():
                result_sha = await context.storage.put_bytes(
                    payload["output"]["bucket"], result_key, result_bytes, "application/json"
                )
                overlay_sha = await context.storage.put_bytes(
                    payload["output"]["bucket"], overlay_key, overlay, "image/png"
                )
            result["artifacts"]["result_sha256"] = result_sha
            result["artifacts"]["overlay_sha256"] = overlay_sha
            if result.get("reason") == "ood":
                CXR_OOD.labels("abstain").inc()
            else:
                CXR_OOD.labels("in_distribution").inc()
            CONF.observe(float(result["confidence"]))
            site = bounded_site(payload["tenant_id"])
            SITE_CONF.labels(site).observe(float(result["confidence"]))
            SITE_OOD.labels(site, "ood" if result.get("reason") == "ood" else "not_ood").inc()
            async with context.pool.acquire() as connection:
                status = await connection.execute(
                    "UPDATE studies SET status='DONE',result=$4::jsonb,worker=$5,updated_at=now() "
                    "WHERE study_id=$1 AND tenant_id=$2 AND attempts=$3 AND status='PROCESSING'",
                    uuid.UUID(payload["study_id"]),
                    payload["tenant_id"],
                    attempt,
                    json.dumps(result, separators=(",", ":")),
                    context.worker_id,
                )
            if status.endswith(" 1"):
                TASKS.labels("done").inc()
            else:
                TASKS.labels("stale_attempt").inc()
            await message.ack()
        except PermanentTaskError as exc:
            if attempt is not None:
                await _set_failed(context, payload, attempt, str(exc))
            TASKS.labels("permanent_error").inc()
            await message.reject(requeue=False)
        except torch_oom_exception() as exc:
            import torch

            del exc
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            context.runner.release()
            if attempt is None:
                await message.reject(requeue=True)
            else:
                retry = await _retry_or_fail(context, payload, attempt, "cuda_oom")
                if retry:
                    await message.ack()
                else:
                    await message.reject(requeue=False)
        except Exception as exc:
            LOG.exception("transient task failure")
            if attempt is None:
                await message.reject(requeue=True)
            else:
                retry = await _retry_or_fail(context, payload, attempt, type(exc).__name__)
                if retry:
                    await message.ack()
                else:
                    await message.reject(requeue=False)
        finally:
            if extend_task:
                stop_extend.set()
                extend_task.cancel()
                try:
                    await extend_task
                except asyncio.CancelledError:
                    pass
            if lock_key and got_lock:
                await _release_lock(context, lock_key, lock_token)
            context.runner.release()
    except (jsonschema.ValidationError, PermanentTaskError) as exc:
        LOG.warning("permanent invalid message: %s", exc)
        TASKS.labels("invalid_message").inc()
        await message.reject(requeue=False)
    except Exception:
        LOG.exception("message handler setup failed")
        await message.reject(requeue=True)


def torch_oom_exception():
    import torch

    return torch.cuda.OutOfMemoryError
