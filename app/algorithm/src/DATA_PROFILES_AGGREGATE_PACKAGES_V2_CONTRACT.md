# Контракт `aggregate.packages/2`

Runtime поддерживает только Graph Summary profile `aggregate.packages/2`.
Object-wire v1 отклонён по size gate и удалён из документации/API; aliases,
`latest` и fallback отсутствуют.

Transferable payload:

```json
{"graph_kind":"quotient","wire_format":2,"grouping_version":1,"packages":[],"imports":[]}
```

Package row:

```text
[label, files, declarations, classes, abstract_classes,
 external, unresolved, internal_unique_pairs, internal_exact, internal_self]
```

Import row:

```text
[source_package_index, target_package_index, unique_file_pairs, exact_count]
```

Package — первый POSIX-сегмент root path либо `<root>`. Packages сортируются по
aggregate package ID, imports — по aggregate edge ID. IDs — SHA-256 canonical
compact JSON с profile/version/grouping и label/endpoints. Canonical IDs не
переиспользуются.

Normative decoder строго валидирует positional rows и восстанавливает logical
quotient tree с package populations, resolution counts и раздельными unique
file pair/canonical edge/exact occurrence meanings. Non-exact imports не создают
edges; package self-relations остаются node counters. Package cycle не означает
file-level SCC.

Summary является one-way projection и маркируется `graph_kind: quotient`.
Fingerprint покрывает transferable envelope без собственного поля. Accepted
representative family проходит target не более 15% полного Graph DTO.
