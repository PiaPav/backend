# Контракт `dependency.architecture/1`

Graph View schema 1 строится из Graph DTO schema 1 / Parser semantics 7 и не
является входом Metrics Core.

Payload содержит только:

- root и class `nodes`;
- root-to-class `contains` и агрегированные exact `imports` в `edges`;
- все occurrence-level `import_references`;
- zero-filled `import_resolution_counts`;
- versioned `package_grouping`.

Root хранит `id`, `kind`, `qualified_name`, `path`; class дополнительно
`parent_id`, `class_kind`. Один import edge соответствует уникальной ordered
root pair, имеет нормативный aggregate ID и `exact_occurrence_count`. Reverse и
self pairs сохраняются. External/unresolved references не создают topology.

Counts равны распределению references; exact count равен сумме edge weights;
каждый class/target/endpoint присутствует в nodes. Package — первый POSIX-сегмент
root path, либо `<root>` для пути без `/`; это не Python package discovery.

Профиль query-lossless для root/class population, class ownership, import
occurrences, exact topology и grouping semantics. Calls, types, complexity,
diagnostics и другие declarations исключены. Collections сортируются по ID,
source не мутируется. Benchmark target на representative family: `<=30%`
полного Graph DTO.
