# Контракт `aggregate.packages` v2

Профиль является артефактом Graph Summary schema 1. Profile version 1 сохранён
как отклонённая по size gate история и не поддерживается runtime; aliases,
`latest` и fallback отсутствуют.

Transferable payload содержит ровно пять полей:

```json
{"graph_kind":"quotient","wire_format":2,"grouping_version":1,"packages":[],"imports":[]}
```

Строка `packages` имеет форму `[label, file_count, declaration_count,
class_count, abstract_class_count, external_count, unresolved_count,
internal_unique_pairs, internal_exact_count, internal_self_count]`. Строка
`imports` имеет форму `[source_index, target_index, unique_file_pairs,
exact_count]`; индексы адресуют строки packages. Packages сортируются по
вычисленному package ID v2, imports — по edge ID v2. Пустой graph имеет
единственное представленное выше кодирование.

Переиспользуемая path policy v1 использует `/`, первый сегмент path и `<root>`
для path без `/`. Aggregate descriptor отдельно определяет populations files,
declarations, direct-root classes, import occurrences и quotient edges; это не
контракт Metrics `PACKAGE_GROUPING`.

IDs являются SHA-256 от compact JSON в UTF-8 с `ensure_ascii=false`, сортировкой
object keys и separators `,`/`:`. Package hash input:
`["aggregate.packages",2,full_aggregate_grouping_descriptor,label]`; edge hash
input: `["aggregate.packages",2,source_id,target_id]`. Префиксы:
`aggregate:package:` и `aggregate:package-imports:`.

Нормативный decoder строго валидирует positional wire и разворачивает его в
logical object semantics v1 (`graph_kind`, полный `package_grouping`, `nodes`,
`edges`). Exact occurrence восстанавливает отдельные поля canonical edge count
и exact occurrence count. Exact status package node равен internal exact плюс
исходящие cross-package exact occurrences. Полный canonical source восстановить
нельзя.

Fingerprint охватывает compact transferable envelope без собственного поля
`summary_fingerprint`. Size acceptance измеряет полный compact envelope вместе
с fingerprint и требует `artifact_bytes * 100 <= source_bytes * 15`.
