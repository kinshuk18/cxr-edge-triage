"""Pure idempotency rules, split from SQL for straightforward unit testing."""


class IdempotencyConflict(ValueError):
    """Raised when one idempotency key is reused for a different body."""


def idempotency_action(existing_sha256: str, incoming_sha256: str) -> str:
    if existing_sha256 != incoming_sha256:
        raise IdempotencyConflict("Idempotency-Key was reused with a different payload")
    return "reuse"


def dedup_action(existing_sha256: str, incoming_sha256: str) -> str:
    """Body-hash deduplication is tenant-scoped by the database query."""
    return idempotency_action(existing_sha256, incoming_sha256)
