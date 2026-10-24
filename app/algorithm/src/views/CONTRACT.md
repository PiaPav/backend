# Graph profiles и Graph View DTO v1

Публичный `materialize_graph_profile` поддерживает точные пары
`canonical.full / 1`, `inventory.minimal / 1` и
`structure.declarations / 1` и `dependency.files / 1`. Первый профиль возвращает
глубокую копию полного Graph DTO schema 1 / Parser semantics 7 и не является
Graph View: он не получает view envelope или новый fingerprint и остаётся
допустимым входом Metrics Core. `project_graph_view` по-прежнему принимает
только Graph View profiles.

## Graph Summary DTO v1: `inventory.minimal` v1

`inventory.minimal` создаётся как отдельный `artifact_kind: graph_summary` с
`summary_schema_version` и `summary_fingerprint`; это не Graph View и не Graph
DTO. Специализированный gateway — `project_graph_summary`. Строгие публичные
операции `validate_graph_summary_v1`, `graph_summary_fingerprint` и
`serialize_graph_summary` не зависят от Graph View contract.

Payload и populations определены в `DATA_PROFILES_INITIAL_CONTRACT.md`.
Completeness маркирует one-way projection и явно перечисляет сохранённые counts
и исключённые details/relations. Validator проверяет закрытые zero-filled
categories, root descriptors, неотрицательные non-boolean counts, joint
diagnostic distribution и summary fingerprint. Serialization использует
sorted indented UTF-8 JSON, LF и один завершающий newline.

Summary не содержит topology или occurrence details и отклоняется Metrics Core.
Отсутствие relation/detail нельзя интерпретировать как ноль или отсутствие
runtime relation.

## `structure.declarations` v1

The Graph View contract supports profile ID `structure.declarations`, profile
version `1`, view schema `1`, and source Graph DTO schema `1` / Parser semantics
`7`. There is no default, `latest`, version negotiation, or fallback.

The strict envelope contains exactly `artifact_kind` (`graph_view`),
`view_schema_version`, `profile` (`id`, `version`), `source`
(`graph_schema_version`, `parser_semantics_version`, `graph_fingerprint`),
`completeness`, `payload` (`nodes`, `edges`), and `view_fingerprint`.

The node whitelist is `id`, `kind`, `qualified_name`, `parent_id`, and `path`,
plus `class_kind` only for classes and `synthetic: true` only for synthetic
methods. Every canonical node is retained. The edge whitelist is `id`, `kind`,
`source_id`, and `target_id`; exactly the canonical `contains` edges are
retained. Canonical IDs and ownership are unchanged. Nodes and edges are sorted
lexicographically by ID, and completeness lists are fixed registry metadata.

The query guarantee is lossless preservation of canonical declaration nodes
and canonical declaration ownership. The machine-readable omissions are:
callsites, callable complexity facts, diagnostics, import references, owner
structural facts, type references, node locations, and edge locations. Omitted
relation classes are listed separately and explicitly: call relations, import
relations, type relations, and field access relations. Thus, for example, this
view cannot answer how often a function is called. Absence from an omitted
domain does not mean zero or no relation.

`source.graph_fingerprint` binds provenance to the complete validated source.
`view_fingerprint` is SHA-256 of compact canonical UTF-8 JSON for the entire
envelope except the top-level `view_fingerprint`; therefore source, profile,
completeness, and payload are all bound. A fingerprint detects accidental or
content changes. It is **not a signature** and provides no authenticity.

The standalone validator checks exact shapes and fields, versions, lowercase
SHA-256 values, POSIX-relative paths, sorted unique IDs, endpoint closure,
ownership consistency, one `contains` edge per non-root, and an acyclic forest.
Serialization is sorted, indented UTF-8 JSON with LF and one trailing newline.

## `dependency.files` v1

This Graph View profile uses the same strict envelope and exact source-version
policy. Its payload is exactly `nodes`, `edges`, and
`import_resolution_counts`. Nodes are all and only canonical `file`/`module`
roots with exactly `id`, `kind`, `qualified_name`, and `path`. Each edge has
exactly `id`, `kind: imports`, `source_id`, `target_id`, and a positive
non-boolean `exact_occurrence_count`; endpoints must exist in the projected
roots. Ordered endpoint pairs are unique. Reverse pairs remain distinct and
self-loops are retained.

The aggregate ID is `aggregate:imports:<sha256>`, where the digest input is the
UTF-8 encoding of compact `ensure_ascii=false` JSON `[source_id,target_id]`.
Both projector and validator use this rule. Nodes and edges are sorted by ID;
duplicates, stale aggregate IDs, dangling endpoints, booleans as counts, and
non-canonical ordering are rejected. The closed count object has exactly
`exact`, `external`, and `unresolved`, each a nonnegative non-boolean integer,
and the sum of edge occurrence counts equals `exact`.

The query guarantee is lossless exact import topology between roots, including
multiplicity, plus global import-resolution occurrence counts. External and
unresolved references contribute to counters but never topology. No resolution
is repeated by the projector. Occurrence IDs, source spelling, alias and
location are omitted: for example, an edge count of two cannot answer whether
either occurrence used an alias. Absence of a non-exact edge does not mean the
source had no external or unresolved import; consult the counters.

A Graph View DTO is **not Graph DTO v1**: required canonical collections have
been omitted. It must not be passed to Metrics; Metrics continues to consume a
complete validated canonical Graph DTO only. Parser semantics other than `7`
are unsupported.
