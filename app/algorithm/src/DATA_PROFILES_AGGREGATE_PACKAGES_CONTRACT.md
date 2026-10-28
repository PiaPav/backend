# Контракт `aggregate.packages` v1

Этот документ до runtime-реализации фиксирует package quotient profile version
1 для canonical Graph DTO schema 1 / Parser semantics 7. Профиль не меняет
Parser или Metrics и создаётся только после полной валидации canonical graph.

## Вид артефакта

`aggregate.packages` является Graph Summary DTO schema 1, а не Graph View и не
Graph DTO. Payload имеет ровно поля:

```json
{"graph_kind": "quotient", "package_grouping": {}, "nodes": [], "edges": []}
```

`graph_kind: "quotient"` запрещает трактовать summary как canonical file graph.

## Package grouping

Используется действующая Metrics policy version 1: package определяется первым
POSIX-сегментом root path, а path без `/` относится к `<root>`. Это не Python
package discovery. Литеральный первый сегмент `<root>` совпадает с sentinel;
исправление этой коллизии требует новой grouping/profile version.

Нормативный `package_grouping`:

```json
{
  "descriptor_version": 1,
  "path_policy": {
    "separator": "/",
    "package": "first POSIX path segment",
    "root_package": "<root>",
    "root_condition": "path contains no '/'"
  },
  "populations": {
    "files": "all canonical file/module roots",
    "declarations": "all canonical non-root nodes attributed through their owning root; synthetic methods included",
    "classes": "canonical classes directly owned by roots",
    "abstract_classes": "direct-root-owned classes with class_kind abstract",
    "import_occurrences": "all canonical import references attributed by importer root package"
  },
  "quotient_edges": {
    "direction": "dependent package to dependency package",
    "source_relation": "exact canonical root imports",
    "self_edges": "omitted",
    "non_exact_relations": "do not create edges"
  }
}
```

Существующий `views.metrics_contract.PACKAGE_GROUPING` не изменяется.

## Aggregate IDs

Package ID имеет вид `aggregate:package:<sha256>`. Digest строится из compact
UTF-8 JSON:

```json
["aggregate.packages", 1, <полный package_grouping descriptor>, "<package>"]
```

Edge ID имеет вид `aggregate:package-imports:<sha256>` и digest input:

```json
["aggregate.packages", 1, "<source_package_id>", "<target_package_id>"]
```

Используются `ensure_ascii=False`, `sort_keys=True`, separators `(",", ":")`.
Canonical IDs не переиспользуются; reverse edge получает другой ID.

## Package node

Node содержит ровно:

```json
{
  "id": "aggregate:package:...",
  "package": "pkg",
  "file_count": 3,
  "declaration_count": 17,
  "class_count": 4,
  "abstract_class_count": 1,
  "import_occurrence_counts": {"exact": 8, "external": 2, "unresolved": 1},
  "internal_imports": {
    "unique_file_pair_count": 2,
    "canonical_import_edge_count": 3,
    "exact_import_occurrence_count": 3,
    "self_import_occurrence_count": 1
  }
}
```

Populations:

- `file_count` — canonical file/module roots package;
- `declaration_count` — все non-root nodes через ownership ancestor root,
  включая synthetic methods;
- `class_count` — classes, непосредственно принадлежащие roots;
- `abstract_class_count` — subset с `class_kind: "abstract"`;
- status counts — все `import_references` importer package;
- `internal_imports` — exact relations с одинаковым source/target package;
- self count — internal occurrences с одинаковым importer/target root.

Buckets обязательны и zero-filled. Counts — integer, но не boolean:

```text
file_count > 0
abstract_class_count <= class_count <= declaration_count
self_import_occurrence_count <= exact_import_occurrence_count
unique_file_pair_count <= canonical_import_edge_count
canonical_import_edge_count == exact_import_occurrence_count
```

Пустой graph даёт пустые `nodes` и `edges`.

## Quotient edge

Edge существует для distinct ordered пары разных packages с exact import и
содержит ровно:

```json
{
  "id": "aggregate:package-imports:...",
  "kind": "imports",
  "source_id": "aggregate:package:...",
  "target_id": "aggregate:package:...",
  "unique_file_pair_count": 2,
  "canonical_import_edge_count": 4,
  "exact_import_occurrence_count": 4
}
```

- unique pairs — distinct ordered `(importer_id, target_id)`;
- canonical edges — canonical `imports` edge objects;
- exact occurrences — exact `import_references`.

Для semantics 7:

```text
1 <= unique_file_pair_count <= canonical_import_edge_count
canonical_import_edge_count == exact_import_occurrence_count
```

Два последних поля равны, но сохраняются раздельно как разные populations.

## Internal и non-exact relations

Package self-edges запрещены. File self-import и imports между files одной
package учитываются в node exact/internal counts, но не создают quotient edge.
External/unresolved references учитываются только у importer package. Projector
не угадывает target и не превращает non-exact fact в semantic relation.

## Глобальные инварианты

```text
sum(file_count) == число canonical roots
sum(declaration_count) == число canonical non-root nodes
sum(class_count) == число canonical classes
sum(status count) == соответствующая import_reference population
exact references == cross-edge exact occurrences + internal exact occurrences
canonical import edges == cross-edge canonical edges + internal canonical edges
distinct exact file pairs == cross-edge unique pairs + internal unique pairs
```

Endpoints существуют, ordered package pairs уникальны, nodes/edges сортируются
по aggregate ID.

Package cycle означает cycle quotient graph. Например `A/a1 -> B/b1` и
`B/b2 -> A/a2` образуют package cycle без file-level SCC. Внутрипакетный file
cycle, напротив, не виден в quotient graph.

## Completeness

Нормативный descriptor:

```json
{
  "kind": "one_way_projection",
  "preserves": [
    "package_declaration_population_counts",
    "package_file_and_class_population_counts",
    "package_import_resolution_occurrence_counts",
    "package_internal_import_population_counts",
    "package_quotient_exact_import_topology",
    "package_quotient_weight_populations",
    "source_graph_identity"
  ],
  "omits": [
    "call_relations",
    "callable_complexity_facts",
    "callsites",
    "canonical_declaration_descriptors",
    "canonical_file_descriptors",
    "canonical_import_edge_ids",
    "diagnostics",
    "import_occurrence_details",
    "intra_package_import_topology",
    "node_and_edge_locations",
    "owner_structural_facts",
    "type_references_and_relations"
  ]
}
```

Полный source восстановить нельзя.

## Детерминизм и границы

- source полностью валидируется; schema 1 / semantics 7 обязательны;
- source не мутируется, collection permutation не меняет summary;
- compatible extensions не попадают в summary;
- fingerprint охватывает envelope без собственного поля;
- projector не импортирует Parser или Metrics;
- Metrics продолжает вычисляться только из canonical Graph DTO.

Package labels, file/class/abstract counts и число quotient edges должны
совпадать с текущей Metrics architecture semantics на одном source.

## Benchmark gate

До runtime фиксируется family `representative_packages_v1`, поскольку
`representative_graph_v2` содержит только package `benchmark`.

Medium/large fixtures заранее включают `<root>`, несколько packages, isolated
package, repeated exact imports, несколько file pairs одной package pair,
reverse edges, file self-import, within-package import, external/unresolved
references, abstract/concrete classes, synthetic methods и package cycle без
file-level SCC. Source composition, hashes и populations фиксируются до
измерения projector.

Target неизменяем:

```text
artifact_compact_bytes * 100 <= source_compact_bytes * 15
```

Размер и SHA-256 относятся к полному compact UTF-8 artifact, включая
`summary_fingerprint`. Target является fixture-scoped product acceptance.
