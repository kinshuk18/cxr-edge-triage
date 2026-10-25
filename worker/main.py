"""Spawn-based worker supervisor: one isolated child per discovered GPU (or one CPU child)."""

import asyncio
import json
import logging
import multiprocessing as mp
import signal
import time
import uuid

import aio_pika
import asyncpg
import torch
from redis.asyncio import Redis
from prometheus_client import start_http_server

from app.config import settings
from app.storage import ObjectStore
from app.topology import MAIN_QUEUES, declare_topology
from worker.handle import WorkerContext, handle, load_task_schema
from worker.infer import InferenceRunner
from worker.metrics import WORKER_UP

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("worker-supervisor")


async def child_main(device_index: int, stop_event) -> None:
    if torch.cuda.is_available():
        torch.cuda.set_device(device_index)
        device = "cuda"
    else:
        device = "cpu"
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=4)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    connection = await aio_pika.connect_robust(settings.amqp_url)
    runner = None
    try:
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=1)
            _, retry_exchange, _ = await declare_topology(channel)
            queues = {priority: await channel.get_queue(queue_name) for priority, queue_name in MAIN_QUEUES.items()}
            runner = InferenceRunner(settings.model_path, device=device)
            context = WorkerContext(
                pool=pool,
                redis=redis,
                retry_exchange=retry_exchange,
                storage=ObjectStore(),
                runner=runner,
                worker_id=f"pid-{__import__('os').getpid()}-gpu-{device_index}-{uuid.uuid4().hex[:8]}",
                schema=load_task_schema(),
            )
            # One port per child avoids bind collisions on multi-GPU hosts; Kubernetes requests one GPU per pod.
            start_http_server(9100 + device_index, addr="0.0.0.0")
            WORKER_UP.set(1)
            while not stop_event.is_set():
                message = await queues["stat"].get(no_ack=False, fail=False)
                if message is None:
                    message = await queues["routine"].get(no_ack=False, fail=False)
                if message is None:
                    await asyncio.sleep(settings.worker_poll_seconds)
                    continue
                if len(message.body) > 1_048_576:
                    await message.reject(requeue=False)
                    continue
                try:
                    payload = json.loads(message.body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    await message.reject(requeue=False)
                    continue
                await handle(payload, message, context)
            WORKER_UP.set(0)
    finally:
        if runner:
            runner.close()
        await redis.aclose()
        await pool.close()


def _child_entry(device_index: int, stop_event):
    asyncio.run(child_main(device_index, stop_event))


def supervise() -> None:
    context = mp.get_context("spawn")
    stop_event = context.Event()

    def stop_handler(signum, frame):
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    device_count = torch.cuda.device_count() if torch.cuda.is_available() else 1
    device_count = max(1, device_count)
    children = {}
    backoff = {index: 1.0 for index in range(device_count)}
    for index in range(device_count):
        process = context.Process(target=_child_entry, args=(index, stop_event), name=f"rad-worker-{index}")
        process.start()
        children[index] = process
    try:
        while not stop_event.is_set():
            for index, process in list(children.items()):
                if process.is_alive():
                    continue
                process.join()
                if stop_event.is_set():
                    break
                delay = backoff[index]
                LOG.error("worker child %d exited (%s); restarting in %.1fs", index, process.exitcode, delay)
                time.sleep(delay)
                backoff[index] = min(60.0, delay * 2.0)
                replacement = context.Process(
                    target=_child_entry,
                    args=(index, stop_event),
                    name=f"rad-worker-{index}",
                )
                replacement.start()
                children[index] = replacement
            time.sleep(0.5)
    finally:
        stop_event.set()
        deadline = time.monotonic() + 100.0
        for process in children.values():
            process.join(timeout=max(0.0, deadline - time.monotonic()))
        for process in children.values():
            if process.is_alive():
                LOG.warning("worker child %s exceeded 100s drain; terminating", process.name)
                process.terminate()
                process.join(timeout=5)


if __name__ == "__main__":
    supervise()
