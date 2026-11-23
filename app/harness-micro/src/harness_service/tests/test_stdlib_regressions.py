"""Standard-library runner for the pre-existing pytest-style regression functions."""

import tempfile
import unittest
from pathlib import Path

from harness_service.tests import (
    test_analysis_context,
    test_composition,
    test_handler,
    test_orchestrator_context,
    test_runner,
    test_tools_context,
)


class ExistingRegressionTests(unittest.TestCase):
    def test_orchestrator_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_orchestrator_context.test_orchestrator_builds_context_and_uses_overview_profiles(Path(directory))

    def test_tools_context(self) -> None:
        test_tools_context.test_tools_engine_passes_analysis_context_to_tool()

    def test_analysis_context(self) -> None:
        test_analysis_context.test_analysis_context_defensively_copies_read_only_profile_mappings()

    def test_composition(self) -> None:
        test_composition.test_composition_builds_core_around_current_orchestrator_api()

    def test_handler_success(self) -> None:
        test_handler.test_success_saves_before_confirmed_publish()

    def test_handler_publish_failure(self) -> None:
        test_handler.test_publish_failure_retries_after_persisting_result()

    def test_handler_republish(self) -> None:
        test_handler.test_saved_event_is_republished_without_llm_call()

    def test_handler_contract(self) -> None:
        test_handler.test_contract_and_trusted_tenant_are_checked_before_processing()

    def test_handler_fingerprints(self) -> None:
        test_handler.test_graph_and_source_index_fingerprints_are_independent()

    def test_handler_metrics_graph(self) -> None:
        test_handler.test_metrics_must_refer_to_input_graph()

    def test_handler_legacy_payload(self) -> None:
        test_handler.test_legacy_payload_is_normalized_to_full_profiles()

    def test_handler_profile_contract(self) -> None:
        test_handler.test_profile_payload_requires_mvp_profiles_and_rejects_mixed_contract()

    def test_runner_state(self) -> None:
        test_runner.test_runner_only_maps_request_and_returns_result()

    def test_runner_core_failure(self) -> None:
        test_runner.test_runner_propagates_core_failure_without_lifecycle_access()

    def test_runner_tenant_scope(self) -> None:
        test_runner.test_task_id_is_tenant_scoped()

    def test_runner_timeout(self) -> None:
        test_runner.test_runner_enforces_timeout()


if __name__ == "__main__":
    unittest.main()
