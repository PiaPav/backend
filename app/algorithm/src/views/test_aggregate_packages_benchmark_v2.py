"""Frozen, reproducible acceptance evidence for aggregate.packages v2."""
import hashlib
import json
from pathlib import Path

from views import project_graph_summary
from views.testdata import build_representative_packages_v1


_MANIFEST = Path(__file__).with_name("testdata") / "aggregate_packages_benchmark_v2.json"
_TARGET = {"source_basis": 100, "maximum_artifact_basis": 15}
_FIXTURE_FAMILY = "representative_packages_v1"


def _compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def build_v2_benchmark_candidate():
    fixtures = []
    for name in ("medium", "large"):
        source = build_representative_packages_v1(name)
        artifact = project_graph_summary(source, profile_id="aggregate.packages", profile_version=2)
        source_raw, artifact_raw = _compact(source), _compact(artifact)
        # Necessary preflight: exact serialized required envelope/payload/rows, with
        # variable fingerprints replaced by their required 64-byte wire values.
        skeleton = {**artifact, "payload": {**artifact["payload"], "packages": [], "imports": []}}
        lower_bound = len(_compact(skeleton)) - 4  # remove the two empty [] tokens
        lower_bound += sum(len(_compact(row)) + 1 for row in artifact["payload"]["packages"])
        lower_bound += sum(len(_compact(row)) + 1 for row in artifact["payload"]["imports"])
        # Excludes no required fields; comma correction makes it a conservative bound.
        source_bytes, artifact_bytes = len(source_raw), len(artifact_raw)
        fixtures.append({
            "name": name,
            "source": {"compact_bytes": source_bytes,
                       "size_cap_bytes": source_bytes * _TARGET["maximum_artifact_basis"]
                       // _TARGET["source_basis"]},
            "artifact": {"compact_bytes": artifact_bytes,
                         "compact_ratio_percent": round(artifact_bytes * 100 / source_bytes, 4),
                         "full_compact_sha256": hashlib.sha256(artifact_raw).hexdigest(),
                         "summary_fingerprint": artifact["summary_fingerprint"],
                         "contract_lower_bound_bytes": lower_bound},
        })
    return {"manifest_schema_version": 1,
            "artifact_schema": {"artifact_kind": "graph_summary", "summary_schema_version": 1,
                                "profile_id": "aggregate.packages", "profile_version": 2,
                                "wire_format": 2, "grouping_version": 1},
            "target": _TARGET, "fixture_family": _FIXTURE_FAMILY, "fixtures": fixtures}


def test_compact_v2_acceptance_measurements_are_frozen():
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    candidate = build_v2_benchmark_candidate()
    assert candidate == manifest

    for fixture in candidate["fixtures"]:
        source, artifact = fixture["source"], fixture["artifact"]
        assert artifact["contract_lower_bound_bytes"] <= artifact["compact_bytes"]
        assert artifact["compact_bytes"] * candidate["target"]["source_basis"] <= \
            source["compact_bytes"] * candidate["target"]["maximum_artifact_basis"]
