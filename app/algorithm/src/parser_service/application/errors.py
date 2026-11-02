"""Safe, typed Parser Service application failures."""

from enum import Enum
import unicodedata


class ErrorDisposition(str, Enum):
    RETRY = "retry"
    FAILURE = "failure"
    REJECT = "reject"


class ApplicationError(Exception):
    error_code: str
    disposition: ErrorDisposition

    def __init__(self, safe_message: str) -> None:
        if type(safe_message) is not str:
            raise TypeError("safe_message must be a string")
        if not safe_message:
            raise ValueError("safe_message must not be empty")
        if any(unicodedata.category(c) == "Cc" or 0xD800 <= ord(c) <= 0xDFFF for c in safe_message):
            raise ValueError("safe_message contains unsafe characters")
        self.safe_message = safe_message
        super().__init__(safe_message)


class RetryableError(ApplicationError):
    disposition = ErrorDisposition.RETRY


class TerminalProcessingError(ApplicationError):
    disposition = ErrorDisposition.FAILURE


class RejectedInputError(ApplicationError):
    disposition = ErrorDisposition.REJECT


def classify_error(error: ApplicationError) -> ErrorDisposition:
    if not isinstance(error, ApplicationError) or not isinstance(error.disposition, ErrorDisposition):
        raise TypeError("error must belong to the ApplicationError hierarchy")
    return error.disposition


def _errors(base: type[ApplicationError], definitions: dict[str, str]) -> None:
    for name, code in definitions.items():
        globals()[name] = type(name, (base,), {"error_code": code, "__module__": __name__})


_errors(RejectedInputError, {
    "MalformedEnvelopeError": "malformed_envelope", "UnsupportedEnvelopeVersionError": "unsupported_envelope_version",
    "UnsupportedEventTypeError": "unsupported_event_type", "TenantMismatchError": "tenant_mismatch",
})
_errors(TerminalProcessingError, {
    "UnsupportedUriSchemeError": "unsupported_uri_scheme", "SourceNotFoundError": "source_not_found",
    "InvalidGraphDtoError": "invalid_graph_dto", "ParserProcessingError": "parser_processing_failed",
    "IdempotencyPayloadConflictError": "idempotency_payload_conflict", "ArtifactConflictError": "artifact_conflict",
})
_errors(RetryableError, {
    "ClaimBusyError": "claim_busy", "PublisherUnavailableError": "publisher_unavailable",
    "IdempotencyStoreUnavailableError": "idempotency_store_unavailable",
    "SourceTemporarilyUnavailableError": "source_temporarily_unavailable", "StagingUnavailableError": "staging_unavailable",
    "ArtifactStoreUnavailableError": "artifact_store_unavailable", "TemporaryIoError": "temporary_io_error",
})

__all__ = [
    "ApplicationError", "ErrorDisposition", "RejectedInputError", "RetryableError", "TerminalProcessingError", "classify_error",
    "MalformedEnvelopeError", "UnsupportedEnvelopeVersionError", "UnsupportedEventTypeError", "TenantMismatchError",
    "UnsupportedUriSchemeError", "SourceNotFoundError", "InvalidGraphDtoError", "ParserProcessingError",
    "IdempotencyPayloadConflictError", "ArtifactConflictError", "ClaimBusyError", "PublisherUnavailableError",
    "IdempotencyStoreUnavailableError", "SourceTemporarilyUnavailableError", "StagingUnavailableError",
    "ArtifactStoreUnavailableError", "TemporaryIoError",
]
