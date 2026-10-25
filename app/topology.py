"""Idempotent RabbitMQ topology declaration for the inference queues."""

EXCHANGE_MAIN = "radiology.direct"
EXCHANGE_RETRY = "radiology.retry"
EXCHANGE_DLX = "radiology.dlx"
MAIN_QUEUES = {"stat": "infer.stat.q", "routine": "infer.routine.q"}
RETRY_QUEUES = {"stat": "infer.stat.retry.q", "routine": "infer.routine.retry.q"}
DEAD_QUEUE = "infer.dead.q"


async def declare_topology(channel):
    main = await channel.declare_exchange(EXCHANGE_MAIN, "direct", durable=True)
    retry = await channel.declare_exchange(EXCHANGE_RETRY, "direct", durable=True)
    dlx = await channel.declare_exchange(EXCHANGE_DLX, "direct", durable=True)
    dead = await channel.declare_queue(
        DEAD_QUEUE,
        durable=True,
        arguments={"x-queue-type": "quorum", "x-delivery-limit": 3},
    )
    await dead.bind(dlx, routing_key="stat")
    await dead.bind(dlx, routing_key="routine")
    for key, queue_name in MAIN_QUEUES.items():
        queue = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-delivery-limit": 3,
                "x-dead-letter-exchange": EXCHANGE_DLX,
            },
        )
        await queue.bind(main, routing_key=key)
        retry_queue = await channel.declare_queue(
            RETRY_QUEUES[key],
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-message-ttl": 30_000,
                "x-dead-letter-exchange": EXCHANGE_MAIN,
                "x-dead-letter-routing-key": key,
            },
        )
        await retry_queue.bind(retry, routing_key=key)
    return main, retry, dlx
