import json
from pathlib import Path
from urllib.parse import urljoin

import jsonschema
import pytest
from referencing import Registry, Resource

from response_models.models import Issue, LLMAnalysis

from benchmarks.evaluators.deterministic import evaluate_deterministic
from benchmarks.project import load_project


SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _run_validator() -> jsonschema.Draft202012Validator:
    run_schema = _schema("run_result.schema.json")
    judge_schema = _schema("judge_result.schema.json")
    judge_uri = urljoin(run_schema["$id"], "judge_result.schema.json")
    registry = Registry().with_resource(judge_uri, Resource.from_contents(judge_schema))
    return jsonschema.Draft202012Validator(run_schema, registry=registry)


def _judge_result() -> dict:
    return {"matched_issue_id": "ISSUE-001", "verdict": "confirmed", "category_score": 2, "location_score": 2, "evidence_score": 3, "severity_score": 2, "recommendation_score": 2, "unsupported_claims": [], "confidence": 0.9}


@pytest.mark.parametrize("name", [
    "artifact_manifest.schema.json", "benchmark.schema.json",
    "run_result.schema.json", "judge_result.schema.json", "technical_run.schema.json",
])
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    jsonschema.Draft202012Validator.check_schema(_schema(name))


def test_technical_schema_status_invariants() -> None:
    fixture = {"schema_version": 1, "run_id": "run-1", "project_id": "project",
               "project_version": "1.0.0", "project_sha256": "a" * 64,
               "configuration_id": "baseline", "configuration_sha256": "b" * 64,
               "model": "offline", "prompt_version": "1.0.0", "prompt_sha256": "c" * 64,
               "context_variant": "overview", "toolset_variant": "full", "tool_budget": 2,
               "repeat": 1, "status": "passed", "delivery_decision": "ack",
               "checks": [{"name": "lifecycle", "passed": True, "details": None}], "error": None,
               "llm_analysis": {"issues": [], "strengths": []}, "result_sha256": "d" * 64,
               "completed_event": {"event_type": "harness.completed.v1"}, "total_seconds": 0}
    validator = jsonschema.Draft202012Validator(_schema("technical_run.schema.json"))
    validator.validate(fixture)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({**fixture, "schema_version": True})
    for field, value in (("delivery_decision", "retry"), ("error", {"type": "x", "message": "x"}),
                         ("llm_analysis", None), ("checks", [{"name": "x", "passed": False, "details": None}])):
        invalid = {**fixture, field: value}
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(invalid)


@pytest.mark.parametrize(("status", "decision"), [
    ("failed", "retry"),
    ("infrastructure_error", "ack"),
    ("infrastructure_error", "reject"),
])
def test_technical_schema_rejects_status_delivery_contradictions(
        status: str, decision: str) -> None:
    fixture = {"schema_version": 1, "run_id": "run-1", "project_id": "project",
               "project_version": "1.0.0", "project_sha256": "a" * 64,
               "configuration_id": "baseline", "configuration_sha256": "b" * 64,
               "model": "offline", "prompt_version": "1.0.0", "prompt_sha256": "c" * 64,
               "context_variant": "overview", "toolset_variant": "full", "tool_budget": 2,
               "repeat": 1, "status": status, "delivery_decision": decision, "checks": [],
               "error": {"type": "failure", "message": "Safe failure."},
               "llm_analysis": None, "result_sha256": None, "completed_event": None,
               "total_seconds": 0}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema("technical_run.schema.json")).validate(fixture)


def test_technical_schema_passed_requires_nonempty_checks() -> None:
    fixture = {"schema_version": 1, "run_id": "run-1", "project_id": "project",
               "project_version": "1.0.0", "project_sha256": "a" * 64,
               "configuration_id": "baseline", "configuration_sha256": "b" * 64,
               "model": "offline", "prompt_version": "1.0.0", "prompt_sha256": "c" * 64,
               "context_variant": "overview", "toolset_variant": "full", "tool_budget": 2,
               "repeat": 1, "status": "passed", "delivery_decision": "ack", "checks": [],
               "error": None, "llm_analysis": {"issues": [], "strengths": []},
               "result_sha256": "d" * 64,
               "completed_event": {"event_type": "harness.completed.v1"}, "total_seconds": 0}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema("technical_run.schema.json")).validate(fixture)


@pytest.mark.parametrize("producer,profile", [
    ({"service": "producer\nforged", "version": "1.0"}, "canonical.full"),
    ({"service": "producer", "version": "1.0\u0000forged"}, "canonical.full"),
    ({"service": "producer", "version": "1.0"}, "extra\nprofile"),
])
def test_artifact_manifest_rejects_unsafe_public_strings(producer: dict, profile: str) -> None:
    descriptor = {"path": "artifact", "sha256": "c" * 64, "size_bytes": 0, "schema_version": 1}
    manifest = {
        "schema_version": 1, "producer": producer,
        "source": {"path": "source", "project_fingerprint": "a" * 64},
        "graph_profiles": {"parser_semantics_version": 7, "graph_fingerprint": "b" * 64,
                           "artifacts": {profile: descriptor}},
        "metrics_profiles": {"metrics_semantics_version": 4, "graph_fingerprint": "b" * 64,
                             "artifacts": {"metrics.full": descriptor}},
        "source_index": {**descriptor, "project_fingerprint": "a" * 64},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(_schema("artifact_manifest.schema.json")).validate(manifest)


def test_benchmark_fixture_and_semver_compatibility() -> None:
    fixture = {
        "schema_version": 1, "project_id": "import_cycle", "project_version": "1.0.0-rc.1+build.5",
        "description": "Cycle fixture", "additional_findings_policy": "require_evidence",
        "expected_findings": [{
            "id": "ISSUE-001", "category": "dependency_cycle", "severity_min": "medium", "severity_max": "high",
            "locations": ["package_a/service.py"], "evidence": {"nodes": ["package_a.service"], "relations": ["imports"]},
            "acceptable_meanings": ["cyclic dependency"], "required_data": {"graph": True, "metrics": False, "source": "optional"},
            "forbidden_claims": ["runtime deadlock"],
        }],
    }
    jsonschema.Draft202012Validator(_schema("benchmark.schema.json")).validate(fixture)
    run = _run_fixture("failed")
    run["project_version"] = fixture["project_version"]
    _run_validator().validate(run)


def test_real_import_cycle_card_matches_benchmark_schema() -> None:
    card = SCHEMAS.parent / "projects" / "import_cycle" / "benchmark.yml"
    import yaml
    jsonschema.Draft202012Validator(_schema("benchmark.schema.json")).validate(
        yaml.safe_load(card.read_text(encoding="utf-8"))
    )


def test_passed_run_with_completed_judge_and_aggregates() -> None:
    _run_validator().validate(_run_fixture("passed"))


def test_real_deterministic_result_validates_against_run_schema_definition() -> None:
    project = SCHEMAS.parent / "projects" / "import_cycle"
    analysis = LLMAnalysis(issues=[Issue(
        title="Circular import",
        severity="high",
        description="The modules form a dependency cycle.",
        location="package_a/service.py",
        evidence="package_a.service and package_b.repository import each other.",
        recommendation="Extract the shared contract.",
    )], strengths=[])
    result = evaluate_deterministic(analysis, load_project(project))
    fixture = _run_fixture("passed")
    fixture["llm_analysis"] = analysis.model_dump()
    fixture["deterministic_evaluation"] = result

    _run_validator().validate(fixture)


@pytest.mark.parametrize("status", ["failed", "infrastructure_error"])
def test_non_passed_run_fixture(status: str) -> None:
    _run_validator().validate(_run_fixture(status))


@pytest.mark.parametrize("status,field,value", [
    ("passed", "llm_analysis", None),
    ("passed", "deterministic_evaluation", None),
    ("passed", "technical_error", {"type": "failure", "message": "contradiction"}),
    ("failed", "llm_analysis", {"issues": [], "strengths": []}),
    ("failed", "deterministic_evaluation", {"checks": [], "candidate_matches": [], "violations": []}),
    ("failed", "technical_error", None),
    ("failed", "aggregated_evaluation", {"quality_score": 1, "weighted_recall": 1, "precision": 1, "false_positive_rate": 0, "hallucination_rate": 0, "location_accuracy": 1, "normalized_evidence_score": 1, "normalized_recommendation_score": 1, "requires_human_review": False}),
    ("infrastructure_error", "judge_evaluations", [{}]),
])
def test_technical_status_contradictions(status: str, field: str, value: object) -> None:
    fixture = _run_fixture(status)
    if field == "technical_error":
        fixture["technical_result"]["error"] = value
    else:
        fixture[field] = value
    with pytest.raises(jsonschema.ValidationError):
        _run_validator().validate(fixture)


@pytest.mark.parametrize("status,result,error", [
    ("completed", None, None),
    ("completed", _judge_result(), {"type": "judge", "message": "bad"}),
    ("judge_error", _judge_result(), {"type": "judge", "message": "bad"}),
    ("infrastructure_error", None, None),
])
def test_judge_envelope_status_contradictions(status: str, result: object, error: object) -> None:
    fixture = _run_fixture("passed")
    envelope = fixture["judge_evaluations"][0]
    envelope.update(status=status, result=result, error=error)
    with pytest.raises(jsonschema.ValidationError):
        _run_validator().validate(fixture)


def test_run_validator_does_not_silently_ignore_unresolvable_judge_ref() -> None:
    fixture = _run_fixture("passed")
    schema = _schema("run_result.schema.json")
    with pytest.raises(jsonschema.exceptions._WrappedReferencingError):
        jsonschema.Draft202012Validator(schema).validate(fixture)


def _usage() -> dict:
    return {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "prompt_cache_hit_tokens": 10, "prompt_cache_miss_tokens": 90, "cost": None, "currency": None}


def _run_fixture(status: str) -> dict:
    passed = status == "passed"
    fixture = {
        "schema_version": 1, "run_id": "run-1", "project_id": "sample", "project_version": "1.0.0",
        "project_sha256": "a" * 64, "configuration_id": "baseline", "configuration_sha256": "b" * 64,
        "model": "deepseek-flash", "prompt_version": "0.1.0", "prompt_sha256": "c" * 64,
        "context_variant": "overview", "toolset_variant": "full", "tool_budget": 6, "repeat": 1,
        "judge_config": {"enabled": True, "url": "https://judge.example/v1", "model": "judge-1", "temperature": 0.1, "timeout_seconds": 120, "max_transport_retries": 2, "evaluations_per_finding": 3, "confidence_threshold": 0.7, "prompt_version": "0.1.0", "prompt_sha256": "d" * 64, "calibration_status": "uncalibrated"},
        "technical_result": {"status": status, "checks": [], "error": None if passed else {"type": "failure", "message": "failed"}},
        "llm_analysis": {"issues": [], "strengths": []} if passed else None,
        "deterministic_evaluation": {"checks": [], "candidate_matches": [{"finding_index": 0, "expected_issue_ids": ["ISSUE-001"]}], "violations": []} if passed else None,
        "judge_evaluations": [], "aggregated_evaluation": None,
        "analyzer_provider": {"response_id": "response-1" if passed else None, "finish_reason": "stop" if passed else None, "finalization_reason": "complete" if passed else "technical_failure", "provider_retries": 0},
        "tool_summary": {"calls_count": 1 if passed else 0, "errors_count": 0, "trace_reference": "trace-1" if passed else None},
        "usage": _usage(), "timings": {"total_seconds": 1, "provider_seconds": 0.5, "tool_seconds": 0.2, "deterministic_seconds": 0.1, "judge_seconds": 0.2 if passed else 0},
    }
    if passed:
        fixture["judge_evaluations"] = [{"finding_index": 0, "evaluation_repeat": 1, "status": "completed", "result": _judge_result(), "error": None, "model": "judge-1", "response_id": "judge-response-1", "usage": _usage(), "duration_seconds": 0.2, "transport_retries": 0}]
        fixture["aggregated_evaluation"] = {"quality_score": 0.9, "weighted_recall": 1, "precision": 0.9, "false_positive_rate": 0.1, "hallucination_rate": 0, "location_accuracy": 1, "normalized_evidence_score": 1, "normalized_recommendation_score": 0.8, "requires_human_review": False}
    return fixture
