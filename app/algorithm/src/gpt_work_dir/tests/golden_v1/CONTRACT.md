# Golden Graph/Metrics contract v1

This directory contains immutable full-equality regression oracles for Graph
DTO schema v1 / parser semantics v1 and Metrics DTO schema v1 / metrics
semantics v2.

## Scenarios

- `source`, `graph.json`, `metrics.json`: minimal single-file baseline.
- `package_calls/source`, `package_calls/graph.json`,
  `package_calls/metrics.json`: package/module collision, import direction,
  repeated and nested calls.

Parser tests reproduce each `graph.json` from its committed source. Metrics
tests consume the committed Graph file directly and never invoke Parser. Full
decoded-object equality is the compatibility oracle; focused assertions make
the semantic reason for the larger scenario explicit.

## Edge and package rules

- `contains`: container -> declaration.
- `imports`: dependent -> dependency.
- `calls` / `awaits`: caller -> callee.
- `pkg/__init__.py` wins semantic module `pkg` over sibling `pkg.py`; both
  retain distinct collision-safe file IDs and the shadowed module is diagnosed.
- Repeated and nested calls remain separate canonical callsites.
- Aggregate call-edge `weight` equals the number of exact callsites for the
  same caller, target, and edge kind.
- Canonical callsite depth is zero-based. The transitional legacy Metrics
  nesting aggregate is one-based.

## `package_calls` key results

The scenario fixes these semantics in addition to the complete JSON snapshots:

- three files and one directory;
- one import edge `file:consumer.py -> file:pkg/__init__.py`;
- `file:pkg.py` remains isolated;
- four exact callsites owned by `consumer.run`;
- canonical depths: three outer calls at `0`, one nested call at `1`;
- call weights: `consumer.run -> pkg.outer` is `3`, and
  `consumer.run -> pkg.inner` is `1`;
- dependency density `0.1667`, average fan-in/out `0.3333`;
- call graph has four nodes, two edges, four locally resolved callsites and
  maximum legacy syntactic nesting `2`;
- semantics-v2 activity averages are both `1.0`, preserving the historical
  hybrid call-owner denominator.

Fingerprints, rounding, deterministic ordering and all remaining metrics in
the JSON files are also part of the golden contract. Updating snapshots requires
reviewing the focused invariants rather than accepting regenerated JSON alone.
