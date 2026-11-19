"""Durable SQLite idempotency store for a local Parser Service instance.

SQLite and its WAL files must reside on a local filesystem; network filesystems
do not provide the locking/durability assumptions used here.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ..application.errors import ClaimBusyError, IdempotencyPayloadConflictError, IdempotencyStoreUnavailableError
from ..application.models import ClaimDisposition, ClaimResult, ProcessingRecord, ProcessingState
from ..contracts import EventEnvelope
from ..contracts.codecs import decode_json, encode_json

_TABLE = "parser_processing_v1"
_TOKENS = "parser_claim_tokens_v1"
_SAFE = "Parser idempotency store is temporarily unavailable"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class SQLiteIdempotencyStore:
    def __init__(self, database: Path, *, now: Callable[[], datetime] | None = None,
                 busy_timeout_ms: int = 5000) -> None:
        self._database = str(database)
        self._now = now or (lambda: datetime.now(timezone.utc))
        if type(busy_timeout_ms) is not int or busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be a nonnegative integer")
        self._timeout = busy_timeout_ms
        def initialize(connection: sqlite3.Connection) -> None:
            connection.execute(f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
            key TEXT PRIMARY KEY, payload_digest TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('claimed','saved','published','failed_saved','failed_published')),
            output_event BLOB, claim_token TEXT NOT NULL, lease_expires_us INTEGER,
            CHECK((state='claimed' AND output_event IS NULL AND lease_expires_us IS NOT NULL) OR
                  (state<>'claimed' AND output_event IS NOT NULL AND typeof(output_event)='blob'
                   AND lease_expires_us IS NULL)))""")
            connection.execute(f"CREATE TABLE IF NOT EXISTS {_TOKENS} (token TEXT PRIMARY KEY)")
            connection.execute(
                f"INSERT OR IGNORE INTO {_TOKENS}(token) SELECT claim_token FROM {_TABLE}"
            )
        self._write(initialize)

    def claim(self, key: str, payload_digest: str, claim_token: str,
              lease_expires_at: datetime) -> ClaimResult:
        now_us, lease_us = self._micros(self._now()), self._micros(lease_expires_at)
        def operation(connection: sqlite3.Connection) -> ClaimResult:
            row = connection.execute(f"SELECT * FROM {_TABLE} WHERE key=?", (key,)).fetchone()
            if row is None:
                self._reserve_token(connection, claim_token)
                connection.execute(f"INSERT INTO {_TABLE} VALUES (?,?,?,?,?,?)",
                                   (key, payload_digest, "claimed", None, claim_token, lease_us))
                return ClaimResult(ClaimDisposition.ACQUIRED, self._record((key, payload_digest, "claimed", None, claim_token, lease_us)))
            record = self._record(row)
            if record.payload_digest != payload_digest:
                raise IdempotencyPayloadConflictError("Idempotency key has a different payload")
            if record.state is not ProcessingState.CLAIMED:
                return ClaimResult(ClaimDisposition.EXISTING, record)
            if row[5] > now_us:
                return ClaimResult(ClaimDisposition.BUSY, record)
            self._reserve_token(connection, claim_token)
            connection.execute(f"UPDATE {_TABLE} SET claim_token=?, lease_expires_us=? WHERE key=? AND state='claimed' AND lease_expires_us<=?",
                               (claim_token, lease_us, key, now_us))
            return ClaimResult(ClaimDisposition.ACQUIRED, ProcessingRecord(
                key, payload_digest, ProcessingState.CLAIMED, None, claim_token, self._datetime(lease_us)))
        return self._write(operation)

    def load(self, key: str) -> ProcessingRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(f"SELECT * FROM {_TABLE} WHERE key=?", (key,)).fetchone()
                return None if row is None else self._record(row)
        except IdempotencyStoreUnavailableError:
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError, OSError) as error:
            raise IdempotencyStoreUnavailableError(_SAFE) from error

    def record_saved(self, key: str, claim_token: str, event: EventEnvelope) -> ProcessingRecord:
        return self._record_event(key, claim_token, event, ProcessingState.SAVED)

    def record_failure(self, key: str, claim_token: str, event: EventEnvelope) -> ProcessingRecord:
        return self._record_event(key, claim_token, event, ProcessingState.FAILED_SAVED)

    def record_published(self, key: str, claim_token: str) -> ProcessingRecord:
        def operation(connection: sqlite3.Connection) -> ProcessingRecord:
            row = connection.execute(f"SELECT * FROM {_TABLE} WHERE key=?", (key,)).fetchone()
            if row is None or row[4] != claim_token:
                raise ClaimBusyError("Idempotency claim is no longer owned")
            state = ProcessingState(row[2])
            if state in {ProcessingState.PUBLISHED, ProcessingState.FAILED_PUBLISHED}:
                return self._record(row)
            target = {ProcessingState.SAVED: "published", ProcessingState.FAILED_SAVED: "failed_published"}.get(state)
            if target is None:
                raise ClaimBusyError("Idempotency state transition is not available")
            connection.execute(f"UPDATE {_TABLE} SET state=? WHERE key=? AND claim_token=? AND state=?",
                               (target, key, claim_token, state.value))
            return self._record(connection.execute(f"SELECT * FROM {_TABLE} WHERE key=?", (key,)).fetchone())
        return self._write(operation)

    def _record_event(self, key: str, token: str, event: EventEnvelope,
                      target: ProcessingState) -> ProcessingRecord:
        encoded = encode_json(event)
        def operation(connection: sqlite3.Connection) -> ProcessingRecord:
            row = connection.execute(f"SELECT * FROM {_TABLE} WHERE key=?", (key,)).fetchone()
            if row is None or row[4] != token:
                raise ClaimBusyError("Idempotency claim is no longer owned")
            if row[2] != "claimed":
                record = self._record(row)
                if record.state is target and row[3] == encoded:
                    return record
                raise ClaimBusyError("Idempotency state transition is not available")
            connection.execute(f"UPDATE {_TABLE} SET state=?, output_event=?, lease_expires_us=NULL WHERE key=? AND claim_token=? AND state='claimed'",
                               (target.value, encoded, key, token))
            return self._record(connection.execute(f"SELECT * FROM {_TABLE} WHERE key=?", (key,)).fetchone())
        return self._write(operation)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database, isolation_level=None, timeout=self._timeout / 1000)
        connection.execute(f"PRAGMA busy_timeout={self._timeout}")
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        if mode is None or str(mode[0]).lower() != "wal":
            connection.close()
            raise IdempotencyStoreUnavailableError(_SAFE)
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _write(self, operation):
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect(); connection.execute("BEGIN IMMEDIATE")
            result = operation(connection); connection.execute("COMMIT")
            return result
        except (IdempotencyPayloadConflictError, ClaimBusyError):
            if connection is not None and connection.in_transaction: connection.execute("ROLLBACK")
            raise
        except (sqlite3.Error, TypeError, ValueError, OverflowError, OSError) as error:
            if connection is not None and connection.in_transaction:
                try: connection.execute("ROLLBACK")
                except sqlite3.Error: pass
            raise IdempotencyStoreUnavailableError(_SAFE) from error
        finally:
            if connection is not None: connection.close()

    @staticmethod
    def _micros(value: datetime) -> int:
        try:
            if type(value) is not datetime or value.utcoffset() is None:
                raise ValueError
            delta = value.astimezone(timezone.utc) - _EPOCH
            return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
        except (OSError, OverflowError, TypeError, ValueError) as error:
            raise IdempotencyStoreUnavailableError(_SAFE) from error

    @staticmethod
    def _datetime(value: int) -> datetime:
        if type(value) is not int:
            raise IdempotencyStoreUnavailableError(_SAFE)
        try:
            return _EPOCH + timedelta(microseconds=value)
        except (OSError, OverflowError, ValueError) as error:
            raise IdempotencyStoreUnavailableError(_SAFE) from error

    @staticmethod
    def _reserve_token(connection: sqlite3.Connection, token: str) -> None:
        try:
            connection.execute(f"INSERT INTO {_TOKENS}(token) VALUES (?)", (token,))
        except sqlite3.IntegrityError as error:
            raise ClaimBusyError("Idempotency claim token was already used") from error

    @classmethod
    def _record(cls, row) -> ProcessingRecord:
        state = ProcessingState(row[2])
        event = None
        if row[3] is not None:
            if type(row[3]) is not bytes:
                raise IdempotencyStoreUnavailableError(_SAFE)
            raw = row[3]; event = decode_json(raw)
            if encode_json(event) != raw: raise ValueError("noncanonical event")
        lease = cls._datetime(row[5]) if row[5] is not None else None
        return ProcessingRecord(row[0], row[1], state, event, row[4], lease)


__all__ = ["SQLiteIdempotencyStore"]
