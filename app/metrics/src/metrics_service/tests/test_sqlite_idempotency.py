import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone, tzinfo

import pytest

from metrics_service.adapters.sqlite_idempotency import SQLiteIdempotencyStore
from metrics_service.application.errors import (ClaimBusyError, IdempotencyPayloadConflictError,
                                                IdempotencyStoreUnavailableError)
from metrics_service.application.models import ClaimDisposition, ProcessingState
from metrics_service.contracts import (EventEnvelope, Failure, GraphReference, MetricsDescriptor,
                                      MetricsReady, Producer)


def test_claim_persists_and_reclaims_at_expiry_boundary(tmp_path):
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]; db = tmp_path / "state.sqlite"
    store = SQLiteIdempotencyStore(db, now=lambda: clock[0])
    assert store.claim("key", "c" * 64, "old", clock[0] + timedelta(microseconds=1)).disposition is ClaimDisposition.ACQUIRED
    clock[0] += timedelta(microseconds=1)
    assert store.claim("key", "c" * 64, "new", clock[0] + timedelta(seconds=1)).disposition is ClaimDisposition.ACQUIRED
    with pytest.raises(ClaimBusyError): store.record_published("key", "old")
    assert SQLiteIdempotencyStore(db, now=lambda: clock[0]).load("key").claim_token == "new"


def test_digest_conflict_is_preserved(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); store = SQLiteIdempotencyStore(tmp_path / "db", now=lambda: now)
    store.claim("key", "a" * 64, "one", now + timedelta(seconds=1))
    with pytest.raises(IdempotencyPayloadConflictError): store.claim("key", "b" * 64, "two", now + timedelta(seconds=1))


def _event(failed=False):
    payload = (Failure("metrics", "input", "bad", "safe", False) if failed else
               MetricsReady(GraphReference("file:///graph", "a" * 64),
                            MetricsDescriptor("file:///metrics", "b" * 64, 1, 1, 4)))
    return EventEnvelope("out", "metrics.failed.v1" if failed else "metrics.ready.v1", 1,
                         "2026-01-01T00:00:00Z", "corr", "in", "tenant",
                         Producer("metrics-service", "1"), payload)


@pytest.mark.parametrize("failed,intermediate,terminal", [
    (False, ProcessingState.SAVED, ProcessingState.PUBLISHED),
    (True, ProcessingState.FAILED_SAVED, ProcessingState.FAILED_PUBLISHED),
])
def test_event_transitions_persist_exactly_across_reopen(tmp_path, failed, intermediate, terminal):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"
    store = SQLiteIdempotencyStore(db, now=lambda: now); store.claim("key", "a" * 64, "token", now)
    event = _event(failed)
    saved = store.record_failure("key", "token", event) if failed else store.record_saved("key", "token", event)
    assert saved.state is intermediate and SQLiteIdempotencyStore(db, now=lambda: now).load("key") == saved
    with pytest.raises(IdempotencyPayloadConflictError): store.claim("key", "b" * 64, "new", now)
    assert store.record_published("key", "token").state is terminal
    with pytest.raises(ClaimBusyError): store.record_failure("key", "token", event)


def test_invalid_transition_and_corrupt_blob_mapping(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"; store = SQLiteIdempotencyStore(db, now=lambda: now)
    original = store.claim("key", "a" * 64, "token", now + timedelta(seconds=1)).record
    with pytest.raises(ClaimBusyError): store.record_published("key", "token")
    assert store.load("key") == original
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE metrics_processing_v1 SET state='saved',output_event=?,lease_expires_us=NULL", (b'{ }',))
    with pytest.raises(IdempotencyStoreUnavailableError): store.load("key")


def test_concurrent_claim_has_one_winner(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"
    stores = [SQLiteIdempotencyStore(db, now=lambda: now) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda pair: pair[0].claim("key", "a" * 64, pair[1], now + timedelta(seconds=1)),
                                zip(stores, ("a", "b", "c", "d"))))
    assert sum(result.disposition is ClaimDisposition.ACQUIRED for result in results) == 1
    assert sum(result.disposition is ClaimDisposition.BUSY for result in results) == 3


@pytest.mark.parametrize("stored", [7, "text", 1.25])
def test_non_blob_storage_classes_are_rejected_without_mutation(tmp_path, stored):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"
    store = SQLiteIdempotencyStore(db, now=lambda: now); store.claim("key", "a" * 64, "token", now)
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE metrics_processing_v1 SET state='saved',output_event=?,lease_expires_us=NULL", (stored,))
    with pytest.raises(IdempotencyStoreUnavailableError): store.load("key")
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT typeof(output_event) FROM metrics_processing_v1").fetchone()[0] in {"integer", "text", "real"}


def test_token_history_prevents_aba_and_cross_key_reuse(tmp_path):
    clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]; db = tmp_path / "db"
    store = SQLiteIdempotencyStore(db, now=lambda: clock[0])
    store.claim("key", "a" * 64, "T", clock[0]); store.claim("key", "a" * 64, "U", clock[0] + timedelta(seconds=1))
    clock[0] += timedelta(seconds=1); before = store.load("key")
    with pytest.raises(ClaimBusyError): store.claim("key", "a" * 64, "T", clock[0] + timedelta(seconds=1))
    assert store.load("key") == before
    with pytest.raises(ClaimBusyError): store.claim("other", "b" * 64, "U", clock[0] + timedelta(seconds=1))
    assert store.load("other") is None


def test_wal_datetime_boundaries_and_naive_rejection(tmp_path):
    db = tmp_path / "db"; now = datetime.min.replace(tzinfo=timezone.utc)
    store = SQLiteIdempotencyStore(db, now=lambda: now)
    with sqlite3.connect(db) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert store.claim("min", "a" * 64, "token", now).record.lease_expires_at == now
    naive = SQLiteIdempotencyStore(tmp_path / "naive", now=lambda: datetime(2026, 1, 1))
    with pytest.raises(IdempotencyStoreUnavailableError):
        naive.claim("key", "a" * 64, "token", datetime(2026, 1, 2))
    extreme = SQLiteIdempotencyStore(tmp_path / "extreme", now=lambda: datetime.max.replace(tzinfo=timezone.utc))
    assert extreme.claim("max", "b" * 64, "max-token", datetime.max.replace(tzinfo=timezone.utc)).record.lease_expires_at == datetime.max.replace(tzinfo=timezone.utc)


def test_external_immediate_lock_maps_to_fixed_safe_error(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"
    store = SQLiteIdempotencyStore(db, now=lambda: now, busy_timeout_ms=0)
    blocker = sqlite3.connect(db, isolation_level=None); blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(IdempotencyStoreUnavailableError) as caught:
            store.claim("key", "a" * 64, "token", now)
        assert str(caught.value) == "Metrics idempotency store is temporarily unavailable"
    finally:
        blocker.execute("ROLLBACK"); blocker.close()


@pytest.mark.parametrize("method,state", [("record_saved", "saved"), ("record_failure", "failed_saved")])
def test_record_event_rejects_corrupt_existing_target_without_mutation(tmp_path, method, state):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"
    store = SQLiteIdempotencyStore(db, now=lambda: now); store.claim("key", "a" * 64, "token", now)
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        connection.execute("UPDATE metrics_processing_v1 SET state=?,output_event=7,lease_expires_us=NULL", (state,))
    with pytest.raises(IdempotencyStoreUnavailableError):
        getattr(store, method)("key", "token", _event(method == "record_failure"))
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT state,typeof(output_event),output_event FROM metrics_processing_v1").fetchone() == (state, "integer", 7)


def test_tzinfo_type_error_maps_to_fixed_safe_error(tmp_path):
    class BrokenTimezone(tzinfo):
        def utcoffset(self, value): raise TypeError("private")
        def dst(self, value): return None
    malformed = datetime(2026, 1, 1, tzinfo=BrokenTimezone())
    store = SQLiteIdempotencyStore(tmp_path / "db", now=lambda: malformed)
    with pytest.raises(IdempotencyStoreUnavailableError) as caught:
        store.claim("key", "a" * 64, "token", datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert str(caught.value) == "Metrics idempotency store is temporarily unavailable"


def test_legacy_claim_token_is_migrated_to_history(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"
    with sqlite3.connect(db) as connection:
        connection.execute("""CREATE TABLE metrics_processing_v1 (
            key TEXT PRIMARY KEY, payload_digest TEXT NOT NULL, state TEXT NOT NULL,
            output_event BLOB, claim_token TEXT NOT NULL, lease_expires_us INTEGER)""")
        connection.execute("INSERT INTO metrics_processing_v1 VALUES (?,?,?,?,?,?)",
                           ("legacy", "a" * 64, "claimed", None, "used", 0))
    store = SQLiteIdempotencyStore(db, now=lambda: now)
    with pytest.raises(ClaimBusyError): store.claim("legacy", "a" * 64, "used", now)
    with pytest.raises(ClaimBusyError): store.claim("different", "b" * 64, "used", now)
    assert store.load("legacy").claim_token == "used" and store.load("different") is None


def test_failed_processing_insert_rolls_back_token_reservation(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc); db = tmp_path / "db"
    store = SQLiteIdempotencyStore(db, now=lambda: now)
    with sqlite3.connect(db) as connection:
        connection.execute("""CREATE TRIGGER reject_metrics_claim BEFORE INSERT ON metrics_processing_v1
                            BEGIN SELECT RAISE(ABORT, 'controlled'); END""")
    with pytest.raises(IdempotencyStoreUnavailableError):
        store.claim("key", "a" * 64, "reusable", now)
    with sqlite3.connect(db) as connection: connection.execute("DROP TRIGGER reject_metrics_claim")
    assert store.claim("key", "a" * 64, "reusable", now).disposition is ClaimDisposition.ACQUIRED
