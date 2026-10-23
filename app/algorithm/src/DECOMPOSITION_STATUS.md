# Статус декомпозиции

Статус сопоставлен с `DECOMPOSITION_PLAN.md`, кодом и независимыми прогонами.
Последний совместный прогон `graph_dto/test_contract.py`,
`graph_dto/test_boundaries.py`, `parser/test_core.py` и `metrics/test_core.py`:
172 passed, 0 failed, 0 skipped. Отдельный legacy regression
`gpt_work_dir/tests/test_parser.py` и `test_metrics_serialization.py`: 16 passed.

## Общий итог

| Этап | Итог |
|---|---|
| 1. Фиксация текущей семантики | **выполнен** |
| 2. Независимый файловый API Parser | **выполнен** |
| 3. Независимый файловый API Metrics | **выполнен** |
| 4. Версионированный Graph DTO | **выполнен для текущего canonical output** |
| 5. Формулы сложности в Metrics | **выполнен** |
| 6. Аналитические проекции | **выполнен** |
| 7. Независимость ядер | **выполнен для запланированных границ** |

## Этапы 1–3. Контракты и файловые API

Историческая семантика зафиксирована golden-тестами и архивным
`metrics/LEGACY_GRAPH_CONTRACT.md`. Legacy fixtures в `gpt_work_dir` не
переписывались и продолжают проверять прежний Parser/serializer сценарий.

`parser/core.py::parse_project(source_path, output_path) -> Path` строит Graph
DTO schema v1 / parser semantics v7, атомарно сохраняет его и возвращает
resolved `Path`. Файловый DTO не содержит `body`. `starter()` сохранён как
отдельный совместимый in-memory API и не является входом нового Metrics.

`metrics/core.py::calculate_metrics(graph_path, output_path) -> Path` принимает
только Graph DTO schema v1 / parser semantics 6 или 7. Unversioned graph и
semantics v1-v5 отклоняются с migration error и рекомендацией повторно создать
граф через `parser.parse_project()`. Semantics v6 может содержать optional
`body`, но Metrics его не читает; semantics v7 запрещает `body`. Результат
атомарно сохраняется как Metrics DTO schema v1 / metrics semantics v4.

Удаление старых входов не изменило формулы или output semantics, поэтому версия
математической семантики осталась 4. Общий `graph_dto` validator продолжает
распознавать исторические parser semantics v1-v7 независимо от более узкой
политики текущего Metrics consumer.

## Этап 4. Версионированный Graph DTO

Canonical Graph DTO содержит стабильные IDs, parent ownership, typed import,
inheritance, field-type, field-access и call/await edges, occurrence-level
callsites/import/type references, diagnostics, complexity facts и structural
owner facts. Import направлен `dependent -> dependency`; exact call edge weights
согласованы с callsites. Текущий Parser выдаёт bodyless semantics v7.

Semantics v6/v7 самодостаточны для Metrics. Общая схема сохраняет чтение
исторических версий как форматный контракт, однако adapters v1-v5 в новом
Metrics удалены отдельным breaking-инкрементом. Parser `starter()` и
`gpt_work_dir` этим изменением не затронуты.

## Этап 5. Формулы сложности в Metrics

Parser сериализует нейтральные `complexity_facts`; `metrics/logic/complexity.py`
вычисляет cyclomatic/cognitive complexity, nesting, LOC и quality facts без AST,
Parser imports или готовых legacy `function.metrics`. Quality, WMC и call-graph
risk используют canonical facts по node ID. Synthetic constructors исключены из
структурных и complexity populations согласно контракту.

## Этап 6. Централизовать аналитические проекции

`metrics/logic/projections.py::MetricsGraphProjection` является единственным
immutable snapshot canonical graph для расчёта. Aggregate gateway валидирует
schema/semantics и строит projection ровно один раз; внутренние calculators
принимают только projection.

Централизованы:

- directed file/package imports и normalized undirected file imports;
- canonical root-to-package ownership;
- weighted ID-only `calls`/`awaits` topology;
- `inherits`, `field_type` и `accesses_field` relations;
- canonical nodes, callsites, import references и owner structural facts.

Legacy identity module, nested `body` traversal, suffix/short-name resolution,
semantics-v2 WMC matching и все legacy object/call branches удалены. Production
Metrics не читает `body` и не меняет topology эвристически. Size, activity,
architecture, quality, object и call-graph sections используют один snapshot.

## Этап 7. Закрепить независимость

Parser tests не импортируют Metrics. Metrics tests используют только статически
собранные Graph DTO semantics v6/v7 и не запускают Parser. AST boundary tests
запрещают Parser↔Metrics cross-imports, production-доступ Metrics к `body`,
legacy identity imports, известные string-resolution markers и возврат mode
flags. Projection-only signatures внутренних calculators закреплены тестами.

Файловые контракты документированы отдельно в `parser/CONTRACT.md`,
`graph_dto/CONTRACT.md` и `metrics/CONTRACT.md`. Архивный legacy contract явно
помечен как неактивный. Удаление adapters v1-v5 выполнено отдельно от сохранения
`starter()` и подтверждено canonical, Parser и legacy regression-прогонами.

## Подтверждённые инварианты

- activity сохраняет hybrid denominator: все реальные callable плюс roots с
  root-level calls;
- import activity считает occurrences, а topology — уникальные non-self edges;
- call weights влияют на multiplicity, но не на SCC/centrality topology;
- DIT/NOC/CBO/RFC/LCOM/WMC вычисляются по canonical IDs;
- package instability/abstractness/distance используют canonical ownership;
- canonical-equivalent semantics v6/v7 дают одинаковый раздел `metrics`;
- ошибки входного контракта и записи не оставляют частичный корректный output.

## Остаток

Пункты исходного плана декомпозиции закрыты в согласованных границах двух ядер.
Дальнейшие изменения формул, DTO schema, parser semantics или удаление
`starter()` являются отдельными продуктовыми и версионированными задачами, а не
остатком текущей декомпозиции.
