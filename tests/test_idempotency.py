import pytest

from app.idempotency import IdempotencyConflict, dedup_action, idempotency_action


def test_same_idempotency_key_and_same_payload_reuses_record():
    assert idempotency_action("abc", "abc") == "reuse"


def test_same_idempotency_key_with_different_payload_conflicts():
    with pytest.raises(IdempotencyConflict):
        idempotency_action("sha-old", "sha-new")


def test_tenant_scoped_body_dedup_logic():
    assert dedup_action("0" * 64, "0" * 64) == "reuse"
    with pytest.raises(IdempotencyConflict):
        dedup_action("0" * 64, "1" * 64)
