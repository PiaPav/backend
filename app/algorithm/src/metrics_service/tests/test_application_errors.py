import pytest

from metrics_service.application import errors


EXPECTED = {
    errors.MalformedEnvelopeError: ("malformed_envelope", errors.ErrorDisposition.REJECT),
    errors.UnsupportedEnvelopeVersionError: ("unsupported_envelope_version", errors.ErrorDisposition.REJECT),
    errors.UnsupportedEventTypeError: ("unsupported_event_type", errors.ErrorDisposition.REJECT),
    errors.TenantMismatchError: ("tenant_mismatch", errors.ErrorDisposition.REJECT),
    errors.UnsupportedUriSchemeError: ("unsupported_uri_scheme", errors.ErrorDisposition.FAILURE),
    errors.GraphNotFoundError: ("graph_not_found", errors.ErrorDisposition.FAILURE),
    errors.GraphChecksumMismatchError: ("graph_checksum_mismatch", errors.ErrorDisposition.FAILURE),
    errors.GraphFingerprintMismatchError: ("graph_fingerprint_mismatch", errors.ErrorDisposition.FAILURE),
    errors.InvalidGraphDtoError: ("invalid_graph_dto", errors.ErrorDisposition.FAILURE),
    errors.UnsupportedParserSemanticsError: ("unsupported_parser_semantics", errors.ErrorDisposition.FAILURE),
    errors.InvalidMetricsDtoError: ("invalid_metrics_dto", errors.ErrorDisposition.FAILURE),
    errors.MetricsGraphFingerprintMismatchError: ("metrics_graph_fingerprint_mismatch", errors.ErrorDisposition.FAILURE),
    errors.MetricsCalculationError: ("metrics_calculation_failed", errors.ErrorDisposition.FAILURE),
    errors.IdempotencyPayloadConflictError: ("idempotency_payload_conflict", errors.ErrorDisposition.FAILURE),
    errors.ArtifactConflictError: ("artifact_conflict", errors.ErrorDisposition.FAILURE),
    errors.ClaimBusyError: ("claim_busy", errors.ErrorDisposition.RETRY),
    errors.PublisherUnavailableError: ("publisher_unavailable", errors.ErrorDisposition.RETRY),
    errors.IdempotencyStoreUnavailableError: ("idempotency_store_unavailable", errors.ErrorDisposition.RETRY),
    errors.GraphTemporarilyUnavailableError: ("graph_temporarily_unavailable", errors.ErrorDisposition.RETRY),
    errors.StagingUnavailableError: ("staging_unavailable", errors.ErrorDisposition.RETRY),
    errors.ArtifactStoreUnavailableError: ("artifact_store_unavailable", errors.ErrorDisposition.RETRY),
    errors.TemporaryIoError: ("temporary_io_error", errors.ErrorDisposition.RETRY),
}


def test_all_error_codes_and_classification_are_stable_and_unique():
    concrete_error_types = {
        value for value in vars(errors).values()
        if isinstance(value, type)
        and issubclass(value, errors.ApplicationError)
        and value not in {errors.ApplicationError, errors.RetryableError,
                          errors.TerminalProcessingError, errors.RejectedInputError}
    }
    assert set(EXPECTED) == concrete_error_types
    assert len({code for code, _ in EXPECTED.values()}) == len(EXPECTED)
    for error_type, (code, disposition) in EXPECTED.items():
        error = error_type("safe diagnostic")
        assert error.error_code == code
        assert errors.classify_error(error) is disposition
        assert str(error) == "safe diagnostic"


def test_error_disposition_values_are_stable():
    assert {item.name: item.value for item in errors.ErrorDisposition} == {
        "RETRY": "retry", "FAILURE": "failure", "REJECT": "reject",
    }


def test_unsupported_uri_scheme_error_is_publicly_exported():
    from metrics_service.application import UnsupportedUriSchemeError

    assert UnsupportedUriSchemeError is errors.UnsupportedUriSchemeError


@pytest.mark.parametrize("message", ["", "line\nsecret", "bad\ud800", 1])
def test_unsafe_messages_are_rejected(message):
    with pytest.raises((TypeError, ValueError)):
        errors.ClaimBusyError(message)


def test_arbitrary_exception_is_rejected_and_cause_is_not_rendered():
    with pytest.raises(TypeError):
        errors.classify_error(Exception("secret"))
    error = errors.MetricsCalculationError("safe")
    error.__cause__ = RuntimeError("secret")
    assert str(error) == "safe"
