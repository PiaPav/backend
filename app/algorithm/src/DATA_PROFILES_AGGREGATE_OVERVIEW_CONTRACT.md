# Контракт `aggregate.overview/1`

Graph Summary schema 1 строится только из полного Graph DTO schema 1 / Parser
semantics 7. Профиль реализован как compact graph-native dashboard; Metrics DTO
и Metrics Core не используются.

Payload wire v1:

```json
{"graph_kind":"overview","wire_format":1,"policy_version":1,
 "totals":[],"statuses":[],"file_identities":[],
 "package_identities":[],"rankings":[]}
```

`totals` содержит 19 integers: size populations, structural call/import
activity, file/package vertices/edges и числа cyclic SCC. `statuses` содержит 12
zero-filled import/type/callsite resolution counts. File graph использует exact
non-self root pairs; package graph — quotient по первому POSIX-сегменту path.

Три независимых top-10:

1. files by unique exact fan-in;
2. files by unique exact fan-out;
3. packages by efferent coupling.

Порядок — score descending, authoritative ID ascending; boundary ties не
расширяют limit. Каждая ranking row хранит total, returned, truncated и indexed
items. Decoder отклоняет неверные row lengths/types, duplicates, ordering,
indices и metadata.

Completeness — `one_way_projection`: сохраняются source identity, totals,
resolution populations и три rankings; descriptors, locations, individual
references/edges, formulas, averages, risk и object metrics исключены.
Fingerprint покрывает полный transferable envelope без собственного поля.
Accepted family проходит size target `artifact_bytes * 100 <= source_bytes * 8`.
