import hashlib
import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Protocol

from harness_service.harness_runner import HarnessRequest, HarnessResult, HarnessRunner


# ---------------------------------------------------------------------------
# Delivery model
# ---------------------------------------------------------------------------

class DeliveryDecision(StrEnum):
    ACK = "ACK"
    RETRY = "RETRY"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class DeliveryContext:
    # Tenant берётся из доверенного broker context, а не из payload.
    authorized_tenant_id: str


# ---------------------------------------------------------------------------
# Wire contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    uri: str
    sha256: str
    size_bytes: int
    schema_version: int


@dataclass(frozen=True, slots=True)
class HarnessStart:
    event_id: str
    correlation_id: str
    tenant_id: str
    graph: ArtifactDescriptor
    metrics: ArtifactDescriptor
    source_index: ArtifactDescriptor


@dataclass(frozen=True, slots=True)
class MaterializedInputs:
    graph_path: Path
    metrics_path: Path
    source_index_path: Path


# ---------------------------------------------------------------------------
# Application ports
# ---------------------------------------------------------------------------

class InputMaterializer(Protocol):
    def materialize(
        self,
        *,
        graph: ArtifactDescriptor,
        metrics: ArtifactDescriptor,
        source_index: ArtifactDescriptor,
    ) -> AbstractContextManager[MaterializedInputs]:
        """
        Скачивает артефакты во временную директорию, проверяет size/SHA-256
        и удаляет временные файлы после выхода из context manager.
        """
        ...


class ResultStore(Protocol):
    async def save(
        self,
        *,
        tenant_id: str,
        event_id: str,
        content: str,
    ) -> ArtifactDescriptor:
        ...


class EventPublisher(Protocol):
    async def publish(self, event: Mapping[str, object]) -> None:
        """
        Возвращает управление только после broker publisher confirmation.
        """
        ...


class ClaimDisposition(StrEnum):
    NEW = "NEW"
    BUSY = "BUSY"
    SAVED = "SAVED"
    PUBLISHED = "PUBLISHED"


@dataclass(frozen=True, slots=True)
class Claim:
    disposition: ClaimDisposition
    claim_token: str

    # Заполняется для SAVED: событие можно переиздать без повторного LLM-вызова.
    output_event: Mapping[str, object] | None = None


class IdempotencyStore(Protocol):
    async def claim(
        self,
        *,
        key: str,
        payload_digest: str,
    ) -> Claim:
        ...

    async def save_output(
        self,
        *,
        key: str,
        claim_token: str,
        output_event: Mapping[str, object],
    ) -> None:
        ...

    async def mark_published(
        self,
        *,
        key: str,
        claim_token: str,
    ) -> None:
        ...


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class InvalidEventError(ValueError):
    """Payload некорректен и повторная доставка не поможет."""


class PayloadConflictError(RuntimeError):
    """
    Один event_id уже был принят с другим payload.

    IdempotencyStore должен выбрасывать эту ошибку при несовпадении digest.
    """


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

class HarnessHandler:
    EXPECTED_EVENT_TYPE = "harness.start.v1"
    EXPECTED_SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        runner: HarnessRunner,
        materializer: InputMaterializer,
        result_store: ResultStore,
        idempotency: IdempotencyStore,
        publisher: EventPublisher,
    ) -> None:
        self._runner = runner
        self._materializer = materializer
        self._result_store = result_store
        self._idempotency = idempotency
        self._publisher = publisher

    async def handle(
        self,
        wire: Mapping[str, object],
        context: DeliveryContext,
    ) -> DeliveryDecision:
        try:
            event = self._parse_event(wire)

            if event.tenant_id != context.authorized_tenant_id:
                return DeliveryDecision.REJECT

            payload_digest = self._payload_digest(wire)
            idempotency_key = (
                f"harness:{event.tenant_id}:{event.event_id}"
            )

            claim = await self._idempotency.claim(
                key=idempotency_key,
                payload_digest=payload_digest,
            )

        except (InvalidEventError, PayloadConflictError):
            return DeliveryDecision.REJECT
        except Exception:
            return DeliveryDecision.RETRY

        if claim.disposition is ClaimDisposition.PUBLISHED:
            return DeliveryDecision.ACK

        if claim.disposition is ClaimDisposition.BUSY:
            return DeliveryDecision.RETRY

        if claim.disposition is ClaimDisposition.SAVED:
            return await self._republish_saved(
                key=idempotency_key,
                claim=claim,
            )

        try:
            # Materializer обязан проверить URI, размер и checksum.
            with self._materializer.materialize(
                graph=event.graph,
                metrics=event.metrics,
                source_index=event.source_index,
            ) as inputs:
                result = await self._runner.execute(
                    HarnessRequest(
                        event_id=event.event_id,
                        graph_path=inputs.graph_path,
                        metrics_path=inputs.metrics_path,
                        source_index_path=inputs.source_index_path,
                    )
                )

            result_descriptor = await self._result_store.save(
                tenant_id=event.tenant_id,
                event_id=event.event_id,
                content=result.content,
            )

            output_event = self._make_completed_event(
                source=event,
                result=result,
                descriptor=result_descriptor,
            )

            # Сначала сохраняем событие, потом публикуем.
            # При падении publisher повторная доставка не запустит LLM заново.
            await self._idempotency.save_output(
                key=idempotency_key,
                claim_token=claim.claim_token,
                output_event=output_event,
            )

            await self._publisher.publish(output_event)

            await self._idempotency.mark_published(
                key=idempotency_key,
                claim_token=claim.claim_token,
            )

            return DeliveryDecision.ACK

        except InvalidEventError:
            return DeliveryDecision.REJECT
        except Exception:
            # Timeout LLM, недоступное storage, publisher failure и прочие
            # временные ошибки приводят к broker redelivery.
            return DeliveryDecision.RETRY

    async def _republish_saved(
        self,
        *,
        key: str,
        claim: Claim,
    ) -> DeliveryDecision:
        if claim.output_event is None:
            return DeliveryDecision.RETRY

        try:
            await self._publisher.publish(claim.output_event)

            await self._idempotency.mark_published(
                key=key,
                claim_token=claim.claim_token,
            )

            return DeliveryDecision.ACK
        except Exception:
            return DeliveryDecision.RETRY

    def _parse_event(
        self,
        wire: Mapping[str, object],
    ) -> HarnessStart:
        if wire.get("event_type") != self.EXPECTED_EVENT_TYPE:
            raise InvalidEventError("Unsupported event_type")

        if wire.get("schema_version") != self.EXPECTED_SCHEMA_VERSION:
            raise InvalidEventError("Unsupported schema_version")

        payload = self._require_mapping(wire, "payload")

        return HarnessStart(
            event_id=self._require_string(wire, "event_id"),
            correlation_id=self._require_string(wire, "correlation_id"),
            tenant_id=self._require_string(wire, "tenant_id"),
            graph=self._parse_descriptor(payload, "graph"),
            metrics=self._parse_descriptor(payload, "metrics"),
            source_index=self._parse_descriptor(payload, "source_index"),
        )

    def _parse_descriptor(
        self,
        payload: Mapping[str, object],
        field: str,
    ) -> ArtifactDescriptor:
        data = self._require_mapping(payload, field)

        sha256 = self._require_string(data, "sha256")
        if len(sha256) != 64:
            raise InvalidEventError(f"{field}.sha256 is invalid")

        size_bytes = data.get("size_bytes")
        schema_version = data.get("schema_version")

        if type(size_bytes) is not int or size_bytes < 0:
            raise InvalidEventError(f"{field}.size_bytes is invalid")

        if type(schema_version) is not int or schema_version < 1:
            raise InvalidEventError(f"{field}.schema_version is invalid")

        return ArtifactDescriptor(
            uri=self._require_string(data, "uri"),
            sha256=sha256,
            size_bytes=size_bytes,
            schema_version=schema_version,
        )

    @staticmethod
    def _payload_digest(wire: Mapping[str, object]) -> str:
        canonical = json.dumps(
            wire,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _make_completed_event(
        *,
        source: HarnessStart,
        result: HarnessResult,
        descriptor: ArtifactDescriptor,
    ) -> dict[str, object]:
        return {
            # В production event_id лучше получать через отдельный EventIdGenerator.
            "event_id": f"{source.event_id}:harness-result",
            "event_type": "harness.completed.v1",
            "schema_version": 1,
            "correlation_id": source.correlation_id,
            "causation_id": source.event_id,
            "tenant_id": source.tenant_id,
            "payload": {
                "result": {
                    "uri": descriptor.uri,
                    "sha256": descriptor.sha256,
                    "size_bytes": descriptor.size_bytes,
                    "schema_version": descriptor.schema_version,
                }
            },
        }

    @staticmethod
    def _require_mapping(
        source: Mapping[str, object],
        field: str,
    ) -> Mapping[str, object]:
        value = source.get(field)
        if not isinstance(value, Mapping):
            raise InvalidEventError(f"{field} must be an object")
        return value

    @staticmethod
    def _require_string(
        source: Mapping[str, object],
        field: str,
    ) -> str:
        value = source.get(field)
        if not isinstance(value, str) or not value.strip():
            raise InvalidEventError(f"{field} must be a non-empty string")
        return value