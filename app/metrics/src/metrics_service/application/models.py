"""Validated application state owned by Metrics Service."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from ..contracts import EventEnvelope


def _string(value: object, name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if any(unicodedata.category(character) == "Cc" or 0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError(f"{name} contains unsafe characters")


def _digest(value: object, name: str) -> None:
    _string(value, name)
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 value")


class DeliveryDecision(str, Enum):
    ACK = "ack"
    RETRY = "retry"
    REJECT = "reject"


@dataclass(frozen=True)
class DeliveryContext:
    authorized_tenant_id: str

    def __post_init__(self) -> None:
        _string(self.authorized_tenant_id, "authorized_tenant_id")


@dataclass(frozen=True)
class ArtifactDescriptor:
    uri: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _string(self.uri, "uri")
        _digest(self.sha256, "sha256")
        if type(self.size_bytes) is not int:
            raise TypeError("size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be nonnegative")


class ProcessingState(str, Enum):
    CLAIMED = "claimed"
    SAVED = "saved"
    PUBLISHED = "published"
    FAILED_SAVED = "failed_saved"
    FAILED_PUBLISHED = "failed_published"


@dataclass(frozen=True)
class ProcessingRecord:
    key: str
    payload_digest: str
    state: ProcessingState
    output_event: EventEnvelope | None
    claim_token: str
    lease_expires_at: datetime | None

    def __post_init__(self) -> None:
        _string(self.key, "key")
        _digest(self.payload_digest, "payload_digest")
        if type(self.state) is not ProcessingState:
            raise TypeError("state must be a ProcessingState")
        _string(self.claim_token, "claim_token")
        if self.state is ProcessingState.CLAIMED:
            if self.output_event is not None:
                raise ValueError("CLAIMED record must not contain an output event")
            if type(self.lease_expires_at) is not datetime:
                raise TypeError("CLAIMED record requires a datetime lease")
            if self.lease_expires_at.utcoffset() != timedelta(0):
                raise ValueError("lease_expires_at must be timezone-aware UTC")
            return
        if type(self.output_event) is not EventEnvelope:
            raise TypeError("post-claim record requires an exact EventEnvelope")
        if self.lease_expires_at is not None:
            raise ValueError("post-claim record must not have a lease")
        ready = self.state in {ProcessingState.SAVED, ProcessingState.PUBLISHED}
        expected = "metrics.ready.v1" if ready else "metrics.failed.v1"
        if self.output_event.event_type != expected:
            raise ValueError(f"{self.state.value} requires {expected}")
        if not ready and self.output_event.payload.retryable is not False:
            raise ValueError("persisted failure must not be retryable")


class ClaimDisposition(str, Enum):
    ACQUIRED = "acquired"
    BUSY = "busy"
    EXISTING = "existing"


@dataclass(frozen=True)
class ClaimResult:
    disposition: ClaimDisposition
    record: ProcessingRecord

    def __post_init__(self) -> None:
        if type(self.disposition) is not ClaimDisposition:
            raise TypeError("disposition must be a ClaimDisposition")
        if type(self.record) is not ProcessingRecord:
            raise TypeError("record must be a ProcessingRecord")
        claimed = self.record.state is ProcessingState.CLAIMED
        if (self.disposition is ClaimDisposition.EXISTING) == claimed:
            raise ValueError("claim disposition does not match record state")
