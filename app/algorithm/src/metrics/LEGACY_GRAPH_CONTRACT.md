# Legacy Graph compatibility contract

This document freezes the actual unversioned `body` input consumed by Metrics
during migration to canonical Graph DTO edges. `metrics/core.py` validates this
projection, and `metrics/logic/identity.py` supplies its shared file identity.
Every legacy field also affects the legacy-body fingerprint even when no
formula reads it. Therefore `unused` below means "unused by metric formulas",
not "safe to remove".

For parser semantics v5, structural `size`, package file/class/abstract
populations, quality, WMC, object metrics and call-graph metrics use canonical
facts. The legacy fields listed below remain validated and fingerprinted;
activity and its historical denominators still consume them. Older parser
semantics retain the compatibility consumers documented in the tables.

## Root and files

| JSON path | Validation / producer | Metrics consumers |
|---|---|---|
| `body` | Required list produced by the legacy serializer | `core` validation/fingerprint; `identity.graph_files`; input to every calculation |
| `body[].file` | Required object | Unwrapped by `identity.graph_files` |
| `file.name` | Required non-empty string; unique together with `path` | `identity` file/module IDs and `__init__.py` handling; all qualified names |
| `file.path` | Required string consistent with `path_parts` | `identity`; package and directory fallback in `calculator`/`architecture` |
| `file.path_parts` | Required list of non-empty strings | Collision-safe file ID, directory count, package identity |
| `file.imports` | Required list | Import counts/dependency graph in `calculator`; legacy call resolution in `call_graph` |
| `file.classes` | Optional list | Size, abstractness, quality, object and call-graph metrics |
| `file.functions` | Optional list | Size, activity denominator, quality, object and call-graph metrics |
| `file.calls` | Optional list | Module call count/owner, call-graph module node and topology |
| `file.constants` | Optional list | Only its length contributes to `size.constants` |

The effective file identity distinguishes `pkg.py` from `pkg/__init__.py`.
When both expose the same semantic module, package `__init__.py` is effective.

## Imports

| JSON path | Validation / producer | Metrics consumers |
|---|---|---|
| `imports[].object` | Required truthy value | Imported symbol/local binding in `call_graph` |
| `imports[].asname` | Optional | Alias binding in `call_graph` |
| `imports[].path` | Serialized import module path | Dependency target in `calculator`; local/external target in `call_graph` |
| `imports[].from_lib` | Required `bool` | Local/external counts; only local imports form dependency edges |

The dependency direction is always **dependent -> dependency**.

## Classes and fields

| JSON path | Validation / producer | Metrics consumers |
|---|---|---|
| `classes[].name` | Serialized class name | Class identity and inheritance resolution; method identities |
| `classes[].parent` | Optional null, string, or list | Legacy DIT/NOC and parent contribution to CBO in `object_metrics` |
| `classes[].type` | Required: `class`, `dataclass`, `enum`, or `abstract` | Size classification and package abstractness |
| `classes[].fields` | Optional list | Field count, type-based CBO, LCOM |
| `classes[].methods` | Required list | Callable validation, size/activity, quality/object/call graph |
| `fields[].name` | Serialized field name | Matched with `self_attribute_accesses` for LCOM |
| `fields[].type` | Optional annotation string | Legacy type-based CBO heuristic |
| `fields[].value` | Optional serialized value | Unused by formulas |
| `constants[].name/type/value` | Serialized constant details | Individually unused; only the enclosing list length is counted |

Inheritance, field-type and coupling names are still legacy heuristics. Their
replacement by typed canonical ID edges belongs to decomposition stage 4.

## Functions and methods

`file.functions[]` and `classes[].methods[]` share the callable shape.

| JSON path | Validation / producer | Metrics consumers |
|---|---|---|
| `callable.name` | Serialized declaration name | Identity in `quality`, `object_metrics`, and `call_graph` |
| `callable.args` and `args[].name/type/value` | Serialized signature facts | Unused by formulas |
| `callable.return_type` | Optional serialized annotation | Unused by formulas |
| `callable.metrics` | Required object | Validated by `core`; consumed by quality/object/call-graph metrics |
| `callable.calls` | Optional list | Activity, call topology/nesting, RFC and CBO |

### `callable.metrics`

| Field | Metrics consumers |
|---|---|
| `cyclomatic_complexity` | Required integer >= 1; quality averages/ranking, WMC, risk |
| `cognitive_complexity` | Quality averages/ranking and risk |
| `max_nesting` | Maximum and deeply-nested rankings |
| `lines_of_code` | Average and largest-callable rankings |
| `is_async` | Async callable count |
| `await_count` | Async-without-await count |
| `raise_count` | Raise totals and callables-raising count |
| `raised_exceptions` | Raised exception frequency |
| `caught_exceptions` | Caught exception frequency |
| `broad_exception_handlers` | Broad-handler count |
| `self_attribute_accesses` | LCOM field access sets |
| `statement_count`, `return_count` | Preserved but unused by current formulas |

## Calls and nesting

| JSON path | Validation / producer | Metrics consumers |
|---|---|---|
| `calls[].object` | Serialized call target text; loader does not require or type-check it | Legacy target resolution/external classification; RFC/CBO |
| `calls[].args` | Optional; loader requires a list when present | Recursive call count, syntactic nesting, RFC/CBO traversal |
| `calls[].args[].name` | Optional argument name | Unused by formulas |
| `calls[].args[].value` | Scalar or structured value | Recursed into only when it is an object with `type == "call"` |
| nested `value.type/object/args/semantic_target` | Nested call record | Handled like a top-level call record |
| `calls[].semantic_target.module/object` | Optional parser-resolved target; loader does not structurally validate its contents | Exclusive exact target for modern transitional records |

Every repeated and nested call record contributes one callsite. Legacy Metrics
counts outer calls at nesting level 1, while canonical Graph DTO callsites use
zero-based `syntactic_depth`.

## Transitional fields and non-consumers

For Graph DTO v1, `parser_semantics_version` accompanies `body` in the Metrics
compatibility projection. Its presence disables unsafe short-name fallbacks in
`call_graph`. `graph_algorithms.py` consumes already-built nodes and edges;
`serialization.py` consumes calculated Metrics output, so neither reads Graph
JSON fields directly.

This matrix must be updated whenever the legacy serializer, validator, or any
compatibility consumer changes. Removing a field requires a separately
versioned migration because fingerprints and/or metric results can change.
