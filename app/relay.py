"""Transactional PostgreSQL outbox relay with confirmed, mandatory publishing."""

import asyncio
import json
import logging

import aio_pika

from app.config import settings
from app.db import create_pool
from app.topology import EXCHANGE_MAIN, declare_topology

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger("outbox-relay")


async def relay_once(pool, exchange, limit: int = 100) -> int:
    published = 0
    async with pool.acquire() as connection:
        async with connection.transaction():
            rows = await connection.fetch(
                "SELECT id, study_id, routing_key, payload FROM outbox "
                "WHERE published_at IS NULL ORDER BY id "
                "FOR UPDATE SKIP LOCKED LIMIT $1",
                limit,
            )
            for row in rows:
                body = row["payload"]
                if not isinstance(body, str):
                    body = json.dumps(body, separators=(",", ":"))
                message = aio_pika.Message(
                    body=body.encode("utf-8"),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=str(row["id"]),
                    content_type="application/json",
                    headers={"outbox_id": int(row["id"])},
                )
                await exchange.publish(message, routing_key=row["routing_key"], mandatory=True)
                await connection.execute("UPDATE outbox SET published_at=now() WHERE id=$1", row["id"])
                published += 1
    return published


async def run() -> None:
    pool = await create_pool()
    try:
        connection = await aio_pika.connect_robust(settings.amqp_url)
        async with connection:
            channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
            exchanges = await declare_topology(channel)
            main_exchange = await channel.get_exchange(EXCHANGE_MAIN)
            del exchanges
            while True:
                count = await relay_once(pool, main_exchange)
                if count == 0:
                    await asyncio.sleep(0.5)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run())
