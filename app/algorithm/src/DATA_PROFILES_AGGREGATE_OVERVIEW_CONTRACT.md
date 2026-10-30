# Контракт `aggregate.overview/1` (до-runtime)

Этот документ нормативно фиксирует source-side/preflight инкремент. Профиль ещё
не зарегистрирован, projector, runtime API и decoder ещё не реализованы.

## Identity и source

Artifact после acceptance — Graph Summary schema 1, profile
`aggregate.overview/1`. Единственный input — полный canonical Graph DTO schema 1
с Parser semantics 7. Metrics DTO не является input, Metrics Core не
импортируется. Все определения ниже graph-native; совпадение отдельных смыслов
с Metrics не означает literal-copy. Любое изменение semantics, grouping,
population, top-k либо wire требует profile version bump.

Completeness: `one_way_projection`. Сохраняются source identity, перечисленные
ниже totals, resolution occurrences, topology scalar counts и три top-k.
Опускаются canonical descriptors/locations, individual references/callsites,
diagnostics, exact edge lists, Metrics formulas/risk/PageRank/object metrics,
averages и rates.

## Logical decoded tree

Decoder обязан выдавать явные секции `size`, `activity`, `file_graph`,
`package_graph`, `resolution_counts`, `hotspots`, а также descriptors
`populations`, `top_k` и `package_grouping`.

* `size`: directories — множество всех непустых POSIX parent prefixes paths
  roots; files — все file/module roots; classes; classes с `class_kind` равным
  `abstract`; classes с `class_kind` равным `dataclass`; functions; methods с
  `synthetic != true`; synthetic methods отдельно; fields; constants.
* `activity`: calls — сумма `call_occurrences` у roots, functions и
  non-synthetic methods в `owner_structural_facts`; local/external imports —
  сумма root `direct_import_occurrences.project_local/non_project`. Это
  structural occurrences, не число callsites/import references.
* `file_graph`: vertices — все roots. Edges — уникальные ordered exact,
  non-self root pairs из import references. `cyclic_components` — число SCC
  размера >1.
* `package_graph`: grouping использует тот же path descriptor (`/`, первый
  segment, `<root>` при отсутствии `/`) и population смысл, что
  `aggregate.packages/2`, но является profile-coupled descriptor overview.
  Vertices — присутствующие packages; edges — уникальные cross-package ordered
  pairs file edges; SCC считаются на quotient и не выводятся из file SCC.
* `resolution_counts` — zero-filled maps: imports
  `exact/external/unresolved`; types `exact/ambiguous/external/unresolved`;
  callsites `exact/ambiguous/external/dynamic/unresolved`.

Package ID: prefix `aggregate:overview-package:` плюс SHA-256 compact JSON
`["aggregate.overview",1,<full grouping descriptor>,label]` (UTF-8,
`ensure_ascii=false`, sorted object keys, separators `,`/`:`, lowercase hex).
Он намеренно не переиспользует IDs `aggregate.packages`.

## Hotspots

Только homogeneous graph-native rankings, limit ровно 10:

1. `files_by_fan_in`: roots с positive unique non-self exact file fan-in;
2. `files_by_fan_out`: roots с positive unique non-self exact file fan-out;
3. `packages_by_efferent_coupling`: packages с positive числом distinct
   cross-package outgoing neighbours.

Порядок: score descending, затем authoritative ID ascending. Boundary ties не
расширяют выдачу. Для каждого ranking сохраняются `total_matching` до
truncation, `returned_count=len(items)`, `truncated=returned_count <
total_matching`; empty population кодируется нулями и `false`. File identity —
canonical root ID, package identity — overview package ID.

## Compact transferable wire v1

Полный envelope имеет ровно поля `artifact_kind`, `summary_schema_version`,
`profile`, `source`, `completeness`, `payload`, `summary_fingerprint` обычного
Graph Summary. `source` содержит graph schema/parser semantics/fingerprint;
fingerprint — SHA-256 compact envelope без собственного поля.

Payload имеет ровно:

```json
{"graph_kind":"overview","wire_format":1,"policy_version":1,
 "totals":[],"statuses":[],"file_identities":[],"package_identities":[],
 "rankings":[]}
```

Positional layouts:

* `totals` (19 integers): `[directories,files,classes,abstract_classes,
  dataclasses,functions,methods,synthetic_methods,fields,constants,calls,
  local_imports,external_imports,file_vertices,file_edges,file_cyclic_components,
  package_vertices,package_edges,package_cyclic_components]`.
* `statuses` (12 integers): imports exact/external/unresolved; types
  exact/ambiguous/external/unresolved; callsites
  exact/ambiguous/external/dynamic/unresolved, in that order.
* `file_identities`: sorted unique `[canonical_root_id,path]` rows used by file
  rankings only. `package_identities`: sorted unique `[overview_package_id,label]`
  rows used by package ranking only. Tables are deduplicated across rankings.
* `rankings`: exactly three rows in the order above. Each is
  `[total_matching,returned_count,truncated,items]`; item is
  `[identity_table_index,score]`. Indices address the matching identity table.

Normative decoder must reject wrong key sets, booleans in integer positions,
negative values, duplicate/unsorted identities, wrong row lengths/order,
non-positive scores, more than 10 items, bad indices, duplicate items,
non-canonical ranking order, metadata inconsistencies and non-zero omitted
status buckets. It reconstructs the logical descriptors and named fields; that
decoded output is not benchmarked.

## Acceptance gate

Serialization is compact UTF-8 JSON (`ensure_ascii=false`, sorted keys,
separators `,`/`:`). Both operands are full transferable values. Artifact size
includes every envelope field and `summary_fingerprint`; exact integer gate:

`artifact_bytes * 100 <= source_graph_bytes * 8`.

The pending preflight lower-bound candidate includes all mandatory envelope,
source/completeness metadata, payload keys, totals/statuses, a 64-byte
fingerprint placeholder and the fixture's actual mandatory identity/ranking
rows. It excludes no required wire bytes. Passing it is necessary, not
sufficient: the eventual runtime artifact must independently pass the same gate.
